"""Configuração lida de variáveis de ambiente (e de um .env opcional)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # Se o arquivo .env não existir, ele é simplesmente ignorado.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    """Devolve uma única instância de Settings (lida uma vez)."""
    return Settings()
