"""Testes do contrato (app/schemas.py). Sem internet, com números fixos."""

import copy
import json

import pytest
from pydantic import ValidationError

from app.config import LIMITE_DESVIO_PP
from app.rules import Cenario, PreferenciaIndexador
from app.schemas import RespostaMacro

# Exemplo do SPEC §6. Os valores que o SPEC deixa null vêm de saídas já verificadas:
# - selic efetiva 13,65 (2026-11-13), ipca 4,63 (2026-10-01) e dólar 5,6518 (2026-11-13):
#   coletas verificadas em 13-15/11/2026 (R2);
# - meta Selic 13,75 (2026-11-14): SPEC §5;
# - volatilidade 23,18: R3, teste "internet" de 15/11/2026.
EXEMPLO = {
    "gerado_em": "2026-11-14T09:00:00-03:00",
    "aviso": "Simulação educacional. Não é recomendação de investimento.",
    "cenario": {
        "classificacao": "ESTAGFLACAO",
        "criterios": {
            "crescimento_ibcbr_pct": -0.64,
            "ipca_12m_pct": 4.63,
            "limiar_crescimento_pct": 0.0,
            "limiar_ipca_pct": 4.5,
        },
        "o_que_mudaria": {
            "ipca_precisa_cair_pp": 0.13,
            "ibcbr_proximo_mes_precisa_superar": 112.23,
        },
    },
    "indicadores": {
        "selic_efetiva_aa": {"valor": 13.65, "data": "2026-11-13", "fonte": "BCB SGS 1178"},
        "meta_selic_aa": {"valor": 13.75, "data": "2026-11-14", "fonte": "BCB SGS 432"},
        "ipca_12m": {"valor": 4.63, "data": "2026-10-01", "fonte": "BCB SGS 13522"},
        "dolar_venda": {"valor": 5.6518, "data": "2026-11-13", "fonte": "BCB SGS 1"},
        "volatilidade_dolar_63d_anualizada_pct": {
            "valor": 23.18,
            "data": "2026-11-13",
            "fonte": "calculado sobre BCB SGS 1",
        },
        "ibcbr": {
            "fonte": "BCB SGS 24364",
            "janela_recente": {"media": 110.2705, "meses": ["jun", "jul", "ago"]},
            "janela_anterior": {"media": 110.9836, "meses": ["mar", "abr", "mai"]},
        },
    },
    "juro_real": {
        "ex_post_pct": 8.62,
        "projetado_12m_pct": 7.37,
        "entradas_projetado": {
            "selic_esperada_pct": 12.75,
            "reuniao": "R7/2027",
            "ipca_esperado_12m_pct": 5.0117,
            "data_focus": "2026-11-06",
        },
    },
    "carteira": {
        "base": {"renda_fixa": 0.60, "fundos_cambiais": 0.25, "renda_variavel": 0.15},
        "sugerida": {"renda_fixa": 0.55, "fundos_cambiais": 0.20, "renda_variavel": 0.25},
        "limite_desvio_pp": 15,
        "renda_fixa_preferencia": "POSFIXADA",
    },
    "justificativa": {"texto": "...", "origem": "llm", "provedor": "gemini"},
    "avisos_de_qualidade": [
        "IBC-Br com defasagem de ~2,5 meses (último ponto: agosto/2026).",
        "Focus: mediana semanal; baseCalculo não documentado (usado 0).",
    ],
}


def exemplo() -> dict:
    return copy.deepcopy(EXEMPLO)


def carteira(base: tuple, sugerida: tuple) -> dict:
    c = exemplo()["carteira"]
    chaves = ("renda_fixa", "fundos_cambiais", "renda_variavel")
    c["base"] = dict(zip(chaves, base))
    c["sugerida"] = dict(zip(chaves, sugerida))
    return c


def com(**mudancas) -> dict:
    d = exemplo()
    d.update(mudancas)
    return d


# ---------------------------------------------------------------- a. exemplo válido


def test_exemplo_do_spec_valida_e_reproduz_campos():
    r = RespostaMacro.model_validate(EXEMPLO)
    assert r.cenario.classificacao is Cenario.ESTAGFLACAO
    assert r.cenario.criterios.crescimento_ibcbr_pct == -0.64
    assert r.cenario.o_que_mudaria.ibcbr_proximo_mes_precisa_superar == 112.23
    assert r.indicadores.selic_efetiva_aa.valor == 13.65
    assert r.indicadores.meta_selic_aa.valor == 13.75
    assert r.indicadores.meta_selic_aa.fonte == "BCB SGS 432"
    assert r.indicadores.dolar_venda.valor == 5.6518
    assert r.indicadores.volatilidade_dolar_63d_anualizada_pct.valor == 23.18
    assert r.indicadores.ibcbr.janela_recente.meses == ["jun", "jul", "ago"]
    assert r.indicadores.ibcbr.janela_anterior.media == 110.9836
    assert r.juro_real.ex_post_pct == 8.62
    assert r.juro_real.entradas_projetado.reuniao == "R7/2027"
    assert r.juro_real.entradas_projetado.ipca_esperado_12m_pct == 5.0117
    assert r.carteira.renda_fixa_preferencia is PreferenciaIndexador.POSFIXADA
    assert r.carteira.limite_desvio_pp == LIMITE_DESVIO_PP
    assert r.justificativa.provedor == "gemini"
    assert len(r.avisos_de_qualidade) == 2


def test_ida_e_volta_do_json_preserva_estrutura_e_nomes():
    r = RespostaMacro.model_validate(EXEMPLO)
    saida = json.loads(r.model_dump_json())
    # Mesmos nomes de campo e mesma estrutura do exemplo (datas em ISO).
    assert saida == EXEMPLO | {"gerado_em": saida["gerado_em"]}
    assert list(saida["indicadores"]) == list(EXEMPLO["indicadores"])
    chaves = list(saida["indicadores"])
    assert chaves[chaves.index("selic_efetiva_aa") + 1] == "meta_selic_aa"
    assert saida["indicadores"]["dolar_venda"]["data"] == "2026-11-13"
    # Recarregar o JSON gerado dá o mesmo objeto.
    assert RespostaMacro.model_validate(saida) == r


# ---------------------------------------------------------------- b. inválidos


@pytest.mark.parametrize("sugerida", [(0.55, 0.20, 0.20), (0.55, 0.25, 0.25)])
def test_soma_da_sugerida_diferente_de_1_e_rejeitada(sugerida):  # somas 0,95 e 1,05
    with pytest.raises(ValidationError, match="soma"):
        RespostaMacro.model_validate(
            com(carteira=carteira((0.60, 0.25, 0.15), sugerida))
        )


def test_peso_negativo_e_rejeitado():
    with pytest.raises(ValidationError):
        RespostaMacro.model_validate(
            com(carteira=carteira((0.60, 0.25, 0.15), (0.60, 0.50, -0.10)))
        )


def test_peso_acima_de_1_e_rejeitado():
    with pytest.raises(ValidationError):
        RespostaMacro.model_validate(
            com(carteira=carteira((0.60, 0.25, 0.15), (1.10, 0.0, -0.10)))
        )


def test_desvio_de_15_01_pp_e_rejeitado():
    # renda_fixa 0,60 -> 0,4499 (15,01 p.p.); fundos 0,25 -> 0,35 e rv 0,15 -> 0,2001.
    c = carteira((0.60, 0.25, 0.15), (0.4499, 0.35, 0.2001))
    with pytest.raises(ValidationError, match="desvia"):
        RespostaMacro.model_validate(com(carteira=c))


def test_cenario_fora_do_conjunto_e_rejeitado():
    d = exemplo()
    d["cenario"]["classificacao"] = "BOOM"
    with pytest.raises(ValidationError):
        RespostaMacro.model_validate(d)


def test_preferencia_fora_do_conjunto_e_rejeitada():
    d = exemplo()
    d["carteira"]["renda_fixa_preferencia"] = "IPCA_MAIS"
    with pytest.raises(ValidationError):
        RespostaMacro.model_validate(d)


def test_fallback_com_sugerida_diferente_da_base_e_rejeitado():
    d = exemplo()  # sugerida != base
    d["justificativa"] = {"texto": "modelo fixo", "origem": "fallback", "provedor": None}
    with pytest.raises(ValidationError, match="fallback"):
        RespostaMacro.model_validate(d)


def test_fallback_com_sugerida_igual_a_base_e_aceito():
    d = exemplo()
    d["carteira"]["sugerida"] = dict(d["carteira"]["base"])
    d["justificativa"] = {"texto": "modelo fixo", "origem": "fallback"}
    assert RespostaMacro.model_validate(d).justificativa.provedor is None


def test_fallback_com_provedor_e_rejeitado():
    d = exemplo()
    d["carteira"]["sugerida"] = dict(d["carteira"]["base"])
    d["justificativa"] = {"texto": "x", "origem": "fallback", "provedor": "gemini"}
    with pytest.raises(ValidationError, match="provedor"):
        RespostaMacro.model_validate(d)


def test_llm_sem_provedor_e_rejeitado():
    d = exemplo()
    d["justificativa"] = {"texto": "x", "origem": "llm"}
    with pytest.raises(ValidationError, match="provedor"):
        RespostaMacro.model_validate(d)


def test_gerado_em_sem_fuso_e_rejeitado():
    with pytest.raises(ValidationError):
        RespostaMacro.model_validate(com(gerado_em="2026-11-14T09:00:00"))


@pytest.mark.parametrize("campo", list(EXEMPLO))
def test_campo_obrigatorio_ausente_e_rejeitado(campo):
    d = exemplo()
    del d[campo]
    with pytest.raises(ValidationError):
        RespostaMacro.model_validate(d)


def test_meta_selic_ausente_e_rejeitada():
    d = exemplo()
    del d["indicadores"]["meta_selic_aa"]
    with pytest.raises(ValidationError):
        RespostaMacro.model_validate(d)


def test_valor_de_indicador_none_e_rejeitado():
    d = exemplo()
    d["indicadores"]["dolar_venda"]["valor"] = None
    with pytest.raises(ValidationError):
        RespostaMacro.model_validate(d)


def test_campo_desconhecido_e_rejeitado():
    with pytest.raises(ValidationError):
        RespostaMacro.model_validate(com(extra="x"))


# ---------------------------------------------------------------- c. fronteira (15 p.p.)
#
# Conta crua (rodada no terminal em 15/11/2026):
#   base 0.25 sugerida 0.4 diff 0.15000000000000002 diff<=0.15: False | round(diff,6)<=0.15: True
#   base 0.55 sugerida 0.4 diff 0.15000000000000002 diff<=0.15: False | round(diff,6)<=0.15: True
#   base 0.35 sugerida 0.5 diff 0.15000000000000002 diff<=0.15: False | round(diff,6)<=0.15: True
# Sem o round() esses ajustes válidos seriam rejeitados.


def test_conta_crua_de_ponto_flutuante_dos_pares_de_fronteira():
    for base, sugerida in [(0.25, 0.40), (0.55, 0.40), (0.35, 0.50)]:
        diferenca = abs(sugerida - base)
        assert not diferenca <= 0.15  # sem round() quebraria
        assert round(diferenca, 6) <= 0.15


@pytest.mark.parametrize(
    "base, sugerida",
    [
        # Estagflação: fundos 0,25 -> 0,40 (+15 p.p.); renda_fixa 0,60 -> 0,50 (-10) e
        # renda_variavel 0,15 -> 0,10 (-5). Soma: 0,50 + 0,40 + 0,10 = 1,0.
        ((0.60, 0.25, 0.15), (0.50, 0.40, 0.10)),
        # Contração: renda_fixa 0,55 -> 0,40 (-15 p.p.); fundos 0,20 -> 0,30 (+10) e
        # renda_variavel 0,25 -> 0,30 (+5). Soma: 0,40 + 0,30 + 0,30 = 1,0.
        ((0.55, 0.20, 0.25), (0.40, 0.30, 0.30)),
        # Expansão: renda_fixa 0,35 -> 0,50 (+15 p.p.); fundos 0,10 -> 0,05 (-5) e
        # renda_variavel 0,55 -> 0,45 (-10). Soma: 0,50 + 0,05 + 0,45 = 1,0.
        ((0.35, 0.10, 0.55), (0.50, 0.05, 0.45)),
    ],
)
def test_ajuste_exatamente_no_limite_de_15_pp_e_aceito(base, sugerida):
    r = RespostaMacro.model_validate(com(carteira=carteira(base, sugerida)))
    assert r.carteira.sugerida.soma() == pytest.approx(1.0)


# ---------------------------------------------------------------- d. opcionais


def test_o_que_mudaria_aceita_none():
    d = exemplo()
    d["cenario"]["o_que_mudaria"] = {
        "ipca_precisa_cair_pp": None,
        "ibcbr_proximo_mes_precisa_superar": None,
    }
    r = RespostaMacro.model_validate(d)
    assert r.cenario.o_que_mudaria.ipca_precisa_cair_pp is None


def test_juro_real_projetado_e_entradas_none_juntos_sao_aceitos():
    d = exemplo()
    d["juro_real"]["projetado_12m_pct"] = None
    d["juro_real"]["entradas_projetado"] = None
    r = RespostaMacro.model_validate(d)
    assert r.juro_real.projetado_12m_pct is None
    assert r.juro_real.entradas_projetado is None


def test_projetado_none_com_entradas_preenchidas_e_rejeitado():
    d = exemplo()
    d["juro_real"]["projetado_12m_pct"] = None
    with pytest.raises(ValidationError, match="ambos"):
        RespostaMacro.model_validate(d)


def test_entradas_none_com_projetado_preenchido_e_rejeitado():
    d = exemplo()
    d["juro_real"]["entradas_projetado"] = None
    with pytest.raises(ValidationError, match="ambos"):
        RespostaMacro.model_validate(d)


def test_ex_post_none_e_rejeitado():
    d = exemplo()
    d["juro_real"]["ex_post_pct"] = None
    with pytest.raises(ValidationError):
        RespostaMacro.model_validate(d)


# ---------------------------------------------------------------- e. arredondamento


def test_crescimento_menos_0_6425_sai_como_menos_0_64():
    d = exemplo()
    d["cenario"]["criterios"]["crescimento_ibcbr_pct"] = -0.6425
    assert RespostaMacro.model_validate(d).cenario.criterios.crescimento_ibcbr_pct == -0.64


def test_campos_calculados_sao_arredondados_e_coletados_passam_como_vieram():
    d = exemplo()
    d["juro_real"]["ex_post_pct"] = 8.6249
    d["juro_real"]["projetado_12m_pct"] = 7.3751
    d["juro_real"]["entradas_projetado"]["selic_esperada_pct"] = 12.7549
    d["juro_real"]["entradas_projetado"]["ipca_esperado_12m_pct"] = 5.01174
    d["indicadores"]["ibcbr"]["janela_recente"]["media"] = 110.27054
    d["indicadores"]["volatilidade_dolar_63d_anualizada_pct"]["valor"] = 23.18449
    d["indicadores"]["dolar_venda"]["valor"] = 5.65184  # coletado: não arredonda
    r = RespostaMacro.model_validate(d)
    assert r.juro_real.ex_post_pct == 8.62
    assert r.juro_real.projetado_12m_pct == 7.38
    assert r.juro_real.entradas_projetado.selic_esperada_pct == 12.75
    assert r.juro_real.entradas_projetado.ipca_esperado_12m_pct == 5.0117
    assert r.indicadores.ibcbr.janela_recente.media == 110.2705
    assert r.indicadores.volatilidade_dolar_63d_anualizada_pct.valor == 23.18
    assert r.indicadores.dolar_venda.valor == 5.65184


def test_zero_negativo_vira_zero_positivo_e_o_json_nao_tem_menos_zero():
    d = exemplo()
    d["cenario"]["criterios"]["crescimento_ibcbr_pct"] = -0.004  # round() daria -0.0
    d["cenario"]["o_que_mudaria"]["ipca_precisa_cair_pp"] = -0.001
    d["juro_real"]["ex_post_pct"] = -0.0001
    d["indicadores"]["ibcbr"]["janela_anterior"]["media"] = -0.00001
    r = RespostaMacro.model_validate(d)
    assert str(r.cenario.criterios.crescimento_ibcbr_pct) == "0.0"
    assert str(r.cenario.o_que_mudaria.ipca_precisa_cair_pp) == "0.0"
    assert str(r.juro_real.ex_post_pct) == "0.0"
    assert str(r.indicadores.ibcbr.janela_anterior.media) == "0.0"
    assert "-0.0" not in r.model_dump_json()
