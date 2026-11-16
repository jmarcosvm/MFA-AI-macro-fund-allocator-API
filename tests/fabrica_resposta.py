"""Fábrica de RespostaMacro válidas para os testes do cache e da API (sem internet).

Roda o pipeline real (service.gerar_resposta) com coletores, Focus e LLM FALSOS, reaproveitando
as peças de tests/test_service.py. Variantes por model_copy (gerado_em, avisos).
"""

from datetime import datetime, timedelta, timezone
from functools import lru_cache

from test_service import AGORA, analise_falha, analise_ok, rodar

from app.schemas import RespostaMacro


@lru_cache
def _base(origem: str) -> RespostaMacro:
    return rodar(analisar=analise_ok if origem == "llm" else analise_falha)


def resposta(origem: str = "llm", gerado_em: datetime | None = None) -> RespostaMacro:
    """Resposta válida com a origem pedida ("llm" ou "fallback"). Cada chamada devolve um
    objeto NOVO (o cache da fábrica nunca é compartilhado com o código testado)."""
    base = _base(origem).model_copy(deep=True)
    if gerado_em is not None:
        base = base.model_copy(update={"gerado_em": gerado_em})
    return base


def instante(minutos: int = 0) -> datetime:
    """AGORA (14/11/2026 12:00 UTC) mais N minutos, com fuso."""
    return (AGORA + timedelta(minutes=minutos)).astimezone(timezone.utc)
