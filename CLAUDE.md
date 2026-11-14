# CLAUDE.md — AI Macro Fund Allocator (MFA)

## O que é
API FastAPI (GET /api/v1/macro/analyze) que coleta dados do BCB (sem chave), calcula indicadores com pandas, classifica o cenário macro (EXPANSAO | CONTRACAO | ESTAGFLACAO) por REGRAS e usa um LLM só para escrever texto e propor um ajuste limitado da carteira.

## Princípio inegociável
O LLM interpreta e escreve; o código determinístico decide. O LLM nunca altera números calculados. Se o LLM falhar ou violar o contrato, o resultado sai com carteira base e texto de modelo fixo (fallback).

## Fonte da verdade
- SPEC.md: regras, limiares, contrato JSON (§6), decisões de arquitetura (§8). Leia antes de implementar. Se algo do pedido contradiz o SPEC.md, pare e pergunte.
- Não invente números, limiares, códigos de série ou nomes de modelo. Se faltar, pergunte ou deixe como configuração.

## Stack e decisões
- Python + FastAPI + pandas + Pydantic. LLM via LiteLLM (prefixos gemini/ e nvidia_nim/), cadeia Gemini -> NVIDIA -> fallback sem LLM.
- Nomes de modelo e chaves só em variáveis de ambiente (.env, nunca no git).
- Cache em memória. Deploy: Docker no Render (plano gratuito, 512 MB de RAM).
- Versões de dependências travadas no requirements.txt.

## Como trabalhar
- Passos pequenos, um por vez, na ordem do roadmap (SPEC.md §8 e conversa). Não adiantar passos futuros.
- Cada passo termina com testes passando. Testes de regra usam números fixos (sem internet). Testes que tocam o BCB ficam separados e marcados.
- Ao terminar, listar arquivos criados/alterados e como rodar.
- Comentários e mensagens ao usuário em português. Nomes de código em inglês ou português, de forma consistente.
- Não adicionar dependências fora do necessário; avisar antes de adicionar uma.
