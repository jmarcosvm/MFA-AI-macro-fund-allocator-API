"""Cache em memória de UMA entrada (a análise não tem parâmetros). R7.2.

Estrutura pura: sem FastAPI, sem rede, sem threads próprias. O CACHE é o dono do relógio
(monotônico, injetável nos testes): quem pergunta se a entrada está fresca é a própria
entrada, `entrada.fresca()`, sem argumento. A entrada é guardada MESMO VENCIDA: o
orquestrador a usa como "resposta velha" quando o BCB falha (app/orquestrador.py).

O TTL depende da origem da justificativa: "fallback" (o LLM falhou) vence mais cedo.
"""

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from app.schemas import RespostaMacro


@dataclass(frozen=True)
class EntradaCache:
    resposta: RespostaMacro
    guardado_em: float  # leitura do relógio do cache (monotônico), não é data
    ttl_segundos: float
    _relogio: Callable[[], float]

    def fresca(self) -> bool:
        return (self._relogio() - self.guardado_em) < self.ttl_segundos


class CacheResposta:
    def __init__(
        self,
        ttl_segundos: float,
        ttl_fallback_segundos: float,
        relogio: Callable[[], float] = time.monotonic,
    ):
        self._ttl = ttl_segundos
        self._ttl_fallback = ttl_fallback_segundos
        self._relogio = relogio
        self._trava = threading.Lock()
        self._entrada: EntradaCache | None = None

    def obter(self) -> EntradaCache | None:
        """Devolve a entrada guardada, mesmo vencida (ou None se nunca guardou)."""
        with self._trava:
            return self._entrada

    def guardar(self, resposta: RespostaMacro) -> EntradaCache:
        """Substitui a entrada; o TTL é escolhido pela origem da justificativa."""
        ttl = self._ttl_fallback if resposta.justificativa.origem == "fallback" else self._ttl
        entrada = EntradaCache(resposta, self._relogio(), ttl, self._relogio)
        with self._trava:
            self._entrada = entrada
        return entrada
