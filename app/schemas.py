"""Contrato de saída (SPEC.md §6) com as regras de negócio validadas pelo Pydantic.

Este módulo só define FORMATO e REGRAS: não coleta dados, não chama rede nem LLM e não
monta a resposta (isso é a R7). Os campos CALCULADOS são arredondados na construção, só
para exibir (os módulos de cálculo e as regras trabalham sem arredondar); os valores
coletados passam como vieram.
"""

from datetime import date
from typing import Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.config import (
    NARRACAO_MAX_CARACTERES,
    RESUMO_LINHA_MAX_CARACTERES,
    RESUMO_MAX_LINHAS,
    RESUMO_MIN_LINHAS,
    TEXTO_MAX_CARACTERES,
)
from app.rules import Cenario, PreferenciaIndexador

# Tolerância da soma dos pesos da carteira: abs(soma - 1,0) <= 1e-6.
TOLERANCIA_SOMA_PESOS: float = 1e-6

# Casas decimais ao comparar diferenças de pesos (evita resíduo de ponto flutuante:
# 0,40 - 0,25 dá 0,15000000000000002 em float, embora seja exatamente 15 p.p.).
_CASAS_COMPARACAO = 6

_CLASSES = ("renda_fixa", "fundos_cambiais", "renda_variavel")

# Número finito (NaN e infinito são rejeitados).
_Num = Field(allow_inf_nan=False)


def _arredondar(valor: float | None, casas: int) -> float | None:
    """Arredonda para exibir e troca -0.0 por 0.0 (o JSON não pode sair com "-0.0")."""
    if valor is None:
        return None
    r = round(valor, casas)
    return 0.0 if r == 0 else r


class _Modelo(BaseModel):
    """Base: campos desconhecidos são rejeitados."""

    model_config = ConfigDict(extra="forbid")


def _arredonda(*campos: str, casas: int):
    """Cria um validador que arredonda os campos dados (aplicado depois da validação)."""

    def _validar(cls, v):
        return _arredondar(v, casas)

    return field_validator(*campos, mode="after")(_validar)


# ---------------------------------------------------------------- cenário


class Criterios(_Modelo):
    crescimento_ibcbr_pct: float = _Num
    ipca_12m_pct: float = _Num
    limiar_crescimento_pct: float = _Num
    limiar_ipca_pct: float = _Num

    _arred = _arredonda("crescimento_ibcbr_pct", "ipca_12m_pct", casas=2)


class OQueMudaria(_Modelo):
    """None = já está do lado favorável (nada a mudar), como em indicators.py."""

    ipca_precisa_cair_pp: float | None = Field(allow_inf_nan=False)
    ibcbr_proximo_mes_precisa_superar: float | None = Field(allow_inf_nan=False)

    _arred = _arredonda(
        "ipca_precisa_cair_pp", "ibcbr_proximo_mes_precisa_superar", casas=2
    )


class BlocoCenario(_Modelo):
    classificacao: Cenario
    criterios: Criterios
    o_que_mudaria: OQueMudaria


# ---------------------------------------------------------------- indicadores


class Indicador(_Modelo):
    """Valor coletado (ou calculado pelo código), com data e fonte. Sem arredondar aqui."""

    valor: float = _Num
    data: date
    fonte: str


class IndicadorCalculado(Indicador):
    """Indicador calculado (volatilidade): o valor é arredondado a 2 casas."""

    _arred = _arredonda("valor", casas=2)


class JanelaIbcbr(_Modelo):
    media: float = _Num
    meses: list[str]

    _arred = _arredonda("media", casas=4)


class IbcbrIndicador(_Modelo):
    fonte: str
    janela_recente: JanelaIbcbr
    janela_anterior: JanelaIbcbr


class Indicadores(_Modelo):
    selic_efetiva_aa: Indicador
    # Meta Selic atual (SGS 432): contra ela a regra do indexador compara a Selic esperada.
    meta_selic_aa: Indicador
    ipca_12m: Indicador
    dolar_venda: Indicador
    volatilidade_dolar_63d_anualizada_pct: IndicadorCalculado
    ibcbr: IbcbrIndicador


# ---------------------------------------------------------------- juro real


class EntradasProjetado(_Modelo):
    selic_esperada_pct: float = _Num
    reuniao: str
    ipca_esperado_12m_pct: float = _Num
    data_focus: date

    _arred_selic = _arredonda("selic_esperada_pct", casas=2)
    _arred_ipca = _arredonda("ipca_esperado_12m_pct", casas=4)


class JuroReal(_Modelo):
    ex_post_pct: float = _Num
    # Os dois ficam None juntos (Focus indisponível) ou preenchidos juntos.
    projetado_12m_pct: float | None = Field(allow_inf_nan=False)
    entradas_projetado: EntradasProjetado | None

    _arred = _arredonda("ex_post_pct", "projetado_12m_pct", casas=2)

    @model_validator(mode="after")
    def _projetado_e_entradas_juntos(self) -> "JuroReal":
        if (self.projetado_12m_pct is None) != (self.entradas_projetado is None):
            raise ValueError(
                "projetado_12m_pct e entradas_projetado devem ser ambos None "
                "ou ambos preenchidos"
            )
        return self


# ---------------------------------------------------------------- carteira


class Pesos(_Modelo):
    """Pesos como frações (0,60 = 60%). Cada um entre 0 e 1."""

    renda_fixa: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    fundos_cambiais: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    renda_variavel: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)

    def soma(self) -> float:
        return sum(getattr(self, c) for c in _CLASSES)


class Carteira(_Modelo):
    base: Pesos
    sugerida: Pesos
    limite_desvio_pp: float = Field(gt=0.0, allow_inf_nan=False)
    renda_fixa_preferencia: PreferenciaIndexador

    @model_validator(mode="after")
    def _regras_da_carteira(self) -> "Carteira":
        for nome in ("base", "sugerida"):
            soma = getattr(self, nome).soma()
            if abs(soma - 1.0) > TOLERANCIA_SOMA_PESOS:
                raise ValueError(f"a soma de carteira.{nome} deve ser 1,0, recebi {soma}")
        limite = self.limite_desvio_pp / 100  # p.p. -> fração
        for c in _CLASSES:
            desvio = round(abs(getattr(self.sugerida, c) - getattr(self.base, c)), _CASAS_COMPARACAO)
            if desvio > round(limite, _CASAS_COMPARACAO):
                raise ValueError(
                    f"{c} desvia {desvio * 100:.2f} p.p. da base; "
                    f"o máximo é {self.limite_desvio_pp} p.p."
                )
        return self


# ---------------------------------------------------------------- justificativa


class Justificativa(_Modelo):
    texto: str
    resumo: str  # 2 a 3 linhas, para o topo da tela
    narracao_o_que_mudaria: str  # prosa sobre os valores de o_que_mudaria (calculados no código)
    origem: Literal["llm", "fallback"]
    provedor: str | None = None

    @field_validator("texto", "resumo", "narracao_o_que_mudaria", mode="after")
    @classmethod
    def _texto_nao_vazio(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("o texto não pode ser vazio")
        return v

    @field_validator("texto", mode="after")
    @classmethod
    def _teto_do_texto(cls, v: str) -> str:
        if len(v) > TEXTO_MAX_CARACTERES:
            raise ValueError(f"texto passa de {TEXTO_MAX_CARACTERES} caracteres")
        return v

    @field_validator("narracao_o_que_mudaria", mode="after")
    @classmethod
    def _teto_da_narracao(cls, v: str) -> str:
        if len(v) > NARRACAO_MAX_CARACTERES:
            raise ValueError(
                f"narracao_o_que_mudaria passa de {NARRACAO_MAX_CARACTERES} caracteres"
            )
        return v

    @field_validator("resumo", mode="after")
    @classmethod
    def _resumo_de_2_a_3_linhas(cls, v: str) -> str:
        linhas = [linha for linha in v.splitlines() if linha.strip()]
        if not RESUMO_MIN_LINHAS <= len(linhas) <= RESUMO_MAX_LINHAS:
            raise ValueError(
                f"o resumo deve ter de {RESUMO_MIN_LINHAS} a {RESUMO_MAX_LINHAS} linhas "
                f"não vazias, recebi {len(linhas)}"
            )
        if any(len(linha) > RESUMO_LINHA_MAX_CARACTERES for linha in linhas):
            raise ValueError(
                f"cada linha do resumo deve ter no máximo {RESUMO_LINHA_MAX_CARACTERES} caracteres"
            )
        return v

    @model_validator(mode="after")
    def _provedor_conforme_origem(self) -> "Justificativa":
        if self.origem == "fallback" and self.provedor is not None:
            raise ValueError("com origem 'fallback' o provedor não se aplica (deve ser None)")
        if self.origem == "llm" and not self.provedor:
            raise ValueError("com origem 'llm' o provedor é obrigatório")
        return self


# ---------------------------------------------------------------- raiz


class RespostaMacro(_Modelo):
    gerado_em: AwareDatetime  # exige fuso horário
    aviso: str
    cenario: BlocoCenario
    indicadores: Indicadores
    juro_real: JuroReal
    carteira: Carteira
    justificativa: Justificativa
    avisos_de_qualidade: list[str]

    @model_validator(mode="after")
    def _fallback_usa_carteira_base(self) -> "RespostaMacro":
        if self.justificativa.origem == "fallback":
            for c in _CLASSES:
                dif = round(
                    abs(getattr(self.carteira.sugerida, c) - getattr(self.carteira.base, c)),
                    _CASAS_COMPARACAO,
                )
                if dif != 0:
                    raise ValueError("com origem 'fallback' a carteira sugerida deve ser igual à base")
        return self

