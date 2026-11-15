"""Testes das regras (SPEC.md §3.2, §3.4, §3.5). Sem internet: a R4 não toca a rede.

Os resultados esperados vêm do SPEC, escritos aqui à mão (não calculados pelo código).
"""

import math

import pytest

from app.rules import (
    Cenario,
    PreferenciaIndexador,
    RegraError,
    carteira_base,
    classificar_cenario,
    preferencia_indexador,
)

POS = PreferenciaIndexador.POSFIXADA
PRE = PreferenciaIndexador.PREFIXADA


# a. Matriz 3x3 do cenário (§3.2): crescimento x IPCA (teto 4,5).
@pytest.mark.parametrize(
    ("crescimento", "ipca", "esperado"),
    [
        (-0.6425, 4.49, Cenario.CONTRACAO),
        (-0.6425, 4.5, Cenario.CONTRACAO),
        (-0.6425, 4.51, Cenario.ESTAGFLACAO),
        (0.0, 4.49, Cenario.CONTRACAO),
        (0.0, 4.5, Cenario.CONTRACAO),
        (0.0, 4.51, Cenario.ESTAGFLACAO),
        (0.01, 4.49, Cenario.EXPANSAO),
        (0.01, 4.5, Cenario.EXPANSAO),
        (0.01, 4.51, Cenario.EXPANSAO),
    ],
)
def test_matriz_cenario(crescimento, ipca, esperado):
    assert classificar_cenario(crescimento, ipca) is esperado


def test_crescimento_nao_e_arredondado():
    # 0,004 aparece como 0,00 no contrato, mas classifica como EXPANSAO (decisão 2).
    assert classificar_cenario(0.004, 9.0) is Cenario.EXPANSAO


# b. Carteira base (§3.4).
@pytest.mark.parametrize(
    ("cenario", "esperado"),
    [
        (Cenario.EXPANSAO, (0.35, 0.10, 0.55)),
        (Cenario.CONTRACAO, (0.55, 0.20, 0.25)),
        (Cenario.ESTAGFLACAO, (0.60, 0.25, 0.15)),
    ],
)
def test_carteira_base(cenario, esperado):
    carteira = carteira_base(cenario)
    assert set(carteira) == {"renda_fixa", "fundos_cambiais", "renda_variavel"}
    assert carteira["renda_fixa"] == pytest.approx(esperado[0])
    assert carteira["fundos_cambiais"] == pytest.approx(esperado[1])
    assert carteira["renda_variavel"] == pytest.approx(esperado[2])
    assert sum(carteira.values()) == pytest.approx(1.0)


def test_carteira_base_devolve_copia():
    carteira = carteira_base(Cenario.EXPANSAO)
    carteira["renda_fixa"] = 0.99
    assert carteira_base(Cenario.EXPANSAO)["renda_fixa"] == pytest.approx(0.35)


# c. Preferência de indexador (§3.5).
@pytest.mark.parametrize("esperada", [5.0, 12.75, 13.75, 20.0, None])
def test_estagflacao_sempre_posfixada_sem_aviso(esperada):
    assert preferencia_indexador(Cenario.ESTAGFLACAO, esperada, 13.75) == (POS, [])


@pytest.mark.parametrize("cenario", [Cenario.EXPANSAO, Cenario.CONTRACAO])
@pytest.mark.parametrize(
    ("esperada", "esperado"),
    [
        (13.50, PRE),  # diferença exata de -0,25
        (13.51, POS),
        (12.75, PRE),
        (13.75, POS),
    ],
)
def test_fronteira_indexador(cenario, esperada, esperado):
    assert preferencia_indexador(cenario, esperada, 13.75) == (esperado, [])


@pytest.mark.parametrize("cenario", [Cenario.EXPANSAO, Cenario.CONTRACAO])
def test_selic_esperada_ausente_vira_posfixada_com_aviso(cenario):
    preferencia, avisos = preferencia_indexador(cenario, None, 13.75)
    assert preferencia is POS
    assert len(avisos) == 1
    assert "Selic esperada" in avisos[0]


@pytest.mark.parametrize("cenario", [Cenario.EXPANSAO, Cenario.CONTRACAO])
@pytest.mark.parametrize(("meta", "esperada"), [(16.06, 15.81), (16.08, 15.83)])
def test_ponto_flutuante_diferenca_de_um_passo(cenario, meta, esperada):
    # Em float, esperada - meta = -0.24999999999999822: a conta crua daria False.
    assert esperada - meta > -0.25
    assert preferencia_indexador(cenario, esperada, meta) == (PRE, [])


# d. Caso de hoje (13-15/11/2026), ponta a ponta.
def test_caso_de_hoje():
    cenario = classificar_cenario(-0.6425, 4.63)
    assert cenario is Cenario.ESTAGFLACAO
    carteira = carteira_base(cenario)
    assert carteira["renda_fixa"] == pytest.approx(0.60)
    assert carteira["fundos_cambiais"] == pytest.approx(0.25)
    assert carteira["renda_variavel"] == pytest.approx(0.15)
    assert preferencia_indexador(cenario, 12.75, 13.75) == (POS, [])


def test_mesmo_par_de_selic_em_expansao_e_prefixada():
    assert preferencia_indexador(Cenario.EXPANSAO, 12.75, 13.75) == (PRE, [])


# e. Entradas inválidas: erro claro, sem chutar cenário.
@pytest.mark.parametrize("invalido", [None, math.nan, math.inf, -math.inf, True, "4,5"])
def test_cenario_rejeita_entrada_invalida(invalido):
    with pytest.raises(RegraError):
        classificar_cenario(invalido, 4.63)
    with pytest.raises(RegraError):
        classificar_cenario(-0.6, invalido)


@pytest.mark.parametrize("meta", [None, math.nan, math.inf])
def test_meta_selic_invalida(meta):
    with pytest.raises(RegraError):
        preferencia_indexador(Cenario.EXPANSAO, 12.75, meta)


@pytest.mark.parametrize("esperada", [math.nan, math.inf])
def test_selic_esperada_nan_ou_infinita(esperada):
    with pytest.raises(RegraError):
        preferencia_indexador(Cenario.EXPANSAO, esperada, 13.75)


def test_cenario_de_tipo_errado():
    with pytest.raises(RegraError):
        carteira_base("EXPANSAO")
    with pytest.raises(RegraError):
        preferencia_indexador("EXPANSAO", 12.75, 13.75)
