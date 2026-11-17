"""R9.1b: nova tentativa em HTTP 304 no coletor do BCB. Sem internet, sem sleep.

Respostas simuladas (httpx2.MockTransport) por roteiro: cada chamada recebe o próximo status.
"""

import logging
from datetime import date

import httpx2
import pytest

from app.collectors import bcb
from app.collectors.bcb import BCBError
from app.config import get_settings

HOJE = date(2026, 11, 17)
INICIO = date(2026, 5, 1)
CORPO = [{"data": "13/11/2026", "valor": "5.65"}]


@pytest.fixture(autouse=True)
def limpa_cache_settings():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class Roteiro:
    """Cliente simulado: devolve os status do roteiro em ordem (o último se repete)."""

    def __init__(self, *status):
        self.status = list(status)
        self.pedidos: list[httpx2.Request] = []

        def handler(request: httpx2.Request) -> httpx2.Response:
            self.pedidos.append(request)
            codigo = self.status[min(len(self.pedidos), len(self.status)) - 1]
            if codigo == 200:
                return httpx2.Response(200, json=CORPO)
            return httpx2.Response(codigo)

        self.cliente = httpx2.Client(transport=httpx2.MockTransport(handler))

    @property
    def chamadas(self) -> int:
        return len(self.pedidos)

    def iniciais(self) -> list[str]:
        return [p.url.params["dataInicial"] for p in self.pedidos]

    def finais(self) -> list[str]:
        return [p.url.params["dataFinal"] for p in self.pedidos]


def buscar(roteiro: Roteiro):
    return bcb.buscar_serie(1, INICIO, HOJE, timeout=5, cliente=roteiro.cliente)


def test_200_de_primeira_faz_uma_chamada_so():
    r = Roteiro(200)
    assert buscar(r) == [bcb.Observacao(date(2026, 11, 13), 5.65)]
    assert r.chamadas == 1
    assert r.iniciais() == ["01/05/2026"]


def test_304_e_depois_200_devolve_os_dados_com_inicio_um_dia_antes():
    r = Roteiro(304, 200)
    assert buscar(r) == [bcb.Observacao(date(2026, 11, 13), 5.65)]
    assert r.chamadas == 2
    assert r.iniciais() == ["01/05/2026", "30/04/2026"]


def test_304_304_e_depois_200_usa_um_e_dois_dias_antes():
    r = Roteiro(304, 304, 200)
    assert len(buscar(r)) == 1
    assert r.chamadas == 3
    assert r.iniciais() == ["01/05/2026", "30/04/2026", "29/04/2026"]


def test_data_final_nao_muda_entre_as_tentativas():
    r = Roteiro(304, 304, 200)
    buscar(r)
    assert r.finais() == ["17/11/2026"] * 3


def test_304_tres_vezes_levanta_bcberror_informando_as_3_tentativas():
    r = Roteiro(304)
    with pytest.raises(BCBError) as erro:
        buscar(r)
    assert r.chamadas == 3
    assert "HTTP 304" in str(erro.value)
    assert "3 tentativas" in str(erro.value)
    assert erro.value.serie == 1
    assert r.iniciais() == ["01/05/2026", "30/04/2026", "29/04/2026"]


@pytest.mark.parametrize("status", [406, 500, 503, 404])
def test_outros_status_nao_geram_nova_tentativa(status):
    r = Roteiro(status, 200)
    with pytest.raises(BCBError, match=f"HTTP {status}"):
        buscar(r)
    assert r.chamadas == 1


def test_304_seguido_de_406_ou_500_para_na_hora_com_o_novo_status():
    r = Roteiro(304, 500, 200)
    with pytest.raises(BCBError, match="HTTP 500"):
        buscar(r)
    assert r.chamadas == 2


def test_timeout_e_erro_de_rede_nao_geram_nova_tentativa():
    for erro, trecho in ((httpx2.ReadTimeout("x"), "timeout"), (httpx2.ConnectError("x"), "falha de rede")):
        chamadas = []

        def handler(request, erro=erro, chamadas=chamadas):
            chamadas.append(request)
            raise erro

        cliente = httpx2.Client(transport=httpx2.MockTransport(handler))
        with pytest.raises(BCBError, match=trecho):
            bcb.buscar_serie(1, INICIO, HOJE, timeout=5, cliente=cliente)
        assert len(chamadas) == 1


def test_log_info_a_cada_nova_tentativa_sem_url_nem_cabecalhos(caplog):
    r = Roteiro(304, 304, 200)
    with caplog.at_level(logging.INFO, logger="mfa.bcb"):
        buscar(r)
    mensagens = [rec.getMessage() for rec in caplog.records if rec.name == "mfa.bcb"]
    assert mensagens == [
        "BCB série 1: HTTP 304; tentativa 2/3 com dataInicial 30/04/2026",
        "BCB série 1: HTTP 304; tentativa 3/3 com dataInicial 29/04/2026",
    ]
    assert all(rec.levelno == logging.INFO for rec in caplog.records)
    assert not any("http" in m.lower().replace("http 304", "") for m in mensagens)


def test_sem_304_nao_ha_log(caplog):
    with caplog.at_level(logging.INFO, logger="mfa.bcb"):
        buscar(Roteiro(200))
    assert caplog.records == []


def test_funcao_por_serie_usa_a_janela_padrao_deslocada_no_304():
    r = Roteiro(304, 200)
    bcb.buscar_dolar_venda(HOJE, cliente=r.cliente)
    dias = get_settings().JANELA_DOLAR_DIAS
    inicio, _ = bcb.calcular_janela(HOJE, dias)
    assert r.iniciais() == [
        inicio.strftime("%d/%m/%Y"),
        bcb.calcular_janela(HOJE, dias + 1)[0].strftime("%d/%m/%Y"),
    ]


def test_cliente_proprio_e_fechado_uma_vez_mesmo_com_retentativas(monkeypatch):
    r = Roteiro(304, 200)
    fechados = []

    class ClienteProprio:
        def __init__(self, *a, **k):
            pass

        def get(self, url, params=None):
            return r.cliente.get(url, params=params)

        def close(self):
            fechados.append(1)

    monkeypatch.setattr(bcb.httpx2, "Client", ClienteProprio)
    assert len(bcb.buscar_serie(1, INICIO, HOJE, timeout=5)) == 1
    assert fechados == [1]
    assert r.chamadas == 2
