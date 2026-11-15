# roadmap.md — MFA (AI Macro Fund Allocator)
Atualizado em 15/11/2026. Fonte da verdade das regras: SPEC.md. Contexto fixo: CLAUDE.md.
Convenção: R = rodada (sprint) numerada a partir de R0. Tempos são PALPITE, não medidos.
Status: [ ] a fazer  [~] em andamento  [x] concluída

## Fase de especificação (concluída, ver SPEC.md)
Problema, fontes de dados, regras e limiares, contrato JSON (§6), arquitetura (§8): LiteLLM (Gemini -> NVIDIA -> fallback), cache em memória, Render grátis em "My Workspace 2".
Stand-by (fora da v1): SPEC.md §7 (curva do Tesouro, cartões de contexto, EVAL.md, /history, pipeline_metrics). Web search do LLM: fora.

## Regras de cada rodada
- Uma rodada por vez; só avança com o critério de pronto cumprido.
- Testes de regra usam números fixos (sem internet). Testes que tocam o BCB ficam marcados e separados.
- Commit ao final de cada rodada (ponto de retorno).
- Todo prompt para o Claude Code segue: Contexto, Tarefa, Restrições, Critério de pronto, Saída.

## R0 — Esqueleto e ambiente [x]  (~20 min)
Entrega: app/main.py (GET /health), app/config.py (variáveis de ambiente), requirements.txt com versões exatas, .env.example, .gitignore, tests/test_health.py.
Pronto quando: venv + pip install ok (Python 3.15.1: se alguma biblioteca falhar, usar versão mais antiga só neste projeto), pytest passa, uvicorn responde /health. git init + commit inicial.

## R1 — Coleta BCB [x]  (~25 min)
Entrega: app/collectors/bcb.py. Séries: 1178 (Selic efetiva), 13522 (IPCA 12m), 1 (dólar venda), 24364 (IBC-Br c/ ajuste sazonal), 432 (meta Selic; linha com data <= hoje).
Cuidados: valores vêm como texto; datas dd/mm/aaaa; ordenar por data; janelas grandes dão HTTP 406; timeout por chamada.
Pronto quando: testes com respostas simuladas passam; 1 teste marcado "internet" roda localmente e traz dados reais.
Validado em 14/11/2026 (teste "internet"): janelas padrão em dias, configuráveis em app/config.py: IBC-Br 365 (10 pontos), dólar 120 (83), Selic efetiva 60 (42), IPCA 150 (5; 60 dias traria só ~2), meta Selic 90 (linha com data <= hoje: 13,75). Timeout 10 s por chamada.

## R2 — Coleta Focus [x]  (~25 min)
Entrega: app/collectors/focus.py (Olinda): IPCA 12m (Suavizada = S, baseCalculo 0) e Selic por reunião (tabela de datas do Copom 2026-2027, SPEC.md §3.3). Queda do Focus -> campo null + aviso, não derruba a API.
Pronto quando: testes simulados passam + 1 teste "internet".
Validado em 15/11/2026 (teste "internet"): IPCA 12m mediana 5,0117 e Selic R7/2027 mediana 12,75, ambas com Data 06/11/2026 (iguais ao SPEC). Cuidado descoberto: o Olinda responde HTTP 400 se o espaço da query vier como "+" (precisa de "%20"); há teste de regressão.
Pendente [resolvido na R2.1]: CALENDARIO_COPOM só tinha R7/2027 (26-27/out/2027, do SPEC); as demais reuniões 2026-2027 foram preenchidas na R2.1.

## R2.1 — Calendário do Copom e virada da reunião [x]  (~25 min)
Entrega: CALENDARIO_COPOM (app/config.py) com as 16 reuniões de 2026-2027 (data da decisão, 2º dia); escolher_reuniao devolve a reunião, o alvo e a distância em dias; coletar_focus aplica TOLERANCIA_REUNIAO_DIAS (padrão 60, variável de ambiente).
Regra: reunião de decisão mais próxima de hoje + 12 meses; empate = a mais cedo; 29/fev + 12 meses = 28/fev. Distância > tolerância (ou tabela vazia): selic_esperada = null + aviso com a distância e o fim da tabela; a API não cai.
Conferência das datas: as 16 datas do CALENDARIO_COPOM foram conferidas na página oficial do BC em 15/11/2026 (BCB Calendar, "Copom meetings Calendar", anos 2026 e 2027): as 16 reuniões batem (Dia 1 - Dia 2). Atualizar quando o BC publicar 2028 (~jun/2027).
Validado em 15/11/2026 (teste "internet"): alvo 15/11/2027, reunião R7/2027 (27/10/2027), distância alvo -> reunião 19 dias (hoje -> reunião: 346 dias), Selic esperada mediana 12,75 (Focus de 06/11/2026), sem avisos. A virada para R8/2027 ocorre a partir de 18/11/2026; sem 2028 na tabela, a Selic esperada vira null depois de 06/02/2027 (aviso).

## R3 — Indicadores (pandas) [x]  (~25 min)
Entrega: app/indicators.py: IBC-Br (média 3m recente vs 3m anterior), volatilidade do dólar (63 dias úteis, anualizada: std dos retornos x raiz(252)), juro real ex-post e projetado (Fisher), "o que mudaria" (distâncias aos limiares).
Pronto quando: testes com números fixos reproduzem os valores do SPEC.md (-0,64%; 8,62%; 7,37%; 0,13 p.p.; 112,23).
Decisões (15/11/2026): desvio-padrão amostral (ddof=1); dados insuficientes ou inválidos levantam IndicadorError (mínimos: 6 pontos do IBC-Br, 64 preços do dólar; só as últimas N contam); "o que mudaria" devolve None quando já está do lado favorável (IPCA <= 4,5 ou crescimento > 0); sem arredondamento em indicators.py (fica para o contrato, R5). Limiares (0,0 e 4,5) em app/config.py. Dependência nova: pandas==3.1.1.
Validado em 15/11/2026 (teste "internet"): IBC-Br 10 pontos; médias 110,9836 (mar-mai) e 110,2705 (jun-ago), variação -0,6425%; volatilidade do dólar 23,18% (82 preços, sem referência no SPEC); juro real ex-post 8,6209% (Selic 13,65; IPCA 4,63); ipca_precisa_cair_pp 0,13; ibcbr_proximo_mes_precisa_superar 112,23. Tudo igual ao SPEC. Os testes de Fisher projetado (7,37%) e da ida e volta rodam sem internet.

## R4 — Regras [x]  (~20 min)
Entrega: app/rules.py: cenário (limiar 0 e 4,5%), carteira base (35/10/55; 55/20/25; 60/25/15), preferência de indexador (SPEC.md §3.5, exceção ESTAGFLACAO).
Pronto quando: testes cobrem os 3 cenários, limites exatos e a exceção.
Decisões (15/11/2026): retorno com Enum (Cenario, PreferenciaIndexador), carteira como dict com as chaves do contrato (cópia a cada chamada) e indexador como (preferência, avisos); crescimento comparado SEM arredondar (0,004 aparece como 0,00 no contrato, mas classifica como EXPANSAO); entradas inválidas (None, NaN, infinito, tipo errado) levantam RegraError; Selic esperada None fora de ESTAGFLACAO -> POSFIXADA com aviso; PASSO_COPOM_PP = 0,25 em app/config.py; a diferença Selic esperada - meta é arredondada a 6 casas (15,81 - 16,06 dá -0,24999999999999822 em float; sem o round() a regra falharia). Sem dependência nova.
Verificado em 15/11/2026: suíte completa 126 passed, 3 deselected; testes sem internet (a R4 não toca a rede). Matriz 3x3 do cenário, fronteiras do indexador (13,50 PREFIXADA; 13,51 POSFIXADA; 12,75 PREFIXADA; 13,75 POSFIXADA; None POSFIXADA com aviso) e caso de hoje (ESTAGFLACAO, 0,60/0,25/0,15, POSFIXADA) passam.

## R5 — Contrato Pydantic [x]  (~20 min)
Entrega: app/schemas.py conforme SPEC.md §6 + validação de negócio (soma = 1,0; desvio <= 15 p.p.; sem pesos negativos).
Pronto quando: exemplo do SPEC.md valida; casos inválidos são rejeitados nos testes.
Decisões (15/11/2026): meta_selic_aa entra em "indicadores" (SGS 432), logo depois da Selic efetiva; pydantic==2.14.3 travado no requirements.txt; LIMITE_DESVIO_PP = 15.0 em app/config.py; soma dos pesos com tolerância de 1e-6; desvio comparado com round(diferença, 6) (0,40 - 0,25 dá 0,15000000000000002 em float); None só em juro_real.projetado_12m_pct e entradas_projetado (os dois juntos ou nenhum dos dois) e nos 2 campos de o_que_mudaria; o schema não confere base x tabela do cenário (a R7 monta a base); campos calculados arredondados na construção (2 casas; médias do IBC-Br e ipca_esperado_12m a 4) e -0.0 normalizado para 0.0; origem "fallback" exige sugerida = base e provedor None; "llm" exige provedor; gerado_em com fuso; campos desconhecidos rejeitados.
Verificado em 15/11/2026: suíte completa 163 passed, 3 deselected (37 testes novos em tests/test_schemas.py, sem internet). Exemplo do SPEC valida e faz ida e volta em JSON; soma 0,95 e 1,05, peso negativo, peso > 1, 15,01 p.p., enums inválidos, fallback com sugerida != base, gerado_em sem fuso e campos ausentes são rejeitados; os pares de fronteira 0,25->0,40, 0,55->0,40 e 0,35->0,50 são aceitos.

## R6 — Camada de LLM [x]  (~35 min)  (precisa da chave do Gemini)
Entrega: app/llm.py com chamadas diretas via httpx2 (uma função por provedor: Gemini generateContent e NVIDIA NIM chat completions; sem LiteLLM). Nomes de modelo em LLM_PRIMARY e LLM_SECONDARY (sem prefixo). Cadeia Gemini -> NVIDIA -> fallback determinístico; saída validada pelo Pydantic; falha ou violação de regra passa ao próximo provedor. O LLM devolve justificativa, resumo de 2 a 3 linhas, narração do "o que mudaria" e carteira sugerida.
Pronto quando: testes com LLM simulado cobrem sucesso, resposta inválida e todos falhando; 1 teste "internet" por provedor com chave real.
Decisões (15/11/2026): (1) LiteLLM descartado: a versão 1.109.1 (publicada em 11/11/2026, sem proveniência assinada) traria 41 pacotes novos (inclusive o httpx 0.28.1 ao lado do httpx2), rebaixaria o python-dateutil e rodaria no mesmo processo que lê as chaves; o João citou o comprometimento de versões em 03/2026 (relato, não verificado por mim). Venv restaurado; requirements.txt não mudou. Memória do litellm, só como evidência (Windows, relato): 97 MB de base, 269 MB após o import, 284 MB após mock; a medição definitiva do app fica para o Docker (R8, limite de 512 MB). (2) Contrato estendido (SPEC §6): justificativa ganha resumo (2 a 3 linhas) e narracao_o_que_mudaria, com tetos de tamanho em app/config.py (sem fonte). (3) Timeout de 25 s por chamada, orçamento de 45 s, uma tentativa por provedor sem retry, LLM_MAX_TOKENS 4096: valores iniciais sem fonte, configuráveis. (4) Chave só em header; exceções com texto fixo, nunca o corpo da resposta. (5) LLM_PRIMARY exige começar com letra ou número e rejeita ".."; vazio = provedor pulado com aviso. (6) O prompt manda citar os pesos como percentual com vírgula nos textos; fração com ponto só em carteira_sugerida.
Achados da NVIDIA (15/11/2026): o formato OpenAI (POST /v1/chat/completions, Authorization: Bearer, finish_reason "stop" ou "length") foi confirmado na prática, mas a doc oficial não o mostra em texto. Modelos de raciocínio podem devolver finish_reason "length" com content vazio (visto com max_tokens 32); a cadeia trata como resposta truncada e passa ao próximo. Há ids do catálogo (/v1/models) que dão 404 por conta, então estar na lista não garante resposta. O openai/gpt-oss-20b, primeira escolha do João, não respondeu nesta conta; o poolside/laguna-xs-2.1 respondeu em 22 s (perto do timeout, com qualidade baixa); LLM_SECONDARY = nvidia/nemotron-3.5-bolt-e4b (cerca de 5 s). O response_format da NVIDIA foi aceito por esses dois modelos; LLM_SECONDARY_JSON_MODE fica desligada por padrão.
Resultado: pytest padrão 304 passed, 6 deselected (sem internet e sem chave); pip check ok; requirements.txt sem mudança; PR #11. Testes internet (saída crua colada pelo João, 15/11/2026, duas execuções, 3 passed in 12.78s e 3 passed in 15.51s): Gemini 2,31 s e 6,02 s; NVIDIA 4,75 s e 4,56 s; JSON válido nas duas; response_format da NVIDIA aceito (5,55 s e 4,70 s).
Nota para a R7: httpx2.Client é síncrono; o endpoint deve ser def (executado em thread) ou chamar a cadeia numa thread.

## R7.1 — Pipeline (app/service.py) [x]
Entrega: gerar_resposta(agora, *, cliente, coletores, focus, analisar) -> RespostaMacro; sem cache, rota nem threads (R7.2). Hoje = data em UTC-3 fixo (sem horário de verão desde 2019: conhecimento geral, não verificado). BCB falhando ou sem dados -> ServicoIndisponivelError (a R7.2 vira 503 ou cache antigo); Focus e LLM seguem com None/fallback.
Decisões: coleta sequencial; um httpx2.Client compartilhado; avisos gerados dos dados (IBC-Br, nota do Focus, Focus, regra, LLM), sem aviso de defasagem para IPCA/dólar (SPEC não define limiar); AVISO_FIXO e FUSO_BRASIL em service.py.
Resultado (15/11/2026): pytest -q 332 passed, 7 deselected; 28 casos em tests/test_service.py (fixture do IBC-Br sintética, 10 pontos); requirements.txt sem mudança; commits 1f13189 (feat) e 5e1d647 (test).
Teste "internet" (saída colada pelo João): 1 passed in 4,51 s; pipeline 3,89 s, medido uma vez (Gemini); origem llm; números iguais ao SPEC §6.
Avisos reais: IBC-Br ~2,5 meses (ago/2026) e nota do Focus de 06/11/2026.
Observação: meta_selic_aa.data é a data da última linha da série 432 (hoje), não a da decisão do Copom (inferência; série diária não confirmada).
Pior caso nominal 115 s (50 BCB + 20 Focus + 45 LLM), calculado de config.py, não medido.

## R7.2 — Cache e endpoint [ ]  (~25 min)
Entrega: app/cache.py (TTL, padrão 6 h) e GET /api/v1/macro/analyze completo; CORS; "desatualizado" quando o BCB falha e há cache antigo; pré-aquecer cache ao iniciar.
Pronto quando: resposta bate com o contrato; 2a chamada vem do cache.

## R8 — Docker e deploy [ ]  (~30 min)
Entrega: Dockerfile, medir memória do container, serviço no Render ("My Workspace 2", plano Hobby), variáveis de ambiente no painel.
Pronto quando: URL pública responde /health e /api/v1/macro/analyze.

## R9 — Interface (v0) [ ]  (~1 h)
Entrega: tela com cenário, carteira base x sugerida, juro real ex-post x projetado, "o que mudaria", IBC-Br clicável (3 meses), avisos de qualidade, estado de carregamento ("acordando o servidor, ~1 min").
Pronto quando: front publicado consome a API pública.

## R10 — README e pitch [ ]  (~30 min)
Entrega: README (problema, arquitetura, limitações do SPEC.md §4, aviso educacional, como rodar) e texto curto para o recrutador.
