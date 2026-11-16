"""Testes do orquestrador (app/orquestrador.py): cache, resposta velha e single-flight.

Sem internet, sem rede, sem time.sleep: gerador FALSO, relógio FALSO e threading.Event/Condition.
"""

import threading

import pytest
from fabrica_resposta import instante, resposta

from app.cache import CacheResposta
from app.orquestrador import ErroGeracao, ServicoComCache, aviso_desatualizado
from app.schemas import RespostaMacro
from app.service import ServicoIndisponivelError

TTL = 21600
TTL_FALLBACK = 900
ESPERA = 10  # segundos; só como rede de segurança contra travar a suíte


class Relogio:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class Gerador:
    """Gerador falso: devolve/levanta o próximo item de `roteiro` e conta as chamadas."""

    def __init__(self, *roteiro):
        self.roteiro = list(roteiro)
        self.chamadas = 0

    def __call__(self):
        self.chamadas += 1
        item = self.roteiro.pop(0) if len(self.roteiro) > 1 else self.roteiro[0]
        if isinstance(item, BaseException):
            raise item
        return item


def montar(*roteiro):
    relogio = Relogio()
    cache = CacheResposta(TTL, TTL_FALLBACK, relogio)
    gerador = Gerador(*roteiro)
    return ServicoComCache(gerador, cache), gerador, relogio, cache


INDISPONIVEL = ServicoIndisponivelError("Dados do BCB indisponíveis: série 4189 (teste).")


# ------------------------------------------------------------------ cache


def test_cache_fresco_nao_chama_o_gerador():
    servico, gerador, _, cache = montar(resposta())
    cache.guardar(resposta())
    servico.obter()
    assert gerador.chamadas == 0


def test_segunda_chamada_vem_do_cache_com_o_mesmo_gerado_em():
    servico, gerador, _, _ = montar(resposta(gerado_em=instante(0)), resposta(gerado_em=instante(5)))
    a = servico.obter()
    b = servico.obter()
    assert gerador.chamadas == 1
    assert a.gerado_em == b.gerado_em == instante(0)


def test_ttl_de_6h_vence_e_regenera():
    servico, gerador, relogio, _ = montar(
        resposta(gerado_em=instante(0)), resposta(gerado_em=instante(400))
    )
    primeira = servico.obter()
    relogio.t += TTL - 1
    assert servico.obter().gerado_em == primeira.gerado_em
    relogio.t += 1
    nova = servico.obter()
    assert gerador.chamadas == 2
    assert nova.gerado_em == instante(400)


def test_fallback_usa_o_ttl_curto():
    servico, gerador, relogio, _ = montar(resposta("fallback"))
    servico.obter()
    relogio.t += TTL_FALLBACK - 1
    servico.obter()
    assert gerador.chamadas == 1
    relogio.t += 1
    servico.obter()
    assert gerador.chamadas == 2


def test_llm_nao_vence_no_ttl_do_fallback():
    servico, gerador, relogio, _ = montar(resposta("llm"))
    servico.obter()
    relogio.t += TTL_FALLBACK
    servico.obter()
    assert gerador.chamadas == 1


# ------------------------------------------------------------------ resposta velha


def vencer(servico, relogio):
    servico.obter()
    relogio.t += TTL


def test_vencida_mais_servico_indisponivel_devolve_a_velha_com_aviso():
    original = resposta(gerado_em=instante(0))
    servico, _, relogio, _ = montar(original, INDISPONIVEL)
    vencer(servico, relogio)
    velha = servico.obter()
    assert velha.gerado_em == original.gerado_em  # ORIGINAL
    assert velha.avisos_de_qualidade[0] == aviso_desatualizado(original)
    assert velha.avisos_de_qualidade[1:] == original.avisos_de_qualidade
    RespostaMacro.model_validate(velha.model_dump(mode="json"))  # continua válida


def test_texto_do_aviso_de_desatualizado():
    # 14/11/2026 12:00 UTC = 09:00 em UTC-3
    r = resposta(gerado_em=instante(0))
    assert aviso_desatualizado(r) == (
        "Dados desatualizados: não foi possível atualizar os dados do BCB agora; "
        "esta análise foi gerada em 14/11/2026 09:00 (UTC-3)."
    )


def test_resposta_velha_nao_altera_o_objeto_guardado():
    original = resposta(gerado_em=instante(0))
    avisos_antes = list(original.avisos_de_qualidade)
    servico, _, relogio, cache = montar(original, INDISPONIVEL)
    vencer(servico, relogio)
    velha = servico.obter()
    assert velha is not original
    assert cache.obter().resposta is original
    assert original.avisos_de_qualidade == avisos_antes


def test_resposta_velha_nao_renova_o_relogio_e_a_proxima_chamada_tenta_de_novo():
    servico, gerador, relogio, cache = montar(
        resposta(gerado_em=instante(0)), INDISPONIVEL, INDISPONIVEL, resposta(gerado_em=instante(500))
    )
    vencer(servico, relogio)
    servico.obter()
    assert not cache.obter().fresca()
    servico.obter()
    assert gerador.chamadas == 3  # a 1ª geração + 2 tentativas que falharam
    nova = servico.obter()  # agora o BCB voltou
    assert gerador.chamadas == 4
    assert nova.gerado_em == instante(500)
    assert nova.avisos_de_qualidade == resposta().avisos_de_qualidade  # sem aviso de velha


def test_sem_entrada_e_servico_indisponivel_levanta():
    servico, _, _, _ = montar(INDISPONIVEL)
    with pytest.raises(ServicoIndisponivelError) as erro:
        servico.obter()
    assert erro.value.motivo == INDISPONIVEL.motivo


def test_excecao_que_nao_e_servico_indisponivel_nao_usa_cache_velho():
    servico, _, relogio, _ = montar(resposta(), ValueError("bug nosso"))
    vencer(servico, relogio)
    with pytest.raises(ValueError):
        servico.obter()


def test_erro_nunca_e_cacheado():
    servico, gerador, _, cache = montar(INDISPONIVEL, resposta())
    with pytest.raises(ServicoIndisponivelError):
        servico.obter()
    assert cache.obter() is None
    servico.obter()  # tenta de novo e funciona
    assert gerador.chamadas == 2


# ------------------------------------------------------------------ concorrência


class GeradorBloqueante:
    """Bloqueia até `liberar` e, só então, devolve/levanta `resultado`."""

    def __init__(self, resultado):
        self.resultado = resultado
        self.liberar = threading.Event()
        self.entrou = threading.Event()
        self.chamadas = 0
        self._trava = threading.Lock()

    def __call__(self):
        with self._trava:
            self.chamadas += 1
        self.entrou.set()
        assert self.liberar.wait(ESPERA), "gerador nunca foi liberado"
        if isinstance(self.resultado, BaseException):
            raise self.resultado
        return self.resultado


def disparar(servico, n):
    """Roda n threads chamando obter(); devolve (threads, resultados), onde cada resultado
    é uma resposta ou a exceção levantada."""
    resultados = [None] * n

    def alvo(i):
        try:
            resultados[i] = servico.obter()
        except BaseException as erro:  # noqa: BLE001 - o teste examina qualquer falha
            resultados[i] = erro

    threads = [threading.Thread(target=alvo, args=(i,), daemon=True) for i in range(n)]
    return threads, resultados


def esperar_seguidoras(servico, quantas):
    """Bloqueia (sem sleep) até `quantas` requisições serem seguidoras do voo."""
    with servico.condicao:
        assert servico.condicao.wait_for(lambda: servico.seguidoras >= quantas, timeout=ESPERA)


def montar_bloqueante(resultado):
    relogio = Relogio()
    cache = CacheResposta(TTL, TTL_FALLBACK, relogio)
    gerador = GeradorBloqueante(resultado)
    return ServicoComCache(gerador, cache), gerador, cache


def rodar_voo(servico, gerador, n=20):
    """1 líder + (n-1) seguidoras; só libera o gerador quando as n-1 já esperam."""
    threads, resultados = disparar(servico, 1)
    threads[0].start()  # líder
    assert gerador.entrou.wait(ESPERA)
    outras, resultados_outras = disparar(servico, n - 1)
    for t in outras:
        t.start()
    esperar_seguidoras(servico, n - 1)  # PROVA: as 19 estão esperando o voo, sem sleep
    gerador.liberar.set()
    for t in threads + outras:
        t.join(ESPERA)
        assert not t.is_alive()
    return resultados + resultados_outras


def test_20_requisicoes_simultaneas_com_cache_vazio_fazem_1_chamada():
    r = resposta()
    servico, gerador, _ = montar_bloqueante(r)
    resultados = rodar_voo(servico, gerador, 20)
    assert gerador.chamadas == 1
    assert servico.seguidoras == 19
    assert len(resultados) == 20
    for item in resultados:
        assert isinstance(item, RespostaMacro)
        assert item.gerado_em == r.gerado_em
        RespostaMacro.model_validate(item.model_dump(mode="json"))


def test_lider_falhando_com_seguidoras_esperando_todas_recebem_servico_indisponivel():
    servico, gerador, cache = montar_bloqueante(INDISPONIVEL)
    resultados = rodar_voo(servico, gerador, 20)
    assert gerador.chamadas == 1  # a coleta NÃO se repete 20 vezes em série
    assert all(isinstance(i, ServicoIndisponivelError) for i in resultados)
    assert all(i.motivo == INDISPONIVEL.motivo for i in resultados)
    assert len({id(i) for i in resultados}) == 20  # uma instância por requisição
    assert cache.obter() is None  # sem cache negativo


def test_lider_falhando_com_cache_velho_todas_recebem_a_velha_com_aviso():
    servico, gerador, cache = montar_bloqueante(INDISPONIVEL)
    velha = resposta(gerado_em=instante(0))
    cache.guardar(velha)
    cache._relogio.t += TTL  # vence a entrada guardada
    resultados = rodar_voo(servico, gerador, 20)
    assert gerador.chamadas == 1
    for item in resultados:
        assert isinstance(item, RespostaMacro)
        assert item.gerado_em == velha.gerado_em
        assert item.avisos_de_qualidade[0] == aviso_desatualizado(velha)
    assert cache.obter().resposta is velha  # intacta


def test_excecao_inesperada_no_lider_seguidoras_recebem_erro_generico():
    bug = ValueError("detalhe interno que não deve vazar")
    servico, gerador, _ = montar_bloqueante(bug)
    resultados = rodar_voo(servico, gerador, 20)
    assert gerador.chamadas == 1
    assert sum(1 for i in resultados if i is bug) == 1  # só o líder vê a original
    seguidoras = [i for i in resultados if i is not bug]
    assert len(seguidoras) == 19
    assert all(isinstance(i, ErroGeracao) for i in seguidoras)
    assert all("interno" not in str(i) for i in seguidoras)
    assert len({id(i) for i in seguidoras}) == 19


@pytest.mark.parametrize("interrupcao", [KeyboardInterrupt(), SystemExit(1)])
def test_baseexception_no_lider_libera_o_voo_e_seguidoras_recebem_erro_generico(interrupcao):
    servico, gerador, _ = montar_bloqueante(interrupcao)
    resultados = rodar_voo(servico, gerador, 5)
    assert sum(1 for i in resultados if i is interrupcao) == 1
    seguidoras = [i for i in resultados if i is not interrupcao]
    assert len(seguidoras) == 4
    assert all(isinstance(i, ErroGeracao) for i in seguidoras)
    assert servico._voo is None  # o finally limpou o voo


def test_lock_mal_liberado_nao_trava_a_requisicao_seguinte_apos_excecao():
    servico, gerador, _, _ = montar(RuntimeError("falha"), resposta())
    with pytest.raises(RuntimeError):
        servico.obter()
    assert servico._voo is None
    assert isinstance(servico.obter(), RespostaMacro)  # não trava e tenta de novo
    assert gerador.chamadas == 2


def test_voo_novo_depois_do_voo_anterior_terminar():
    servico, gerador, relogio, _ = montar(resposta(), resposta())
    servico.obter()
    relogio.t += TTL
    servico.obter()
    assert gerador.chamadas == 2
    assert servico.seguidoras == 0
