"""Testes do coletor do Focus.

Os testes padrão usam respostas simuladas (httpx2.MockTransport) e NÃO tocam a
internet. O teste marcado "internet" só roda com: pytest -m internet -s
"""

from datetime import date

import httpx2
import pytest

from app.collectors import focus
from app.collectors.focus import FocusError, MedianaFocus, ReuniaoEscolhida, SelicEsperada
from app.config import CALENDARIO_COPOM, get_settings

HOJE = date(2026, 11, 13)

# Datas FICTÍCIAS, só para testar a escolha (não são o calendário real do Copom).
CALENDARIO_FALSO = {
    "R1/2027": date(2027, 1, 20),
    "R4/2027": date(2027, 5, 5),
    "R7/2027": date(2027, 10, 27),
    "R8/2027": date(2027, 12, 8),
}


def linha_ipca(mediana=5.0117, data="2026-11-06"):
    return {"Indicador": "IPCA", "Data": data, "Suavizada": "S", "Mediana": mediana, "baseCalculo": 0}


def linha_selic(mediana=12.75, data="2026-11-06", reuniao="R7/2027"):
    return {"Indicador": "Selic", "Data": data, "Reuniao": reuniao, "Mediana": mediana, "baseCalculo": 0}


def cliente_simulado(handler) -> httpx2.Client:
    return httpx2.Client(transport=httpx2.MockTransport(handler))


def cliente_focus(ipca=None, selic=None) -> httpx2.Client:
    """Responde por recurso: `ipca`/`selic` são listas de linhas (ou Response pronta)."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        resposta = ipca if "Inflacao12Meses" in request.url.path else selic
        if isinstance(resposta, httpx2.Response):
            return resposta
        return httpx2.Response(200, json={"value": resposta})

    return cliente_simulado(handler)


@pytest.fixture(autouse=True)
def limpa_cache_settings():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# --- escolha da reunião ----------------------------------------------------


def test_somar_meses_basico_e_virada_de_ano():
    assert focus.somar_meses(date(2026, 11, 13), 12) == date(2027, 11, 13)
    assert focus.somar_meses(date(2026, 12, 15), 1) == date(2027, 1, 15)


def test_somar_meses_ajusta_dia_inexistente():
    assert focus.somar_meses(date(2027, 2, 28), 12) == date(2028, 2, 28)
    assert focus.somar_meses(date(2028, 2, 29), 12) == date(2029, 2, 28)
    assert focus.somar_meses(date(2026, 8, 31), 1) == date(2026, 9, 30)


def test_escolhe_a_reuniao_mais_proxima_de_hoje_mais_12_meses():
    # alvo = 13/11/2027: R8/2027 (08/12) está a 25 dias; R7/2027 (27/10) a 17 dias.
    assert focus.escolher_reuniao(HOJE, CALENDARIO_FALSO) == ReuniaoEscolhida(
        "R7/2027", date(2027, 10, 27), date(2027, 11, 13), 17
    )


def test_escolha_considera_reunioes_depois_do_alvo():
    # alvo = 01/12/2027: R8/2027 (08/12) a 7 dias; R7/2027 a 35 dias.
    assert focus.escolher_reuniao(date(2026, 12, 1), CALENDARIO_FALSO).reuniao == "R8/2027"


def test_escolha_na_virada_de_ano():
    # alvo = 05/01/2028; a mais próxima é R8/2027 (08/12/2027).
    assert focus.escolher_reuniao(date(2027, 1, 5), CALENDARIO_FALSO).reuniao == "R8/2027"


def test_empate_vence_a_reuniao_mais_antiga():
    calendario = {"RA/2027": date(2027, 11, 10), "RB/2027": date(2027, 11, 16)}  # alvo 13/11
    assert focus.escolher_reuniao(HOJE, calendario).reuniao == "RA/2027"


def test_calendario_vazio_devolve_none():
    assert focus.escolher_reuniao(HOJE, {}) is None


def test_calendario_padrao_vem_da_configuracao():
    escolhida = focus.escolher_reuniao(HOJE)
    assert escolhida is not None
    assert escolhida.reuniao in focus.CALENDARIO_COPOM


# --- calendário real (R2.1) e virada da reunião ----------------------------


def test_calendario_real_tem_16_reunioes_em_ordem_e_rotulos_coerentes():
    itens = list(CALENDARIO_COPOM.items())
    assert len(itens) == 16
    datas = [data for _, data in itens]
    assert datas == sorted(datas) and len(set(datas)) == 16
    for ano in (2026, 2027):
        do_ano = [(nome, data) for nome, data in itens if data.year == ano]
        assert [nome for nome, _ in do_ano] == [f"R{n}/{ano}" for n in range(1, 9)]
    assert CALENDARIO_COPOM["R7/2027"] == date(2027, 10, 27)  # SPEC.md §3.3


@pytest.mark.parametrize(
    "hoje, reuniao, distancia",
    [
        (date(2026, 11, 15), "R7/2027", 19),
        (date(2026, 11, 16), "R7/2027", 20),
        (date(2026, 11, 17), "R7/2027", 21),  # empate (21 dias para cada lado): a mais cedo
        (date(2026, 11, 18), "R8/2027", 20),
        (date(2027, 2, 6), "R8/2027", 60),
    ],
)
def test_virada_da_reuniao_no_calendario_real(hoje, reuniao, distancia):
    escolhida = focus.escolher_reuniao(hoje)
    assert (escolhida.reuniao, escolhida.distancia_dias) == (reuniao, distancia)
    assert escolhida.alvo == focus.somar_meses(hoje, 12)


def test_empate_do_dia_17_tem_mesma_distancia_nos_dois_lados():
    alvo = date(2027, 11, 17)
    assert (alvo - CALENDARIO_COPOM["R7/2027"]).days == (CALENDARIO_COPOM["R8/2027"] - alvo).days == 21


def test_escolha_nao_depende_da_ordem_da_tabela():
    desordenada = dict(sorted(CALENDARIO_COPOM.items(), key=lambda item: item[1], reverse=True))
    assert list(desordenada) != list(CALENDARIO_COPOM)
    for hoje in (date(2026, 11, 15), date(2026, 11, 17), date(2026, 11, 18), date(2027, 2, 6)):
        assert focus.escolher_reuniao(hoje, desordenada) == focus.escolher_reuniao(hoje)


def test_29_de_fevereiro_usa_28_de_fevereiro_do_ano_seguinte():
    # 29/02/2028 + 12 meses: 29/02/2029 não existe -> alvo = 28/02/2029 (último dia do mês).
    calendario = {"RX/2029": date(2029, 2, 20), "RY/2029": date(2029, 3, 10)}
    escolhida = focus.escolher_reuniao(date(2028, 2, 29), calendario)
    assert escolhida == ReuniaoEscolhida("RX/2029", date(2029, 2, 20), date(2029, 2, 28), 8)


# --- tolerância (R2.1) ------------------------------------------------------


def _handler_selic_conta_chamadas(chamadas):
    def handler(request: httpx2.Request) -> httpx2.Response:
        chamadas.append(request.url.path)
        if "Inflacao12Meses" in request.url.path:
            return httpx2.Response(200, json={"value": [linha_ipca()]})
        return httpx2.Response(200, json={"value": [linha_selic(reuniao="R8/2027")]})

    return handler


def test_no_limite_de_60_dias_a_selic_e_coletada():
    chamadas = []
    cliente = cliente_simulado(_handler_selic_conta_chamadas(chamadas))
    resultado = focus.coletar_focus(date(2027, 2, 6), cliente=cliente)

    assert resultado.selic_esperada is not None
    assert resultado.selic_esperada.reuniao == "R8/2027"
    assert resultado.selic_esperada.distancia_dias == 60
    assert resultado.avisos == []


def test_com_61_dias_a_selic_vira_none_com_aviso_e_nao_chama_o_olinda():
    chamadas = []
    cliente = cliente_simulado(_handler_selic_conta_chamadas(chamadas))
    resultado = focus.coletar_focus(date(2027, 2, 7), cliente=cliente)

    assert resultado.ipca_12m is not None
    assert resultado.selic_esperada is None
    assert len(chamadas) == 1 and "Inflacao12Meses" in chamadas[0]  # só o IPCA
    (aviso,) = resultado.avisos
    for trecho in ("61 dias", "60 dias", "R8/2027", "08/12/2027", "07/02/2028"):
        assert trecho in aviso


def test_tolerancia_por_parametro():
    chamadas = []
    cliente = cliente_simulado(_handler_selic_conta_chamadas(chamadas))
    resultado = focus.coletar_focus(date(2027, 2, 7), tolerancia_dias=61, cliente=cliente)
    assert resultado.selic_esperada is not None

    recusada = focus.coletar_focus(date(2027, 2, 6), tolerancia_dias=59, cliente=cliente)
    assert recusada.selic_esperada is None and "59 dias" in recusada.avisos[0]


def test_tolerancia_por_variavel_de_ambiente(monkeypatch):
    monkeypatch.setenv("TOLERANCIA_REUNIAO_DIAS", "70")
    get_settings.cache_clear()
    cliente = cliente_simulado(_handler_selic_conta_chamadas([]))
    resultado = focus.coletar_focus(date(2027, 2, 7), cliente=cliente)
    assert resultado.selic_esperada is not None

    monkeypatch.setenv("TOLERANCIA_REUNIAO_DIAS", "10")
    get_settings.cache_clear()
    resultado = focus.coletar_focus(date(2027, 2, 6), cliente=cliente)
    assert resultado.selic_esperada is None and "10 dias" in resultado.avisos[0]


def test_aviso_de_tolerancia_informa_o_fim_da_tabela_desordenada():
    desordenada = {"RB/2027": date(2027, 12, 8), "RA/2027": date(2027, 1, 27)}
    resultado = focus.coletar_focus(
        date(2030, 1, 1), calendario=desordenada, cliente=cliente_focus(ipca=[linha_ipca()])
    )
    assert resultado.selic_esperada is None
    assert "termina em 08/12/2027 (RB/2027)" in resultado.avisos[0]


# --- coleta: sucesso --------------------------------------------------------


def test_coleta_com_sucesso_devolve_valores_datas_e_reuniao():
    cliente = cliente_focus(ipca=[linha_ipca()], selic=[linha_selic()])
    resultado = focus.coletar_focus(HOJE, calendario=CALENDARIO_FALSO, cliente=cliente)

    assert resultado.ipca_12m == MedianaFocus(5.0117, date(2026, 11, 6))
    assert resultado.selic_esperada == SelicEsperada(
        12.75, date(2026, 11, 6), "R7/2027", date(2027, 10, 27), 17
    )
    assert resultado.avisos == []


def test_envia_filtros_corretos_ao_olinda():
    vistas = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        vistas.append(request)
        return httpx2.Response(200, json={"value": [linha_ipca()]})

    focus.buscar_ipca_12m(cliente=cliente_simulado(handler))
    focus.buscar_selic_reuniao("R7/2027", cliente=cliente_simulado(handler))

    ipca, selic = vistas
    assert "ExpectativasMercadoInflacao12Meses" in ipca.url.path
    filtro_ipca = ipca.url.params["$filter"]
    assert "Indicador eq 'IPCA'" in filtro_ipca
    assert "Suavizada eq 'S'" in filtro_ipca
    assert "baseCalculo eq 0" in filtro_ipca
    assert ipca.url.params["$orderby"] == "Data desc"
    assert ipca.url.params["$top"] == "1"

    assert "ExpectativasMercadoSelic" in selic.url.path
    assert "Reuniao eq 'R7/2027'" in selic.url.params["$filter"]
    assert "baseCalculo eq 0" in selic.url.params["$filter"]


def test_espaco_na_query_vai_como_percent20_nunca_como_mais():
    """Regressão: o Olinda responde HTTP 400 quando o espaço vem como '+'."""
    vistas = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        vistas.append(str(request.url))
        return httpx2.Response(200, json={"value": [linha_ipca()]})

    focus.buscar_ipca_12m(cliente=cliente_simulado(handler))

    assert "+" not in vistas[0]
    assert "%20" in vistas[0]


# --- coleta: falhas viram None + aviso, nunca exceção ----------------------


def test_json_vazio_vira_none_com_aviso():
    cliente = cliente_focus(ipca=[], selic=[linha_selic()])
    resultado = focus.coletar_focus(HOJE, calendario=CALENDARIO_FALSO, cliente=cliente)

    assert resultado.ipca_12m is None
    assert resultado.selic_esperada is not None
    assert len(resultado.avisos) == 1
    assert "IPCA" in resultado.avisos[0]
    assert "resposta vazia" in resultado.avisos[0]


def test_timeout_vira_none_com_aviso_nos_dois_campos():
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("lento demais", request=request)

    resultado = focus.coletar_focus(
        HOJE, calendario=CALENDARIO_FALSO, cliente=cliente_simulado(handler)
    )

    assert resultado.ipca_12m is None
    assert resultado.selic_esperada is None
    assert len(resultado.avisos) == 2
    assert all("timeout" in aviso for aviso in resultado.avisos)


def test_http_de_erro_afeta_so_o_recurso_que_falhou():
    cliente = cliente_focus(ipca=httpx2.Response(500, json={}), selic=[linha_selic()])
    resultado = focus.coletar_focus(HOJE, calendario=CALENDARIO_FALSO, cliente=cliente)

    assert resultado.ipca_12m is None
    assert resultado.selic_esperada is not None
    assert "HTTP 500" in resultado.avisos[0]


def test_falha_de_rede_vira_none_com_aviso():
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("sem rede", request=request)

    resultado = focus.coletar_focus(
        HOJE, calendario=CALENDARIO_FALSO, cliente=cliente_simulado(handler)
    )
    assert resultado.ipca_12m is None and resultado.selic_esperada is None
    assert all("falha de rede" in aviso for aviso in resultado.avisos)


def test_calendario_vazio_nao_chama_a_selic_e_avisa():
    chamadas = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        chamadas.append(request.url.path)
        return httpx2.Response(200, json={"value": [linha_ipca()]})

    resultado = focus.coletar_focus(HOJE, calendario={}, cliente=cliente_simulado(handler))

    assert resultado.ipca_12m is not None
    assert resultado.selic_esperada is None
    assert len(chamadas) == 1  # só o IPCA
    assert "Calendário do Copom vazio" in resultado.avisos[0]


@pytest.mark.parametrize(
    "corpo",
    [
        {"erro": "x"},  # sem 'value'
        {"value": "texto"},  # 'value' não é lista
        [],  # raiz não é objeto
    ],
)
def test_json_fora_do_formato_levanta_focuserror(corpo):
    cliente = cliente_simulado(lambda request: httpx2.Response(200, json=corpo))
    with pytest.raises(FocusError, match="value"):
        focus.buscar_ipca_12m(cliente=cliente)


def test_resposta_que_nao_e_json_levanta_focuserror():
    cliente = cliente_simulado(lambda request: httpx2.Response(200, content=b"<html/>"))
    with pytest.raises(FocusError, match="JSON"):
        focus.buscar_ipca_12m(cliente=cliente)


@pytest.mark.parametrize(
    "linha",
    [
        {"Data": "06/11/2026", "Mediana": 5.0},  # data fora do formato ISO
        {"Data": "2026-11-06", "Mediana": "abc"},  # mediana não numérica
        {"Data": "2026-11-06"},  # sem Mediana
    ],
)
def test_linha_em_formato_inesperado_levanta_focuserror(linha):
    cliente = cliente_focus(ipca=[linha])
    with pytest.raises(FocusError, match="formato inesperado"):
        focus.buscar_ipca_12m(cliente=cliente)


# --- internet (fora do pytest padrão) --------------------------------------


@pytest.mark.internet
def test_internet_coleta_focus_real():
    """Roda com: pytest -m internet -s. Não confere valores fixos."""
    hoje = date.today()
    resultado = focus.coletar_focus(hoje)

    escolhida = focus.escolher_reuniao(hoje)

    print(f"\nhoje = {hoje.isoformat()}")
    print(f"alvo (hoje + 12 meses) = {escolhida.alvo.isoformat()}")
    print(f"reunião escolhida = {escolhida.reuniao} (decisão em {escolhida.data_reuniao.isoformat()})")
    print(f"distância alvo -> reunião = {escolhida.distancia_dias} dias")
    print(f"distância hoje -> reunião = {(escolhida.data_reuniao - hoje).days} dias")
    print(f"ipca_12m: {resultado.ipca_12m}")
    print(f"selic_esperada: {resultado.selic_esperada}")
    print(f"avisos: {resultado.avisos}")

    assert resultado.ipca_12m is not None, resultado.avisos
    assert resultado.ipca_12m.data <= hoje
    assert resultado.selic_esperada is not None, resultado.avisos
    assert resultado.selic_esperada.data <= hoje
    assert resultado.selic_esperada.reuniao in focus.CALENDARIO_COPOM
