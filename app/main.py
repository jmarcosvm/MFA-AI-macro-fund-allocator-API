"""Ponto de entrada da API do AI Macro Fund Allocator (MFA)."""

from fastapi import FastAPI

app = FastAPI(title="AI Macro Fund Allocator")


@app.get("/health")
def health() -> dict[str, str]:
    """Verifica se o servidor está de pé."""
    return {"status": "ok"}
