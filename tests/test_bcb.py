"""Testes do coletor do BCB.

Os testes padrão usam respostas simuladas (httpx2.MockTransport) e NÃO tocam a
internet. O teste marcado "internet" só roda com: pytest -m internet -s
"""

from datetime import date

import httpx2
import pytest

from app.collectors import bcb
from app.collectors.bcb import BCBError, Observacao
from app.config import get_settings

HOJE = date(2026, 11, 14)


def cliente_simulado(handler) -> httpx2.Client:
    """Cliente cujo transporte chama `handler(request)` em vez de ir à rede."""
    return httpx2.Client(transport=httpx2.MockTransport(handler))


def cliente_json(corpo, status: int = 200) -> httpx2.Client:
    return cliente_simulado(lambda request: httpx2.Response(status, json=corpo))


@pytest.fixture(autouse=True)
def limpa_cache_settings():
    """Garante que variáveis de ambiente alteradas num teste não vazem para outro."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# --- parsing ---------------------------------------------------------------


def test_converte_texto_em_float_e_data_dd_mm_aaaa_em_date():
    corpo = [{"data": "13/11/2026", "valor": "13.65"}]
    resultado = bcb.buscar_serie(
        1178, date(2026, 9, 1), HOJE, timeout=5, cliente=cliente_json(corpo)
    )
    assert resultado == [Observacao(date(2026, 11, 13), 13.65)]
    assert isinstance(resultado[0].valor, float)


def test_ordena_resposta_desordenada_por_data_ascendente():
    corpo = [
        {"data": "13/11/2026", "valor": "3"},
        {"data": "11/11/2026", "valor": "1"},
        {"data": "12/11/2026", "valor": "2"},
    ]
    resultado = bcb.buscar_serie(1, date(2026, 11, 1), HOJE, timeout=5, cliente=cliente_json(corpo))
    assert [obs.data for obs in resultado] == [
        date(2026, 11, 11),
        date(2026, 11, 12),
        date(2026, 11, 13),
    ]


def test_envia_serie_formato_e_datas_dd_mm_aaaa():
    vistas = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        vistas.append(request)
        return httpx2.Response(200, json=[{"data": "13/11/2026", "valor": "1"}])

    bcb.buscar_serie(1178, date(2026, 9, 15), HOJE, timeout=5, cliente=cliente_simulado(handler))

    assert len(vistas) == 1
    assert "bcdata.sgs.1178" in vistas[0].url.path
    assert vistas[0].url.params["formato"] == "json"
    assert vistas[0].url.params["dataInicial"] == "15/09/2026"
    assert vistas[0].url.params["dataFinal"] == "14/11/2026"


# --- janela ----------------------------------------------------------------


def test_calcula_janela_com_hoje_fixo():
    assert bcb.calcular_janela(HOJE, 60) == (date(2026, 9, 15), HOJE)
    assert bcb.calcular_janela(HOJE, 150) == (date(2026, 6, 17), HOJE)


def test_funcoes_por_serie_usam_a_janela_padrao_de_cada_uma():
    esperado = {
        bcb.buscar_ibcbr: (24364, 365),
        bcb.buscar_dolar_venda: (1, 120),
        bcb.buscar_selic_efetiva: (1178, 60),
        bcb.buscar_ipca_12m: (13522, 150),
    }
    for funcao, (codigo, dias) in esperado.items():
        vistas = []

        def handler(request: httpx2.Request) -> httpx2.Response:
            vistas.append(request)
            return httpx2.Response(200, json=[{"data": "01/10/2026", "valor": "1"}])

        funcao(HOJE, cliente=cliente_simulado(handler))

        inicio, _ = bcb.calcular_janela(HOJE, dias)
        assert f"bcdata.sgs.{codigo}/" in str(vistas[0].url)
        assert vistas[0].url.params["dataInicial"] == inicio.strftime("%d/%m/%Y")


def test_janela_vem_da_variavel_de_ambiente(monkeypatch):
    monkeypatch.setenv("JANELA_SELIC_DIAS", "10")
    vistas = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        vistas.append(request)
        return httpx2.Response(200, json=[{"data": "13/11/2026", "valor": "13.65"}])

    bcb.buscar_selic_efetiva(HOJE, cliente=cliente_simulado(handler))

    assert vistas[0].url.params["dataInicial"] == "04/11/2026"


# --- meta da Selic (432) ---------------------------------------------------


def test_meta_selic_ignora_datas_futuras_e_devolve_a_ultima_ate_hoje():
    corpo = [
        {"data": "17/12/2026", "valor": "13.25"},  # futura
        {"data": "05/11/2026", "valor": "13.75"},  # a vigente
        {"data": "16/09/2026", "valor": "14.00"},
        {"data": "28/01/2027", "valor": "13.00"},  # futura
    ]
    meta = bcb.buscar_meta_selic(HOJE, cliente=cliente_json(corpo))
    assert meta == Observacao(date(2026, 11, 5), 13.75)


def test_meta_selic_aceita_linha_com_data_igual_a_hoje():
    corpo = [{"data": "14/11/2026", "valor": "13.75"}, {"data": "20/11/2026", "valor": "13.00"}]
    assert bcb.buscar_meta_selic(HOJE, cliente=cliente_json(corpo)).data == HOJE


def test_meta_selic_sem_linha_ate_hoje_levanta_erro_claro():
    corpo = [{"data": "17/12/2026", "valor": "13.25"}]
    with pytest.raises(BCBError) as erro:
        bcb.buscar_meta_selic(HOJE, cliente=cliente_json(corpo))
    assert erro.value.serie == 432
    assert "nenhuma linha com data <= 2026-11-14" in str(erro.value)


# --- erros -----------------------------------------------------------------


def test_http_406_vira_bcberror_com_serie_e_motivo():
    with pytest.raises(BCBError) as erro:
        bcb.buscar_serie(1, date(2016, 1, 1), HOJE, timeout=5, cliente=cliente_json({}, status=406))
    assert erro.value.serie == 1
    assert "406" in erro.value.motivo


def test_outro_status_de_erro_vira_bcberror():
    with pytest.raises(BCBError, match="HTTP 500"):
        bcb.buscar_serie(1, date(2026, 1, 1), HOJE, timeout=5, cliente=cliente_json({}, status=500))


def test_timeout_vira_bcberror():
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("lento demais", request=request)

    with pytest.raises(BCBError, match="timeout"):
        bcb.buscar_serie(
            1178, date(2026, 9, 1), HOJE, timeout=5, cliente=cliente_simulado(handler)
        )


def test_falha_de_rede_vira_bcberror():
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("sem rede", request=request)

    with pytest.raises(BCBError, match="falha de rede"):
        bcb.buscar_serie(
            1178, date(2026, 9, 1), HOJE, timeout=5, cliente=cliente_simulado(handler)
        )


@pytest.mark.parametrize("valor", ["abc", "13,65", None])
def test_valor_nao_numerico_vira_bcberror(valor):
    corpo = [{"data": "13/11/2026", "valor": valor}]
    with pytest.raises(BCBError, match="valor não numérico"):
        bcb.buscar_serie(1178, date(2026, 9, 1), HOJE, timeout=5, cliente=cliente_json(corpo))


def test_data_invalida_vira_bcberror():
    corpo = [{"data": "2026-11-13", "valor": "1"}]
    with pytest.raises(BCBError, match="data inválida"):
        bcb.buscar_serie(1178, date(2026, 9, 1), HOJE, timeout=5, cliente=cliente_json(corpo))


def test_resposta_vazia_vira_bcberror():
    with pytest.raises(BCBError, match="resposta vazia"):
        bcb.buscar_serie(1178, date(2026, 9, 1), HOJE, timeout=5, cliente=cliente_json([]))


def test_json_invalido_vira_bcberror():
    cliente = cliente_simulado(lambda request: httpx2.Response(200, content=b"<html>erro</html>"))
    with pytest.raises(BCBError, match="JSON"):
        bcb.buscar_serie(1178, date(2026, 9, 1), HOJE, timeout=5, cliente=cliente)


def test_json_que_nao_e_lista_vira_bcberror():
    with pytest.raises(BCBError, match="lista"):
        bcb.buscar_serie(
            1178, date(2026, 9, 1), HOJE, timeout=5, cliente=cliente_json({"erro": "x"})
        )


# --- internet (fora do pytest padrão) --------------------------------------


@pytest.mark.internet
def test_internet_busca_as_cinco_series_reais():
    """Roda com: pytest -m internet -s. Não confere valores fixos."""
    hoje = date.today()
    series = {
        "selic_efetiva (1178)": bcb.buscar_selic_efetiva(hoje),
        "ipca_12m (13522)": bcb.buscar_ipca_12m(hoje),
        "dolar_venda (1)": bcb.buscar_dolar_venda(hoje),
        "ibcbr (24364)": bcb.buscar_ibcbr(hoje),
    }
    meta = bcb.buscar_meta_selic(hoje)

    print(f"\nhoje = {hoje.isoformat()}")
    for nome, observacoes in series.items():
        assert observacoes, nome
        datas = [obs.data for obs in observacoes]
        assert datas == sorted(datas), f"{nome} fora de ordem"
        assert all(isinstance(obs.valor, float) for obs in observacoes), nome
        print(
            f"{nome}: n={len(observacoes)} primeira={datas[0].isoformat()} "
            f"ultima={datas[-1].isoformat()} ultimo_valor={observacoes[-1].valor}"
        )

    assert isinstance(meta.valor, float)
    assert meta.data <= hoje
    print(f"meta_selic (432): data={meta.data.isoformat()} valor={meta.valor}")
