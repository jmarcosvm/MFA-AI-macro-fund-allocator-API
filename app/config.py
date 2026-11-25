"""Configuração lida de variáveis de ambiente (e de um .env opcional)."""

from datetime import date
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Provedores de LLM conhecidos pela cadeia (app/llm.py), na ordem padrão.
PROVEDORES_LLM: tuple[str, ...] = ("gemini", "nvidia_nim", "groq")


# Calendário do Copom usado para escolher a reunião da Selic no Focus (SPEC.md §3.3).
# Chave = nome da reunião no Olinda ("R#/aaaa", ordem da reunião no ano);
# valor = dia da DECISÃO (2º dia da reunião).
# As 16 datas foram conferidas na página oficial do BC em 15/11/2026 (BCB Calendar,
# "Copom meetings Calendar", anos 2026 e 2027): as 16 reuniões batem (Dia 1 - Dia 2).
# Atualizar quando o BC publicar 2028 (~jun/2027).
# O código não inventa datas: atualizar esta tabela uma vez por ano.
CALENDARIO_COPOM: dict[str, date] = {
    "R1/2026": date(2026, 1, 28),
    "R2/2026": date(2026, 3, 18),
    "R3/2026": date(2026, 4, 29),
    "R4/2026": date(2026, 6, 17),
    "R5/2026": date(2026, 8, 5),
    "R6/2026": date(2026, 9, 16),
    "R7/2026": date(2026, 11, 4),
    "R8/2026": date(2026, 12, 9),
    "R1/2027": date(2027, 1, 27),
    "R2/2027": date(2027, 3, 17),
    "R3/2027": date(2027, 4, 28),
    "R4/2027": date(2027, 6, 16),
    "R5/2027": date(2027, 8, 4),
    "R6/2027": date(2027, 9, 22),
    "R7/2027": date(2027, 10, 27),
    "R8/2027": date(2027, 12, 8),
}


# Limiares das regras do cenário (SPEC.md §3.2).
# Crescimento do IBC-Br (variação %, média 3m vs 3m anteriores): sem faixa neutra.
LIMIAR_CRESCIMENTO_IBCBR: float = 0.0
# IPCA 12m (%): teto da banda da meta (3% ± 1,5 p.p.).
LIMIAR_IPCA_PCT: float = 4.5

# Passo do Copom (p.p.): a Selic esperada precisa estar pelo menos um passo abaixo da
# meta atual para preferir prefixados (SPEC.md §3.5).
PASSO_COPOM_PP: float = 0.25

# Desvio máximo (em pontos percentuais) de cada classe da carteira sugerida em relação
# à base (SPEC.md §3.4 e §6). Os pesos são frações: 15 p.p. = 0,15.
LIMITE_DESVIO_PP: float = 15.0

# Tetos de tamanho dos textos da justificativa (R6). São proteção contra resposta
# descontrolada, NÃO critério de qualidade; têm margem acima do que o prompt pede
# (texto 1200, linha do resumo 160, narração 500). Sem fonte: ajustar após os testes
# "internet". O resumo deve ter de 2 a 3 linhas não vazias (SPEC.md §8).
TEXTO_MAX_CARACTERES: int = 2000
RESUMO_LINHA_MAX_CARACTERES: int = 240
NARRACAO_MAX_CARACTERES: int = 900
RESUMO_MIN_LINHAS: int = 2
RESUMO_MAX_LINHAS: int = 3


# Simulador (R9.1): faixas aceitas nos parâmetros. ESCOLHA DIDÁTICA, sem fonte.
SIM_IPCA_MIN, SIM_IPCA_MAX = -5.0, 30.0
SIM_CRESCIMENTO_MIN, SIM_CRESCIMENTO_MAX = -20.0, 20.0
SIM_SELIC_MIN, SIM_SELIC_MAX = 0.0, 50.0

# Tamanho máximo de cada série do bloco `series` (R9.1).
SERIE_MAX_IBCBR = 12
SERIE_MAX_IPCA = 12
SERIE_MAX_SELIC = 60
SERIE_MAX_DOLAR = 120


class Settings(BaseSettings):
    """Todas as chaves e nomes de modelo são opcionais; o app sobe sem .env."""

    GEMINI_API_KEY: str = ""
    NVIDIA_NIM_API_KEY: str = ""
    GROQ_API_KEY: str = ""
    # Nomes de modelo SEM prefixo (SPEC.md §8). LLM_PRIMARY = modelo Gemini (vai na URL);
    # LLM_SECONDARY = id do modelo NVIDIA como aparece no catálogo; LLM_TERTIARY = id do
    # modelo Groq (console.groq.com/docs/models). Os nomes PRIMARY/SECONDARY/TERTIARY
    # identificam o PROVEDOR, não a posição: a ordem vem de LLM_ORDEM. Vazio = provedor
    # sem modelo: falha rápida com aviso e a cadeia segue.
    LLM_PRIMARY: str = ""
    LLM_SECONDARY: str = ""
    LLM_TERTIARY: str = ""
    # Ordem da cadeia: nomes separados por vírgula, entre gemini, nvidia_nim e groq. Pode
    # omitir provedores (ex.: "nvidia_nim,groq" pula o Gemini). Vazio = ordem padrão.
    # Nome desconhecido ou repetido impede o app de subir (erro de configuração explícito).
    LLM_ORDEM: str = ",".join(PROVEDORES_LLM)
    CACHE_TTL_SECONDS: int = 21600
    # TTL curto para resposta com justificativa.origem == "fallback" (o LLM falhou): tenta
    # de novo mais cedo. Valor inicial SEM fonte (15 min); ajustar conforme o uso.
    CACHE_TTL_FALLBACK_SECONDS: int = 900

    # Origens permitidas pelo CORS, separadas por vírgula. Vazio (ou só espaços) volta a
    # "*". GET público, sem cookies. Fechar para o domínio do front na R8/R9.
    CORS_ORIGINS: str = "*"

    # Cadeia de LLM. Timeout por chamada e orçamento total da cadeia (uma tentativa por
    # provedor, sem retry). Timeout padrão de 15 s (era 25 s): em 25/11/2026 as respostas
    # válidas vieram em 2 a 6 s (Gemini, R6) e 4 a 5 s (NVIDIA bolt), e um Gemini travado
    # consumia 25 s dos 45 s. Com 15 s, três provedores cabem no orçamento de 45 s.
    # LLM_TIMEOUT_<PROVEDOR>_SEGUNDOS, se definido, substitui o padrão só para ele.
    # LLM_MAX_TOKENS inclui os tokens de raciocínio (se estourar, a resposta vem
    # truncada e a cadeia passa ao próximo). response_format da NVIDIA e do Groq fica
    # desligado até o teste "internet" provar que o modelo escolhido o aceita.
    LLM_TIMEOUT_SEGUNDOS: float = 15.0
    LLM_TIMEOUT_GEMINI_SEGUNDOS: float | None = None
    LLM_TIMEOUT_NVIDIA_NIM_SEGUNDOS: float | None = None
    LLM_TIMEOUT_GROQ_SEGUNDOS: float | None = None
    LLM_ORCAMENTO_SEGUNDOS: float = 45.0
    LLM_MAX_TOKENS: int = 4096
    LLM_SECONDARY_JSON_MODE: bool = False
    LLM_TERTIARY_JSON_MODE: bool = False

    @field_validator("LLM_ORDEM")
    @classmethod
    def _validar_ordem(cls, v: str) -> str:
        nomes = [n.strip().lower() for n in v.split(",") if n.strip()]
        if not nomes:
            return ",".join(PROVEDORES_LLM)
        desconhecidos = [n for n in nomes if n not in PROVEDORES_LLM]
        if desconhecidos:
            raise ValueError(
                f"LLM_ORDEM com provedor desconhecido: {desconhecidos}; "
                f"use só {', '.join(PROVEDORES_LLM)}"
            )
        if len(set(nomes)) != len(nomes):
            raise ValueError("LLM_ORDEM com provedor repetido")
        return ",".join(nomes)

    @property
    def ordem_llm(self) -> tuple[str, ...]:
        """LLM_ORDEM já validada, como tupla."""
        return tuple(self.LLM_ORDEM.split(","))

    def timeout_llm(self, provedor: str) -> float:
        """Timeout por chamada do provedor: o específico, se definido; senão o padrão."""
        especifico = getattr(self, f"LLM_TIMEOUT_{provedor.upper()}_SEGUNDOS", None)
        return especifico if especifico is not None else self.LLM_TIMEOUT_SEGUNDOS

    # Coleta do BCB: janela (em dias antes de hoje) de cada série e timeout por chamada.
    # Os valores são palpite inicial; o teste "internet" valida.
    # R9.1: ampliadas para o bloco `series` (medido em 16/11/2026: IPCA 13 pontos, IBC-Br 15,
    # Selic 62, dólar 138). Uma janela de 180 d do dólar deu HTTP 304 sem corpo (tratar na R9.1b).
    JANELA_IBCBR_DIAS: int = 480
    JANELA_DOLAR_DIAS: int = 200
    JANELA_SELIC_DIAS: int = 90
    JANELA_IPCA_DIAS: int = 400
    JANELA_META_SELIC_DIAS: int = 90
    BCB_TIMEOUT_SEGUNDOS: float = 10.0

    # Focus: distância máxima (em dias) entre "hoje + 12 meses" e a reunião do
    # Copom escolhida. Acima disso, a Selic esperada fica indisponível (None + aviso).
    TOLERANCIA_REUNIAO_DIAS: int = 60

    # Se o arquivo .env não existir, ele é simplesmente ignorado.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    """Devolve uma única instância de Settings (lida uma vez)."""
    return Settings()
