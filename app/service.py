"""Pipeline da análise macro (R7.1): coleta -> indicadores -> regras -> LLM -> RespostaMacro.

O código determinístico decide (cenário, carteira base, preferência de indexador); o LLM só
escreve o texto e propõe um ajuste limitado (app/llm.py). Este módulo é SÍNCRONO, sem cache,
sem rota e sem threads (isso é a R7.2). Não arredonda: o schema arredonda ao construir.

Fuso: "hoje" é a data em UTC-3 fixo (sem zoneinfo). LIMITAÇÃO: isso vale porque o Brasil
não tem horário de verão desde 2019 (conhecimento geral, não verificado); se voltar,
atualizar FUSO_BRASIL.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import httpx2

from app.collectors import bcb
from app.collectors.bcb import BCBError, Observacao
from app.collectors.focus import ResultadoFocus, coletar_focus
from app.config import (
    LIMIAR_CRESCIMENTO_IBCBR,
    LIMIAR_IPCA_PCT,
    LIMITE_DESVIO_PP,
    get_settings,
)
from app.indicators import (
    IndicadorError,
    crescimento_ibcbr,
    juro_real_ex_post,
    juro_real_projetado,
    o_que_mudaria,
    volatilidade_dolar_anualizada,
)
from app.llm import EntradaLLM, ResultadoLLM, gerar_analise
from app.rules import (
    carteira_base,
    classificar_cenario,
    preferencia_indexador,
)
from app.schemas import (
    BlocoCenario,
    Carteira,
    Criterios,
    EntradasProjetado,
    IbcbrIndicador,
    Indicador,
    IndicadorCalculado,
    Indicadores,
    JanelaIbcbr,
    JuroReal,
    OQueMudaria,
    Pesos,
    RespostaMacro,
)

FUSO_BRASIL = timezone(timedelta(hours=-3))
AVISO_FIXO = "Simulação educacional. Não é recomendação de investimento."

_MES_ABREV = ("jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez")
_MES_NOME = (
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
)  # fmt: skip

# Convenção do SPEC §6 ("~2,5 meses" em 14/11/2026 com último ponto em agosto): dias desde o
# fim do mês do último ponto, divididos por 30.
_DIAS_POR_MES_DEFASAGEM = 30


class ServicoIndisponivelError(Exception):
    """Dados do BCB indisponíveis ou insuficientes. A R7.2 decide o que fazer (503/cache)."""

    def __init__(self, motivo: str):
        self.motivo = motivo
        super().__init__(motivo)


@dataclass(frozen=True)
class ColetoresBCB:
    """As 5 coletas do BCB; os testes trocam por funções falsas (hoje, *, cliente=None)."""

    selic_efetiva: Callable = bcb.buscar_selic_efetiva
    ipca_12m: Callable = bcb.buscar_ipca_12m
    dolar_venda: Callable = bcb.buscar_dolar_venda
    ibcbr: Callable = bcb.buscar_ibcbr
    meta_selic: Callable = bcb.buscar_meta_selic


def _fonte(chave: str) -> str:
    return f"BCB SGS {bcb.SERIES[chave]}"


def _coletar(serie: str, funcao: Callable, hoje: date, cliente: httpx2.Client):
    try:
        return funcao(hoje, cliente=cliente)
    except BCBError as erro:
        raise ServicoIndisponivelError(
            f"Dados do BCB indisponíveis: série {bcb.SERIES[serie]} ({erro.motivo})."
        ) from erro


def _ultimo(observacoes: list[Observacao]) -> Observacao:
    return max(observacoes, key=lambda o: o.data)


def _rotulos(meses: tuple[date, ...]) -> list[str]:
    return [_MES_ABREV[d.month - 1] for d in meses]


def _aviso_defasagem_ibcbr(hoje: date, ultimo_ponto: date) -> str | None:
    primeiro_do_mes_seguinte = (ultimo_ponto.replace(day=1) + timedelta(days=32)).replace(day=1)
    fim_do_mes = primeiro_do_mes_seguinte - timedelta(days=1)
    dias = (hoje - fim_do_mes).days
    if dias <= 0:
        return None
    meses = f"{dias / _DIAS_POR_MES_DEFASAGEM:.1f}".replace(".", ",")
    return (
        f"IBC-Br com defasagem de ~{meses} meses "
        f"(último ponto: {_MES_NOME[ultimo_ponto.month - 1]}/{ultimo_ponto.year})."
    )


def _nota_focus(focus: ResultadoFocus) -> str | None:
    datas = [m.data for m in (focus.ipca_12m, focus.selic_esperada) if m is not None]
    if not datas:
        return None
    return (
        f"Focus: mediana semanal de {max(datas):%d/%m/%Y}; "
        "baseCalculo não documentado (usado 0)."
    )


def _sem_duplicatas(avisos: list[str]) -> list[str]:
    return list(dict.fromkeys(avisos))


def gerar_resposta(
    agora: datetime | None = None,
    *,
    cliente: httpx2.Client | None = None,
    coletores: ColetoresBCB | None = None,
    focus: Callable[..., ResultadoFocus] | None = None,
    analisar: Callable[[EntradaLLM], ResultadoLLM] | None = None,
) -> RespostaMacro:
    """Roda o pipeline inteiro e devolve a resposta validada.

    `agora` (com fuso) e as peças `coletores`, `focus` e `analisar` são injetáveis para os
    testes. Um `cliente` injetado não é fechado aqui. Levanta ServicoIndisponivelError se
    qualquer série do BCB falhar ou faltar dado; Focus e LLM nunca derrubam.
    """
    if agora is None:
        agora = datetime.now(timezone.utc)
    if agora.tzinfo is None or agora.utcoffset() is None:
        raise ValueError("agora deve ter fuso horário")
    agora = agora.astimezone(FUSO_BRASIL)
    hoje = agora.date()

    coletores = coletores or ColetoresBCB()
    focus = focus or coletar_focus
    analisar = analisar or gerar_analise

    proprio_cliente = cliente is None
    if proprio_cliente:
        cliente = httpx2.Client(timeout=get_settings().BCB_TIMEOUT_SEGUNDOS)
    try:
        selic_obs = _coletar("selic_efetiva", coletores.selic_efetiva, hoje, cliente)
        ipca_obs = _coletar("ipca_12m", coletores.ipca_12m, hoje, cliente)
        dolar_obs = _coletar("dolar_venda", coletores.dolar_venda, hoje, cliente)
        ibcbr_obs = _coletar("ibcbr", coletores.ibcbr, hoje, cliente)
        meta = _coletar("meta_selic", coletores.meta_selic, hoje, cliente)
        resultado_focus = focus(hoje, cliente=cliente)
    finally:
        if proprio_cliente:
            cliente.close()

    selic = _ultimo(selic_obs)
    ipca = _ultimo(ipca_obs)
    dolar = _ultimo(dolar_obs)
    ultimo_ibcbr = _ultimo(ibcbr_obs)

    try:
        cresc = crescimento_ibcbr(ibcbr_obs)
        volatilidade = volatilidade_dolar_anualizada(dolar_obs)
        ex_post = juro_real_ex_post(selic.valor, ipca.valor)
        mudaria = o_que_mudaria(ipca.valor, ibcbr_obs)
        selic_esp = resultado_focus.selic_esperada
        ipca_esp = resultado_focus.ipca_12m
        projetado = None
        if selic_esp is not None and ipca_esp is not None:
            projetado = juro_real_projetado(selic_esp.valor, ipca_esp.valor)
    except IndicadorError as erro:
        raise ServicoIndisponivelError(f"Dados insuficientes: {erro}.") from erro

    cenario = classificar_cenario(cresc.variacao_pct, ipca.valor)
    base = Pesos(**carteira_base(cenario))
    preferencia, avisos_regra = preferencia_indexador(
        cenario, selic_esp.valor if selic_esp else None, meta.valor
    )

    bloco_cenario = BlocoCenario(
        classificacao=cenario,
        criterios=Criterios(
            crescimento_ibcbr_pct=cresc.variacao_pct,
            ipca_12m_pct=ipca.valor,
            limiar_crescimento_pct=LIMIAR_CRESCIMENTO_IBCBR,
            limiar_ipca_pct=LIMIAR_IPCA_PCT,
        ),
        o_que_mudaria=OQueMudaria(
            ipca_precisa_cair_pp=mudaria.ipca_precisa_cair_pp,
            ibcbr_proximo_mes_precisa_superar=mudaria.ibcbr_proximo_mes_precisa_superar,
        ),
    )
    indicadores = Indicadores(
        selic_efetiva_aa=Indicador(valor=selic.valor, data=selic.data, fonte=_fonte("selic_efetiva")),
        meta_selic_aa=Indicador(valor=meta.valor, data=meta.data, fonte=_fonte("meta_selic")),
        ipca_12m=Indicador(valor=ipca.valor, data=ipca.data, fonte=_fonte("ipca_12m")),
        dolar_venda=Indicador(valor=dolar.valor, data=dolar.data, fonte=_fonte("dolar_venda")),
        volatilidade_dolar_63d_anualizada_pct=IndicadorCalculado(
            valor=volatilidade,
            data=dolar.data,
            fonte=f"calculado sobre {_fonte('dolar_venda')}",
        ),
        ibcbr=IbcbrIndicador(
            fonte=_fonte("ibcbr"),
            janela_recente=JanelaIbcbr(
                media=cresc.media_recente, meses=_rotulos(cresc.meses_recente)
            ),
            janela_anterior=JanelaIbcbr(
                media=cresc.media_anterior, meses=_rotulos(cresc.meses_anterior)
            ),
        ),
    )
    entradas = None
    if projetado is not None:
        entradas = EntradasProjetado(
            selic_esperada_pct=selic_esp.valor,
            reuniao=selic_esp.reuniao,
            ipca_esperado_12m_pct=ipca_esp.valor,
            data_focus=max(selic_esp.data, ipca_esp.data),
        )
    juro_real = JuroReal(ex_post_pct=ex_post, projetado_12m_pct=projetado, entradas_projetado=entradas)

    avisos: list[str] = []
    for aviso in (_aviso_defasagem_ibcbr(hoje, ultimo_ibcbr.data), _nota_focus(resultado_focus)):
        if aviso:
            avisos.append(aviso)
    avisos += resultado_focus.avisos + avisos_regra
    avisos = _sem_duplicatas(avisos)

    entrada = EntradaLLM(
        cenario=bloco_cenario,
        indicadores=indicadores,
        juro_real=juro_real,
        carteira_base=base,
        limite_desvio_pp=LIMITE_DESVIO_PP,
        renda_fixa_preferencia=preferencia,
        avisos_de_qualidade=list(avisos),
    )
    analise = analisar(entrada)

    return RespostaMacro(
        gerado_em=agora,
        aviso=AVISO_FIXO,
        cenario=bloco_cenario,
        indicadores=indicadores,
        juro_real=juro_real,
        carteira=Carteira(
            base=base,
            sugerida=analise.carteira_sugerida,
            limite_desvio_pp=LIMITE_DESVIO_PP,
            renda_fixa_preferencia=preferencia,
        ),
        justificativa=analise.justificativa,
        avisos_de_qualidade=_sem_duplicatas(avisos + analise.avisos),
    )
