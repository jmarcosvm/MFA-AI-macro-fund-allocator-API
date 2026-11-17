"""Indicadores macro (SPEC.md §3). Funções puras: sem rede e sem variável de ambiente.

Entram listas de observações (data, valor) como as devolvidas por app/collectors/bcb.py
(ou qualquer objeto com .data e .valor). Os resultados saem SEM arredondamento; o
arredondamento fica para o contrato (R5). Dados insuficientes ou inválidos viram
IndicadorError, com mensagem clara.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from math import isfinite, sqrt
from typing import Protocol

import pandas as pd

from app.config import LIMIAR_CRESCIMENTO_IBCBR, LIMIAR_IPCA_PCT

# Constantes do SPEC.
IBCBR_PONTOS_POR_JANELA = 3  # média de 3 meses vs média dos 3 meses anteriores
IBCBR_PONTOS_NECESSARIOS = 2 * IBCBR_PONTOS_POR_JANELA  # 6
DOLAR_RETORNOS = 63  # janela de 63 dias úteis
DOLAR_PRECOS_NECESSARIOS = DOLAR_RETORNOS + 1  # 63 retornos exigem 64 preços
DIAS_UTEIS_ANO = 252


class _Observacao(Protocol):
    data: date
    valor: float


class IndicadorError(Exception):
    """Dados insuficientes ou inválidos para calcular um indicador."""

    def __init__(self, indicador: str, motivo: str):
        self.indicador = indicador
        self.motivo = motivo
        super().__init__(f"{indicador}: {motivo}")


@dataclass(frozen=True)
class CrescimentoIbcbr:
    """Médias das duas janelas de 3 meses e a variação % entre elas."""

    media_recente: float
    media_anterior: float
    meses_recente: tuple[date, ...]
    meses_anterior: tuple[date, ...]
    variacao_pct: float
    # R9.1: valores brutos de cada janela, cronológicos (mesma ordem de `meses_*`).
    valores_recente: tuple[float, ...] = ()
    valores_anterior: tuple[float, ...] = ()


@dataclass(frozen=True)
class OQueMudaria:
    """Distâncias aos limiares. None = já está do lado favorável (nada a mudar)."""

    ipca_precisa_cair_pp: float | None
    ibcbr_proximo_mes_precisa_superar: float | None


def _ultimas(
    indicador: str, observacoes: Sequence[_Observacao], quantidade: int
) -> list[_Observacao]:
    """Ordena por data e devolve as `quantidade` últimas; erro se houver menos."""
    if len(observacoes) < quantidade:
        raise IndicadorError(
            indicador,
            f"precisa de pelo menos {quantidade} observações, recebi {len(observacoes)}",
        )
    ordenadas = sorted(observacoes, key=lambda obs: obs.data)
    ultimas = ordenadas[-quantidade:]
    for obs in ultimas:
        if not isfinite(obs.valor):
            raise IndicadorError(indicador, f"valor inválido em {obs.data}: {obs.valor!r}")
    return ultimas


def _ultimas_ibcbr(observacoes: Sequence[_Observacao]) -> list[_Observacao]:
    return _ultimas("IBC-Br", observacoes, IBCBR_PONTOS_NECESSARIOS)


def crescimento_ibcbr(observacoes: Sequence[_Observacao]) -> CrescimentoIbcbr:
    """Média dos 3 últimos meses vs média dos 3 meses anteriores (SPEC.md §3.2).

    Só as 6 últimas observações contam; a lista pode ter mais (a R1 mostrou que
    a série traz 1 ponto a mais no início da janela).
    """
    ultimas = _ultimas_ibcbr(observacoes)
    serie = pd.Series([obs.valor for obs in ultimas], dtype="float64")
    anterior = serie.iloc[:IBCBR_PONTOS_POR_JANELA]
    recente = serie.iloc[IBCBR_PONTOS_POR_JANELA:]
    media_anterior = float(anterior.mean())
    media_recente = float(recente.mean())
    if media_anterior <= 0:
        raise IndicadorError("IBC-Br", f"média anterior não positiva: {media_anterior}")
    return CrescimentoIbcbr(
        media_recente=media_recente,
        media_anterior=media_anterior,
        meses_recente=tuple(obs.data for obs in ultimas[IBCBR_PONTOS_POR_JANELA:]),
        meses_anterior=tuple(obs.data for obs in ultimas[:IBCBR_PONTOS_POR_JANELA]),
        variacao_pct=(media_recente / media_anterior - 1) * 100,
        valores_recente=tuple(float(v) for v in recente),
        valores_anterior=tuple(float(v) for v in anterior),
    )


def ultimos_pontos(observacoes: Sequence[_Observacao] | None, quantidade: int) -> list[_Observacao]:
    """As `quantidade` últimas observações VÁLIDAS, em ordem crescente de data (R9.1).

    Descarta valor não finito ou não numérico (NaN, inf, None) e data repetida (vale a última
    que apareceu). Nunca preenche: menos pontos válidos = lista menor; nada válido = [].
    """
    if not observacoes or quantidade <= 0:
        return []
    por_data: dict[date, _Observacao] = {}
    for obs in observacoes:
        valor = getattr(obs, "valor", None)
        if isinstance(valor, bool) or not isinstance(valor, (int, float)) or not isfinite(valor):
            continue
        por_data[obs.data] = obs
    return [por_data[d] for d in sorted(por_data)][-quantidade:]


def volatilidade_dolar_anualizada(observacoes: Sequence[_Observacao]) -> float:
    """Volatilidade anualizada do dólar, em %: std dos retornos diários x raiz(252).

    Janela de 63 retornos simples (pct_change), que exigem os 64 últimos preços.
    Desvio-padrão amostral (ddof=1, padrão do pandas).
    """
    ultimas = _ultimas("Dólar", observacoes, DOLAR_PRECOS_NECESSARIOS)
    precos = pd.Series([obs.valor for obs in ultimas], dtype="float64")
    if (precos <= 0).any():
        raise IndicadorError("Dólar", "preço não positivo na janela")
    retornos = precos.pct_change().dropna()
    return float(retornos.std(ddof=1)) * sqrt(DIAS_UTEIS_ANO) * 100


def _fisher(indicador: str, selic: float, ipca: float) -> float:
    if 1 + ipca / 100 <= 0:
        raise IndicadorError(indicador, f"IPCA {ipca} inválido (1 + IPCA/100 <= 0)")
    return ((1 + selic / 100) / (1 + ipca / 100) - 1) * 100


def juro_real_ex_post(selic_efetiva: float, ipca_12m: float) -> float:
    """Juro real ex-post em %: (1 + Selic/100) / (1 + IPCA 12m/100) - 1."""
    return _fisher("Juro real ex-post", selic_efetiva, ipca_12m)


def juro_real_projetado(
    selic_esperada: float | None, ipca_esperado_12m: float | None
) -> float | None:
    """Juro real projetado em %. None se qualquer entrada for None (Focus indisponível)."""
    if selic_esperada is None or ipca_esperado_12m is None:
        return None
    return _fisher("Juro real projetado", selic_esperada, ipca_esperado_12m)


def o_que_mudaria(
    ipca_12m: float, observacoes_ibcbr: Sequence[_Observacao]
) -> OQueMudaria:
    """Distâncias aos limiares da regra do cenário.

    - ipca_precisa_cair_pp = IPCA 12m - 4,5; None se já for <= 4,5.
    - ibcbr_proximo_mes_precisa_superar: valor x do próximo mês para o qual a média
      (m5, m6, x) iguala a média (m2, m3, m4), isto é, crescimento 0:
      x = (m2 + m3 + m4) - (m5 + m6), sobre as 6 últimas observações (m1..m6).
      None se o crescimento atual já for > 0. A fórmula vale para o limiar 0 do SPEC.
    """
    ipca_pp = ipca_12m - LIMIAR_IPCA_PCT
    ipca_precisa_cair = ipca_pp if ipca_pp > 0 else None

    crescimento = crescimento_ibcbr(observacoes_ibcbr)
    ultimas = _ultimas_ibcbr(observacoes_ibcbr)
    v = [obs.valor for obs in ultimas]
    if crescimento.variacao_pct > LIMIAR_CRESCIMENTO_IBCBR:
        ibcbr_precisa_superar = None
    else:
        ibcbr_precisa_superar = (v[1] + v[2] + v[3]) - (v[4] + v[5])
    return OQueMudaria(
        ipca_precisa_cair_pp=ipca_precisa_cair,
        ibcbr_proximo_mes_precisa_superar=ibcbr_precisa_superar,
    )
