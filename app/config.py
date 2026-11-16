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


class Settings(BaseSettings):
    """Todas as chaves e nomes de modelo são opcionais; o app sobe sem .env."""

    GEMINI_API_KEY: str = ""
    NVIDIA_NIM_API_KEY: str = ""
    # Nomes de modelo SEM prefixo (SPEC.md §8). LLM_PRIMARY = modelo Gemini (vai na URL);
    # LLM_SECONDARY = id do modelo NVIDIA como aparece no catálogo. Vazio = provedor sem
    # modelo: falha rápida com aviso e a cadeia segue.
    LLM_PRIMARY: str = ""
    LLM_SECONDARY: str = ""
    CACHE_TTL_SECONDS: int = 21600
    # TTL curto para resposta com justificativa.origem == "fallback" (o LLM falhou): tenta
    # de novo mais cedo. Valor inicial SEM fonte (15 min); ajustar conforme o uso.
    CACHE_TTL_FALLBACK_SECONDS: int = 900

    # Origens permitidas pelo CORS, separadas por vírgula. Vazio (ou só espaços) volta a
    # "*". GET público, sem cookies. Fechar para o domínio do front na R8/R9.
    CORS_ORIGINS: str = "*"

    # Cadeia de LLM (R6). Valores iniciais SEM fonte: calibrar com o teste "internet".
    # Timeout por chamada e orçamento total da cadeia (uma tentativa por provedor, sem
    # retry). LLM_MAX_TOKENS inclui os tokens de raciocínio do Gemini (se estourar, a
    # resposta vem truncada e a cadeia passa ao próximo). response_format da NVIDIA fica
    # desligado até o teste "internet" provar que o modelo escolhido o aceita.
    LLM_TIMEOUT_SEGUNDOS: float = 25.0
    LLM_ORCAMENTO_SEGUNDOS: float = 45.0
    LLM_MAX_TOKENS: int = 4096
    LLM_SECONDARY_JSON_MODE: bool = False

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
