"""Teste "internet" do pipeline: roda gerar_resposta() UMA vez, com BCB, Focus e LLM reais.

Rodar (fora do pytest padrão):
    .\\.venv\\Scripts\\python.exe -m pytest -m internet -s tests/test_service_internet.py

Usa as chaves do .env (via get_settings). Sem chave/modelo, a cadeia cai no fallback e o
teste imprime origem "fallback". Imprime o JSON da resposta (que não contém chaves), o tempo
total em segundos, a origem e o provedor. NUNCA imprime chave.
"""

import time

import pytest

from app.schemas import RespostaMacro
from app.service import gerar_resposta

pytestmark = pytest.mark.internet


def test_internet_pipeline_completo():
    inicio = time.perf_counter()
    resposta = gerar_resposta()
    segundos = time.perf_counter() - inicio

    RespostaMacro.model_validate(resposta.model_dump(mode="json"))  # contrato do SPEC §6
    print("\n" + resposta.model_dump_json(indent=2))
    print(f"\n[pipeline] tempo total: {segundos:.2f} s")
    print(f"[pipeline] origem: {resposta.justificativa.origem}")
    print(f"[pipeline] provedor: {resposta.justificativa.provedor}")
    print(f"[pipeline] cenário: {resposta.cenario.classificacao.value}")
