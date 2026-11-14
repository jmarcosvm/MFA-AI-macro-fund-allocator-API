# HANDOFF — MFA (AI Macro Fund Allocator) — estado em 14/11/2026, 05:10

## Quem e como trabalhar com ele
João Marcos, aluno da FATEC. Prazo curto (estágio Gen AI do iFood, trilha AI Builder; também portfólio). Preferências dele (mantenha):
- Antes de executar qualquer coisa: resumir o entendimento e pedir confirmação.
- Explicar do zero, passo a passo, com analogias e o "porquê". Sem exercícios ("preciso terminar logo").
- Objetivo, sem elogios nem enrolação.
- Citar fonte (nome, link, data) e mostrar os dados. Separar o verificado do inferido. Se não achar fonte, dizer.
- Ele cola resultados de terminal/prints; o ambiente do assistente NÃO alcança o BCB (rede bloqueada): testes que tocam a internet são rodados por ele.
- Respostas de outras IAs (Gemini, Perplexity) que ele cola: verificar antes de aceitar (já falharam várias vezes).

## Onde estamos
- Roadmap: P0 problema, P1 dados BCB, P2 regras+contrato, P3 arquitetura = FECHADAS. Próximo: **Parte 4 (backend)**, passo 1 (esqueleto) AINDA NÃO INICIADO.
- Arquivos na pasta do projeto: roadmap.md (sprints R0 a R10), SPEC.md (§1 a §8, fonte da verdade: regras, limiares, contrato JSON §6, stand-by §7, arquitetura §8) e CLAUDE.md (contexto para o Claude Code).
- Código será feito no Cursor com Claude Code (terminal). O assistente ENSINA a escrever os prompts (estrutura: Contexto, Tarefa, Restrições, Critério de pronto, Saída) e o João cola no Claude Code. Cada passo termina com testes passando.
- Pedido do João para a próxima sessão: construir o app em **sprints, começando da R0, definidos no roadmap.md** (como fizeram no projeto IFO). O assistente NÃO tem o formato das sprints do IFO. O roadmap.md atual (R0 a R10) foi escrito em 14/11/2026 com formato PRÓPRIO, assumido: R = rodada; cada rodada tem entrega, cuidados e "pronto quando". No início da sessão: perguntar ao João se o formato do IFO é diferente e, se for, pedir que cole/coloque o roadmap do IFO na pasta e adaptar o roadmap.md. O passo 1 do backend = **R0**, ainda NÃO iniciado.

## Ambiente do João
Windows; pasta C:\Users\João Marcos\Documents\Meus projetos\MFA - AI Macro Fund Allocator; Cursor + Claude Code; Python 3.15.1 (pandas 3.1.1 lista 3.15 e LiteLLM exige <3.16; Pydantic não verificado: o pip install é o teste); Docker instalado; v0 para a interface; chave Gemini ainda NÃO criada (só necessária no passo do LLM); chave NVIDIA depois. Render: workspace "My Workspace 2" (Hobby, grátis) criado; serviço NÃO criado (só no passo de deploy); o IFO V1 está no outro workspace.

## Decisões fechadas (detalhes no SPEC.md)
- Cenário por regra: IBC-Br (média 3 meses vs 3 anteriores, limiar 0, sem faixa neutra) e IPCA 12m (limiar 4,5%). Carteira base 35/10/55, 55/20/25, 60/25/15 (renda fixa/fundos cambiais/renda variável). LLM ajusta até ±15 p.p. por classe (opção A). Preferência de indexador: regra 3.5.
- Juro real ex-post e projetado (Selic esperada na reunião do Copom ~12m à frente vs IPCA esperado 12m do Focus) lado a lado.
- Volatilidade do dólar: 63 dias úteis, anualizada (std dos retornos diários x raiz(252)), informativa.
- LLM: LiteLLM, Gemini (gemini/...) principal, NVIDIA NIM (nvidia_nim/...) reserva, depois fallback determinístico. Nomes de modelo em variáveis de ambiente (Gemini estáveis em 14/11/2026: gemini-3.6-flash, gemini-3.5-flash-lite). LLM faz: justificativa + ajuste + resumo de 2 a 3 linhas + narração do "o que mudaria", em UMA chamada. Sem web search. Validação Pydantic + regras de negócio; se reprovar, próximo provedor.
- Cache em memória (algumas horas). Hospedagem: Render grátis (dorme após 15 min, ~1 min para voltar; 512 MB RAM; 750 h por workspace). Sem ping de manutenção. Front mostra "acordando o servidor"; pré-aquecer o cache ao iniciar. v0 chama a API em outro domínio: configurar CORS.
- Stand-by (fora da v1): curva de juros do Tesouro, cartões de contexto (DBGG 13762, crédito 20539, fluxo estrangeiro 22924, desemprego 24369), EVAL.md, /history, pipeline_metrics.

## Pendências e riscos abertos
- Obter a meta Selic vigente (série 432, linha com data <= hoje; não testado). PTAX via Olinda não testada. Aviso CVM é premissa não verificada.
- Limites do plano gratuito do Gemini NÃO verificados (página não abriu). Termos da NVIDIA free para demo pública não lidos (só blogs); Brasil como país suportado não confirmado; escolher o modelo no catálogo "Free Endpoint" na hora.
- Memória do LiteLLM dentro de 512 MB desconhecida: medir no passo de Docker; plano B é chamar as APIs direto com httpx.
- Checar se o plano do workspace novo do Render é Hobby (Billing).
- Aprendizado: uma resposta de WebFetch mostrou só 3 pontos antigos de uma série (22924) e eu afirmei defasagem errada; conferir dados importantes com mais de uma consulta.
- README deve dizer: limitação do juro real ex-post, limites do Focus (baseCalculo não documentado, semanal, mediana), alocações didáticas sem evidência vs 1/N, expectativas já precificadas, evidência do problema é indireta, ajuste da carteira é ilustração.

## Prompt do passo 1 (pronto para o Claude Code)
```
Leia CLAUDE.md e SPEC.md (seções 6 e 8).

TAREFA: criar o esqueleto do backend (passo 1 do roadmap).
- app/__init__.py e app/main.py: FastAPI com GET /health retornando {"status": "ok"}
- app/config.py: lê variáveis de ambiente com pydantic-settings
  (GEMINI_API_KEY, NVIDIA_NIM_API_KEY, LLM_PRIMARY, LLM_SECONDARY,
  CACHE_TTL_SECONDS com padrão 21600)
- requirements.txt com as versões exatas que você instalar
- .env.example com essas variáveis, sem valores reais; LLM_PRIMARY e
  LLM_SECONDARY vazios, com comentário dizendo que o nome do modelo
  será definido depois
- .gitignore (inclua .env, .venv, __pycache__)
- tests/test_health.py usando o TestClient

RESTRIÇÕES: não implemente coleta de dados, regras nem LLM ainda.
Não invente nomes de modelo. Avise antes de adicionar qualquer
dependência além de fastapi, uvicorn, pydantic-settings, pytest e httpx.

PRONTO QUANDO: venv criado, pip install -r requirements.txt sem erro,
pytest passa e o uvicorn sobe com /health respondendo.

SAÍDA: liste os arquivos criados e o comando para rodar o servidor.
```
Antes de rodar: git init e um commit inicial.
