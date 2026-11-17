"""Simulador determinístico (R9.1). Sem rede, sem LLM, sem cache, sem pipeline.

Reusa as funções de app/rules.py e app/indicators.py; nenhuma regra é reimplementada.
Não existe carteira "sugerida" aqui (ela depende do LLM).
"""

from app.indicators import juro_real_ex_post
from app.rules import (
    Cenario,
    PreferenciaIndexador,
    carteira_base,
    classificar_cenario,
    preferencia_indexador,
)
from app.schemas import (
    BlocoCenarioSimulacao,
    EntradasSimulacao,
    Pesos,
    RespostaSimulacao,
)

AVISO_OPCIONAIS_IGNORADOS = (
    "Em ESTAGFLACAO a preferência é sempre POSFIXADA; a Selic esperada e a meta da Selic "
    "informadas não foram usadas."
)
AVISO_SEM_META = (
    "Você não informou a meta da Selic, então não dá para comparar com a Selic esperada; "
    "a preferência de indexador ficou POSFIXADA."
)
AVISO_SEM_ESPERADA = (
    "Você não informou a Selic esperada, então não dá para saber se os juros devem cair; "
    "a preferência de indexador ficou POSFIXADA."
)


def simular(
    ipca_12m_pct: float,
    crescimento_ibcbr_pct: float,
    selic_efetiva_aa_pct: float,
    selic_esperada_pct: float | None = None,
    meta_selic_pct: float | None = None,
) -> RespostaSimulacao:
    cenario = classificar_cenario(crescimento_ibcbr_pct, ipca_12m_pct)
    avisos: list[str] = []

    if cenario is Cenario.ESTAGFLACAO:
        preferencia, avisos_regra = preferencia_indexador(cenario, None, None)
        if selic_esperada_pct is not None or meta_selic_pct is not None:
            avisos.append(AVISO_OPCIONAIS_IGNORADOS)
    elif meta_selic_pct is None:
        # A regra exige a meta antes de olhar a Selic esperada: sem meta não se chama a regra.
        preferencia, avisos_regra = PreferenciaIndexador.POSFIXADA, [AVISO_SEM_META]
    else:
        preferencia, avisos_regra = preferencia_indexador(
            cenario, selic_esperada_pct, meta_selic_pct
        )
        if selic_esperada_pct is None:
            # O aviso da regra fala de "Focus fora do ar", que não existe no simulador.
            avisos_regra = [AVISO_SEM_ESPERADA]
    avisos += avisos_regra

    return RespostaSimulacao(
        entradas=EntradasSimulacao(
            ipca_12m_pct=ipca_12m_pct,
            crescimento_ibcbr_pct=crescimento_ibcbr_pct,
            selic_efetiva_aa_pct=selic_efetiva_aa_pct,
            selic_esperada_pct=selic_esperada_pct,
            meta_selic_pct=meta_selic_pct,
        ),
        cenario=BlocoCenarioSimulacao(classificacao=cenario),
        carteira_base=Pesos(**carteira_base(cenario)),
        renda_fixa_preferencia=preferencia,
        juro_real_ex_post_pct=juro_real_ex_post(selic_efetiva_aa_pct, ipca_12m_pct),
        avisos=avisos,
    )
