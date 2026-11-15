# SPEC.md — AI Macro Fund Allocator (v0.2, 14/11/2026)

Status: Partes 0 a 3 fechadas. Contém regras (§3), alocações-base (§3.4), contrato JSON (§6), stand-by (§7) e decisões de arquitetura (§8). Próximo: Parte 4 (backend).
Convenção: [verificado] = conferido em fonte; [decisão] = escolha do João Marcos; [inferência] = cálculo/hipótese do Claude; [pendente] = em aberto.

## 1. Problema e posicionamento
Protótipo educacional de pipeline de dados e orquestração de IA, para treinar vibe coding. Não é recomendação de investimento nem concorrente de terminais.

Texto do problema (aprovado):
> Analistas e estudantes de finanças gastam parte relevante do tempo coletando e cruzando dados de fontes diferentes antes de analisar. Evidência indireta: pesquisa da Anaconda (2020, 2.360 profissionais de dados) estimou 45% do tempo em carga e limpeza de dados; a Alveo reportou 25% a 50% em serviços financeiros. Nenhuma mede especificamente séries macro. O protótipo automatiza uma parte desse fluxo: ingestão de séries oficiais do BCB, cálculo de indicadores e rascunho de relatório.

Notas: Anaconda e Alveo são fornecedores de software de dados. Da Alveo não vi amostra nem data. Não existe fonte específica para analistas macro.

## 2. Fontes de dados (testadas em 13/11/2026, sem chave)
| Série | ID | Unidade | Frequência | Último valor | Observação |
|---|---|---|---|---|---|
| Selic efetiva anualizada | 1178 | % a.a. | diária | 13,65 (13/11/2026) | usar esta |
| IPCA acumulado 12m | 13522 | % | mensal | 4,63 (ref. out/2026) | data no JSON = dia 1 do mês de referência |
| Dólar comercial venda | 1 | R$ | diária (dias úteis) | 5,6518 (13/11/2026) | |
| IBC-Br com ajuste sazonal | 24364 | índice | mensal | 110,40624 (ago/2026) | defasagem ~2,5 meses |
| Focus (Olinda) ExpectativasMercadoAnuais | — | % | estatística diária, publicada às segundas | IPCA 2027 mediana 4,9005; Selic 2027 mediana 12,50 (Data 06/11/2026, baseCalculo=0) | numérico; 2 linhas por data (baseCalculo 0 e 1) |

Descartadas: 432 (Selic meta; devolve datas futuras; meta de 13,75% mantida pelo Copom em 04/11/2026, segundo Rankia; usada na R1 com filtro data <= hoje (ver §5)), 11, 433.
Cuidados: SGS devolve valor como texto e data dd/mm/aaaa; ordenar por data; janelas grandes dão HTTP 406 (fatiar); licença ODbL (citar fonte e data).
Focus: relatório sai toda segunda 8h30 com dados até a sexta anterior (FAQ13 do BCB). Significado de baseCalculo 0/1 NÃO confirmado em fonte; usar 0 (mais respondentes) e declarar.
IPCA: em 10/11 a série terminava em set/2026; em 13/11 já trazia out/2026 (uma observação).

## 3. Regras
### 3.1 Juro real [decisão]
- Ex-post: (1 + Selic 1178) / (1 + IPCA 12m 13522) − 1. Hoje: 8,62%.
- Projetado, horizonte hoje + 12 meses (Focus) [decisão]: (1 + Selic esperada na reunião do Copom mais próxima de hoje + 12 meses) / (1 + IPCA esperado 12 meses, Suavizada=S) − 1, medianas, baseCalculo=0. Em 06/11/2026: Selic R7/2027 = 12,75%; IPCA 12m = 5,0117%; resultado 7,37% [inferência, cálculo manual]. Rótulo: "projeção do mercado", não previsão do app.
- Mostrados lado a lado. O Focus é informativo e NÃO entra na regra do cenário.

### 3.2 Cenário (heurística didática, não modelo econométrico) [decisão]
- Crescimento do IBC-Br = média dos 3 últimos meses vs média dos 3 meses anteriores (série 24364).
- crescimento ≤ 0 e IPCA 12m > 4,5% → ESTAGFLACAO; crescimento ≤ 0 e IPCA ≤ 4,5% → CONTRACAO; crescimento > 0 → EXPANSAO.
- Limiar do crescimento = 0, sem faixa neutra (opção A) [decisão]. A interface mostra a distância ao limiar (hoje: faltam +0,64 p.p. para chegar a zero; o IPCA precisaria cair 0,13 p.p. para ficar ≤ 4,5%) [inferência, cálculo manual].
- A API devolve os 6 meses, as duas médias e a variação; a interface mostra o detalhe ao clicar (decisão: opção A).
- Valores de hoje [inferência, cálculo manual; o código recalcula]: médias 110,2705 (jun-ago) e 110,9836 (mar-mai); variação −0,64%; IPCA 4,63% → ESTAGFLACAO.
- Teto 4,5% = limite superior da banda (meta 3% ± 1,5 p.p. para 2025–2027). Fonte secundária: Safra, 26/06/2024. Resolução do CMN não verificada. Uso didático, sem afirmar "descumprimento".

### 3.3 Horizonte do Focus [decisão]
- IPCA: ExpectativasMercadoInflacao12Meses (Indicador=IPCA, Suavizada=S, baseCalculo=0). Significado de S/N não confirmado em fonte; mediana de 06/11/2026: S = 5,0117, N = 4,9557.
- Selic: ExpectativasMercadoSelic (Reuniao='R#/aaaa', baseCalculo=0), na reunião do Copom mais próxima de hoje + 12 meses, escolhida por uma tabela de datas mantida no código (2026-2027 conforme Rankia, atualizada em 05/11/2026; página do BC não verificada). Em 13/11/2026 hoje + 12 meses = 13/11/2027, então R7/2027 (26-27/out/2027); mediana 12,75% em 06/11/2026 (12,50% em 05/11 e 04/11).
- Plano B: recurso anual (ExpectativasMercadoAnuais) com o ano de referência declarado.

### 3.4 Alocações-base [decisão]
Premissas didáticas, a partir da tabela de um texto do Perplexity; nenhum estudo dá esses percentuais.

| Cenário | Renda fixa | Fundos cambiais | Renda variável |
|---|---|---|---|
| EXPANSAO | 35% | 10% | 55% |
| CONTRACAO | 55% | 20% | 25% |
| ESTAGFLACAO | 60% | 25% | 15% |

Mecanismo: a base vem do código; o LLM pode ajustar cada classe até ±15 p.p., justificando; o código valida (soma 1,0 e limite) e corrige ou rejeita. Exemplo: com base 60/25/15, uma carteira 55/20/25 está dentro do limite.

### 3.5 Preferência de indexador da renda fixa [decisão, confirmada em 13/11/2026]
- Campo calculado pelo código (renda_fixa_preferencia: PREFIXADA ou POSFIXADA); o LLM só explica.
- Se cenário = ESTAGFLACAO: POSFIXADA/curto prazo (Man Group: em inflação alta e crescente, ações -7% e título de 10 anos -5% ao ano acima da inflação, dados desde 1926; prazos mais longos vão pior).
- Senão: se Selic esperada (reunião ~12 meses, Focus) <= meta atual - 0,25 p.p. (um passo do Copom): PREFIXADA; senão: POSFIXADA.
- Hoje: 12,75% esperada contra meta 13,75% = -1,00 p.p. (queda), mas o cenário é ESTAGFLACAO, então POSFIXADA [inferência, cálculo manual].
- Limitação: a expectativa do Focus já está embutida nos preços dos prefixados; sem curva de juros, a regra é uma heurística didática.

## 4. Limitações (para o README)
- Juro real ex-post usa inflação passada como aproximação.
- Focus: mediana de ~144 instituições, atualizada semanalmente; Selic esperada é meta e a de hoje é efetiva (~0,10 p.p.); a mediana da Selic anda em passos de 0,25 p.p.; o horizonte da Selic é aproximado pela reunião mais próxima (diferença de algumas semanas); a tabela de datas do Copom precisa de atualização anual.
- Regra do IBC-Br é retrospectiva: a queda de junho ainda pesa na média apesar da alta de agosto.
- Limiar zero é sensível: o cenário atual está a 0,64 p.p. do limiar.
- Alocações são premissas didáticas: a direção das mudanças é inspirada em literatura, os números não vêm de estudo; não há evidência de que superem a divisão igual (DeMiguel et al., 2009; resultado conhecido por mim, fonte não aberta).
- Casos isolados (2007, 2008, 2015) foram escolhidos sem usar a regra do app; só citar depois de rodar o /history.
- A preferência por prefixado ignora que a expectativa de queda já está nos preços.

## 5. Pendências
- [resolvido, 14/11/2026] Meta vigente da Selic: série 432 com filtro data <= hoje; valor 13,75% (data 14/11/2026), obtido no teste 'internet' da R1.
- [pendente] Aviso obrigatório: simulação educacional, não é recomendação de investimento (risco regulatório CVM; premissa não verificada).
- [decisão, 14/11/2026] Volatilidade do dólar: janela de 63 dias úteis, **anualizada** = desvio-padrão dos retornos diários simples (pct_change da série 1) x raiz(252), em %. Papel na v1: informativa, fora da regra do cenário.
- [pendente] PTAX via Olinda não testada.

## 6. Contrato de saída (JSON) [decisão, 14/11/2026]
Escopo v1 = opção A: só o núcleo. Campos abaixo; os valores do exemplo são os de 13/11/2026, exceto `carteira.sugerida` (hipotética, ilustra o ajuste do LLM).
Regras do contrato (validadas com Pydantic): soma de `carteira.sugerida` = 1,0; cada classe desvia no máximo `limite_desvio_pp` da `base`; se o LLM falhar ou violar, `justificativa.origem = "fallback"` e `sugerida = base`. `justificativa` tem `texto`, `resumo` e `narracao_o_que_mudaria` (todos texto não vazio; `resumo` = 2 a 3 linhas não vazias; com tetos de tamanho como proteção, em `app/config.py`), `origem` ("llm" | "fallback") e `provedor` (preenchido se "llm"; `null` se "fallback"). No fallback, os três textos vêm de modelo fixo montado só com os números calculados.

```json
{
  "gerado_em": "2026-11-14T09:00:00-03:00",
  "aviso": "Simulação educacional. Não é recomendação de investimento.",
  "cenario": {
    "classificacao": "ESTAGFLACAO",
    "criterios": {
      "crescimento_ibcbr_pct": -0.64,
      "ipca_12m_pct": 4.63,
      "limiar_crescimento_pct": 0.0,
      "limiar_ipca_pct": 4.5
    },
    "o_que_mudaria": {
      "ipca_precisa_cair_pp": 0.13,
      "ibcbr_proximo_mes_precisa_superar": 112.23
    }
  },
  "indicadores": {
    "selic_efetiva_aa": {"valor": null, "data": null, "fonte": "BCB SGS 1178"},
    "meta_selic_aa": {"valor": null, "data": null, "fonte": "BCB SGS 432"},
    "ipca_12m": {"valor": 4.63, "data": null, "fonte": "BCB SGS 13522"},
    "dolar_venda": {"valor": null, "data": null, "fonte": "BCB SGS 1"},
    "volatilidade_dolar_63d_anualizada_pct": {"valor": null, "data": null, "fonte": "calculado sobre BCB SGS 1"},
    "ibcbr": {
      "fonte": "BCB SGS 24364",
      "janela_recente":  {"media": 110.2705, "meses": ["jun", "jul", "ago"]},
      "janela_anterior": {"media": 110.9836, "meses": ["mar", "abr", "mai"]}
    }
  },
  "juro_real": {
    "ex_post_pct": 8.62,
    "projetado_12m_pct": 7.37,
    "entradas_projetado": {
      "selic_esperada_pct": 12.75,
      "reuniao": "R7/2027",
      "ipca_esperado_12m_pct": 5.0117,
      "data_focus": "2026-11-06"
    }
  },
  "carteira": {
    "base":     {"renda_fixa": 0.60, "fundos_cambiais": 0.25, "renda_variavel": 0.15},
    "sugerida": {"renda_fixa": 0.55, "fundos_cambiais": 0.20, "renda_variavel": 0.25},
    "limite_desvio_pp": 15,
    "renda_fixa_preferencia": "POSFIXADA"
  },
  "justificativa": {
    "texto": "...",
    "resumo": "Linha 1 do resumo.\nLinha 2 do resumo.",
    "narracao_o_que_mudaria": "...",
    "origem": "llm",
    "provedor": "gemini"
  },
  "avisos_de_qualidade": [
    "IBC-Br com defasagem de ~2,5 meses (último ponto: agosto/2026).",
    "Focus: mediana semanal; baseCalculo não documentado (usado 0)."
  ]
}
```
Campos com `null` no exemplo (Selic efetiva, meta Selic, dólar, volatilidade, datas) serão preenchidos pelo código na coleta; não os inventei. A `meta_selic_aa` entrou no contrato por decisão de 15/11/2026: a regra do indexador (§3.5) compara a Selic esperada com ela, e o contrato mostra contra o quê a comparação foi feita.

## 7. Stand-by (fora da v1; implementar depois, nesta ordem sugerida)
1. Curva de juros do Tesouro Direto (Tesouro Transparente CSV): inflação implícita vs IPCA esperado do Focus; taxa prefixada vs Selic média esperada; decide PREFIXADO / IPCA+ / PÓS. A regra 3.5 vira fallback.
2. Cartões de contexto, sem limiar e fora da regra do cenário: DBGG % PIB (SGS 13762); crédito total (SGS 20539, nominal: converter para variação em 12 meses vs IPCA); fluxo estrangeiro em carteira (SGS 22924 passivos líquido total, e opcionalmente 22927 só ações; US$ milhões, mensal; último ponto set/2026 em 14/11/2026, ~1 mês à frente do IBC-Br; sinal positivo = entrada líquida é inferência minha, não verificada; **correção:** a nota anterior de 'defasada até jun/2026' estava errada); desemprego PNAD (SGS 24369, trimestre móvel, nome oficial não confirmado). O código 22934 sugerido pelo Gemini é outra série (ações no exterior, ingresso): não usar.
3. `EVAL.md` (checagem de números citados pelo LLM).
4. Endpoint/aba `/history` (rodar a regra em anos passados).
5. `pipeline_metrics`: tempo de execução da coleta (ms), status HTTP de cada série consultada no BCB e quantidade de linhas processadas no pandas antes da agregação.

## 8. Decisões de arquitetura [decisão, 14/11/2026]
- Demo **hospedada** (link público). Hospedagem: **Render** (plano gratuito, Docker), em um **segundo workspace** ("My Workspace 2", criado em 14/11/2026) separado do IFO V1; plano do novo workspace a conferir no Billing; horas gratuitas são por workspace (render.com/docs/free); termos sobre múltiplos workspaces não lidos. Fatos oficiais (render.com/docs/free, 14/11/2026): dorme após 15 min sem tráfego; volta em ~1 min; 750 h/mês; disco efêmero; "não usar em produção". Mitigação: tela de carregamento no front + pré-aquecer o cache ao iniciar. Ping externo para não dormir: não verificado nos termos; evitar por ora.
- Camada de LLM: **LiteLLM** (prefixos `gemini/` e `nvidia_nim/`), versão travada no requirements. Cadeia: Gemini (principal) -> NVIDIA NIM (reserva) -> resultado determinístico sem LLM. OpenRouter fora da v1.
- Nomes de modelo em variáveis de ambiente (não fixos no código). Gemini estáveis em 14/11/2026: gemini-3.6-flash, gemini-3.5-flash-lite. Modelo da NVIDIA: escolher no catálogo "Free Endpoint" na hora de construir (muda com frequência).
- Cache da resposta por algumas horas, **em memória** (perdido quando o servidor dorme/reinicia; aceitável: reconstruir = 1 coleta + 1 chamada ao LLM).
- Validação em duas camadas: formato (Pydantic) e regras de negócio (soma = 1,0; desvio <= 15 p.p. por classe). Falhou -> próximo provedor -> fallback.
- Limitações: limites do plano gratuito do Gemini não verificados; NVIDIA free registra entradas/saídas e termos para demo pública não lidos (blogs e página comunitária, não oficial); Brasil como país suportado pela NVIDIA não confirmado.
- Papel do LLM na v1 [decisão, 14/11/2026]: **opção A** = justificativa + ajuste limitado (±15 p.p.), mais **resumo de 2 a 3 linhas** no topo e **narração do "o que mudaria"** (valores calculados pelo código), tudo em **uma chamada**. O ajuste da carteira é ilustração didática (README deve dizer isso). **Web search do LLM: fora**, sem stand-by (decisão do João); o LLM só vê números já calculados.
