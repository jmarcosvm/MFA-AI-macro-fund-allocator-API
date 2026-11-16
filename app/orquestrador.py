"""Orquestração do cache (R7.2): single-flight e uso da resposta velha. Sem FastAPI.

Fluxo de `obter()`:
1. Cache fresco -> devolve (nenhuma chamada ao gerador).
2. Senão, a 1ª requisição vira LÍDER e chama o gerador; as demais viram SEGUIDORAS do mesmo
   "voo" e esperam o líder terminar (só UMA coleta, mesmo com N requisições simultâneas).
3. Sucesso -> guarda no cache (TTL pela origem) e todas recebem a resposta.
4. ServicoIndisponivelError -> se há resposta guardada (mesmo vencida), devolve uma CÓPIA
   com o aviso de desatualizado na 1ª posição de avisos_de_qualidade (gerado_em continua o
   ORIGINAL e o relógio do cache NÃO é renovado: a próxima requisição tenta de novo); sem
   resposta guardada, levanta ServicoIndisponivelError (a rota vira 503).
5. Qualquer outra falha do gerador (bug nosso) NUNCA usa cache velho: o líder relança a
   exceção original e as seguidoras recebem ErroGeracao (genérico, sem reaproveitar a mesma
   instância em várias threads). Erros nunca são cacheados.

Nenhum lock é segurado durante a chamada ao gerador; o mutex só protege a decisão
líder/seguidora e o `finally` do líder sempre limpa o voo e acorda as seguidoras.

LIMITAÇÕES (documentadas, não resolvidas):
- A espera das seguidoras não tem limite de tempo. O pior caso NOMINAL do pipeline é 115 s
  (50 BCB + 20 Focus + 45 LLM; calculado, não medido) e o limite de requisição do Render
  NÃO foi verificado.
- Rotas `def` rodam no pool de threads do anyio (40, verificado em anyio 4.16.0); cada
  seguidora esperando ocupa uma vaga. A 41ª requisição não é recusada: espera uma vaga.
- Durante uma queda do BCB com resposta velha em cache, cada requisição NOVA paga uma
  tentativa (o cache velho não renova o relógio); as simultâneas dividem a mesma tentativa.
- O cliente que desconecta não cancela a coleta em andamento.
"""

import threading
from collections.abc import Callable

from app.cache import CacheResposta
from app.schemas import RespostaMacro
from app.service import FUSO_BRASIL, ServicoIndisponivelError


class ErroGeracao(Exception):
    """Falha inesperada (não é ServicoIndisponivelError) na geração feita por outra requisição."""


class _Voo:
    """Uma tentativa de geração em andamento, compartilhada pelo líder e pelas seguidoras."""

    def __init__(self) -> None:
        self.evento = threading.Event()
        self.resposta: RespostaMacro | None = None
        self.motivo: str | None = None  # preenchido se o gerador levantou ServicoIndisponivelError


def aviso_desatualizado(resposta: RespostaMacro) -> str:
    gerado = resposta.gerado_em.astimezone(FUSO_BRASIL)
    return (
        "Dados desatualizados: não foi possível atualizar os dados do BCB agora; "
        f"esta análise foi gerada em {gerado:%d/%m/%Y %H:%M} (UTC-3)."
    )


def com_aviso_desatualizado(resposta: RespostaMacro) -> RespostaMacro:
    """Cópia com o aviso na 1ª posição. O objeto original (do cache) não é alterado."""
    avisos = [aviso_desatualizado(resposta), *resposta.avisos_de_qualidade]
    return resposta.model_copy(update={"avisos_de_qualidade": avisos})


class ServicoComCache:
    def __init__(self, gerador: Callable[[], RespostaMacro], cache: CacheResposta):
        self._gerador = gerador
        self._cache = cache
        self._voo: _Voo | None = None
        # Mutex da decisão líder/seguidora. É uma Condition para os testes poderem esperar
        # (sem sleep) até `seguidoras` chegar a N.
        self.condicao = threading.Condition()
        # Gancho de observação: quantas requisições entraram como SEGUIDORAS (cumulativo).
        # Incrementado dentro do mutex.
        self.seguidoras = 0

    def obter(self) -> RespostaMacro:
        with self.condicao:
            entrada = self._cache.obter()
            if entrada is not None and entrada.fresca():
                return entrada.resposta
            voo = self._voo
            lider = voo is None
            if lider:
                voo = self._voo = _Voo()
            else:
                self.seguidoras += 1
                self.condicao.notify_all()

        if lider:
            self._executar(voo)
        else:
            voo.evento.wait()  # sem limite de tempo (ver LIMITAÇÕES)
        return self._resolver(voo)

    def _executar(self, voo: _Voo) -> None:
        try:
            resposta = self._gerador()
            self._cache.guardar(resposta)
            voo.resposta = resposta
        except ServicoIndisponivelError as erro:
            voo.motivo = erro.motivo
        finally:
            # Roda também para KeyboardInterrupt/SystemExit: o voo nunca fica preso.
            with self.condicao:
                self._voo = None
            voo.evento.set()

    def _resolver(self, voo: _Voo) -> RespostaMacro:
        if voo.resposta is not None:
            return voo.resposta
        if voo.motivo is None:
            # Sem resposta e sem ServicoIndisponivelError: o líder levantou outra coisa.
            # (O líder nunca chega aqui: a exceção original dele já subiu em _executar.)
            raise ErroGeracao("A geração da análise falhou por erro inesperado.")
        entrada = self._cache.obter()
        if entrada is None:
            raise ServicoIndisponivelError(voo.motivo)
        if entrada.fresca():  # outra tentativa já renovou enquanto esperávamos
            return entrada.resposta
        return com_aviso_desatualizado(entrada.resposta)
