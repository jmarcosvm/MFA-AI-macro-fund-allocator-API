"""Testes do cache puro (app/cache.py). Sem internet; relógio falso."""

from fabrica_resposta import resposta

from app.cache import CacheResposta

TTL = 21600
TTL_FALLBACK = 900


class Relogio:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def novo():
    relogio = Relogio()
    return CacheResposta(TTL, TTL_FALLBACK, relogio), relogio


def test_vazio_devolve_none():
    cache, _ = novo()
    assert cache.obter() is None


def test_guardar_e_obter_devolvem_a_mesma_resposta():
    cache, _ = novo()
    r = resposta("llm")
    cache.guardar(r)
    assert cache.obter().resposta is r


def test_llm_fresca_ate_o_ttl_e_vencida_no_ttl():
    cache, relogio = novo()
    cache.guardar(resposta("llm"))
    entrada = cache.obter()
    assert entrada.ttl_segundos == TTL
    relogio.t += TTL - 1
    assert entrada.fresca()
    relogio.t += 1
    assert not entrada.fresca()


def test_fallback_usa_o_ttl_curto():
    cache, relogio = novo()
    cache.guardar(resposta("fallback"))
    entrada = cache.obter()
    assert entrada.ttl_segundos == TTL_FALLBACK
    relogio.t += TTL_FALLBACK - 1
    assert entrada.fresca()
    relogio.t += 1
    assert not entrada.fresca()


def test_llm_ainda_fresca_quando_o_fallback_ja_venceu():
    llm, relogio = novo()
    fallback = CacheResposta(TTL, TTL_FALLBACK, relogio)
    llm.guardar(resposta("llm"))
    fallback.guardar(resposta("fallback"))
    relogio.t += TTL_FALLBACK
    assert llm.obter().fresca()
    assert not fallback.obter().fresca()


def test_devolve_a_entrada_mesmo_vencida():
    cache, relogio = novo()
    r = resposta("llm")
    cache.guardar(r)
    relogio.t += TTL * 10
    entrada = cache.obter()
    assert entrada is not None and entrada.resposta is r
    assert not entrada.fresca()


def test_guardar_de_novo_substitui_e_renova_o_relogio():
    cache, relogio = novo()
    cache.guardar(resposta("llm"))
    relogio.t += TTL
    nova = resposta("llm")
    cache.guardar(nova)
    entrada = cache.obter()
    assert entrada.resposta is nova and entrada.fresca()
