"""Coletor das séries do SGS (Banco Central do Brasil). Sem chave de API.

Cada função devolve observações (data, valor) ordenadas por data, ascendente.
Qualquer falha vira BCBError, com a série e o motivo.
"""

from datetime import date, datetime, timedelta
from typing import NamedTuple

import httpx2

from app.config import get_settings

# Códigos das séries (SPEC.md §2).
SERIES = {
    "selic_efetiva": 1178,
    "ipca_12m": 13522,
    "dolar_venda": 1,
    "ibcbr": 24364,
    "meta_selic": 432,
}

# URL padrão do SGS (conhecimento geral; o teste "internet" é quem confirma).
URL_BASE = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados"

FORMATO_DATA_BCB = "%d/%m/%Y"


class Observacao(NamedTuple):
    """Um ponto da série: data e valor numérico."""

    data: date
    valor: float


class BCBError(Exception):
    """Falha ao obter ou interpretar uma série do BCB."""

    def __init__(self, serie: int | str, motivo: str):
        self.serie = serie
        self.motivo = motivo
        super().__init__(f"BCB série {serie}: {motivo}")


def calcular_janela(hoje: date, dias: int) -> tuple[date, date]:
    """Devolve (data_inicial, data_final) = (hoje - dias, hoje)."""
    return hoje - timedelta(days=dias), hoje


def _parse_observacao(codigo: int, linha: object) -> Observacao:
    """Converte uma linha {"data": "dd/mm/aaaa", "valor": "texto"} em Observacao."""
    if not isinstance(linha, dict) or "data" not in linha or "valor" not in linha:
        raise BCBError(codigo, f"linha em formato inesperado: {linha!r}")
    try:
        data = datetime.strptime(linha["data"], FORMATO_DATA_BCB).date()
    except (TypeError, ValueError):
        raise BCBError(codigo, f"data inválida: {linha['data']!r}") from None
    try:
        valor = float(linha["valor"])
    except (TypeError, ValueError):
        raise BCBError(codigo, f"valor não numérico: {linha['valor']!r}") from None
    return Observacao(data, valor)


def buscar_serie(
    codigo: int,
    data_inicial: date,
    data_final: date,
    *,
    timeout: float,
    cliente: httpx2.Client | None = None,
) -> list[Observacao]:
    """Busca uma série no SGS no intervalo dado e devolve ordenada por data.

    `cliente` é opcional: os testes injetam um cliente com transporte simulado.
    """
    params = {
        "formato": "json",
        "dataInicial": data_inicial.strftime(FORMATO_DATA_BCB),
        "dataFinal": data_final.strftime(FORMATO_DATA_BCB),
    }
    url = URL_BASE.format(codigo=codigo)
    proprio_cliente = cliente is None
    if proprio_cliente:
        cliente = httpx2.Client(timeout=timeout)
    try:
        resposta = cliente.get(url, params=params)
    except httpx2.TimeoutException:
        raise BCBError(codigo, f"timeout após {timeout} s") from None
    except httpx2.HTTPError as erro:
        raise BCBError(codigo, f"falha de rede: {erro}") from None
    finally:
        if proprio_cliente:
            cliente.close()

    if resposta.status_code != 200:
        raise BCBError(codigo, f"HTTP {resposta.status_code}")
    try:
        corpo = resposta.json()
    except ValueError:
        raise BCBError(codigo, "resposta não é JSON válido") from None
    if not isinstance(corpo, list):
        raise BCBError(codigo, "JSON não é uma lista de observações")
    if not corpo:
        raise BCBError(codigo, "resposta vazia")

    return sorted(_parse_observacao(codigo, linha) for linha in corpo)


def _buscar_com_janela(
    codigo: int, hoje: date, dias: int, cliente: httpx2.Client | None
) -> list[Observacao]:
    inicio, fim = calcular_janela(hoje, dias)
    return buscar_serie(
        codigo,
        inicio,
        fim,
        timeout=get_settings().BCB_TIMEOUT_SEGUNDOS,
        cliente=cliente,
    )


def buscar_selic_efetiva(hoje: date, *, cliente: httpx2.Client | None = None) -> list[Observacao]:
    """Selic efetiva anualizada (% a.a., diária)."""
    return _buscar_com_janela(
        SERIES["selic_efetiva"], hoje, get_settings().JANELA_SELIC_DIAS, cliente
    )


def buscar_ipca_12m(hoje: date, *, cliente: httpx2.Client | None = None) -> list[Observacao]:
    """IPCA acumulado em 12 meses (%, mensal; data = dia 1 do mês de referência)."""
    return _buscar_com_janela(
        SERIES["ipca_12m"], hoje, get_settings().JANELA_IPCA_DIAS, cliente
    )


def buscar_dolar_venda(hoje: date, *, cliente: httpx2.Client | None = None) -> list[Observacao]:
    """Dólar comercial, venda (R$, dias úteis)."""
    return _buscar_com_janela(
        SERIES["dolar_venda"], hoje, get_settings().JANELA_DOLAR_DIAS, cliente
    )


def buscar_ibcbr(hoje: date, *, cliente: httpx2.Client | None = None) -> list[Observacao]:
    """IBC-Br com ajuste sazonal (índice, mensal)."""
    return _buscar_com_janela(
        SERIES["ibcbr"], hoje, get_settings().JANELA_IBCBR_DIAS, cliente
    )


def buscar_meta_selic(hoje: date, *, cliente: httpx2.Client | None = None) -> Observacao:
    """Meta da Selic vigente: a última linha com data <= hoje.

    A API pode devolver datas futuras; por isso o filtro é feito aqui também.
    """
    codigo = SERIES["meta_selic"]
    observacoes = _buscar_com_janela(
        codigo, hoje, get_settings().JANELA_META_SELIC_DIAS, cliente
    )
    vigentes = [obs for obs in observacoes if obs.data <= hoje]
    if not vigentes:
        raise BCBError(codigo, f"nenhuma linha com data <= {hoje.isoformat()}")
    return vigentes[-1]
