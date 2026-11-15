"""Configuração lida de variáveis de ambiente (e de um .env opcional)."""

from datetime import date
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


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


class Settings(BaseSettings):
    """Todas as chaves e nomes de modelo são opcionais; o app sobe sem .env."""

    GEMINI_API_KEY: str = ""
    NVIDIA_NIM_API_KEY: str = ""
    LLM_PRIMARY: str = ""
    LLM_SECONDARY: str = ""
    CACHE_TTL_SECONDS: int = 21600

    # Coleta do BCB: janela (em dias antes de hoje) de cada série e timeout por chamada.
    # Os valores são palpite inicial; o teste "internet" valida.
    JANELA_IBCBR_DIAS: int = 365
    JANELA_DOLAR_DIAS: int = 120
    JANELA_SELIC_DIAS: int = 60
    JANELA_IPCA_DIAS: int = 150
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
