"""Testes das funções REAIS de chamada (app/llm.py) com httpx2.MockTransport: sem internet.

Conferem URL, header da chave (nunca na URL), corpo, e a tradução de cada falha em uma
categoria de texto FIXO (sem chave nem corpo da resposta).
"""

import json

import httpx2
import pytest

from app.llm import (
    URL_GEMINI,
    URL_GROQ,
    URL_NVIDIA,
    ErroProvedor,
    _chamar_gemini,
    _chamar_groq,
    _chamar_nvidia,
)

CHAVE = "SENTINELA-CHAVE-789"
CORPO_SECRETO = "SENTINELA-NO-CORPO-DA-RESPOSTA"


def transporte(resposta_ou_funcao, capturadas=None):
    def handler(req: httpx2.Request):
        if capturadas is not None:
            capturadas.append(req)
        if isinstance(resposta_ou_funcao, Exception):
            raise resposta_ou_funcao
        return resposta_ou_funcao(req) if callable(resposta_ou_funcao) else resposta_ou_funcao

    return httpx2.MockTransport(handler)


def gemini(t, modelo="modelo-teste", chave=CHAVE):
    return _chamar_gemini(modelo, "SISTEMA", "USUARIO", chave, 5.0, 123, transporte=t)


def nvidia(t, modelo="dono/modelo-teste", chave=CHAVE, json_mode=False):
    return _chamar_nvidia(modelo, "SISTEMA", "USUARIO", chave, 5.0, 123, json_mode, transporte=t)


def ok_gemini(texto="{}", finish="STOP", extra_partes=()):
    partes = [*extra_partes, {"text": texto}]
    cand = {"content": {"parts": partes}}
    if finish is not None:
        cand["finishReason"] = finish
    return httpx2.Response(200, json={"candidates": [cand]})


def ok_nvidia(texto="{}", finish="stop"):
    escolha = {"message": {"role": "assistant", "content": texto}}
    if finish is not None:
        escolha["finish_reason"] = finish
    return httpx2.Response(200, json={"choices": [escolha]})


# ================================================================ Gemini


def test_gemini_monta_url_header_e_corpo_e_nunca_poe_a_chave_na_url():
    reqs: list[httpx2.Request] = []
    texto = gemini(transporte(ok_gemini('{"a": 1}'), reqs))
    assert texto == '{"a": 1}'
    (req,) = reqs
    assert req.method == "POST"
    assert str(req.url) == URL_GEMINI.format(modelo="modelo-teste")
    assert req.headers["x-goog-api-key"] == CHAVE
    assert CHAVE not in str(req.url) and "key=" not in str(req.url)
    assert "authorization" not in {k.lower() for k in req.headers}
    corpo = json.loads(req.content)
    assert corpo["systemInstruction"]["parts"][0]["text"] == "SISTEMA"
    assert corpo["contents"][0]["role"] == "user"
    assert corpo["contents"][0]["parts"][0]["text"] == "USUARIO"
    cfg = corpo["generationConfig"]
    assert cfg["maxOutputTokens"] == 123 and cfg["temperature"] == 0.2
    assert cfg["responseFormat"]["text"]["mimeType"] == "APPLICATION_JSON"
    assert set(cfg["responseFormat"]["text"]["schema"]["required"]) == {
        "texto",
        "resumo",
        "narracao_o_que_mudaria",
        "carteira_sugerida",
    }
    assert CHAVE not in req.content.decode()


def test_gemini_ignora_partes_de_raciocinio():
    t = transporte(ok_gemini("{}", extra_partes=[{"text": "pensando...", "thought": True}]))
    assert gemini(t) == "{}"


def test_gemini_aceita_finish_reason_ausente():
    assert gemini(transporte(ok_gemini("{}", finish=None))) == "{}"


def test_gemini_max_tokens_e_resposta_truncada():
    with pytest.raises(ErroProvedor, match="resposta truncada"):
        gemini(transporte(ok_gemini("{parcial", finish="MAX_TOKENS")))


@pytest.mark.parametrize("finish", ["SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", "OTHER"])
def test_gemini_bloqueio_por_finish_reason(finish):
    with pytest.raises(ErroProvedor, match="resposta bloqueada"):
        gemini(transporte(ok_gemini("x", finish=finish)))


def test_gemini_bloqueio_do_prompt_sem_candidatos():
    r = httpx2.Response(200, json={"promptFeedback": {"blockReason": "SAFETY"}})
    with pytest.raises(ErroProvedor, match="resposta bloqueada"):
        gemini(transporte(r))


@pytest.mark.parametrize(
    "json_resp",
    [{}, {"candidates": []}, {"candidates": [{}]}, {"candidates": [{"content": {"parts": []}}]}],
)
def test_gemini_resposta_sem_texto_e_vazia(json_resp):
    with pytest.raises(ErroProvedor, match="resposta vazia"):
        gemini(transporte(httpx2.Response(200, json=json_resp)))


def test_gemini_texto_so_com_espacos_e_vazio():
    with pytest.raises(ErroProvedor, match="resposta vazia"):
        gemini(transporte(ok_gemini("   ")))


@pytest.mark.parametrize(
    "status, esperado",
    [
        (429, "limite de uso \\(HTTP 429\\)"),
        (500, "serviço indisponível \\(HTTP 500\\)"),
        (503, "serviço indisponível \\(HTTP 503\\)"),
        (504, "serviço indisponível \\(HTTP 504\\)"),
        (401, "chave recusada \\(HTTP 401\\)"),
        (403, "chave recusada \\(HTTP 403\\)"),
        (400, "requisição recusada \\(HTTP 400\\)"),
        (402, "requisição recusada \\(HTTP 402\\)"),
        (404, "requisição recusada \\(HTTP 404\\)"),
        (302, "resposta inesperada \\(HTTP 302\\)"),
    ],
)
def test_gemini_status_http_viram_categorias_fixas_sem_eco_do_corpo(status, esperado):
    r = httpx2.Response(status, text=f"erro {CORPO_SECRETO} {CHAVE}")
    with pytest.raises(ErroProvedor, match=esperado) as exc:
        gemini(transporte(r))
    assert CORPO_SECRETO not in str(exc.value) and CHAVE not in str(exc.value)


def test_gemini_timeout_e_falha_de_rede():
    req = httpx2.Request("POST", "https://exemplo.invalido")
    with pytest.raises(ErroProvedor, match="tempo esgotado"):
        gemini(transporte(httpx2.ReadTimeout("lento", request=req)))
    with pytest.raises(ErroProvedor, match="falha de rede") as exc:
        gemini(transporte(httpx2.ConnectError(f"sem rota {CHAVE}", request=req)))
    assert CHAVE not in str(exc.value)


def test_gemini_resposta_que_nao_e_json():
    with pytest.raises(ErroProvedor, match="resposta ilegível"):
        gemini(transporte(httpx2.Response(200, text="isto nao e json")))
    with pytest.raises(ErroProvedor, match="resposta ilegível"):
        gemini(transporte(httpx2.Response(200, json=[1, 2])))


def test_gemini_sem_chave_ou_modelo_falha_rapido_sem_rede():
    reqs: list = []
    t = transporte(ok_gemini(), reqs)
    with pytest.raises(ErroProvedor, match="chave ou modelo não configurados"):
        gemini(t, chave="")
    with pytest.raises(ErroProvedor, match="chave ou modelo não configurados"):
        gemini(t, modelo="")
    assert reqs == []


# ================================================================ NVIDIA


def test_nvidia_monta_url_header_bearer_e_corpo():
    reqs: list[httpx2.Request] = []
    texto = nvidia(transporte(ok_nvidia('{"a": 1}'), reqs))
    assert texto == '{"a": 1}'
    (req,) = reqs
    assert req.method == "POST"
    assert str(req.url) == URL_NVIDIA
    assert req.headers["authorization"] == f"Bearer {CHAVE}"
    assert CHAVE not in str(req.url)
    corpo = json.loads(req.content)
    assert corpo["model"] == "dono/modelo-teste"
    assert [m["role"] for m in corpo["messages"]] == ["system", "user"]
    assert corpo["messages"][0]["content"] == "SISTEMA"
    assert corpo["messages"][1]["content"] == "USUARIO"
    assert corpo["max_tokens"] == 123 and corpo["temperature"] == 0.2 and corpo["stream"] is False
    assert "response_format" not in corpo  # desligado por padrão
    assert CHAVE not in req.content.decode()


def test_nvidia_response_format_so_com_a_flag_ligada():
    reqs: list[httpx2.Request] = []
    nvidia(transporte(ok_nvidia(), reqs), json_mode=True)
    assert json.loads(reqs[0].content)["response_format"] == {"type": "json_object"}


def test_nvidia_finish_reason_length_e_truncada():
    with pytest.raises(ErroProvedor, match="resposta truncada"):
        nvidia(transporte(ok_nvidia("{parcial", finish="length")))


def test_nvidia_finish_reason_ausente_e_aceito():
    assert nvidia(transporte(ok_nvidia("{}", finish=None))) == "{}"


def test_nvidia_content_filter_e_bloqueada():
    with pytest.raises(ErroProvedor, match="resposta bloqueada"):
        nvidia(transporte(ok_nvidia("x", finish="content_filter")))


@pytest.mark.parametrize(
    "json_resp",
    [
        {},
        {"choices": []},
        {"choices": [{}]},
        {"choices": [{"message": {"content": None}}]},
        {"choices": [{"message": {"content": "  "}}]},
    ],
)
def test_nvidia_resposta_sem_texto_e_vazia(json_resp):
    with pytest.raises(ErroProvedor, match="resposta vazia"):
        nvidia(transporte(httpx2.Response(200, json=json_resp)))


@pytest.mark.parametrize(
    "status, esperado",
    [
        (429, "limite de uso"),
        (500, "serviço indisponível"),
        (503, "serviço indisponível"),
        (401, "chave recusada"),
        (403, "chave recusada"),
        (400, "requisição recusada"),
        (404, "requisição recusada"),
    ],
)
def test_nvidia_status_http_viram_categorias_fixas_sem_eco_do_corpo(status, esperado):
    r = httpx2.Response(status, text=f"erro {CORPO_SECRETO} {CHAVE}")
    with pytest.raises(ErroProvedor, match=esperado) as exc:
        nvidia(transporte(r))
    assert CORPO_SECRETO not in str(exc.value) and CHAVE not in str(exc.value)


def test_nvidia_timeout_e_falha_de_rede():
    req = httpx2.Request("POST", "https://exemplo.invalido")
    with pytest.raises(ErroProvedor, match="tempo esgotado"):
        nvidia(transporte(httpx2.ReadTimeout("lento", request=req)))
    with pytest.raises(ErroProvedor, match="falha de rede") as exc:
        nvidia(transporte(httpx2.ConnectError(f"sem rota {CHAVE}", request=req)))
    assert CHAVE not in str(exc.value)


def test_nvidia_sem_chave_ou_modelo_falha_rapido_sem_rede():
    reqs: list = []
    t = transporte(ok_nvidia(), reqs)
    with pytest.raises(ErroProvedor, match="chave ou modelo não configurados"):
        nvidia(t, chave="")
    with pytest.raises(ErroProvedor, match="chave ou modelo não configurados"):
        nvidia(t, modelo="  ")
    assert reqs == []


# ================================================================ Groq (mesmo formato da NVIDIA)


def groq(t, modelo="dono/modelo-teste", chave=CHAVE, json_mode=False):
    return _chamar_groq(modelo, "SISTEMA", "USUARIO", chave, 5.0, 123, json_mode, transporte=t)


def test_groq_monta_url_header_bearer_e_corpo_com_max_completion_tokens():
    reqs: list[httpx2.Request] = []
    texto = groq(transporte(ok_nvidia('{"a": 1}'), reqs))
    assert texto == '{"a": 1}'
    (req,) = reqs
    assert req.method == "POST"
    assert str(req.url) == URL_GROQ == "https://api.groq.com/openai/v1/chat/completions"
    assert req.headers["authorization"] == f"Bearer {CHAVE}"
    assert CHAVE not in str(req.url)
    corpo = json.loads(req.content)
    assert corpo["model"] == "dono/modelo-teste"
    assert [m["role"] for m in corpo["messages"]] == ["system", "user"]
    assert corpo["max_completion_tokens"] == 123 and "max_tokens" not in corpo
    assert corpo["temperature"] == 0.2 and corpo["stream"] is False
    assert "response_format" not in corpo
    assert CHAVE not in req.content.decode()


def test_groq_response_format_so_com_a_flag_ligada():
    reqs: list[httpx2.Request] = []
    groq(transporte(ok_nvidia(), reqs), json_mode=True)
    assert json.loads(reqs[0].content)["response_format"] == {"type": "json_object"}


def test_groq_ignora_o_campo_reasoning_dos_modelos_de_raciocinio():
    msg = {"role": "assistant", "content": "{}", "reasoning": "pensando..."}
    r = httpx2.Response(200, json={"choices": [{"message": msg, "finish_reason": "stop"}]})
    assert groq(transporte(r)) == "{}"


def test_groq_truncada_bloqueada_e_vazia():
    with pytest.raises(ErroProvedor, match="resposta truncada"):
        groq(transporte(ok_nvidia("{parcial", finish="length")))
    with pytest.raises(ErroProvedor, match="resposta bloqueada"):
        groq(transporte(ok_nvidia("x", finish="content_filter")))
    with pytest.raises(ErroProvedor, match="resposta vazia"):
        groq(transporte(httpx2.Response(200, json={"choices": []})))


@pytest.mark.parametrize(
    "status, esperado",
    [(429, "limite de uso"), (503, "serviço indisponível"), (401, "chave recusada"), (404, "requisição recusada")],
)
def test_groq_status_http_viram_categorias_fixas_sem_eco_do_corpo(status, esperado):
    r = httpx2.Response(status, text=f"erro {CORPO_SECRETO} {CHAVE}")
    with pytest.raises(ErroProvedor, match=esperado) as exc:
        groq(transporte(r))
    assert CORPO_SECRETO not in str(exc.value) and CHAVE not in str(exc.value)


def test_groq_timeout_e_sem_chave():
    req = httpx2.Request("POST", "https://exemplo.invalido")
    with pytest.raises(ErroProvedor, match="tempo esgotado"):
        groq(transporte(httpx2.ReadTimeout("lento", request=req)))
    reqs: list = []
    with pytest.raises(ErroProvedor, match="chave ou modelo não configurados"):
        groq(transporte(ok_nvidia(), reqs), chave="")
    assert reqs == []
