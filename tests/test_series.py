"""R9.1: `pontos` do IBC-Br e bloco `series` do /analyze. Sem internet: dados fixos e fakes."""

import json
import math
from datetime import date, timedelta

import pytest
from fabrica_resposta import resposta
from fastapi.testclient import TestClient
from test_service import (
    Pecas,
    analise_falha,
    analise_ok,
    rodar,
    serie_dolar,
    serie_ibcbr,
)

from app.collectors.bcb import Observacao
from app.config import Settings
from app.indicators import IndicadorError, crescimento_ibcbr, ultimos_pontos
from app.main import criar_app
from app.schemas import PontoSerie, RespostaMacro, SeriesMacro

NAN = float("nan")
INF = float("inf")


def mensais(valores, fim=date(2026, 10, 1)):
    """Pontos mensais (dia 1) terminando em `fim`; None/NaN permitidos nos valores."""
    obs = []
    for i, v in enumerate(reversed(valores)):
        indice = fim.year * 12 + fim.month - 1 - i
        obs.append(Observacao(date(indice // 12, indice % 12 + 1, 1), v))
    return list(reversed(obs))


# ------------------------------------------------------------- ultimos_pontos (puro)


def test_ultimos_pontos_ordena_e_pega_as_ultimas():
    obs = [Observacao(date(2026, 3, 1), 3.0), Observacao(date(2026, 1, 1), 1.0),
           Observacao(date(2026, 2, 1), 2.0)]  # fmt: skip
    assert [o.valor for o in ultimos_pontos(obs, 2)] == [2.0, 3.0]


def test_ultimos_pontos_descarta_nan_inf_none_e_texto_sem_preencher():
    obs = [
        Observacao(date(2026, 1, 1), 1.0),
        Observacao(date(2026, 2, 1), NAN),
        Observacao(date(2026, 3, 1), INF),
        Observacao(date(2026, 4, 1), None),
        Observacao(date(2026, 5, 1), "x"),
        Observacao(date(2026, 6, 1), 6.0),
    ]
    assert [o.valor for o in ultimos_pontos(obs, 12)] == [1.0, 6.0]


def test_ultimos_pontos_data_repetida_vale_a_ultima():
    obs = [Observacao(date(2026, 1, 1), 1.0), Observacao(date(2026, 1, 1), 9.0)]
    assert [o.valor for o in ultimos_pontos(obs, 5)] == [9.0]


@pytest.mark.parametrize("entrada", [[], None])
def test_ultimos_pontos_vazio(entrada):
    assert ultimos_pontos(entrada, 12) == []


# --------------------------------------------------------------- pontos do IBC-Br


def test_pontos_das_janelas_sao_3_cronologicos_e_batem_com_a_serie():
    r = rodar()
    ibc = r.indicadores.ibcbr
    assert [p.valor for p in ibc.janela_anterior.pontos] == [111.5323, 110.7, 110.7185]
    assert [p.valor for p in ibc.janela_recente.pontos] == [110.8115, 110.0, 110.0]
    assert [p.data for p in ibc.janela_anterior.pontos] == [
        date(2026, 3, 1), date(2026, 4, 1), date(2026, 5, 1)
    ]  # fmt: skip
    assert [p.data for p in ibc.janela_recente.pontos] == [
        date(2026, 6, 1), date(2026, 7, 1), date(2026, 8, 1)
    ]  # fmt: skip


def test_media_dos_pontos_bate_com_media_em_5e_5_e_a_conta_exata_com_valores_brutos():
    r = rodar()
    for janela in (r.indicadores.ibcbr.janela_recente, r.indicadores.ibcbr.janela_anterior):
        media_pontos = sum(p.valor for p in janela.pontos) / 3
        assert abs(media_pontos - janela.media) <= 5e-5  # media sai com 4 casas
    # Conta exata (sem arredondamento), direto do indicador:
    cresc = crescimento_ibcbr(serie_ibcbr())
    assert math.isclose(sum(cresc.valores_recente) / 3, cresc.media_recente, abs_tol=1e-12)
    assert math.isclose(sum(cresc.valores_anterior) / 3, cresc.media_anterior, abs_tol=1e-12)


def test_json_traz_data_iso_e_valor_nao_arredondado():
    saida = json.loads(rodar().model_dump_json())
    p = saida["indicadores"]["ibcbr"]["janela_anterior"]["pontos"][0]
    assert p == {"data": "2026-03-01", "valor": 111.5323}


def test_ibcbr_com_menos_de_6_pontos_continua_levantando_indicador_error():
    with pytest.raises(IndicadorError):
        crescimento_ibcbr(serie_ibcbr()[-5:])


# ---------------------------------------------------------------------- series


def test_series_tamanhos_ordem_e_dados_fixos():
    # 10 pontos de IBC-Br, 2 de IPCA, 2 de Selic, 70 de dólar (dados do test_service).
    s = rodar().series
    assert len(s.ibcbr_mensal) == 10
    assert len(s.ipca_12m_mensal) == 2
    assert len(s.selic_efetiva_diaria) == 2
    assert len(s.dolar_diario) == 70
    for lista in (s.ibcbr_mensal, s.ipca_12m_mensal, s.selic_efetiva_diaria, s.dolar_diario):
        datas = [p.data for p in lista]
        assert datas == sorted(datas)
    assert s.ipca_12m_mensal[-1] == PontoSerie(data=date(2026, 10, 1), valor=4.63)
    assert s.dolar_diario[-1] == PontoSerie(data=date(2026, 11, 13), valor=5.6518)


def test_series_limitam_ao_maximo_pedido_mantendo_as_mais_recentes():
    ibc = mensais([100.0 + i for i in range(20)], fim=date(2026, 8, 1))
    ipca = mensais([4.0 + i / 100 for i in range(20)])
    selic = [Observacao(date(2026, 8, 1) + timedelta(days=i), 13.0 + i / 100) for i in range(100)]
    dolar = serie_dolar(200)
    s = rodar(Pecas(ibcbr=ibc, ipca=ipca, dolar=dolar)).series
    assert (len(s.ibcbr_mensal), len(s.ipca_12m_mensal), len(s.dolar_diario)) == (12, 12, 120)
    assert s.ibcbr_mensal[-1].valor == 119.0 and s.ibcbr_mensal[0].valor == 108.0
    assert len(rodar(Pecas()).series.selic_efetiva_diaria) == 2
    assert len(SeriesMacro(selic_efetiva_diaria=[
        PontoSerie(data=o.data, valor=o.valor) for o in ultimos_pontos(selic, 60)
    ]).selic_efetiva_diaria) == 60  # fmt: skip


def test_series_com_valores_sem_arredondar():
    ipca = mensais([4.123456789, 4.987654321])
    s = rodar(Pecas(ipca=ipca)).series
    assert [p.valor for p in s.ipca_12m_mensal] == [4.123456789, 4.987654321]


def test_series_desordenadas_com_nan_e_none_saem_ordenadas_e_sem_invalidos():
    ipca = [
        Observacao(date(2026, 10, 1), 4.63),
        Observacao(date(2026, 8, 1), NAN),
        Observacao(date(2026, 9, 1), 4.5),
        Observacao(date(2026, 7, 1), None),
    ]
    s = rodar(Pecas(ipca=ipca)).series
    assert [(p.data, p.valor) for p in s.ipca_12m_mensal] == [
        (date(2026, 9, 1), 4.5), (date(2026, 10, 1), 4.63)
    ]  # fmt: skip


def test_serie_sem_pontos_validos_vira_lista_vazia_sem_quebrar_a_resposta():
    ipca = [Observacao(date(2026, 10, 1), 4.63)]  # o último valor é usado pelo cálculo...
    r = rodar(Pecas(ipca=ipca))
    assert len(r.series.ipca_12m_mensal) == 1  # menos pontos = lista menor
    # SeriesMacro vazia é válida e o JSON sai com listas vazias:
    assert json.loads(SeriesMacro().model_dump_json()) == {
        "ibcbr_mensal": [], "ipca_12m_mensal": [], "selic_efetiva_diaria": [], "dolar_diario": []
    }  # fmt: skip


def test_schema_rejeita_series_fora_de_ordem_e_valor_nao_finito():
    p1, p2 = PontoSerie(data=date(2026, 1, 1), valor=1.0), PontoSerie(data=date(2026, 2, 1), valor=2.0)
    with pytest.raises(ValueError):
        SeriesMacro(ibcbr_mensal=[p2, p1])
    with pytest.raises(ValueError):
        PontoSerie(data=date(2026, 1, 1), valor=NAN)


def test_fallback_tambem_leva_series_e_pontos():
    r = rodar(analisar=analise_falha)
    assert r.justificativa.origem == "fallback"
    assert len(r.series.ibcbr_mensal) == 10
    assert len(r.indicadores.ibcbr.janela_recente.pontos) == 3


def test_series_nao_entram_no_prompt_do_llm():
    from app.llm import montar_mensagens

    capturado = {}

    def analisar(entrada):
        capturado["msgs"] = montar_mensagens(entrada)
        return analise_ok(entrada)

    rodar(analisar=analisar)
    usuario = capturado["msgs"][1]  # a mensagem do sistema tem a palavra "pontos" (p.p.)
    assert "series" not in usuario and "pontos" not in usuario
    assert "2026-03-01" not in usuario and "111,5323" not in usuario  # valor de um ponto mensal


def test_api_devolve_series_e_pontos_e_valida_como_resposta_macro():
    class Gerador:
        def __call__(self):
            return resposta("fallback")

    app = criar_app(gerador=Gerador(), preaquecer=False)
    corpo = TestClient(app).get("/api/v1/macro/analyze").json()
    RespostaMacro.model_validate(corpo)
    assert set(corpo["series"]) == {
        "ibcbr_mensal", "ipca_12m_mensal", "selic_efetiva_diaria", "dolar_diario"
    }  # fmt: skip
    assert len(corpo["indicadores"]["ibcbr"]["janela_recente"]["pontos"]) == 3


def test_janelas_padrao_ampliadas():
    s = Settings(_env_file=None)
    assert (s.JANELA_IBCBR_DIAS, s.JANELA_DOLAR_DIAS, s.JANELA_SELIC_DIAS, s.JANELA_IPCA_DIAS) == (
        480, 200, 90, 400,
    )  # fmt: skip
