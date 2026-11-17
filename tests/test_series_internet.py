"""Teste "internet" da R9.1: janelas ampliadas, `pontos` e `series` com dados REAIS do BCB.

Rodar (fora do pytest padrão):
    .\\.venv\\Scripts\\python.exe -m pytest -m internet -s tests/test_series_internet.py

Sem LLM (usa o fallback) e sem chave. Falha com mensagem clara se alguma janela voltar
com HTTP diferente de 200 (p.ex. o 304 visto em 16/11/2026 com 180 d no dólar) ou com
menos pontos do que o bloco `series` pede.
"""

from datetime import datetime, timezone

import pytest
from test_service import analise_falha

from app.collectors import bcb
from app.config import (
    SERIE_MAX_DOLAR,
    SERIE_MAX_IBCBR,
    SERIE_MAX_IPCA,
    SERIE_MAX_SELIC,
    get_settings,
)
from app.service import FUSO_BRASIL, gerar_resposta

pytestmark = pytest.mark.internet


def test_internet_janelas_ampliadas_rendem_o_tamanho_pedido():
    hoje = datetime.now(timezone.utc).astimezone(FUSO_BRASIL).date()
    s = get_settings()
    casos = [
        ("IBC-Br", bcb.buscar_ibcbr, s.JANELA_IBCBR_DIAS, SERIE_MAX_IBCBR),
        ("IPCA 12m", bcb.buscar_ipca_12m, s.JANELA_IPCA_DIAS, SERIE_MAX_IPCA),
        ("Selic efetiva", bcb.buscar_selic_efetiva, s.JANELA_SELIC_DIAS, SERIE_MAX_SELIC),
        ("Dólar", bcb.buscar_dolar_venda, s.JANELA_DOLAR_DIAS, SERIE_MAX_DOLAR),
    ]
    for nome, funcao, dias, minimo in casos:
        obs = funcao(hoje)  # BCBError (inclui "HTTP 304"/"HTTP 406") derruba com a série no texto
        print(f"[janela] {nome}: {dias} d -> {len(obs)} pontos (pedido: {minimo})")
        assert len(obs) >= minimo, f"{nome}: {len(obs)} pontos em {dias} d; o bloco series pede {minimo}"


def test_internet_pontos_e_series_reais():
    r = gerar_resposta(analisar=analise_falha)
    for janela in (r.indicadores.ibcbr.janela_recente, r.indicadores.ibcbr.janela_anterior):
        assert len(janela.pontos) == 3
        media = sum(p.valor for p in janela.pontos) / 3
        print(f"[pontos] média dos pontos {media!r} x media {janela.media!r}")
        assert abs(media - janela.media) <= 5e-5
    s = r.series
    print(
        f"[series] ibcbr={len(s.ibcbr_mensal)} ipca={len(s.ipca_12m_mensal)} "
        f"selic={len(s.selic_efetiva_diaria)} dolar={len(s.dolar_diario)}"
    )
    assert len(s.ibcbr_mensal) == SERIE_MAX_IBCBR
    assert len(s.ipca_12m_mensal) == SERIE_MAX_IPCA
    assert len(s.selic_efetiva_diaria) == SERIE_MAX_SELIC
    assert len(s.dolar_diario) == SERIE_MAX_DOLAR
