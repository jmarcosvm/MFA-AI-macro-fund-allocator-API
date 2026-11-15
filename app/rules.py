"""Regras determinísticas (SPEC.md §3.2, §3.4 e §3.5). Funções puras: recebem números e
devolvem decisões. Sem rede, sem pandas, sem variável de ambiente.

Os números chegam SEM arredondamento: o crescimento é comparado com o limiar como veio.
Consequência: um crescimento de 0,004 aparece como 0,00 no contrato (a R5 arredonda só
para exibir), mas classifica como EXPANSAO. Entradas inválidas (None, NaN, infinito)
levantam RegraError: nunca se chuta um cenário.
"""

from enum import Enum
from math import isfinite

from app.config import LIMIAR_CRESCIMENTO_IBCBR, LIMIAR_IPCA_PCT, PASSO_COPOM_PP


class Cenario(str, Enum):
    """Cenário macro (conjunto fechado). O valor é a string do contrato (SPEC.md §6)."""

    EXPANSAO = "EXPANSAO"
    CONTRACAO = "CONTRACAO"
    ESTAGFLACAO = "ESTAGFLACAO"


class PreferenciaIndexador(str, Enum):
    """Preferência de indexador da renda fixa (SPEC.md §3.5)."""

    PREFIXADA = "PREFIXADA"
    POSFIXADA = "POSFIXADA"


class RegraError(Exception):
    """Entrada inválida para uma regra (None, NaN, infinito ou tipo errado)."""


# Carteira base (SPEC.md §3.4), em frações que somam 1,0. Chaves do contrato (§6).
_CARTEIRA_BASE: dict[Cenario, dict[str, float]] = {
    Cenario.EXPANSAO: {"renda_fixa": 0.35, "fundos_cambiais": 0.10, "renda_variavel": 0.55},
    Cenario.CONTRACAO: {"renda_fixa": 0.55, "fundos_cambiais": 0.20, "renda_variavel": 0.25},
    Cenario.ESTAGFLACAO: {"renda_fixa": 0.60, "fundos_cambiais": 0.25, "renda_variavel": 0.15},
}


def _validar_numero(nome: str, valor: object) -> float:
    """Exige um número finito (bool não vale); devolve o valor como float."""
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        raise RegraError(f"{nome} deve ser um número, recebi {valor!r}")
    if not isfinite(valor):
        raise RegraError(f"{nome} deve ser um número finito, recebi {valor!r}")
    return float(valor)


def classificar_cenario(crescimento_pct: float, ipca_12m_pct: float) -> Cenario:
    """SPEC.md §3.2. Crescimento <= 0 e IPCA > 4,5 -> ESTAGFLACAO; crescimento <= 0 e
    IPCA <= 4,5 -> CONTRACAO; crescimento > 0 -> EXPANSAO. Sem faixa neutra."""
    crescimento = _validar_numero("crescimento do IBC-Br", crescimento_pct)
    ipca = _validar_numero("IPCA 12m", ipca_12m_pct)
    if crescimento > LIMIAR_CRESCIMENTO_IBCBR:
        return Cenario.EXPANSAO
    if ipca > LIMIAR_IPCA_PCT:
        return Cenario.ESTAGFLACAO
    return Cenario.CONTRACAO


def carteira_base(cenario: Cenario) -> dict[str, float]:
    """SPEC.md §3.4. Devolve uma CÓPIA da carteira base (frações que somam 1,0)."""
    if not isinstance(cenario, Cenario):
        raise RegraError(f"cenário inválido: {cenario!r}")
    return dict(_CARTEIRA_BASE[cenario])


def preferencia_indexador(
    cenario: Cenario,
    selic_esperada_pct: float | None,
    meta_selic_pct: float | None,
) -> tuple[PreferenciaIndexador, list[str]]:
    """SPEC.md §3.5. Devolve (preferência, avisos em português).

    - ESTAGFLACAO -> POSFIXADA, sempre (a Selic esperada nem é usada; sem aviso).
    - Senão, Selic esperada <= meta - 0,25 p.p. -> PREFIXADA; caso contrário POSFIXADA.
    - Selic esperada None (Focus indisponível) fora de ESTAGFLACAO -> POSFIXADA + aviso.
    """
    if not isinstance(cenario, Cenario):
        raise RegraError(f"cenário inválido: {cenario!r}")
    if cenario is Cenario.ESTAGFLACAO:
        return PreferenciaIndexador.POSFIXADA, []

    meta = _validar_numero("meta Selic atual", meta_selic_pct)
    if selic_esperada_pct is None:
        aviso = (
            "A Selic esperada não estava disponível (Focus fora do ar ou reunião do "
            "Copom fora da tolerância); a preferência foi definida como POSFIXADA."
        )
        return PreferenciaIndexador.POSFIXADA, [aviso]

    esperada = _validar_numero("Selic esperada", selic_esperada_pct)
    # Arredonda a diferença para evitar resíduo de ponto flutuante: p.ex. 15,81 - 16,06
    # dá -0,24999999999999822 em float, embora o valor decimal seja exatamente -0,25.
    diferenca = round(esperada - meta, 6)
    if diferenca <= -PASSO_COPOM_PP:
        return PreferenciaIndexador.PREFIXADA, []
    return PreferenciaIndexador.POSFIXADA, []
