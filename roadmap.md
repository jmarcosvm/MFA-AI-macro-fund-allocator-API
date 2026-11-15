# roadmap.md — MFA (AI Macro Fund Allocator)
Atualizado em 14/11/2026. Fonte da verdade das regras: SPEC.md. Contexto fixo: CLAUDE.md.
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
Pendente: CALENDARIO_COPOM (app/config.py) só tem R7/2027 (26-27/out/2027, do SPEC); as demais reuniões 2026-2027 precisam ser preenchidas pelo João.

## R3 — Indicadores (pandas) [ ]  (~25 min)
Entrega: app/indicators.py: IBC-Br (média 3m recente vs 3m anterior), volatilidade do dólar (63 dias úteis, anualizada: std dos retornos x raiz(252)), juro real ex-post e projetado (Fisher), "o que mudaria" (distâncias aos limiares).
Pronto quando: testes com números fixos reproduzem os valores do SPEC.md (-0,64%; 8,62%; 7,37%; 0,13 p.p.; 112,23).

## R4 — Regras [ ]  (~20 min)
Entrega: app/rules.py: cenário (limiar 0 e 4,5%), carteira base (35/10/55; 55/20/25; 60/25/15), preferência de indexador (SPEC.md §3.5, exceção ESTAGFLACAO).
Pronto quando: testes cobrem os 3 cenários, limites exatos e a exceção.

## R5 — Contrato Pydantic [ ]  (~20 min)
Entrega: app/schemas.py conforme SPEC.md §6 + validação de negócio (soma = 1,0; desvio <= 15 p.p.; sem pesos negativos).
Pronto quando: exemplo do SPEC.md valida; casos inválidos são rejeitados nos testes.

## R6 — Camada de LLM [ ]  (~35 min)  (precisa da chave do Gemini)
Entrega: app/llm.py: LiteLLM (gemini/ e nvidia_nim/), nomes de modelo por variável de ambiente, timeout, saída validada pelo Pydantic, tenta o próximo provedor se falhar ou violar regra, fallback determinístico. LLM devolve: justificativa, resumo de 2 a 3 linhas, narração do "o que mudaria", carteira sugerida.
Medir a memória do LiteLLM (limite de 512 MB no Render). Se não couber: httpx direto.
Pronto quando: testes com LLM simulado cobrem sucesso, resposta inválida e todos falhando; 1 teste "internet" com chave real.

## R7 — Cache e endpoint [ ]  (~25 min)
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
