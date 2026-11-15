"""Testes da cadeia de LLM (app/llm.py). Sem internet e sem chave: provedores FALSOS.

As chaves usadas aqui são sentinelas inventadas; nada é lido do .env real
(Settings(_env_file=None)) e nenhuma chave é impressa.
"""

import functools
import json

import httpx2
import pytest

from app.config import (
    NARRACAO_MAX_CARACTERES,
    RESUMO_LINHA_MAX_CARACTERES,
    TEXTO_MAX_CARACTERES,
    Settings,
)
from app.llm import (
    EntradaLLM,
    ErroProvedor,
    _chamar_gemini,
    extrair_json,
    gerar_analise,
    modelo_gemini_valido,
    montar_fallback,
    montar_mensagens,
)
from app.rules import PreferenciaIndexador
from app.schemas import (
    BlocoCenario,
    Indicadores,
    JuroReal,
    Justificativa,
    Pesos,
)

CHAVE_GEMINI = "SENTINELA-GEMINI-123"
CHAVE_NVIDIA = "SENTINELA-NVIDIA-456"

CENARIO = {
    "classificacao": "ESTAGFLACAO",
    "criterios": {
        "crescimento_ibcbr_pct": -0.64,
        "ipca_12m_pct": 4.63,
        "limiar_crescimento_pct": 0.0,
        "limiar_ipca_pct": 4.5,
    },
    "o_que_mudaria": {"ipca_precisa_cair_pp": 0.13, "ibcbr_proximo_mes_precisa_superar": 112.23},
}
INDICADORES = {
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
}
JURO_REAL = {
    "ex_post_pct": 8.62,
    "projetado_12m_pct": 7.37,
    "entradas_projetado": {
        "selic_esperada_pct": 12.75,
        "reuniao": "R7/2027",
        "ipca_esperado_12m_pct": 5.0117,
        "data_focus": "2026-11-06",
    },
}


def entrada(base=(0.60, 0.25, 0.15), limite=15.0, cenario=None, juro=None) -> EntradaLLM:
    return EntradaLLM(
        cenario=BlocoCenario.model_validate(cenario or CENARIO),
        indicadores=Indicadores.model_validate(INDICADORES),
        juro_real=JuroReal.model_validate(juro or JURO_REAL),
        carteira_base=Pesos(renda_fixa=base[0], fundos_cambiais=base[1], renda_variavel=base[2]),
        limite_desvio_pp=limite,
        renda_fixa_preferencia=PreferenciaIndexador.POSFIXADA,
        avisos_de_qualidade=["IBC-Br com defasagem de ~2,5 meses."],
    )


def settings(**kw) -> Settings:
    padrao = dict(
        GEMINI_API_KEY=CHAVE_GEMINI,
        NVIDIA_NIM_API_KEY=CHAVE_NVIDIA,
        LLM_PRIMARY="modelo-gemini-teste",
        LLM_SECONDARY="dono/modelo-nvidia-teste",
    )
    padrao.update(kw)
    return Settings(_env_file=None, **padrao)


def resposta(sugerida=(0.55, 0.20, 0.25), **mudancas) -> str:
    corpo = {
        "texto": "Justificativa do cenário e do ajuste.",
        "resumo": "Cenário de estagflação.\nCarteira ajustada dentro do limite.",
        "narracao_o_que_mudaria": "O IPCA precisaria cair 0,13 p.p.",
        "carteira_sugerida": {
            "renda_fixa": sugerida[0],
            "fundos_cambiais": sugerida[1],
            "renda_variavel": sugerida[2],
        },
    }
    corpo.update(mudancas)
    return json.dumps(corpo)


class Falso:
    """Chamador falso: devolve texto, levanta exceção ou executa uma função; registra as chamadas."""

    def __init__(self, comportamento):
        self.comportamento = comportamento
        self.chamadas: list[dict] = []

    def __call__(self, modelo, sistema, usuario, chave, timeout, max_tokens, json_mode):
        self.chamadas.append(
            dict(modelo=modelo, chave=chave, timeout=timeout, max_tokens=max_tokens, json_mode=json_mode)
        )
        c = self.comportamento
        if isinstance(c, Exception):
            raise c
        if callable(c):
            return c()
        return c


def rodar(gemini=None, nvidia=None, cfg=None, ent=None, **kw):
    gem, nv = Falso(gemini), Falso(nvidia)
    r = gerar_analise(
        ent or entrada(),
        settings=cfg or settings(),
        chamadores={"gemini": gem, "nvidia_nim": nv},
        **kw,
    )
    return r, gem, nv


# ---------------------------------------------------------------- sucesso e parser


def test_sucesso_no_gemini_nao_chama_a_nvidia():
    r, gem, nv = rodar(gemini=resposta(), nvidia=resposta())
    assert r.justificativa.origem == "llm"
    assert r.justificativa.provedor == "gemini"
    assert (r.carteira_sugerida.renda_fixa, r.carteira_sugerida.renda_variavel) == (0.55, 0.25)
    assert r.avisos == []
    assert len(gem.chamadas) == 1 and nv.chamadas == []
    assert gem.chamadas[0]["modelo"] == "modelo-gemini-teste"
    assert [t.ok for t in r.tentativas] == [True]


def test_json_dentro_de_bloco_markdown_e_aceito():
    texto = "```json\n" + resposta() + "\n```"
    r, _, _ = rodar(gemini=texto)
    assert r.justificativa.provedor == "gemini"


def test_bloco_markdown_sem_rotulo_e_aceito():
    r, _, _ = rodar(gemini="```\n" + resposta() + "\n```")
    assert r.justificativa.provedor == "gemini"


@pytest.mark.parametrize(
    "texto",
    [
        "Aqui está: " + "{}",
        "```json\n{}\n```\nObrigado!",
        "Segue:\n```json\n{}\n```",
        "```json\n{}\n```\n```json\n{}\n```",
        "[1, 2, 3]",
        "```python\n{}\n```",
        "```json {} ```",
        "",
    ],
)
def test_extrair_json_rejeita_tudo_que_nao_e_json_puro_ou_um_bloco(texto):
    with pytest.raises(ErroProvedor, match="JSON inválido"):
        extrair_json(texto)


def test_prosa_ao_redor_do_json_vai_para_o_proximo():
    r, _, nv = rodar(gemini="Claro! " + resposta(), nvidia=resposta())
    assert r.justificativa.provedor == "nvidia_nim"
    assert len(nv.chamadas) == 1


# ---------------------------------------------------------------- troca de provedor


def test_json_invalido_no_gemini_usa_a_nvidia():
    r, _, _ = rodar(gemini="{isso nao e json", nvidia=resposta())
    assert r.justificativa.origem == "llm"
    assert r.justificativa.provedor == "nvidia_nim"
    assert r.avisos == ["Gemini indisponível (JSON inválido); usado NVIDIA NIM."]
    assert [t.provedor for t in r.tentativas] == ["gemini", "nvidia_nim"]
    assert [t.ok for t in r.tentativas] == [False, True]


@pytest.mark.parametrize(
    "erro, trecho",
    [
        (ErroProvedor("tempo esgotado"), "tempo esgotado"),
        (ErroProvedor("serviço indisponível (HTTP 503)"), "HTTP 503"),
        (ErroProvedor("limite de uso (HTTP 429)"), "HTTP 429"),
        (ErroProvedor("resposta truncada"), "truncada"),
        (RuntimeError("explodiu"), "RuntimeError"),
    ],
)
def test_erro_de_api_ou_timeout_no_gemini_usa_a_nvidia(erro, trecho):
    r, _, _ = rodar(gemini=erro, nvidia=resposta())
    assert r.justificativa.provedor == "nvidia_nim"
    assert trecho in r.avisos[0] and r.avisos[0].endswith("usado NVIDIA NIM.")


# ---------------------------------------------------------------- regras de negócio


def test_pesos_em_porcentagem_sao_rejeitados():
    r, _, _ = rodar(gemini=resposta((55, 20, 25)), nvidia=resposta((55, 20, 25)))
    assert r.justificativa.origem == "fallback"
    assert "fora do contrato" in r.avisos[0]


@pytest.mark.parametrize("sugerida", [(0.55, 0.20, 0.20), (0.55, 0.25, 0.25)])  # somas 0,95 e 1,05
def test_somas_diferentes_de_1_sao_rejeitadas(sugerida):
    r, _, _ = rodar(gemini=resposta(sugerida), nvidia=resposta(sugerida))
    assert r.justificativa.origem == "fallback"
    assert "soma" in r.avisos[0]


def test_desvio_de_16_pp_e_rejeitado():
    r, _, _ = rodar(gemini=resposta((0.44, 0.35, 0.21)), nvidia=resposta((0.44, 0.35, 0.21)))
    assert r.justificativa.origem == "fallback"
    assert "desvia" in r.avisos[0]


@pytest.mark.parametrize(
    "base, sugerida",
    [
        ((0.25, 0.35, 0.40), (0.40, 0.20, 0.40)),  # 0,25 -> 0,40: 15 p.p. exatos (quebra sem round)
        ((0.55, 0.20, 0.25), (0.40, 0.35, 0.25)),  # 0,55 -> 0,40: 15 p.p. exatos
    ],
)
def test_desvio_de_exatamente_15_pp_e_aceito(base, sugerida):
    r, _, _ = rodar(gemini=resposta(sugerida), ent=entrada(base=base))
    assert r.justificativa.origem == "llm"
    assert r.justificativa.provedor == "gemini"
    assert r.avisos == []


@pytest.mark.parametrize("campo", ["texto", "resumo", "narracao_o_que_mudaria"])
@pytest.mark.parametrize("vazio", ["", "   "])
def test_texto_vazio_e_rejeitado(campo, vazio):
    r, _, _ = rodar(gemini=resposta(**{campo: vazio}), nvidia=resposta(**{campo: vazio}))
    assert r.justificativa.origem == "fallback"


@pytest.mark.parametrize("resumo", ["Uma linha só.", "1\n2\n3\n4"])
def test_resumo_com_numero_de_linhas_errado_e_rejeitado(resumo):
    r, _, _ = rodar(gemini=resposta(resumo=resumo), nvidia=resposta(resumo=resumo))
    assert r.justificativa.origem == "fallback"
    assert "linhas" in r.avisos[0]


def test_tetos_de_tamanho_sao_aplicados():
    longo = resposta(texto="a" * (TEXTO_MAX_CARACTERES + 1))
    r, _, _ = rodar(gemini=longo, nvidia=longo)
    assert r.justificativa.origem == "fallback"


def test_chave_extra_ou_ausente_e_rejeitada():
    base = json.loads(resposta())
    com_extra = json.dumps({**base, "extra": 1})
    sem_chave = json.dumps({k: v for k, v in base.items() if k != "resumo"})
    for ruim in (com_extra, sem_chave):
        r, _, _ = rodar(gemini=ruim, nvidia=ruim)
        assert r.justificativa.origem == "fallback"


@pytest.mark.parametrize("peso", ['"0.55"', "true", "null"])
def test_peso_que_nao_e_numero_e_rejeitado(peso):
    ruim = resposta().replace("0.55", peso)
    r, _, _ = rodar(gemini=ruim, nvidia=ruim)
    assert r.justificativa.origem == "fallback"


def test_carteira_com_chave_a_mais_e_rejeitada():
    base = json.loads(resposta())
    base["carteira_sugerida"]["cripto"] = 0.0
    ruim = json.dumps(base)
    r, _, _ = rodar(gemini=ruim, nvidia=ruim)
    assert r.justificativa.origem == "fallback"


# ---------------------------------------------------------------- fallback


def test_todos_os_provedores_falham_vira_fallback():
    r, _, _ = rodar(gemini=ErroProvedor("tempo esgotado"), nvidia=ErroProvedor("falha de rede"))
    assert r.justificativa.origem == "fallback"
    assert r.justificativa.provedor is None
    assert r.carteira_sugerida == entrada().carteira_base
    assert r.avisos == [
        "Gemini indisponível (tempo esgotado); NVIDIA NIM indisponível (falha de rede); "
        "texto de modelo fixo e carteira base."
    ]
    assert [t.ok for t in r.tentativas] == [False, False]


def test_sem_chaves_no_ambiente_vira_fallback_sem_excecao():
    cfg = settings(GEMINI_API_KEY="", NVIDIA_NIM_API_KEY="", LLM_PRIMARY="", LLM_SECONDARY="")
    # Sem chadores falsos: usa as funções reais, que falham rápido (sem rede).
    r = gerar_analise(entrada(), settings=cfg)
    assert r.justificativa.origem == "fallback"
    assert r.justificativa.provedor is None
    assert r.carteira_sugerida == entrada().carteira_base
    assert "Gemini indisponível (chave ou modelo não configurados)" in r.avisos[0]
    assert "NVIDIA NIM indisponível (chave ou modelo não configurados)" in r.avisos[0]


def test_gemini_ok_sem_chave_da_nvidia_usa_o_gemini_sem_erro():
    cfg = settings(NVIDIA_NIM_API_KEY="", LLM_SECONDARY="")
    r, _, nv = rodar(gemini=resposta(), cfg=cfg)
    assert r.justificativa.provedor == "gemini"
    assert r.avisos == [] and nv.chamadas == []


def test_gemini_sem_chave_e_nvidia_ok_registra_nvidia_nim():
    cfg = settings(GEMINI_API_KEY="")
    # o chamador falso do Gemini não é usado: com chamador real a falta de chave falha rápido
    r = gerar_analise(
        entrada(), settings=cfg, chamadores={"nvidia_nim": Falso(resposta())}
    )
    assert r.justificativa.provedor == "nvidia_nim"
    assert r.avisos == [
        "Gemini indisponível (chave ou modelo não configurados); usado NVIDIA NIM."
    ]


def test_provedor_desconhecido_e_erro_de_programacao():
    with pytest.raises(ValueError):
        gerar_analise(entrada(), settings=settings(), provedores=("outro",))


def test_orcamento_de_tempo_esgotado_vai_direto_ao_fallback():
    relogio = type("R", (), {"t": 0.0})()

    def gasta_tempo():
        relogio.t += 41.0
        raise ErroProvedor("tempo esgotado")

    r, _, nv = rodar(
        gemini=gasta_tempo, nvidia=resposta(), relogio=lambda: relogio.t
    )
    assert r.justificativa.origem == "fallback"
    assert nv.chamadas == []  # restante = 45 - 41 = 4 s (< 5 s): nem tenta
    assert "orçamento de tempo esgotado" in r.avisos[0]


def test_timeout_da_segunda_chamada_respeita_o_que_sobra_do_orcamento():
    relogio = type("R", (), {"t": 0.0})()

    def gasta_tempo():
        relogio.t += 30.0
        raise ErroProvedor("tempo esgotado")

    r, gem, nv = rodar(gemini=gasta_tempo, nvidia=resposta(), relogio=lambda: relogio.t)
    assert gem.chamadas[0]["timeout"] == 25.0
    assert nv.chamadas[0]["timeout"] == 15.0  # 45 - 30
    assert r.justificativa.provedor == "nvidia_nim"


def test_parametros_repassados_aos_chamadores():
    cfg = settings(LLM_MAX_TOKENS=777, LLM_SECONDARY_JSON_MODE=True)
    r, gem, nv = rodar(gemini="x", nvidia=resposta(), cfg=cfg)
    assert gem.chamadas[0]["max_tokens"] == 777
    assert nv.chamadas[0]["json_mode"] is True
    assert nv.chamadas[0]["modelo"] == "dono/modelo-nvidia-teste"
    assert nv.chamadas[0]["chave"] == CHAVE_NVIDIA


def test_fallback_usa_texto_fixo_valido_e_dentro_dos_tetos():
    variantes = [
        entrada(),
        entrada(
            cenario={
                **CENARIO,
                "classificacao": "EXPANSAO",
                "o_que_mudaria": {"ipca_precisa_cair_pp": None, "ibcbr_proximo_mes_precisa_superar": None},
            },
            juro={"ex_post_pct": 8.62, "projetado_12m_pct": None, "entradas_projetado": None},
        ),
    ]
    for e in variantes:
        just, sug = montar_fallback(e)
        Justificativa.model_validate(just.model_dump())  # valida de novo pelo contrato
        assert just.origem == "fallback" and just.provedor is None
        assert sug == e.carteira_base
        assert len(just.texto) <= TEXTO_MAX_CARACTERES
        assert len(just.narracao_o_que_mudaria) <= NARRACAO_MAX_CARACTERES
        assert all(len(l) <= RESUMO_LINHA_MAX_CARACTERES for l in just.resumo.splitlines())
    assert "0,13 p.p." in montar_fallback(variantes[0])[0].narracao_o_que_mudaria
    assert "ESTAGFLACAO" in montar_fallback(variantes[0])[0].texto


# ---------------------------------------------------------------- segurança das chaves


def test_chave_nunca_aparece_em_avisos_nem_tentativas():
    def vaza():
        raise RuntimeError(f"falhou com {CHAVE_GEMINI} e {CHAVE_NVIDIA}")

    r, _, _ = rodar(gemini=vaza, nvidia=vaza)
    visivel = repr(r.avisos) + repr(r.tentativas) + r.justificativa.texto
    assert CHAVE_GEMINI not in visivel and CHAVE_NVIDIA not in visivel
    assert "RuntimeError" in r.avisos[0]


def test_prompt_nao_leva_chave_nem_dado_pessoal():
    sistema, usuario = montar_mensagens(entrada())
    assert CHAVE_GEMINI not in sistema + usuario
    assert "nenhum dado pessoal" in sistema


# ---------------------------------------------------------------- prompt


def test_prompt_traz_pesos_com_ponto_decimal_e_limite():
    sistema, usuario = montar_mensagens(entrada())
    assert "renda_fixa 0.60 (60%)" in usuario
    assert "fundos_cambiais 0.25 (25%)" in usuario
    assert "renda_variavel 0.15 (15%)" in usuario
    assert "15 p.p. (no JSON, em fração: 0.15)" in usuario
    assert "ESTAGFLACAO" in usuario and "POSFIXADA" in usuario
    assert "-0,64%" in usuario and "112,23" in usuario
    assert "0.55 significa 55%" in sistema
    assert "SOMENTE os números fornecidos" in sistema


def test_prompt_manda_citar_pesos_como_percentual_nos_textos():
    sistema, usuario = montar_mensagens(entrada())
    assert "SEMPRE como percentuais" in sistema
    assert "NUNCA como fração" in sistema
    assert 'SOMENTE nas chaves de "carteira_sugerida" do JSON' in sistema
    assert "exceção: os pesos da carteira" in sistema
    # lembrete no fim da mensagem do usuário, logo antes do pedido final
    assert "nos textos, cite os pesos só como percentuais" in usuario
    assert usuario.index("Lembrete:") < usuario.index("Responda agora")
    # a fração só aparece como orientação para o JSON, nunca como "em fração" solta
    assert "0.15 em fração" not in usuario


def test_prompt_marca_indisponivel_e_nada_a_mudar():
    e = entrada(
        cenario={
            **CENARIO,
            "o_que_mudaria": {"ipca_precisa_cair_pp": None, "ibcbr_proximo_mes_precisa_superar": None},
        },
        juro={"ex_post_pct": 8.62, "projetado_12m_pct": None, "entradas_projetado": None},
    )
    _, usuario = montar_mensagens(e)
    assert "Projetado em 12 meses: indisponível" in usuario
    assert usuario.count("já está do lado favorável (nada a mudar)") == 2


# ---------------------------------------------------------------- nome do modelo Gemini


@pytest.mark.parametrize("nome", ["gemini-3.6-flash", "a", "A1_b-2.c", "9modelo"])
def test_nome_de_modelo_gemini_valido(nome):
    assert modelo_gemini_valido(nome)


@pytest.mark.parametrize(
    "nome", ["", ".oculto", "..", "a..b", "-x", "_x", "a/b", "a b", "a?b=1", "modelo:generate", "a\n"]
)
def test_nome_de_modelo_gemini_invalido(nome):
    assert not modelo_gemini_valido(nome)


@pytest.mark.parametrize("nome", ["../x", ".x", "a..b", "a/b", ""])
def test_nome_de_modelo_invalido_falha_rapido_sem_chamar_a_rede(nome):
    chamado = []

    def handler(req):
        chamado.append(req)
        return httpx2.Response(200, json={})

    with pytest.raises(ErroProvedor, match="chave ou modelo não configurados"):
        _chamar_gemini(nome, "s", "u", CHAVE_GEMINI, 5.0, 100, transporte=httpx2.MockTransport(handler))
    assert chamado == []


# ---------------------------------------------------------------- cadeia + HTTP real (transporte falso)


def test_cadeia_completa_com_a_funcao_real_do_gemini_e_transporte_falso():
    def handler(req):
        corpo = {
            "candidates": [
                {"content": {"parts": [{"text": resposta()}]}, "finishReason": "STOP"}
            ]
        }
        return httpx2.Response(200, json=corpo)

    gemini = functools.partial(_chamar_gemini, transporte=httpx2.MockTransport(handler))
    r = gerar_analise(entrada(), settings=settings(), chamadores={"gemini": gemini})
    assert r.justificativa.provedor == "gemini"
    assert r.avisos == []
