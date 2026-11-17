"""R9.1: GET /api/v1/macro/simulate. Sem internet, sem LLM, sem cache."""

import pytest
from fabrica_resposta import resposta
from fastapi.testclient import TestClient

from app.main import criar_app
from app.rules import Cenario, classificar_cenario
from app.schemas import RespostaSimulacao
from app.simulador import AVISO_SEM_ESPERADA, AVISO_SEM_META

ROTA = "/api/v1/macro/simulate"
BASE = {"ipca_12m_pct": 4.63, "crescimento_ibcbr_pct": -0.64, "selic_efetiva_aa_pct": 13.65}


class GeradorQueNaoDeveSerChamado:
    chamadas = 0

    def __call__(self):
        GeradorQueNaoDeveSerChamado.chamadas += 1
        raise AssertionError("o simulador não pode chamar o pipeline")


@pytest.fixture
def api():
    return TestClient(criar_app(gerador=GeradorQueNaoDeveSerChamado(), preaquecer=False))


def get(api, **params):
    return api.get(ROTA, params=params)


def test_estagflacao_com_opcionais_ignorados_e_aviso(api):
    r = get(api, **BASE, selic_esperada_pct=12.75, meta_selic_pct=13.75)
    assert r.status_code == 200
    corpo = r.json()
    RespostaSimulacao.model_validate(corpo)
    assert set(corpo) == {"entradas", "cenario", "carteira_base", "renda_fixa_preferencia",
                          "juro_real_ex_post_pct", "avisos"}  # fmt: skip
    assert corpo["cenario"] == {"classificacao": "ESTAGFLACAO"}
    assert corpo["carteira_base"] == {"renda_fixa": 0.6, "fundos_cambiais": 0.25, "renda_variavel": 0.15}
    assert corpo["renda_fixa_preferencia"] == "POSFIXADA"
    assert corpo["juro_real_ex_post_pct"] == 8.62  # SPEC §3.1
    assert len(corpo["avisos"]) == 1
    assert corpo["entradas"] == BASE | {"selic_esperada_pct": 12.75, "meta_selic_pct": 13.75}


def test_estagflacao_sem_opcionais_nao_tem_aviso(api):
    corpo = get(api, **BASE).json()
    assert corpo["avisos"] == []
    assert corpo["entradas"]["selic_esperada_pct"] is None
    assert corpo["entradas"]["meta_selic_pct"] is None


def test_contracao_prefixada_quando_esperada_ate_meta_menos_025(api):
    corpo = get(api, ipca_12m_pct=4.0, crescimento_ibcbr_pct=-1.0, selic_efetiva_aa_pct=13.65,
                selic_esperada_pct=13.5, meta_selic_pct=13.75).json()  # fmt: skip
    assert corpo["cenario"]["classificacao"] == "CONTRACAO"
    assert corpo["carteira_base"] == {"renda_fixa": 0.55, "fundos_cambiais": 0.2, "renda_variavel": 0.25}
    assert corpo["renda_fixa_preferencia"] == "PREFIXADA"  # diferença exata -0,25
    assert corpo["avisos"] == []


def test_expansao_posfixada_quando_esperada_nao_cai_025(api):
    corpo = get(api, ipca_12m_pct=3.0, crescimento_ibcbr_pct=1.2, selic_efetiva_aa_pct=10.0,
                selic_esperada_pct=13.6, meta_selic_pct=13.75).json()  # fmt: skip
    assert corpo["cenario"]["classificacao"] == "EXPANSAO"
    assert corpo["carteira_base"] == {"renda_fixa": 0.35, "fundos_cambiais": 0.1, "renda_variavel": 0.55}
    assert corpo["renda_fixa_preferencia"] == "POSFIXADA"


@pytest.mark.parametrize(
    "ipca,cresc,esperado",
    [
        (4.5, 0.0, "CONTRACAO"),  # fronteiras inclusivas: IPCA 4,5 e crescimento 0
        (4.5000001, 0.0, "ESTAGFLACAO"),
        (4.5, 0.0000001, "EXPANSAO"),
        (30.0, 20.0, "EXPANSAO"),
        (-5.0, -20.0, "CONTRACAO"),
    ],
)
def test_fronteiras(api, ipca, cresc, esperado):
    corpo = get(api, ipca_12m_pct=ipca, crescimento_ibcbr_pct=cresc, selic_efetiva_aa_pct=10).json()
    assert corpo["cenario"]["classificacao"] == esperado


def test_opcionais_ausentes_fora_de_estagflacao(api):
    sem_nada = get(api, ipca_12m_pct=3.0, crescimento_ibcbr_pct=1.0, selic_efetiva_aa_pct=10).json()
    assert sem_nada["renda_fixa_preferencia"] == "POSFIXADA"
    assert sem_nada["avisos"] == [AVISO_SEM_META]
    so_esperada = get(api, ipca_12m_pct=3.0, crescimento_ibcbr_pct=1.0, selic_efetiva_aa_pct=10,
                      selic_esperada_pct=9.0).json()  # fmt: skip
    assert so_esperada["renda_fixa_preferencia"] == "POSFIXADA"
    assert so_esperada["avisos"] == [AVISO_SEM_META]
    so_meta = get(api, ipca_12m_pct=3.0, crescimento_ibcbr_pct=1.0, selic_efetiva_aa_pct=10,
                  meta_selic_pct=13.75).json()  # fmt: skip
    assert so_meta["renda_fixa_preferencia"] == "POSFIXADA"
    assert so_meta["avisos"] == [AVISO_SEM_ESPERADA]  # texto próprio, não o da regra


def test_redacao_dos_avisos_do_simulador_esta_fixada():
    assert AVISO_SEM_META == (
        "Você não informou a meta da Selic, então não dá para comparar com a Selic esperada; "
        "a preferência de indexador ficou POSFIXADA."
    )
    assert AVISO_SEM_ESPERADA == (
        "Você não informou a Selic esperada, então não dá para saber se os juros devem cair; "
        "a preferência de indexador ficou POSFIXADA."
    )
    assert "Focus" not in AVISO_SEM_META + AVISO_SEM_ESPERADA


def test_nao_chama_o_pipeline_nem_o_cache(api):
    get(api, **BASE)
    assert GeradorQueNaoDeveSerChamado.chamadas == 0
    assert api.app.state.servico._cache.obter() is None


# ------------------------------------------------------------------------- 422


@pytest.mark.parametrize("faltando", list(BASE))
def test_parametro_obrigatorio_ausente_da_422_em_portugues(api, faltando):
    params = {k: v for k, v in BASE.items() if k != faltando}
    r = get(api, **params)
    assert r.status_code == 422
    erro = r.json()["detail"][0]
    assert erro["loc"] == ["query", faltando]
    assert erro["msg"] == "Parâmetro obrigatório ausente."
    assert erro["type"] == "missing"


@pytest.mark.parametrize(
    "campo,valor,msg",
    [
        ("ipca_12m_pct", 30.01, "Deve estar entre -5 e 30."),
        ("ipca_12m_pct", -5.01, "Deve estar entre -5 e 30."),
        ("crescimento_ibcbr_pct", 20.5, "Deve estar entre -20 e 20."),
        ("selic_efetiva_aa_pct", -0.1, "Deve estar entre 0 e 50."),
        ("selic_esperada_pct", 51, "Deve estar entre 0 e 50."),
        ("meta_selic_pct", -1, "Deve estar entre 0 e 50."),
        ("ipca_12m_pct", "abc", "Deve ser um número."),
        ("ipca_12m_pct", "", "Deve ser um número."),
        ("selic_esperada_pct", "x", "Deve ser um número."),
        ("ipca_12m_pct", "nan", "Deve ser um número finito (NaN e infinito não são aceitos)."),
        ("crescimento_ibcbr_pct", "inf", "Deve ser um número finito (NaN e infinito não são aceitos)."),
        ("meta_selic_pct", "-inf", "Deve ser um número finito (NaN e infinito não são aceitos)."),
    ],
)
def test_valores_invalidos_da_422_em_portugues(api, campo, valor, msg):
    r = get(api, **(BASE | {campo: valor}))
    assert r.status_code == 422
    erros = r.json()["detail"]
    assert [e["msg"] for e in erros] == [msg]
    assert erros[0]["loc"] == ["query", campo]


def test_422_so_vale_para_o_simulador_health_e_analyze_nao_mudam():
    from app.service import ServicoIndisponivelError  # noqa: F401

    app = criar_app(gerador=lambda: resposta("llm"), preaquecer=False)
    c = TestClient(app)
    assert c.get("/health").json() == {"status": "ok"}
    assert c.get("/api/v1/macro/analyze").status_code == 200
    # Rota que não é o simulador: erro de validação mantém o formato padrão do FastAPI.
    @app.get("/_teste_validacao")
    def _rota(x: int):
        return x

    erro = c.get("/_teste_validacao", params={"x": "a"}).json()["detail"][0]
    assert erro["msg"] != "Deve ser um número."  # mensagem padrão em inglês
    assert erro["type"] == "int_parsing" and "input" in erro


# ----------------------------------------------------------------- consistência


def test_simulador_classifica_igual_ao_analyze_com_os_valores_devolvidos():
    for origem in ("llm", "fallback"):
        app = criar_app(gerador=lambda o=origem: resposta(o), preaquecer=False)
        c = TestClient(app)
        a = c.get("/api/v1/macro/analyze").json()
        crit = a["cenario"]["criterios"]
        s = c.get(ROTA, params={
            "ipca_12m_pct": crit["ipca_12m_pct"],
            "crescimento_ibcbr_pct": crit["crescimento_ibcbr_pct"],
            "selic_efetiva_aa_pct": a["indicadores"]["selic_efetiva_aa"]["valor"],
        }).json()  # fmt: skip
        assert s["cenario"]["classificacao"] == a["cenario"]["classificacao"]
        assert s["carteira_base"] == a["carteira"]["base"]
        assert s["juro_real_ex_post_pct"] == a["juro_real"]["ex_post_pct"]


def test_borda_documentada_crescimento_bruto_004_aparece_como_0_e_muda_a_classe(api):
    """Limitação conhecida (rules.py): /analyze arredonda o crescimento a 2 casas só para
    exibir. Bruto 0,004 -> EXPANSAO, mas exibido 0,0 -> o simulador classifica CONTRACAO."""
    assert classificar_cenario(0.004, 4.0) is Cenario.EXPANSAO
    exibido = round(0.004, 2) + 0.0
    assert exibido == 0.0
    assert classificar_cenario(exibido, 4.0) is Cenario.CONTRACAO
    corpo = get(api, ipca_12m_pct=4.0, crescimento_ibcbr_pct=exibido, selic_efetiva_aa_pct=10).json()
    assert corpo["cenario"]["classificacao"] == "CONTRACAO"
