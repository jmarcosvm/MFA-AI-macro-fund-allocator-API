"""Testes da API (app/main.py): rota, erros HTTP, /health, pré-aquecimento e CORS.

Sem internet: sempre `criar_app(gerador=FALSO, ...)`. Nunca usa o `app` real com `with`
(dispararia o pré-aquecimento com rede). Sem time.sleep: Event e join com limite.
"""

import threading

import pytest
from fabrica_resposta import instante, resposta
from fastapi.testclient import TestClient

from app.cache import CacheResposta
from app.config import Settings
from app.main import MSG_ERRO_INTERNO, criar_app, parse_origens
from app.orquestrador import aviso_desatualizado
from app.schemas import RespostaMacro
from app.service import ServicoIndisponivelError

ROTA = "/api/v1/macro/analyze"
ESPERA = 10
TTL = 21600
TTL_FALLBACK = 900
INDISPONIVEL = ServicoIndisponivelError("Dados do BCB indisponíveis: série 4189 (teste).")


class Relogio:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class Gerador:
    """Devolve/levanta o próximo item do roteiro (o último se repete) e conta as chamadas."""

    def __init__(self, *roteiro):
        self.roteiro = list(roteiro)
        self.chamadas = 0

    def __call__(self):
        self.chamadas += 1
        item = self.roteiro.pop(0) if len(self.roteiro) > 1 else self.roteiro[0]
        if isinstance(item, BaseException):
            raise item
        return item


def montar(*roteiro, preaquecer=False, **kw):
    relogio = Relogio()
    cache = CacheResposta(TTL, TTL_FALLBACK, relogio)
    gerador = Gerador(*roteiro)
    app = criar_app(gerador=gerador, cache=cache, preaquecer=preaquecer, **kw)
    return app, gerador, relogio


def cliente(app):
    return TestClient(app, raise_server_exceptions=False)


# ------------------------------------------------------------------ rota


def test_rota_200_e_o_json_valida_como_resposta_macro():
    app, _, _ = montar(resposta())
    r = cliente(app).get(ROTA)
    assert r.status_code == 200
    modelo = RespostaMacro.model_validate(r.json())  # ida
    assert modelo.model_dump(mode="json") == r.json()  # e volta


def test_segunda_chamada_http_vem_do_cache_com_o_mesmo_gerado_em():
    app, gerador, _ = montar(resposta(gerado_em=instante(0)), resposta(gerado_em=instante(9)))
    c = cliente(app)
    a, b = c.get(ROTA).json(), c.get(ROTA).json()
    assert gerador.chamadas == 1
    assert a["gerado_em"] == b["gerado_em"]


def test_resposta_velha_via_http_tem_aviso_gerado_em_original_e_valida():
    original = resposta(gerado_em=instante(0))
    app, gerador, relogio = montar(original, INDISPONIVEL)
    c = cliente(app)
    c.get(ROTA)
    relogio.t += TTL
    r = c.get(ROTA)
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["avisos_de_qualidade"][0] == aviso_desatualizado(original)
    assert corpo["gerado_em"] == original.model_dump(mode="json")["gerado_em"]
    RespostaMacro.model_validate(corpo)
    c.get(ROTA)  # não renovou o relógio: tenta de novo
    assert gerador.chamadas == 3


def test_sem_cache_e_servico_indisponivel_da_503_com_mensagem_em_portugues():
    app, _, _ = montar(INDISPONIVEL)
    r = cliente(app).get(ROTA)
    assert r.status_code == 503
    assert r.json() == {"detail": INDISPONIVEL.motivo}


def test_excecao_inesperada_da_500_generico_sem_vazar_detalhe():
    app, _, _ = montar(ValueError("segredo-interno"))
    r = cliente(app).get(ROTA)
    assert r.status_code == 500
    assert r.json() == {"detail": MSG_ERRO_INTERNO}
    assert "segredo-interno" not in r.text


def test_excecao_inesperada_nao_usa_cache_velho_e_da_500():
    app, _, relogio = montar(resposta(), ValueError("bug"))
    c = cliente(app)
    assert c.get(ROTA).status_code == 200
    relogio.t += TTL
    assert c.get(ROTA).status_code == 500


def test_relogio_injetado_vale_para_o_cache_criado_pelo_criar_app():
    relogio = Relogio()
    gerador = Gerador(resposta(gerado_em=instante(0)), resposta(gerado_em=instante(1)))
    app = criar_app(gerador=gerador, relogio=relogio, preaquecer=False)
    c = cliente(app)
    c.get(ROTA)
    c.get(ROTA)
    assert gerador.chamadas == 1
    relogio.t += 10**7
    c.get(ROTA)
    assert gerador.chamadas == 2


# ------------------------------------------------------------------ /health


def test_health_ok():
    app, _, _ = montar(resposta())
    r = cliente(app).get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_health_responde_200_enquanto_o_gerador_esta_bloqueado():
    liberar, entrou = threading.Event(), threading.Event()

    def gerador():
        entrou.set()
        assert liberar.wait(ESPERA)
        return resposta()

    app = criar_app(gerador=gerador, preaquecer=False)
    resultado = {}

    def pedir():
        resultado["r"] = cliente(app).get(ROTA)

    thread = threading.Thread(target=pedir, daemon=True)
    thread.start()
    try:
        assert entrou.wait(ESPERA)  # a rota está presa no gerador
        assert cliente(app).get("/health").status_code == 200
    finally:
        liberar.set()
        thread.join(ESPERA)
    assert resultado["r"].status_code == 200


# ------------------------------------------------------------------ pré-aquecimento


def test_preaquecimento_preenche_o_cache_ao_iniciar():
    app, gerador, _ = montar(resposta(), preaquecer=True)
    with TestClient(app) as c:
        app.state.preaquecimento.join(ESPERA)
        assert app.state.servico._cache.obter() is not None
        assert c.get(ROTA).status_code == 200
    assert gerador.chamadas == 1  # a rota usou o cache pré-aquecido


def test_sem_preaquecer_nao_ha_thread_nem_chamada():
    app, gerador, _ = montar(resposta(), preaquecer=False)
    with TestClient(app):
        assert app.state.preaquecimento is None
    assert gerador.chamadas == 0


def test_health_responde_enquanto_o_preaquecimento_esta_bloqueado():
    liberar, entrou = threading.Event(), threading.Event()
    chamadas = []

    def gerador():
        chamadas.append(1)
        entrou.set()
        assert liberar.wait(ESPERA)
        return resposta()

    app = criar_app(gerador=gerador, preaquecer=True)
    try:
        with TestClient(app) as c:
            assert entrou.wait(ESPERA)  # o pré-aquecimento está preso no gerador
            assert c.get("/health").json() == {"status": "ok"}
            liberar.set()
            app.state.preaquecimento.join(ESPERA)
            assert c.get(ROTA).status_code == 200
    finally:
        liberar.set()
    assert len(chamadas) == 1


@pytest.mark.parametrize("falha", [INDISPONIVEL, RuntimeError("bug")])
def test_falha_no_preaquecimento_nao_derruba_e_a_proxima_requisicao_tenta_de_novo(falha):
    app, gerador, _ = montar(falha, resposta(), preaquecer=True)
    with TestClient(app) as c:
        app.state.preaquecimento.join(ESPERA)
        assert c.get("/health").status_code == 200  # o app continua de pé
        assert app.state.servico._cache.obter() is None
        assert c.get(ROTA).status_code == 200  # tentou de novo e deu certo
    assert gerador.chamadas == 2


# ------------------------------------------------------------------ CORS


def preflight(app, origem, metodo="GET", cabecalhos=None):
    headers = {"Origin": origem, "Access-Control-Request-Method": metodo}
    if cabecalhos:
        headers["Access-Control-Request-Headers"] = cabecalhos
    return cliente(app).options(ROTA, headers=headers)


def app_cors(cors_origins):
    return montar(resposta(), cors_origins=cors_origins)[0]


def test_config_padrao_do_cors_e_do_ttl_do_fallback():
    s = Settings(_env_file=None)
    assert s.CORS_ORIGINS == "*"
    assert s.CACHE_TTL_FALLBACK_SECONDS == 900


def test_cors_padrao_asterisco_libera_qualquer_origem_sem_credenciais():
    r = preflight(app_cors("*"), "https://qualquer.com")
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "*"
    assert "access-control-allow-credentials" not in r.headers


@pytest.mark.parametrize("texto", ["", "   ", " , ,"])
def test_cors_vazio_ou_so_espacos_volta_a_asterisco(texto):
    assert parse_origens(texto) == ["*"]
    r = preflight(app_cors(texto), "https://qualquer.com")
    assert r.headers["access-control-allow-origin"] == "*"


def test_parse_origens_com_varias_origens_strip_e_vazios():
    assert parse_origens(" https://a.com ,https://b.com,, ") == ["https://a.com", "https://b.com"]


def test_cors_com_uma_origem_especifica_libera_so_ela():
    app = app_cors("https://front.exemplo")
    ok = preflight(app, "https://front.exemplo")
    assert ok.status_code == 200
    assert ok.headers["access-control-allow-origin"] == "https://front.exemplo"
    outra = preflight(app, "https://invasor.exemplo")
    assert "access-control-allow-origin" not in outra.headers
    assert "access-control-allow-credentials" not in ok.headers


def test_cors_varias_origens_cada_uma_liberada_e_as_outras_nao():
    app = app_cors(" https://a.com , https://b.com ,, ")
    for origem in ("https://a.com", "https://b.com"):
        assert preflight(app, origem).headers["access-control-allow-origin"] == origem
    assert "access-control-allow-origin" not in preflight(app, "https://c.com").headers


def test_cors_so_permite_get_e_nenhum_cabecalho_extra():
    app = app_cors("*")
    assert preflight(app, "https://x.com").headers["access-control-allow-methods"] == "GET"
    assert preflight(app, "https://x.com", metodo="POST").status_code == 400
    assert preflight(app, "https://x.com", cabecalhos="x-personalizado").status_code == 400


def test_resposta_get_com_origin_traz_o_cabecalho_do_cors_sem_credenciais():
    r = cliente(app_cors("https://front.exemplo")).get(ROTA, headers={"Origin": "https://front.exemplo"})
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "https://front.exemplo"
    assert "access-control-allow-credentials" not in r.headers
