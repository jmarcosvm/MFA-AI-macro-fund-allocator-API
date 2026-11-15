"""Coletor do Focus (expectativas de mercado, Olinda/BCB). Sem chave de API.

Busca duas medianas (SPEC.md §3.3), ambas com baseCalculo=0:
- IPCA esperado para os próximos 12 meses (Suavizada=S);
- Selic esperada na reunião do Copom mais próxima de hoje + 12 meses.

Diferente do coletor do SGS, aqui a falha NÃO derruba a API: cada campo que
não puder ser obtido vira None e entra um aviso em português.
"""

import calendar
from datetime import date, datetime
from typing import NamedTuple
from urllib.parse import quote, urlencode

import httpx2

from app.config import CALENDARIO_COPOM, get_settings

URL_BASE = "https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/odata/{recurso}"
RECURSO_IPCA_12M = "ExpectativasMercadoInflacao12Meses"
RECURSO_SELIC = "ExpectativasMercadoSelic"

# SPEC.md §3.3: baseCalculo=0 (mais respondentes); significado não documentado.
BASE_CALCULO = 0


class MedianaFocus(NamedTuple):
    """Mediana do Focus numa data de coleta (a mais recente disponível)."""

    valor: float
    data: date


class SelicEsperada(NamedTuple):
    """Mediana da Selic esperada para uma reunião do Copom."""

    valor: float
    data: date  # data do Focus
    reuniao: str  # "R#/aaaa"
    data_reuniao: date  # dia da decisão, vindo do calendário do código
    distancia_dias: int  # |(hoje + 12 meses) - data_reuniao|, em dias


class ReuniaoEscolhida(NamedTuple):
    """Reunião do Copom mais próxima de hoje + 12 meses."""

    reuniao: str  # "R#/aaaa"
    data_reuniao: date
    alvo: date  # hoje + 12 meses
    distancia_dias: int  # |alvo - data_reuniao|, em dias


class ResultadoFocus(NamedTuple):
    """Resultado da coleta. Campo None = indisponível (ver `avisos`)."""

    ipca_12m: MedianaFocus | None
    selic_esperada: SelicEsperada | None
    avisos: list[str]


class FocusError(Exception):
    """Falha ao obter ou interpretar um recurso do Focus (uso interno)."""

    def __init__(self, recurso: str, motivo: str):
        self.recurso = recurso
        self.motivo = motivo
        super().__init__(f"Focus {recurso}: {motivo}")


def somar_meses(dia: date, meses: int) -> date:
    """Soma meses a uma data; se o dia não existir no mês de destino, usa o último dia."""
    indice = dia.year * 12 + (dia.month - 1) + meses
    ano, mes = divmod(indice, 12)
    mes += 1
    return date(ano, mes, min(dia.day, calendar.monthrange(ano, mes)[1]))


def escolher_reuniao(
    hoje: date, calendario: dict[str, date] | None = None
) -> ReuniaoEscolhida | None:
    """Reunião do Copom cuja data de decisão fica mais perto de hoje + 12 meses.

    Em empate, vence a mais cedo. Não depende da ordem do dicionário. Devolve None
    só se o calendário estiver vazio; a tolerância é aplicada por quem chama.
    """
    calendario = CALENDARIO_COPOM if calendario is None else calendario
    if not calendario:
        return None
    alvo = somar_meses(hoje, 12)
    nome, data = min(calendario.items(), key=lambda item: (abs((item[1] - alvo).days), item[1]))
    return ReuniaoEscolhida(nome, data, alvo, abs((data - alvo).days))


def _buscar_mediana_recente(
    recurso: str,
    filtro: str,
    *,
    timeout: float,
    cliente: httpx2.Client | None = None,
) -> MedianaFocus:
    """Mediana da data mais recente que atende ao filtro OData."""
    params = {
        "$format": "json",
        "$top": "1",
        "$orderby": "Data desc",
        "$filter": f"{filtro} and baseCalculo eq {BASE_CALCULO}",
    }
    # O Olinda responde HTTP 400 se o espaço vier como "+"; precisa ser "%20".
    url = URL_BASE.format(recurso=recurso) + "?" + urlencode(params, quote_via=quote)
    proprio_cliente = cliente is None
    if proprio_cliente:
        cliente = httpx2.Client(timeout=timeout)
    try:
        resposta = cliente.get(url)
    except httpx2.TimeoutException:
        raise FocusError(recurso, f"timeout após {timeout} s") from None
    except httpx2.HTTPError as erro:
        raise FocusError(recurso, f"falha de rede: {erro}") from None
    finally:
        if proprio_cliente:
            cliente.close()

    if resposta.status_code != 200:
        raise FocusError(recurso, f"HTTP {resposta.status_code}")
    try:
        corpo = resposta.json()
    except ValueError:
        raise FocusError(recurso, "resposta não é JSON válido") from None
    linhas = corpo.get("value") if isinstance(corpo, dict) else None
    if not isinstance(linhas, list):
        raise FocusError(recurso, "JSON sem a lista 'value'")
    if not linhas:
        raise FocusError(recurso, "resposta vazia")

    linha = linhas[0]
    try:
        data = datetime.strptime(linha["Data"], "%Y-%m-%d").date()
        valor = float(linha["Mediana"])
    except (KeyError, TypeError, ValueError):
        raise FocusError(recurso, f"linha em formato inesperado: {linha!r}") from None
    return MedianaFocus(valor, data)


def buscar_ipca_12m(
    *, cliente: httpx2.Client | None = None
) -> MedianaFocus:
    """IPCA esperado 12 meses à frente (Suavizada=S), mediana mais recente."""
    return _buscar_mediana_recente(
        RECURSO_IPCA_12M,
        "Indicador eq 'IPCA' and Suavizada eq 'S'",
        timeout=get_settings().BCB_TIMEOUT_SEGUNDOS,
        cliente=cliente,
    )


def buscar_selic_reuniao(
    reuniao: str, *, cliente: httpx2.Client | None = None
) -> MedianaFocus:
    """Selic esperada para uma reunião ('R#/aaaa'), mediana mais recente."""
    return _buscar_mediana_recente(
        RECURSO_SELIC,
        f"Reuniao eq '{reuniao}'",
        timeout=get_settings().BCB_TIMEOUT_SEGUNDOS,
        cliente=cliente,
    )


def coletar_focus(
    hoje: date,
    *,
    calendario: dict[str, date] | None = None,
    tolerancia_dias: int | None = None,
    cliente: httpx2.Client | None = None,
) -> ResultadoFocus:
    """Coleta IPCA 12m e Selic esperada. Nunca levanta exceção do Focus.

    `tolerancia_dias` (padrão: TOLERANCIA_REUNIAO_DIAS) é a distância máxima entre
    hoje + 12 meses e a reunião escolhida; acima dela a Selic esperada vira None.
    """
    if tolerancia_dias is None:
        tolerancia_dias = get_settings().TOLERANCIA_REUNIAO_DIAS
    avisos: list[str] = []

    ipca = None
    try:
        ipca = buscar_ipca_12m(cliente=cliente)
    except FocusError as erro:
        avisos.append(f"Focus indisponível para o IPCA esperado 12m ({erro.motivo}).")

    selic = None
    tabela = CALENDARIO_COPOM if calendario is None else calendario
    escolhida = escolher_reuniao(hoje, tabela)
    if escolhida is None:
        avisos.append("Calendário do Copom vazio: Selic esperada indisponível.")
    elif escolhida.distancia_dias > tolerancia_dias:
        fim_nome, fim_data = max(tabela.items(), key=lambda item: item[1])
        avisos.append(
            "Selic esperada indisponível: a reunião mais próxima de hoje + 12 meses "
            f"(alvo {escolhida.alvo:%d/%m/%Y}) é {escolhida.reuniao} "
            f"({escolhida.data_reuniao:%d/%m/%Y}), a {escolhida.distancia_dias} dias; "
            f"tolerância de {tolerancia_dias} dias. O calendário do Copom termina em "
            f"{fim_data:%d/%m/%Y} ({fim_nome}); atualize CALENDARIO_COPOM."
        )
    else:
        reuniao = escolhida.reuniao
        try:
            mediana = buscar_selic_reuniao(reuniao, cliente=cliente)
            selic = SelicEsperada(
                mediana.valor,
                mediana.data,
                reuniao,
                escolhida.data_reuniao,
                escolhida.distancia_dias,
            )
        except FocusError as erro:
            avisos.append(f"Focus indisponível para a Selic esperada ({reuniao}): {erro.motivo}.")

    return ResultadoFocus(ipca, selic, avisos)
