"""Testes dos indicadores (R3). Os testes padrão não tocam a internet.

O teste marcado "internet" só roda com: pytest -m internet -s
"""

from datetime import date

import pytest

from app import indicators
from app.collectors.bcb import Observacao
from app.indicators import IndicadorError


def meses(valores, ano=2026, mes_inicial=1):
    """Série mensal sintética: uma observação por mês, no dia 1."""
    obs = []
    for i, valor in enumerate(valores):
        indice = mes_inicial - 1 + i
        obs.append(Observacao(date(ano + indice // 12, indice % 12 + 1, 1), float(valor)))
    return obs


def dias_uteis_sinteticos(valores):
    """Série diária sintética (datas consecutivas; só a ordem importa)."""
    return [Observacao(date.fromordinal(739000 + i), float(v)) for i, v in enumerate(valores)]


# --- Fisher ----------------------------------------------------------------


def test_juro_real_ex_post_reproduz_referencia_do_spec():
    # (1 + 0,1365) / (1 + 0,0463) - 1 = 1,1365 / 1,0463 - 1 = 0,08621 -> 8,62 %
    assert indicators.juro_real_ex_post(13.65, 4.63) == pytest.approx(8.62, abs=0.005)


def test_juro_real_projetado_reproduz_referencia_do_spec():
    # 1,1275 / 1,050117 - 1 = 0,07369 -> 7,37 %
    assert indicators.juro_real_projetado(12.75, 5.0117) == pytest.approx(7.37, abs=0.005)


@pytest.mark.parametrize("selic,ipca", [(None, 5.0117), (12.75, None), (None, None)])
def test_juro_real_projetado_none_propaga(selic, ipca):
    assert indicators.juro_real_projetado(selic, ipca) is None


def test_juro_real_com_ipca_impossivel_da_erro_claro():
    with pytest.raises(IndicadorError, match="inválido"):
        indicators.juro_real_ex_post(13.65, -100.0)


# --- IBC-Br ----------------------------------------------------------------


def test_ibcbr_com_exatamente_6_pontos():
    # anterior = (100+101+102)/3 = 101; recente = (103+104+105)/3 = 104
    # variação = (104/101 - 1) * 100 = 2,9703 %
    r = indicators.crescimento_ibcbr(meses([100, 101, 102, 103, 104, 105]))
    assert r.media_anterior == pytest.approx(101.0)
    assert r.media_recente == pytest.approx(104.0)
    assert r.variacao_pct == pytest.approx(2.9703, abs=0.0001)
    assert r.meses_anterior == (date(2026, 1, 1), date(2026, 2, 1), date(2026, 3, 1))
    assert r.meses_recente == (date(2026, 4, 1), date(2026, 5, 1), date(2026, 6, 1))


def test_ibcbr_com_10_pontos_so_as_6_ultimas_contam():
    # Os 4 primeiros são absurdos de propósito: se contassem, o resultado mudaria.
    r = indicators.crescimento_ibcbr(meses([9999, 9999, 9999, 9999, 100, 101, 102, 103, 104, 105]))
    assert r.media_anterior == pytest.approx(101.0)
    assert r.media_recente == pytest.approx(104.0)
    assert r.meses_anterior[0] == date(2026, 5, 1)
    assert r.meses_recente[-1] == date(2026, 10, 1)


def test_ibcbr_entrada_desordenada_e_ordenada_por_data():
    obs = meses([100, 101, 102, 103, 104, 105])
    r = indicators.crescimento_ibcbr(list(reversed(obs)))
    assert r.media_recente == pytest.approx(104.0)


def test_ibcbr_referencia_do_spec():
    # Médias do SPEC (13/11/2026): 110,9836 (mar-mai) e 110,2705 (jun-ago).
    # (110,2705 / 110,9836 - 1) * 100 = -0,6425 -> -0,64 %
    r = indicators.crescimento_ibcbr(meses([110.9836] * 3 + [110.2705] * 3))
    assert r.variacao_pct == pytest.approx(-0.64, abs=0.005)


def test_ibcbr_com_5_pontos_falha_com_erro_claro():
    with pytest.raises(IndicadorError, match=r"IBC-Br: precisa de pelo menos 6 observações, recebi 5"):
        indicators.crescimento_ibcbr(meses([100, 101, 102, 103, 104]))


# --- Volatilidade do dólar -------------------------------------------------


def precos_com_retornos_de_1_pct(quantidade_precos):
    """Preços cujos retornos simples são exatamente +1 % e -1 % (altas e baixas alternadas,
    começando por alta). Com 64 preços: 63 retornos = 32 altas e 31 baixas."""
    precos = [100.0]
    for i in range(quantidade_precos - 1):
        precos.append(precos[-1] * (1.01 if i % 2 == 0 else 0.99))
    return precos


def test_volatilidade_com_exatamente_64_precos_bate_com_conta_a_mao():
    # 63 retornos r = ±0,01 (32 de +, 31 de -). Sem pandas:
    #   soma(r)   = 0,01            -> média m = 0,01/63
    #   soma(r²)  = 63 * 1e-4
    #   variância amostral (n-1=62) = (63e-4 - 63*m²)/62 = (63e-4 - 1e-4/63)/62 = 1e-4 * 64/63
    #   desvio = 0,01 * 8/raiz(63);  anualizado x raiz(252) = x 2*raiz(63)
    #   => 0,01 * 8 * 2 = 0,16  -> 16,00 %
    vol = indicators.volatilidade_dolar_anualizada(
        dias_uteis_sinteticos(precos_com_retornos_de_1_pct(64))
    )
    assert vol == pytest.approx(16.0, abs=1e-6)


def test_volatilidade_com_mais_de_64_precos_so_os_64_ultimos_contam():
    # 6 preços absurdos na frente; a janela de 64 finais começa com alta (índice par),
    # então o resultado é o mesmo de 64 preços. Reconstruímos a cauda para ter certeza.
    cauda = precos_com_retornos_de_1_pct(64)
    vol = indicators.volatilidade_dolar_anualizada(
        dias_uteis_sinteticos([1.0, 500.0, 3.0, 900.0, 7.0, 1000.0] + cauda)
    )
    assert vol == pytest.approx(16.0, abs=1e-6)


def test_volatilidade_com_63_precos_falha_com_erro_claro():
    with pytest.raises(IndicadorError, match=r"precisa de pelo menos 64 observações, recebi 63"):
        indicators.volatilidade_dolar_anualizada(
            dias_uteis_sinteticos(precos_com_retornos_de_1_pct(63))
        )


def test_volatilidade_com_preco_nao_positivo_falha():
    precos = precos_com_retornos_de_1_pct(64)
    precos[10] = 0.0
    with pytest.raises(IndicadorError, match="não positivo"):
        indicators.volatilidade_dolar_anualizada(dias_uteis_sinteticos(precos))


# --- o que mudaria ---------------------------------------------------------


def test_ipca_precisa_cair_referencia_do_spec():
    # 4,63 - 4,5 = 0,13
    r = indicators.o_que_mudaria(4.63, meses([100, 101, 102, 103, 104, 103]))
    assert r.ipca_precisa_cair_pp == pytest.approx(0.13, abs=1e-9)


@pytest.mark.parametrize("ipca", [4.5, 4.2])
def test_ipca_ja_no_limiar_ou_abaixo_vira_none(ipca):
    r = indicators.o_que_mudaria(ipca, meses([100, 101, 102, 103, 104, 103]))
    assert r.ipca_precisa_cair_pp is None


def test_ibcbr_proximo_mes_precisa_superar_conta_a_mao():
    # Série m1..m6 = 100, 105, 104, 103, 102, 101 (crescimento negativo).
    # x = (m2 + m3 + m4) - (m5 + m6) = (105 + 104 + 103) - (102 + 101) = 312 - 203 = 109
    r = indicators.o_que_mudaria(4.63, meses([100, 105, 104, 103, 102, 101]))
    assert r.ibcbr_proximo_mes_precisa_superar == pytest.approx(109.0)


def test_ibcbr_crescimento_positivo_vira_none():
    r = indicators.o_que_mudaria(4.63, meses([100, 101, 102, 103, 104, 105]))
    assert r.ibcbr_proximo_mes_precisa_superar is None


def test_ida_e_volta_proximo_mes_igual_ao_valor_pedido_zera_o_crescimento():
    # Série em queda: m1..m6 = 100, 105, 104, 103, 102, 101 -> x = 109 (conta acima).
    # Com o próximo mês = 109 as janelas viram:
    #   anterior (105, 104, 103) = 104 ;  recente (102, 101, 109) = 312/3 = 104 -> variação 0
    base = [100, 105, 104, 103, 102, 101]
    x = indicators.o_que_mudaria(4.63, meses(base)).ibcbr_proximo_mes_precisa_superar
    assert x is not None
    recalculado = indicators.crescimento_ibcbr(meses(base + [x]))
    assert recalculado.variacao_pct == pytest.approx(0.0, abs=1e-9)


# --- internet (fora do pytest padrão) --------------------------------------


@pytest.mark.internet
def test_internet_indicadores_com_series_reais():
    """Roda com: pytest -m internet -s. Só imprime; não confere os valores do SPEC.

    Os valores do SPEC são de 13/11/2026; se divergirem, pode ser mês novo do IBC-Br.
    """
    from app.collectors import bcb

    hoje = date.today()
    ibcbr = bcb.buscar_ibcbr(hoje)
    dolar = bcb.buscar_dolar_venda(hoje)
    selic = bcb.buscar_selic_efetiva(hoje)
    ipca = bcb.buscar_ipca_12m(hoje)

    cres = indicators.crescimento_ibcbr(ibcbr)
    vol = indicators.volatilidade_dolar_anualizada(dolar)
    juro = indicators.juro_real_ex_post(selic[-1].valor, ipca[-1].valor)
    mudaria = indicators.o_que_mudaria(ipca[-1].valor, ibcbr)

    print()
    print(f"Hoje: {hoje.isoformat()} | pontos: IBC-Br {len(ibcbr)}, dólar {len(dolar)}")
    print(f"IBC-Br meses anteriores: {[d.isoformat() for d in cres.meses_anterior]}")
    print(f"IBC-Br meses recentes:   {[d.isoformat() for d in cres.meses_recente]}")
    print(f"Média anterior: {cres.media_anterior:.4f} | média recente: {cres.media_recente:.4f}")
    print(f"Variação do IBC-Br: {cres.variacao_pct:.4f} %")
    print(f"Volatilidade do dólar (63d, anualizada): {vol:.4f} %")
    print(
        f"Selic efetiva {selic[-1].valor} ({selic[-1].data}) | "
        f"IPCA 12m {ipca[-1].valor} ({ipca[-1].data}) -> juro real ex-post: {juro:.4f} %"
    )
    print(f"O que mudaria: {mudaria}")
