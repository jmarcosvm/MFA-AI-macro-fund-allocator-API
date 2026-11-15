"""Testes "internet" da camada de LLM: um por provedor, com as chaves REAIS do .env.

Rodar (fora do pytest padrão):
    .\\.venv\\Scripts\\python.exe -m pytest -m internet -s tests/test_llm_internet.py

Se a chave ou o modelo não estiverem no .env, o teste dá SKIP com mensagem clara (não
falha). Imprime: provedor, tempo, se o JSON era válido e o resultado final. NUNCA imprime
chave. Estes testes provam as suposições que a doc oficial não confirma:
- Gemini: o formato generationConfig.responseFormat (se der HTTP 400, trocar na função
  isolada _chamar_gemini).
- NVIDIA NIM: finish_reason e response_format (LLM_SECONDARY_JSON_MODE).
"""

import time

import pytest
from test_llm import entrada  # mesmos números fixos (13/11/2026) dos testes sem internet

from app.config import get_settings
from app.llm import (
    ErroProvedor,
    _chamar_gemini,
    _chamar_nvidia,
    extrair_json,
    gerar_analise,
    modelo_gemini_valido,
    montar_mensagens,
    validar_resposta,
)

pytestmark = pytest.mark.internet


def _mostrar(rotulo: str, r, segundos: float, json_valido: str) -> None:
    print(f"\n[{rotulo}] provedor usado: {r.justificativa.provedor} | origem: {r.justificativa.origem}")
    print(f"[{rotulo}] tempo: {segundos:.2f}s | JSON válido: {json_valido}")
    print(f"[{rotulo}] tentativas: {[(t.provedor, t.ok, round(t.segundos, 2), t.motivo) for t in r.tentativas]}")
    print(f"[{rotulo}] avisos: {r.avisos}")
    s = r.carteira_sugerida
    print(
        f"[{rotulo}] carteira sugerida: renda_fixa={s.renda_fixa} "
        f"fundos_cambiais={s.fundos_cambiais} renda_variavel={s.renda_variavel}"
    )
    print(f"[{rotulo}] resumo:\n{r.justificativa.resumo}")
    print(f"[{rotulo}] narração: {r.justificativa.narracao_o_que_mudaria}")
    print(f"[{rotulo}] texto ({len(r.justificativa.texto)} caracteres): {r.justificativa.texto}")


def _rodar_um_provedor(nome: str, chamador, rotulo: str):
    """Roda a cadeia SÓ com este provedor, guardando o texto cru para checar o JSON."""
    guardado: dict = {}

    def espiao(*args, **kw):
        try:
            guardado["texto"] = chamador(*args, **kw)
        except ErroProvedor as e:
            guardado["erro"] = str(e)
            raise
        return guardado["texto"]

    cfg = get_settings()
    inicio = time.perf_counter()
    r = gerar_analise(entrada(), settings=cfg, chamadores={nome: espiao}, provedores=(nome,))
    segundos = time.perf_counter() - inicio

    if "texto" in guardado:
        try:
            validar_resposta(extrair_json(guardado["texto"]), entrada(), nome)
            json_valido = "sim (e dentro do contrato)"
        except ErroProvedor as e:
            json_valido = f"não ({e})"
    else:
        json_valido = f"sem resposta ({guardado.get('erro', 'falha antes da chamada')})"
    _mostrar(rotulo, r, segundos, json_valido)
    return r


def test_gemini_real():
    cfg = get_settings()
    if not cfg.GEMINI_API_KEY or not cfg.LLM_PRIMARY:
        pytest.skip("Defina GEMINI_API_KEY e LLM_PRIMARY (nome do modelo Gemini) no .env para rodar.")
    if not modelo_gemini_valido(cfg.LLM_PRIMARY):
        pytest.skip("LLM_PRIMARY inválido: use só letras, números, ponto, hífen e sublinhado.")
    r = _rodar_um_provedor("gemini", _chamar_gemini, "gemini")
    assert r.justificativa.origem == "llm", f"Gemini não respondeu dentro do contrato: {r.avisos}"
    assert r.justificativa.provedor == "gemini"


def test_nvidia_nim_real():
    cfg = get_settings()
    if not cfg.NVIDIA_NIM_API_KEY or not cfg.LLM_SECONDARY:
        pytest.skip(
            "Defina NVIDIA_NIM_API_KEY e LLM_SECONDARY (id do modelo no catálogo da NVIDIA) no .env para rodar."
        )
    r = _rodar_um_provedor("nvidia_nim", _chamar_nvidia, "nvidia_nim")
    assert r.justificativa.origem == "llm", f"NVIDIA NIM não respondeu dentro do contrato: {r.avisos}"
    assert r.justificativa.provedor == "nvidia_nim"


def test_nvidia_nim_aceita_response_format():
    """Informativo: diz se o modelo escolhido aceita response_format (decide a flag
    LLM_SECONDARY_JSON_MODE). Só falha se a chamada SEM response_format também falhar."""
    cfg = get_settings()
    if not cfg.NVIDIA_NIM_API_KEY or not cfg.LLM_SECONDARY:
        pytest.skip(
            "Defina NVIDIA_NIM_API_KEY e LLM_SECONDARY (id do modelo no catálogo da NVIDIA) no .env para rodar."
        )
    sistema, usuario = montar_mensagens(entrada())
    inicio = time.perf_counter()
    try:
        texto = _chamar_nvidia(
            cfg.LLM_SECONDARY, sistema, usuario, cfg.NVIDIA_NIM_API_KEY,
            cfg.LLM_TIMEOUT_SEGUNDOS, cfg.LLM_MAX_TOKENS, True,
        )
    except ErroProvedor as e:
        print(f"\n[nvidia_nim response_format] NÃO aceito/sem resposta: {e} ({time.perf_counter() - inicio:.2f}s)")
        print("[nvidia_nim response_format] mantenha LLM_SECONDARY_JSON_MODE=false")
        return
    try:
        validar_resposta(extrair_json(texto), entrada(), "nvidia_nim")
        situacao = "aceito e a resposta validou no contrato"
    except ErroProvedor as e:
        situacao = f"aceito, mas a resposta não validou ({e})"
    print(f"\n[nvidia_nim response_format] {situacao} ({time.perf_counter() - inicio:.2f}s)")
