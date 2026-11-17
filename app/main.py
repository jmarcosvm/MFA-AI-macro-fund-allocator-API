"""Ponto de entrada da API do AI Macro Fund Allocator (MFA).

`criar_app(...)` monta o app; `app = criar_app()` é o de produção (pré-aquece o cache ao
iniciar). Os testes montam o próprio app com gerador FALSO e nunca tocam a rede.

LIMITAÇÕES (detalhes em app/orquestrador.py):
- Rotas `def` rodam no pool de threads do anyio (40 vagas, verificado em anyio 4.16.0);
  seguidoras esperando o líder ocupam vagas. Por isso o /health é `async def`: continua
  respondendo com o pool cheio.
- A espera pela geração não tem limite de tempo (pior caso nominal 115 s, calculado; o
  limite de requisição do Render NÃO foi verificado).
- Durante queda do BCB com resposta velha em cache, cada requisição nova paga uma tentativa.
- Cache só em memória: perdido ao dormir/reiniciar (SPEC §8).
"""

import logging
import threading
import time
from collections.abc import Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import service
from app.cache import CacheResposta
from app.config import (
    SIM_CRESCIMENTO_MAX,
    SIM_CRESCIMENTO_MIN,
    SIM_IPCA_MAX,
    SIM_IPCA_MIN,
    SIM_SELIC_MAX,
    SIM_SELIC_MIN,
    get_settings,
)
from app.orquestrador import ServicoComCache
from app.schemas import RespostaMacro, RespostaSimulacao
from app.service import ServicoIndisponivelError
from app.simulador import simular

logger = logging.getLogger("mfa")

MSG_ERRO_INTERNO = "Erro interno ao gerar a análise. Tente novamente em instantes."

ROTA_SIMULAR = "/api/v1/macro/simulate"

# Faixa aceita por parâmetro do simulador (para a mensagem do 422).
_FAIXAS_SIMULADOR = {
    "ipca_12m_pct": (SIM_IPCA_MIN, SIM_IPCA_MAX),
    "crescimento_ibcbr_pct": (SIM_CRESCIMENTO_MIN, SIM_CRESCIMENTO_MAX),
    "selic_efetiva_aa_pct": (SIM_SELIC_MIN, SIM_SELIC_MAX),
    "selic_esperada_pct": (SIM_SELIC_MIN, SIM_SELIC_MAX),
    "meta_selic_pct": (SIM_SELIC_MIN, SIM_SELIC_MAX),
}


def _num(valor: float) -> str:
    return f"{valor:g}".replace(".", ",")


def _mensagem_422(erro: dict) -> str:
    tipo = erro.get("type")
    campo = erro["loc"][-1] if erro.get("loc") else None
    if tipo == "missing":
        return "Parâmetro obrigatório ausente."
    if tipo == "float_parsing":
        return "Deve ser um número."
    if tipo == "finite_number":
        return "Deve ser um número finito (NaN e infinito não são aceitos)."
    if tipo in ("greater_than_equal", "less_than_equal") and campo in _FAIXAS_SIMULADOR:
        minimo, maximo = _FAIXAS_SIMULADOR[campo]
        return f"Deve estar entre {_num(minimo)} e {_num(maximo)}."
    return "Valor inválido."


async def tratar_422(request: Request, exc: RequestValidationError):
    """422 em português SÓ para o simulador; as demais rotas mantêm o handler padrão."""
    if request.url.path != ROTA_SIMULAR:
        return await request_validation_exception_handler(request, exc)
    detalhes = [
        {"loc": list(e["loc"]), "msg": _mensagem_422(e), "type": e["type"]} for e in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": detalhes})


def parse_origens(texto: str) -> list[str]:
    """Separa por vírgula, tira espaços e ignora vazios. Nada sobrando (vazio ou só
    espaços) volta ao padrão "*"."""
    origens = [parte.strip() for parte in texto.split(",") if parte.strip()]
    return origens or ["*"]


def _preaquecer(servico: ServicoComCache) -> None:
    """Roda em thread de fundo. Nunca derruba o app; só registra (sem chaves nem corpo)."""
    try:
        servico.obter()
    except ServicoIndisponivelError as erro:
        logger.warning("Pré-aquecimento sem dados: %s", erro.motivo)
    except Exception as erro:  # noqa: BLE001 - qualquer falha deve ser só registrada
        logger.warning("Pré-aquecimento falhou: %s", type(erro).__name__)


def criar_app(
    *,
    gerador: Callable[[], RespostaMacro] | None = None,
    cache: CacheResposta | None = None,
    relogio: Callable[[], float] | None = None,
    preaquecer: bool = True,
    cors_origins: str | None = None,
) -> FastAPI:
    """Monta o app.

    gerador: padrão `service.gerar_resposta`. cache: padrão criado com os TTLs do Settings;
    `relogio` (monotônico) só vale para esse cache criado aqui. preaquecer: inicia uma thread
    de fundo no lifespan. cors_origins: padrão `CORS_ORIGINS` do Settings.
    """
    settings = get_settings()
    gerador = gerador or service.gerar_resposta
    if cache is None:
        kwargs = {"relogio": relogio} if relogio is not None else {}
        cache = CacheResposta(
            settings.CACHE_TTL_SECONDS, settings.CACHE_TTL_FALLBACK_SECONDS, **kwargs
        )
    servico = ServicoComCache(gerador, cache)
    origens = parse_origens(settings.CORS_ORIGINS if cors_origins is None else cors_origins)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.preaquecimento = None
        if preaquecer:
            # Thread própria (fora do pool de 40); o lifespan não a espera: /health responde já.
            thread = threading.Thread(
                target=_preaquecer, args=(servico,), name="preaquecimento", daemon=True
            )
            app.state.preaquecimento = thread
            thread.start()
        yield

    app = FastAPI(title="AI Macro Fund Allocator", lifespan=lifespan)
    app.state.servico = servico
    app.state.preaquecimento = None
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origens,
        allow_methods=["GET"],
        allow_credentials=False,
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        """Verifica se o servidor está de pé (async: não usa o pool de threads)."""
        return {"status": "ok"}

    @app.get("/api/v1/macro/analyze", response_model=RespostaMacro)
    def analisar() -> RespostaMacro:
        try:
            return servico.obter()
        except ServicoIndisponivelError as erro:
            raise HTTPException(status_code=503, detail=erro.motivo) from None
        except Exception as erro:  # noqa: BLE001 - bug nosso: 500 genérico, nunca cache velho
            logger.error("Falha inesperada ao gerar a análise: %s", type(erro).__name__)
            raise HTTPException(status_code=500, detail=MSG_ERRO_INTERNO) from None

    app.add_exception_handler(RequestValidationError, tratar_422)

    @app.get(ROTA_SIMULAR, response_model=RespostaSimulacao)
    async def simulador(
        ipca_12m_pct: float = Query(
            ..., ge=SIM_IPCA_MIN, le=SIM_IPCA_MAX, allow_inf_nan=False
        ),
        crescimento_ibcbr_pct: float = Query(
            ..., ge=SIM_CRESCIMENTO_MIN, le=SIM_CRESCIMENTO_MAX, allow_inf_nan=False
        ),
        selic_efetiva_aa_pct: float = Query(
            ..., ge=SIM_SELIC_MIN, le=SIM_SELIC_MAX, allow_inf_nan=False
        ),
        selic_esperada_pct: float | None = Query(
            None, ge=SIM_SELIC_MIN, le=SIM_SELIC_MAX, allow_inf_nan=False
        ),
        meta_selic_pct: float | None = Query(
            None, ge=SIM_SELIC_MIN, le=SIM_SELIC_MAX, allow_inf_nan=False
        ),
    ) -> RespostaSimulacao:
        """Simulação determinística: sem internet, sem LLM, sem cache (async: só conta)."""
        return simular(
            ipca_12m_pct,
            crescimento_ibcbr_pct,
            selic_efetiva_aa_pct,
            selic_esperada_pct,
            meta_selic_pct,
        )

    return app


app = criar_app()
