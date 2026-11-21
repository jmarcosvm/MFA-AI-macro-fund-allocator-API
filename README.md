# MFA — AI Macro Fund Allocator (API)

> **Simulação educacional. Não é recomendação de investimento.**

API em FastAPI que lê séries oficiais do Banco Central do Brasil (sem chave), calcula indicadores com pandas, classifica o
cenário macro por **regras determinísticas** e usa um LLM **só para escrever o texto** e propor um ajuste limitado da
carteira-modelo. Protótipo de pipeline de dados e orquestração de IA, feito para estudo.

- API pública: <https://mfa-api-4u7m.onrender.com> (Render, plano gratuito: dorme após 15 min sem tráfego; a primeira
  chamada pode levar de ~25 a 50 s)
- Interface: <https://mfa-ai-macro-fund-allocator.vercel.app> (repositório
  [MFA-AI-Macro-Fund-Allocator-Web](https://github.com/jmarcosvm/MFA-AI-Macro-Fund-Allocator-Web))

## Princípio de projeto

O código decide; o LLM interpreta e escreve. O LLM nunca altera números calculados e só enxerga valores já prontos (as
séries históricas do `/analyze` nem entram no prompt). Se o LLM falhar ou violar o contrato, a resposta sai com a carteira
base e um texto de modelo fixo (`justificativa.origem = "fallback"`).

## Endpoints

| Rota | O que faz |
|---|---|
| `GET /health` | Verifica se o servidor está de pé. |
| `GET /api/v1/macro/analyze` | Análise completa (contrato em `SPEC.md` §6): cenário, indicadores, juro real, carteira, justificativa, avisos de qualidade e o bloco `series`. Cache em memória (6 h; 15 min quando o LLM falhou). |
| `GET /api/v1/macro/simulate` | Simulador "E se": determinístico, sem internet, sem LLM e sem cache. |

Códigos do `/analyze`: `200`; `503` quando o BCB falha e não há cache; `500` genérico para erro inesperado. Se o BCB falha
e existe cache antigo, a resposta vem com aviso de dados desatualizados.

### `/analyze`: o que vem na resposta

- `cenario`: `EXPANSAO`, `CONTRACAO` ou `ESTAGFLACAO`, com os critérios e "o que mudaria" (distância aos limiares).
- `indicadores`: Selic efetiva, meta da Selic, IPCA 12m, dólar, volatilidade do dólar (63 dias úteis, anualizada) e IBC-Br
  com as duas janelas de 3 meses (`media`, `meses` e `pontos` com data e valor).
- `juro_real`: ex-post (Selic efetiva x IPCA 12m) e projetado em 12 meses (Focus); o Focus é informativo e não entra na
  regra do cenário.
- `carteira`: `base` (do código), `sugerida` (ajuste do LLM, até ±15 p.p. por classe, validado pelo código) e a
  preferência de indexador da renda fixa (`PREFIXADA` ou `POSFIXADA`).
- `justificativa`: texto, resumo de 2 a 3 linhas e narração do "o que mudaria"; `origem` (`llm` ou `fallback`) e `provedor`.
- `series`: IBC-Br (12 pontos), IPCA 12m (12), Selic efetiva (60) e dólar (120), em ordem crescente de data.
- `avisos_de_qualidade`: defasagem do IBC-Br, nota do Focus, falhas de provedor etc.

### `/simulate`: parâmetros

| Parâmetro | Obrigatório | Faixa aceita |
|---|---|---|
| `ipca_12m_pct` | sim | −5 a 30 |
| `crescimento_ibcbr_pct` | sim | −20 a 20 |
| `selic_efetiva_aa_pct` | sim | 0 a 50 |
| `selic_esperada_pct` | não | 0 a 50 |
| `meta_selic_pct` | não | 0 a 50 |

As faixas são escolhas didáticas, sem fonte. Sem `meta_selic_pct` (ou sem `selic_esperada_pct`), a preferência de
indexador fica `POSFIXADA` com um aviso explicando o porquê. Fora da faixa, o erro `422` vem em português (só nesta rota).

```bash
curl "https://mfa-api-4u7m.onrender.com/api/v1/macro/simulate?ipca_12m_pct=4.63&crescimento_ibcbr_pct=-0.64&selic_efetiva_aa_pct=13.65"
```

## Como funciona

1. **Coleta** (`app/collectors/`): séries do SGS do BCB — Selic efetiva (1178), meta da Selic (432), IPCA 12m (13522),
   dólar venda (1) e IBC-Br com ajuste sazonal (24364) — e expectativas do Focus (Olinda). O Focus é opcional: se cair, o
   campo vem `null` com aviso. HTTP 304 do BCB é tratado como falha transitória (até 3 tentativas, deslocando a
   `dataInicial` em 0, 1 e 2 dias); outros erros não têm nova tentativa.
2. **Indicadores** (`app/indicators.py`): crescimento do IBC-Br (média dos 3 últimos meses contra os 3 anteriores),
   volatilidade do dólar, juro real (Fisher) e distâncias aos limiares.
3. **Regras** (`app/rules.py`): cenário, carteira base e preferência de indexador. Limiares e tabelas em `app/config.py`.
4. **LLM** (`app/llm.py`): chamadas diretas por `httpx2`, uma função por provedor. Cadeia Gemini → NVIDIA NIM → fallback
   sem LLM. A saída passa por validação de formato (Pydantic) e de negócio (soma = 1,0; desvio ≤ 15 p.p.).
5. **Contrato** (`app/schemas.py`) e **cache** (`app/cache.py`, `app/orquestrador.py`): o cache é em memória e é
   pré-aquecido ao iniciar o servidor.

| Cenário | Regra | Renda fixa | Fundos cambiais | Renda variável |
|---|---|---|---|---|
| `EXPANSAO` | crescimento > 0 | 35% | 10% | 55% |
| `CONTRACAO` | crescimento ≤ 0 e IPCA 12m ≤ 4,5% | 55% | 20% | 25% |
| `ESTAGFLACAO` | crescimento ≤ 0 e IPCA 12m > 4,5% | 60% | 25% | 15% |

As alocações são premissas didáticas: nenhum estudo dá esses percentuais.

## Como rodar

Python 3.15 (a imagem Docker usa 3.15.1). Todas as variáveis de ambiente são opcionais: sem chaves, o app sobe e responde
com `origem = "fallback"`.

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows (Linux/macOS: source .venv/bin/activate)
pip install -r requirements.txt
cp .env.example .env              # opcional: preencha chaves e nomes de modelo
uvicorn app.main:app --reload     # http://localhost:8000
```

Com Docker (container `mfa-api`, porta 8000 → 10000):

```bash
docker compose -p mfa up -d --build
docker compose -p mfa -f docker-compose.yml -f docker-compose.free.yml up -d --build   # limites do plano grátis (0,1 CPU, 512 MB)
docker compose -p mfa down
```

Use o container **ou** o uvicorn local na porta 8000, nunca os dois.

## Variáveis de ambiente

Modelo em `.env.example`. O `.env` nunca vai para o git.

| Variável | Para quê |
|---|---|
| `GEMINI_API_KEY`, `LLM_PRIMARY` | Provedor principal (nome do modelo sem prefixo). |
| `NVIDIA_NIM_API_KEY`, `LLM_SECONDARY` | Provedor reserva (id do catálogo build.nvidia.com). |
| `CACHE_TTL_SECONDS`, `CACHE_TTL_FALLBACK_SECONDS` | Vida do cache (padrão 21600 s e 900 s). |
| `CORS_ORIGINS` | Origens permitidas, separadas por vírgula; vazio ou `*` libera qualquer origem. |
| `JANELA_*_DIAS`, `BCB_TIMEOUT_SEGUNDOS` | Janelas de coleta e timeout do BCB (padrões em `app/config.py`). |

## Testes

```bash
pytest -q                     # sem internet e sem chaves
pytest -m internet -s         # toca BCB, Focus e LLMs reais (precisa de .env)
```

Testes de regra usam números fixos; os que tocam a rede ficam marcados com `internet` e fora da execução padrão.

## Deploy

Render (Docker, plano gratuito), com deploy automático a cada merge na `main`. Health check em `/health`. Chaves e nomes de
modelo ficam como variáveis de ambiente no painel, nunca na imagem.

## Limitações

- O juro real ex-post usa a inflação passada como aproximação.
- Focus: mediana semanal; o significado de `baseCalculo` não está confirmado em fonte oficial (usado 0); o horizonte da
  Selic é aproximado pela reunião do Copom mais próxima de hoje + 12 meses, e a tabela de datas (2026–2027) precisa de
  atualização anual.
- A regra do IBC-Br é retrospectiva e o limiar zero é sensível: pequenas variações mudam o cenário.
- O `crescimento_ibcbr_pct` do `/analyze` sai arredondado a 2 casas, mas a classificação usa o valor bruto; no `/simulate`,
  um valor como 0,00 pode classificar diferente do `/analyze`.
- O teto de 4,5% do IPCA é o limite superior da banda de meta (3% ± 1,5 p.p.), em uso didático.
- A causa do HTTP 304 do BCB não foi confirmada; o deslocamento da data resolveu nas medições, mas só foi medido no dólar.
- O log INFO das novas tentativas não aparece no container nem no Render (o app não configura logging).
- Cache só em memória e disco efêmero: reiniciar ou dormir perde o cache. O plano gratuito do Render não é para produção.
- Fontes de dados: BCB (licença ODbL; citar fonte e data). Os limites dos planos gratuitos do Gemini e da NVIDIA não
  foram verificados.

## Documentos do projeto

- [`SPEC.md`](SPEC.md): regras, limiares, contrato JSON e decisões de arquitetura (fonte da verdade).
- [`roadmap.md`](roadmap.md): rodadas feitas, medições e pendências.
