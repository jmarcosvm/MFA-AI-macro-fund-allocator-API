"""Testes do pipeline (app/service.py). Sem internet e sem chave: coletores, Focus e LLM FALSOS.

Os dados são FIXOS. As séries de IBC-Br e de dólar são SINTÉTICAS (não são os valores
reais): foram montadas para reproduzir os números do SPEC §6 (médias 110,9836 e 110,2705;
crescimento -0,64; "ibcbr precisa superar" 112,23). Mar-ago/2026 são as 6 últimas; os 4
pontos de nov/2025 a fev/2026 são arbitrários e só provam que apenas as 6 últimas contam.
"""

import json
from datetime import date, datetime, timedelta, timezone

import httpx2
import pytest
from test_llm import CHAVE_GEMINI, CHAVE_NVIDIA, Falso, resposta, settings

from app import service
from app.collectors.bcb import SERIES, BCBError, Observacao
from app.collectors.focus import MedianaFocus, ResultadoFocus, SelicEsperada
from app.indicators import volatilidade_dolar_anualizada
from app.llm import ErroProvedor, gerar_analise
from app.rules import Cenario, PreferenciaIndexador
from app.schemas import RespostaMacro
from app.service import (
    AVISO_FIXO,
    ColetoresBCB,
    ServicoIndisponivelError,
    gerar_resposta,
)

UTC = timezone.utc
AGORA = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)  # 09:00 em UTC-3, dia 14/11/2026

# --------------------------------------------------------------------- dados fixos


def serie_ibcbr(valores=None):
    """10 pontos mensais, nov/2025 a ago/2026 (SINTÉTICOS; ver docstring do módulo)."""
    valores = valores or (
        [100.0, 101.0, 102.0, 103.0]  # nov/25-fev/26: arbitrários
        + [111.5323, 110.7, 110.7185, 110.8115, 110.0, 110.0]  # mar-ago/26
    )
    inicio = date(2026 - 1, 11, 1) if len(valores) == 10 else date(2026, 8, 1)
    obs = []
    for i, v in enumerate(valores):
        indice = inicio.month - 1 + i
        obs.append(Observacao(date(inicio.year + indice // 12, indice % 12 + 1, 1), float(v)))
    if len(valores) != 10:  # termina em ago/2026
        obs = [
            Observacao(date(2026, 8 - (len(valores) - 1 - i), 1), float(v))
            for i, v in enumerate(valores)
        ]
    return obs


def serie_dolar(quantidade=70):
    """Preços diários sintéticos, o último é 5,6518 (data 13/11/2026)."""
    fim = date(2026, 11, 13)
    obs = []
    for i in range(quantidade):
        preco = 5.60 + (0.02 if i % 2 else 0.0)
        obs.append(Observacao(fim - timedelta(days=quantidade - 1 - i), preco))
    obs[-1] = Observacao(fim, 5.6518)
    return obs


SELIC = [Observacao(date(2026, 11, 12), 13.65), Observacao(date(2026, 11, 13), 13.65)]
IPCA = [Observacao(date(2026, 9, 1), 4.5), Observacao(date(2026, 10, 1), 4.63)]
META = Observacao(date(2026, 11, 5), 13.75)

FOCUS_COMPLETO = ResultadoFocus(
    MedianaFocus(5.0117, date(2026, 11, 6)),
    SelicEsperada(12.75, date(2026, 11, 6), "R7/2027", date(2027, 10, 27), 19),
    [],
)
FOCUS_VAZIO = ResultadoFocus(None, None, ["Focus indisponível (teste)."])


class Pecas:
    """Coletores e Focus falsos que registram o que receberam."""

    def __init__(self, ibcbr=None, dolar=None, ipca=None, falhas=(), focus=FOCUS_COMPLETO):
        self.chamadas: list[tuple[str, date, object]] = []
        self.focus_resultado = focus
        self.focus_chamadas: list[tuple[date, object]] = []
        dados = {
            "selic_efetiva": SELIC,
            "ipca_12m": ipca or IPCA,
            "dolar_venda": dolar or serie_dolar(),
            "ibcbr": ibcbr or serie_ibcbr(),
            "meta_selic": META,
        }

        def fazer(nome):
            def coletor(hoje, *, cliente=None):
                self.chamadas.append((nome, hoje, cliente))
                if nome in falhas:
                    raise BCBError(SERIES[nome], "HTTP 500")
                return dados[nome]

            return coletor

        self.coletores = ColetoresBCB(**{nome: fazer(nome) for nome in dados})

    def focus(self, hoje, *, cliente=None):
        self.focus_chamadas.append((hoje, cliente))
        return self.focus_resultado


def analise_ok(entrada):
    return gerar_analise(
        entrada,
        settings=settings(),
        chamadores={"gemini": Falso(resposta()), "nvidia_nim": Falso(resposta())},
    )


def analise_falha(entrada):
    erro = ErroProvedor("falha de teste")
    return gerar_analise(
        entrada,
        settings=settings(),
        chamadores={"gemini": Falso(erro), "nvidia_nim": Falso(erro)},
    )


def rodar(pecas=None, agora=AGORA, analisar=analise_ok, **kw):
    pecas = pecas or Pecas()
    return gerar_resposta(
        agora,
        cliente=kw.pop("cliente", object()),
        coletores=pecas.coletores,
        focus=pecas.focus,
        analisar=analisar,
        **kw,
    )


# ------------------------------------------------------- 1-3: SPEC §6, LLM ok e fallback


def test_1_reproduz_o_spec_secao_6():
    r = rodar()
    assert r.cenario.classificacao == Cenario.ESTAGFLACAO
    assert r.cenario.criterios.crescimento_ibcbr_pct == -0.64
    assert r.cenario.criterios.ipca_12m_pct == 4.63
    assert r.cenario.criterios.limiar_crescimento_pct == 0.0
    assert r.cenario.criterios.limiar_ipca_pct == 4.5
    assert r.cenario.o_que_mudaria.ipca_precisa_cair_pp == 0.13
    assert r.cenario.o_que_mudaria.ibcbr_proximo_mes_precisa_superar == 112.23
    assert r.juro_real.ex_post_pct == 8.62
    assert r.juro_real.projetado_12m_pct == 7.37
    e = r.juro_real.entradas_projetado
    assert (e.selic_esperada_pct, e.reuniao, e.ipca_esperado_12m_pct) == (12.75, "R7/2027", 5.0117)
    assert e.data_focus == date(2026, 11, 6)
    b = r.carteira.base
    assert (b.renda_fixa, b.fundos_cambiais, b.renda_variavel) == (0.60, 0.25, 0.15)
    assert r.carteira.renda_fixa_preferencia == PreferenciaIndexador.POSFIXADA
    assert r.carteira.limite_desvio_pp == 15.0
    ibc = r.indicadores.ibcbr
    assert ibc.janela_recente.meses == ["jun", "jul", "ago"]
    assert ibc.janela_anterior.meses == ["mar", "abr", "mai"]
    assert ibc.janela_recente.media == 110.2705
    assert ibc.janela_anterior.media == 110.9836
    assert r.aviso == AVISO_FIXO
    ind = r.indicadores
    assert (ind.selic_efetiva_aa.valor, ind.selic_efetiva_aa.data) == (13.65, date(2026, 11, 13))
    assert ind.selic_efetiva_aa.fonte == "BCB SGS 1178"
    assert ind.meta_selic_aa.fonte == "BCB SGS 432"
    assert ind.ipca_12m.fonte == "BCB SGS 13522" and ind.ipca_12m.data == date(2026, 10, 1)
    assert ind.dolar_venda.valor == 5.6518 and ind.dolar_venda.fonte == "BCB SGS 1"
    assert ind.volatilidade_dolar_63d_anualizada_pct.fonte == "calculado sobre BCB SGS 1"
    assert ind.volatilidade_dolar_63d_anualizada_pct.valor == round(
        volatilidade_dolar_anualizada(serie_dolar()), 2
    )
    assert ind.ibcbr.fonte == "BCB SGS 24364"
    # ida e volta em JSON
    assert RespostaMacro.model_validate_json(r.model_dump_json()) == r
    assert json.loads(r.model_dump_json())["gerado_em"].endswith("-03:00")


def test_2_llm_com_sucesso_marca_origem_llm_e_provedor():
    r = rodar()
    assert r.justificativa.origem == "llm"
    assert r.justificativa.provedor == "gemini"
    s = r.carteira.sugerida
    assert (s.renda_fixa, s.fundos_cambiais, s.renda_variavel) == (0.55, 0.20, 0.25)


def test_3_llm_falhando_usa_fallback_com_carteira_base_e_aviso():
    r = rodar(analisar=analise_falha)
    assert r.justificativa.origem == "fallback"
    assert r.justificativa.provedor is None
    assert r.carteira.sugerida == r.carteira.base
    assert any("indisponível" in a and "carteira base" in a for a in r.avisos_de_qualidade)


# ------------------------------------------------------- 4-8: cada série do BCB falhando


@pytest.mark.parametrize("serie", list(SERIES))
def test_4_serie_do_bcb_falhando_levanta_servico_indisponivel(serie):
    pecas = Pecas(falhas=(serie,))
    chamou_llm = []
    with pytest.raises(ServicoIndisponivelError) as exc:
        rodar(pecas, analisar=lambda e: chamou_llm.append(e))
    msg = str(exc.value)
    assert f"série {SERIES[serie]}" in msg and "HTTP 500" in msg
    assert CHAVE_GEMINI not in msg and CHAVE_NVIDIA not in msg
    assert exc.value.motivo == msg
    assert isinstance(exc.value.__cause__, BCBError)
    assert chamou_llm == [] and pecas.focus_chamadas == []  # aborta antes do Focus e do LLM


# ------------------------------------------------------- 9-10: dados insuficientes


def test_5_ibcbr_com_5_pontos_levanta_servico_indisponivel():
    with pytest.raises(ServicoIndisponivelError, match=r"IBC-Br.*6 observações, recebi 5"):
        rodar(Pecas(ibcbr=serie_ibcbr([100, 101, 102, 103, 104])))


def test_6_dolar_com_63_precos_levanta_servico_indisponivel():
    with pytest.raises(ServicoIndisponivelError, match=r"Dólar.*64 observações, recebi 63"):
        rodar(Pecas(dolar=serie_dolar(63)))


# ------------------------------------------------------- 11-12: Focus ausente


def test_7_focus_todo_none_deixa_projetado_e_entradas_none():
    r = rodar(Pecas(focus=FOCUS_VAZIO))
    assert r.juro_real.projetado_12m_pct is None
    assert r.juro_real.entradas_projetado is None
    assert "Focus indisponível (teste)." in r.avisos_de_qualidade
    assert not any(a.startswith("Focus: mediana semanal") for a in r.avisos_de_qualidade)
    assert r.juro_real.ex_post_pct == 8.62


def test_8_selic_esperada_none_em_expansao_da_posfixada_com_aviso():
    crescendo = serie_ibcbr([100.0, 101, 102, 103, 104, 105, 106, 107, 108, 109])
    pecas = Pecas(
        ibcbr=crescendo,
        ipca=[Observacao(date(2026, 10, 1), 4.0)],
        focus=ResultadoFocus(MedianaFocus(5.0117, date(2026, 11, 6)), None, ["Selic fora (teste)."]),
    )
    r = rodar(pecas, analisar=analise_falha)
    assert r.cenario.classificacao == Cenario.EXPANSAO
    assert r.carteira.renda_fixa_preferencia == PreferenciaIndexador.POSFIXADA
    assert any("Selic esperada não estava disponível" in a for a in r.avisos_de_qualidade)
    # só o IPCA do Focus existe: projetado e entradas ficam None juntos
    assert r.juro_real.projetado_12m_pct is None and r.juro_real.entradas_projetado is None


def test_9_so_ipca_do_focus_ausente_tambem_zera_projetado():
    focus = ResultadoFocus(None, FOCUS_COMPLETO.selic_esperada, ["IPCA fora (teste)."])
    r = rodar(Pecas(focus=focus))
    assert r.juro_real.projetado_12m_pct is None and r.juro_real.entradas_projetado is None


# ------------------------------------------------------- 13-14: fuso e virada de dia


def test_10_virada_de_dia_usa_a_data_em_utc_menos_3():
    pecas = Pecas()
    rodar(pecas, agora=datetime(2026, 11, 16, 1, 30, tzinfo=UTC))  # 15/11 22:30 em UTC-3
    assert {hoje for _, hoje, _ in pecas.chamadas} == {date(2026, 11, 15)}
    assert [h for h, _ in pecas.focus_chamadas] == [date(2026, 11, 15)]


@pytest.mark.parametrize(
    "instante,esperado",
    [
        (datetime(2026, 11, 15, 2, 59, 59, tzinfo=UTC), date(2026, 11, 14)),  # UTC 15, Brasília 14
        (datetime(2026, 11, 15, 3, 0, 0, tzinfo=UTC), date(2026, 11, 15)),  # os dois no dia 15
        (datetime(2026, 11, 15, 8, 0, tzinfo=timezone(timedelta(hours=9))), date(2026, 11, 14)),
    ],
)
def test_11_utc_e_brasilia_em_dias_diferentes(instante, esperado):
    pecas = Pecas()
    r = rodar(pecas, agora=instante)
    assert {hoje for _, hoje, _ in pecas.chamadas} == {esperado}
    assert r.gerado_em == instante


def test_12_gerado_em_tem_offset_menos_3():
    r = rodar()
    assert r.gerado_em.utcoffset() == timedelta(hours=-3)
    assert r.gerado_em.isoformat() == "2026-11-14T09:00:00-03:00"


def test_13_agora_sem_fuso_levanta_valueerror():
    with pytest.raises(ValueError, match="fuso"):
        rodar(agora=datetime(2026, 11, 14, 12, 0))


# ------------------------------------------------------- 15-16: avisos de qualidade e aviso fixo


def test_14_avisos_gerados_dos_dados_e_na_ordem():
    focus = ResultadoFocus(
        FOCUS_COMPLETO.ipca_12m, FOCUS_COMPLETO.selic_esperada, ["Aviso do Focus (teste)."]
    )
    r = rodar(Pecas(focus=focus), analisar=analise_falha)
    a = r.avisos_de_qualidade
    assert a[0] == "IBC-Br com defasagem de ~2,5 meses (último ponto: agosto/2026)."
    assert a[1] == "Focus: mediana semanal de 06/11/2026; baseCalculo não documentado (usado 0)."
    assert a[2] == "Aviso do Focus (teste)."
    assert "carteira base" in a[3]  # avisos do LLM por último (ESTAGFLACAO: regra sem aviso)
    assert len(a) == len(set(a)) == 4


def test_15_defasagem_do_ibcbr_muda_com_o_agora():
    # 15/12/2026 - 31/08/2026 = 106 dias / 30 = 3,5
    r = rodar(agora=datetime(2026, 12, 15, 12, 0, tzinfo=UTC))
    assert r.avisos_de_qualidade[0] == (
        "IBC-Br com defasagem de ~3,5 meses (último ponto: agosto/2026)."
    )


def test_16_aviso_do_llm_igual_a_um_anterior_nao_duplica():
    def analisar(entrada):
        r = analise_ok(entrada)
        return type(r)(r.justificativa, r.carteira_sugerida, [entrada.avisos_de_qualidade[0]], [])

    r = rodar(analisar=analisar)
    assert r.avisos_de_qualidade.count(r.avisos_de_qualidade[0]) == 1


def test_17_aviso_fixo_literal():
    assert rodar().aviso == "Simulação educacional. Não é recomendação de investimento."


def test_18_so_as_6_ultimas_do_ibcbr_contam_nos_rotulos():
    pecas = Pecas()
    r = rodar(pecas)
    assert len(pecas.coletores.ibcbr(AGORA.date())) == 10
    assert r.indicadores.ibcbr.janela_recente.meses == ["jun", "jul", "ago"]
    assert r.indicadores.ibcbr.janela_anterior.meses == ["mar", "abr", "mai"]


# ------------------------------------------------------- 19-21: cliente compartilhado


class ClienteEspiao:
    def __init__(self):
        self.fechado = False

    def close(self):
        self.fechado = True


def gerar_sem_cliente(pecas):
    return gerar_resposta(
        AGORA, coletores=pecas.coletores, focus=pecas.focus, analisar=analise_ok
    )


def test_19_cliente_criado_aqui_e_compartilhado_e_fechado(monkeypatch):
    criados = []

    def fabrica(**kw):
        c = ClienteEspiao()
        c.timeout = kw["timeout"]
        criados.append(c)
        return c

    monkeypatch.setattr(service.httpx2, "Client", fabrica)
    pecas = Pecas()
    gerar_sem_cliente(pecas)
    assert len(criados) == 1 and criados[0].fechado
    assert criados[0].timeout == 10.0  # BCB_TIMEOUT_SEGUNDOS
    usados = {id(c) for _, _, c in pecas.chamadas} | {id(c) for _, c in pecas.focus_chamadas}
    assert usados == {id(criados[0])}  # os 5 coletores e o Focus usam o MESMO cliente


def test_20_cliente_fechado_mesmo_quando_ha_excecao(monkeypatch):
    criados = []
    monkeypatch.setattr(service.httpx2, "Client", lambda **kw: criados.append(ClienteEspiao()) or criados[-1])
    with pytest.raises(ServicoIndisponivelError):
        gerar_sem_cliente(Pecas(falhas=("ibcbr",)))
    assert criados[0].fechado


def test_21_cliente_injetado_nao_e_fechado():
    espiao = ClienteEspiao()
    pecas = Pecas()
    gerar_resposta(
        AGORA, cliente=espiao, coletores=pecas.coletores, focus=pecas.focus, analisar=analise_ok
    )
    assert not espiao.fechado
    assert all(c is espiao for _, _, c in pecas.chamadas)


# ------------------------------------------------------- 22: coletores reais com MockTransport


def test_22_as_5_funcoes_reais_do_bcb_usam_o_cliente_compartilhado():
    por_codigo = {
        SERIES["selic_efetiva"]: SELIC,
        SERIES["ipca_12m"]: IPCA,
        SERIES["dolar_venda"]: serie_dolar(),
        SERIES["ibcbr"]: serie_ibcbr(),
        SERIES["meta_selic"]: [META],
    }
    pedidos = []

    def handler(request):
        pedidos.append(request.url.path)
        codigo = int(request.url.path.split("bcdata.sgs.")[1].split("/")[0])
        corpo = [
            {"data": o.data.strftime("%d/%m/%Y"), "valor": str(o.valor)} for o in por_codigo[codigo]
        ]
        return httpx2.Response(200, json=corpo)

    cliente = httpx2.Client(transport=httpx2.MockTransport(handler))
    r = gerar_resposta(AGORA, cliente=cliente, focus=Pecas().focus, analisar=analise_ok)
    assert len(pedidos) == 5
    assert sorted(int(p.split("bcdata.sgs.")[1].split("/")[0]) for p in pedidos) == sorted(
        por_codigo
    )
    assert r.cenario.classificacao == Cenario.ESTAGFLACAO
    assert r.cenario.o_que_mudaria.ibcbr_proximo_mes_precisa_superar == 112.23
    assert not cliente.is_closed  # injetado: não fechado pelo service
