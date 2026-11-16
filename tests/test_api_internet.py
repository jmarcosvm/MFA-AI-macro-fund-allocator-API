"""Teste "internet" da API: criar_app com o gerador REAL, 2 GETs seguidos.

Rodar (fora do pytest padrão):
    .\\.venv\\Scripts\\python.exe -m pytest -m internet -s tests/test_api_internet.py

Usa as chaves do .env (via get_settings), mas NUNCA as imprime. A 2ª chamada deve vir do
cache (mesmo gerado_em, bem mais rápida). Sem chave/modelo a origem sai "fallback".
"""

import time

import pytest
from fastapi.testclient import TestClient

from app.main import criar_app
from app.schemas import RespostaMacro

pytestmark = pytest.mark.internet

ROTA = "/api/v1/macro/analyze"


def test_internet_dois_gets_seguidos_o_segundo_vem_do_cache():
    app = criar_app(preaquecer=False)  # gerador REAL (service.gerar_resposta)
    client = TestClient(app)

    t0 = time.perf_counter()
    r1 = client.get(ROTA)
    s1 = time.perf_counter() - t0
    t0 = time.perf_counter()
    r2 = client.get(ROTA)
    s2 = time.perf_counter() - t0

    assert r1.status_code == 200 and r2.status_code == 200
    RespostaMacro.model_validate(r1.json())  # contrato do SPEC §6
    j1 = r1.json()["justificativa"]
    print(f"\n[api] 1º GET: {s1:.3f} s (gera)")
    print(f"[api] 2º GET: {s2:.3f} s (cache)")
    print(f"[api] origem: {j1['origem']}")
    print(f"[api] provedor: {j1['provedor']}")
    print(f"[api] gerado_em igual nas duas: {r1.json()['gerado_em'] == r2.json()['gerado_em']}")

    assert r1.json()["gerado_em"] == r2.json()["gerado_em"]
    assert s2 < s1
