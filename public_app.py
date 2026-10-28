import html
import re
import unicodedata
from decimal import Decimal, InvalidOperation
from uuid import uuid4
from datetime import date, datetime, time as dtime

import pandas as pd
import requests
import streamlit as st

from supabase_rest import table_select, table_insert


# =========================================================
# CONFIGURAÇÃO DA PÁGINA
# =========================================================
st.set_page_config(
    page_title="Solicite sua Festa | TimTim Festas",
    page_icon="🎈",
    layout="centered",
)

st.markdown(
    """
    <h3 style="text-align:center;">🎈 Cadastro</h3>
    """,
    unsafe_allow_html=True
)


# =========================================================
# SESSION STATE
# =========================================================
if "pre_confirm_payload" not in st.session_state:
    st.session_state.pre_confirm_payload = None

if "show_confirm_dialog" not in st.session_state:
    st.session_state.show_confirm_dialog = False

if "brinquedos_sel" not in st.session_state:
    st.session_state.brinquedos_sel = set()

if "pre_confirm_resumo" not in st.session_state:
    st.session_state.pre_confirm_resumo = []

if "pre_confirm_kit" not in st.session_state:
    st.session_state.pre_confirm_kit = None

if "pre_confirm_kit_dialog" not in st.session_state:
    st.session_state.pre_confirm_kit_dialog = None

if "ids_enviados" not in st.session_state:
    st.session_state.ids_enviados = set()

if "assinaturas_enviadas" not in st.session_state:
    st.session_state.assinaturas_enviadas = set()

if "aviso_data_passada" not in st.session_state:
    st.session_state.aviso_data_passada = ""

if "pre_success" not in st.session_state:
    st.session_state.pre_success = False

if "pre_success_msg" not in st.session_state:
    st.session_state.pre_success_msg = ""

# Controle da importação administrativa
if "importacao_autorizada" not in st.session_state:
    st.session_state.importacao_autorizada = False

if "cliente_importado" not in st.session_state:
    st.session_state.cliente_importado = False

if "arquivo_forms_nome" not in st.session_state:
    st.session_state.arquivo_forms_nome = None

if "df_google_forms" not in st.session_state:
    st.session_state.df_google_forms = None

if "forms_registro_selecionado" not in st.session_state:
    st.session_state.forms_registro_selecionado = None


# =========================================================
# FUNÇÕES AUXILIARES GERAIS
# =========================================================
def normalizar_nome(txt: str) -> str:
    if not isinstance(txt, str):
        return ""

    texto = unicodedata.normalize(
        "NFKD",
        txt
    ).encode(
        "ascii",
        "ignore"
    ).decode("utf-8")

    texto = re.sub(r"[^a-zA-Z0-9]+", " ", texto)

    return texto.strip().lower()


def normalizar_titulo_coluna(txt: str) -> str:
    """
    Normaliza o título da coluna para permitir localizar
    campos mesmo com espaços, acentos ou dois-pontos.
    """
    if txt is None:
        return ""

    texto = str(txt).strip().lower()

    texto = unicodedata.normalize(
        "NFKD",
        texto
    ).encode(
        "ascii",
        "ignore"
    ).decode("utf-8")

    texto = re.sub(r"[^a-z0-9]+", " ", texto)

    return texto.strip()


def valor_vazio(valor) -> bool:
    if valor is None:
        return True

    try:
        if pd.isna(valor):
            return True
    except Exception:
        pass

    texto = str(valor).strip().lower()

    return texto in ["", "nan", "none", "nat", "<na>"]


def valor_para_texto(valor) -> str:
    """
    Converte valores do Excel para texto, tentando retirar:
    - notação científica;
    - .0 no final;
    - valores vazios como nan.
    """
    if valor_vazio(valor):
        return ""

    if isinstance(valor, str):
        texto = valor.strip()

        if not texto:
            return ""

        # Tenta converter somente quando o valor realmente
        # estiver em notação científica.
        if re.fullmatch(
            r"[+-]?\d+(?:\.\d+)?[eE][+-]?\d+",
            texto
        ):
            try:
                numero = Decimal(texto)
                return format(numero, "f").split(".")[0]
            except InvalidOperation:
                return texto

        # Remove apenas .0 no final de números inteiros
        if re.fullmatch(r"[+-]?\d+\.0", texto):
            return texto[:-2]

        return texto

    if isinstance(valor, bool):
        return str(valor)

    if isinstance(valor, int):
        return str(valor)

    if isinstance(valor, float):
        if pd.isna(valor):
            return ""

        if valor.is_integer():
            return str(int(valor))

        try:
            numero = Decimal(str(valor))
            texto = format(numero, "f")
            return texto.rstrip("0").rstrip(".")
        except Exception:
            return str(valor)

    return str(valor).strip()


def somente_numeros(valor) -> str:
    texto = valor_para_texto(valor)
    return re.sub(r"\D", "", texto)


def formatar_telefone_importado(valor) -> str:
    telefone = somente_numeros(valor)

    # Não remove o DDI automaticamente.
    # O campo continua editável para conferência.
    return telefone


def formatar_cpf_importado(valor) -> str:
    cpf = somente_numeros(valor)

    # CPF brasileiro possui 11 dígitos.
    # Não completamos zeros automaticamente.
    return cpf


def formatar_cep_importado(valor) -> str:
    cep = somente_numeros(valor)

    # Alguns CEPS vieram com números adicionais.
    if len(cep) > 8:
        cep = cep[:8]

    return cep


def formatar_rg_importado(valor) -> str:
    if valor_vazio(valor):
        return ""

    texto = valor_para_texto(valor)

    # Mantém X quando existir.
    texto = re.sub(
        r"[^0-9xX]",
        "",
        texto
    )

    return texto.upper()


def converter_data_excel(valor):
    """
    Converte datas do Excel e do Google Forms.
    Retorna None quando não for possível determinar
    uma data válida com segurança.
    """
    if valor_vazio(valor):
        return None

    if isinstance(valor, pd.Timestamp):
        data_convertida = valor.date()

        if 2000 <= data_convertida.year <= 2100:
            return data_convertida

        return None

    if isinstance(valor, datetime):
        data_convertida = valor.date()

        if 2000 <= data_convertida.year <= 2100:
            return data_convertida

        return None

    if isinstance(valor, date):
        if 2000 <= valor.year <= 2100:
            return valor

        return None

    # Número serial do Excel
    if isinstance(valor, (int, float)) and not isinstance(valor, bool):
        try:
            data_convertida = pd.to_datetime(
                valor,
                unit="D",
                origin="1899-12-30"
            )

            if 2000 <= data_convertida.year <= 2100:
                return data_convertida.date()

        except Exception:
            pass

    texto = str(valor).strip()

    formatos = [
        "%d/%m/%Y",
        "%m/%d/%Y",
        "%Y-%m-%d",
        "%d-%m-%Y",
        "%m-%d-%Y",
    ]

    for formato in formatos:
        try:
            data_convertida = datetime.strptime(
                texto,
                formato
            ).date()

            if 2000 <= data_convertida.year <= 2100:
                return data_convertida

        except ValueError:
            continue

    try:
        data_convertida = pd.to_datetime(
            texto,
            dayfirst=True,
            errors="coerce"
        )

        if not pd.isna(data_convertida):
            if 2000 <= data_convertida.year <= 2100:
                return data_convertida.date()

    except Exception:
        pass

    return None


def converter_hora_excel(valor):
    """
    Converte horário do Excel para datetime.time.
    """
    if valor_vazio(valor):
        return None

    if isinstance(valor, dtime):
        return valor.replace(second=0, microsecond=0)

    if isinstance(valor, datetime):
        return valor.time().replace(second=0, microsecond=0)

    if isinstance(valor, pd.Timestamp):
        return valor.time().replace(second=0, microsecond=0)

    # Horário pode vir como fração de um dia no Excel
    if isinstance(valor, (int, float)) and not isinstance(valor, bool):
        try:
            total_segundos = int(
                round((float(valor) % 1) * 24 * 60 * 60)
            )

            horas = (total_segundos // 3600) % 24
            minutos = (total_segundos % 3600) // 60

            return dtime(horas, minutos)

        except Exception:
            pass

    texto = str(valor).strip()

    formatos = [
        "%H:%M:%S",
        "%H:%M",
        "%I:%M:%S %p",
        "%I:%M %p",
    ]

    for formato in formatos:
        try:
            return datetime.strptime(
                texto,
                formato
            ).time().replace(second=0, microsecond=0)

        except ValueError:
            continue

    return None


def converter_carimbo_data_hora(valor):
    """
    Utilizado apenas para ordenar os registros mais novos
    do Google Forms primeiro.
    """
    if valor_vazio(valor):
        return pd.NaT

    if isinstance(valor, (int, float)) and not isinstance(valor, bool):
        try:
            return pd.to_datetime(
                valor,
                unit="D",
                origin="1899-12-30"
            )
        except Exception:
            return pd.NaT

    try:
        return pd.to_datetime(
            valor,
            dayfirst=True,
            errors="coerce"
        )
    except Exception:
        return pd.NaT


def localizar_coluna(df, nomes_possiveis):
    """
    Localiza uma coluna mesmo que tenha pequenas diferenças
    de espaço, pontuação ou acentuação.
    """
    mapa_colunas = {
        normalizar_titulo_coluna(coluna): coluna
        for coluna in df.columns
    }

    for nome in nomes_possiveis:
        nome_normalizado = normalizar_titulo_coluna(nome)

        if nome_normalizado in mapa_colunas:
            return mapa_colunas[nome_normalizado]

    return None


def obter_valor_linha(linha, coluna):
    if not coluna:
        return ""

    try:
        return linha.get(coluna, "")
    except Exception:
        return ""


def via_cep(cep: str):
    try:
        cep_num = re.sub(
            r"\D",
            "",
            str(cep)
        )[:8]

        if len(cep_num) != 8:
            return None

        response = requests.get(
            f"https://viacep.com.br/ws/{cep_num}/json/",
            timeout=8
        )

        if (
            response.status_code == 200
            and "erro" not in response.json()
        ):
            dados = response.json()

            return {
                "logradouro": dados.get("logradouro", ""),
                "bairro": dados.get("bairro", ""),
                "cidade": dados.get("localidade", ""),
            }

    except Exception:
        pass

    return None


def carregar_brinquedos():
    colunas = (
        "id_brinquedo,nome,status,"
        "categoria,subcategoria,imagem_url"
    )

    rows = table_select(
        "brinquedos",
        select=colunas,
        where={"status": "Disponível"},
        order=("nome", "asc"),
    )

    if rows:
        return pd.DataFrame(rows)

    return pd.DataFrame(
        columns=colunas.split(",")
    )


def carregar_reservas_do_dia(data_evento_consulta):
    rows = table_select(
        "reservas",
        select="data,brinquedos",
        where={"data": str(data_evento_consulta)}
    )

    if rows:
        return pd.DataFrame(rows)

    return pd.DataFrame(
        columns=["data", "brinquedos"]
    )


def ocupados_no_dia(df):
    ocupados = set()

    for _, linha in df.iterrows():
        for pedaco in str(
            linha.get("brinquedos", "")
        ).split(","):
            nome = pedaco.strip()

            if nome:
                ocupados.add(
                    normalizar_nome(nome)
                )

    return ocupados


# =========================================================
# CATÁLOGO VISUAL DE BRINQUEDOS
# =========================================================
# Quantos brinquedos por linha no computador (no celular são 3).
# Para fotos maiores, diminua (ex.: 4). Para menores, aumente (ex.: 8).
COLUNAS_POR_LINHA = 6

# Distância do topo onde o painel do kit fica "preso".
# Se o painel ficar escondido atrás da barra do Streamlit, aumente (ex.: 4rem).
TOPO_PAINEL_FIXO = "4rem"

ORDEM_SUB = ["G", "M", "P", "E"]

TITULOS_SUB = {
    "G": "Grandes (G)",
    "M": "Médios (M)",
    "P": "Pequenos (P)",
    "E": "Extras (E)",
}

TITULOS_GRUPO = {
    "G": "🌿 Montessori · Grandes (G)",
    "M": "🌿 Montessori · Médios (M)",
    "P": "🌿 Montessori · Pequenos (P)",
    "E": "🌿 Montessori · Extras (E)",
    "OUT": "🌿 Montessori · Outros",
    "TRAD": "🎪 Tradicional",
}

TITULOS_FILTRO = {
    "TODOS": "Todos",
    "G": "Grandes",
    "M": "Médios",
    "P": "Pequenos",
    "E": "Extras",
    "OUT": "Outros",
    "TRAD": "Tradicional",
}

ORDEM_GRUPOS = ["G", "M", "P", "E", "OUT", "TRAD"]

# Composição padrão de cada kit (apenas orientação, não bloqueia).
# Para alterar quantidades ou criar kit novo, edite aqui.
KITS = {
    "LIVRE": {
        "nome": "Escolha livre (sem kit)",
        "G": 0, "M": 0, "P": 0,
    },
    "ESSENCIA": {
        "nome": "Kit Essência",
        "G": 3, "M": 4, "P": 5,
    },
    "ENCANTOS": {
        "nome": "Kit Encantos",
        "G": 4, "M": 5, "P": 7,
    },
    "TIMTIM": {
        "nome": "Kit TimTim",
        "G": 5, "M": 6, "P": 9,
    },
}

NOMES_SUB_SING = {"G": "Grande", "M": "Médio", "P": "Pequeno"}
NOMES_SUB_PLURAL = {"G": "Grandes", "M": "Médios", "P": "Pequenos"}


def total_kit(chave_kit) -> int:
    kit = KITS[chave_kit]
    return kit["G"] + kit["M"] + kit["P"]


def rotulo_kit(chave_kit) -> str:
    if chave_kit == "LIVRE":
        return KITS["LIVRE"]["nome"]

    kit = KITS[chave_kit]
    return (
        f"{kit['nome']} · {total_kit(chave_kit)} itens "
        f"(G{kit['G']} · M{kit['M']} · P{kit['P']})"
    )


def montar_resumo_kit(chave_kit, selec_por_grupo):
    """
    Compara o que o cliente escolheu com a composição do kit.
    """
    kit = KITS[chave_kit]
    linhas = []

    for sub in ["G", "M", "P"]:
        meta = kit[sub]
        atual = selec_por_grupo.get(sub, 0)
        linhas.append(
            {
                "sub": sub,
                "meta": meta,
                "atual": atual,
                "dif": atual - meta,
            }
        )

    meta_total = total_kit(chave_kit)
    atual_total = sum(l["atual"] for l in linhas)

    extras = (
        selec_por_grupo.get("E", 0)
        + selec_por_grupo.get("OUT", 0)
        + selec_por_grupo.get("TRAD", 0)
    )

    partes = [
        f"{l['sub']} {l['atual']}/{l['meta']}" for l in linhas
    ]

    texto = (
        f"{kit['nome']}: "
        + " · ".join(partes)
        + f" | Total {atual_total}/{meta_total}"
    )

    if extras:
        texto += f" | Extras/Tradicional: {extras}"

    return {
        "chave": chave_kit,
        "nome": kit["nome"],
        "linhas": linhas,
        "meta_total": meta_total,
        "atual_total": atual_total,
        "extras": extras,
        "texto": texto,
    }


def sem_indentacao(txt: str) -> str:
    """Remove a indentação de cada linha (o Markdown trata 4+ espaços como código)."""
    return "\n".join(l.strip() for l in txt.splitlines() if l.strip())


def css_fixo() -> str:
    """CSS que deixa o painel preso no topo enquanto a página rola."""
    return f"""
    <style>
    div[data-testid="stElementContainer"]:has(.kit-fixo),
    div[data-testid="element-container"]:has(.kit-fixo) {{
        position: sticky;
        top: {TOPO_PAINEL_FIXO};
        z-index: 999;
    }}
    .kit-fixo {{
        background: #ffffff;
        border-radius: 12px;
        padding: 6px 8px 4px 8px;
        box-shadow: 0 3px 10px rgba(0,0,0,0.18);
        border: 1px solid #e6e6e6;
    }}
    </style>
    """


def mostrar_contador_livre(total):
    """Contador simples (também fixo) quando o cliente não escolheu kit."""
    st.markdown(
        sem_indentacao(css_fixo() + f"""
        <div class="kit-fixo" style="text-align:center;padding:8px;">
            <span style="font-size:1rem;font-weight:700;color:#1b7f3b;">
                🎠 {total} brinquedo(s) selecionado(s)
            </span>
        </div>
        """),
        unsafe_allow_html=True,
    )


def mostrar_painel_kit(resumo):
    """
    Painel compacto G / M / P / Total.
    Fica fixo no topo da tela enquanto o cliente rola a página.
    Tudo vai em UM único st.markdown para o CSS conseguir fixar o bloco.
    """

    def cartao(titulo, atual, meta):
        dif = atual - meta

        if dif == 0:
            cor, fundo, msg = "#1b7f3b", "#e8f6ec", "✅ completo"
        elif dif < 0:
            cor, fundo = "#b26a00", "#fff4e0"
            msg = f"faltam {abs(dif)}"
        else:
            cor, fundo = "#0b5cad", "#e7f1fc"
            msg = f"+{dif} a mais"

        return (
            f'<div style="flex:1;min-width:0;background:{fundo};'
            f'border-radius:8px;padding:4px 2px;text-align:center;'
            f'line-height:1.15;">'
            f'<div style="font-size:0.68rem;color:#555;">{titulo}</div>'
            f'<div style="font-size:1.15rem;font-weight:700;'
            f'color:{cor};">{atual}/{meta}</div>'
            f'<div style="font-size:0.65rem;color:{cor};">{msg}</div>'
            f'</div>'
        )

    cartoes = "".join(
        cartao(
            NOMES_SUB_PLURAL[l["sub"]],
            l["atual"],
            l["meta"],
        )
        for l in resumo["linhas"]
    )

    cartoes += cartao(
        "Total",
        resumo["atual_total"],
        resumo["meta_total"],
    )

    faltam = []
    sobram = []

    for l in resumo["linhas"]:
        if l["dif"] < 0:
            nome = (
                NOMES_SUB_SING[l["sub"]]
                if abs(l["dif"]) == 1
                else NOMES_SUB_PLURAL[l["sub"]]
            )
            faltam.append(f"{abs(l['dif'])} {nome}")
        elif l["dif"] > 0:
            nome = (
                NOMES_SUB_SING[l["sub"]]
                if l["dif"] == 1
                else NOMES_SUB_PLURAL[l["sub"]]
            )
            sobram.append(f"{l['dif']} {nome}")

    if not faltam and not sobram:
        mensagem = (
            f"✅ Composição do {resumo['nome']} completa!"
        )
    else:
        partes = []

        if faltam:
            partes.append("🔸 Faltam: " + ", ".join(faltam))

        if sobram:
            partes.append("🔹 A mais: " + ", ".join(sobram))

        mensagem = " &nbsp;|&nbsp; ".join(partes)

    st.markdown(
        sem_indentacao(css_fixo() + f"""
        <div class="kit-fixo">
            <div style="font-size:0.72rem;color:#666;margin-bottom:3px;">
                🎁 {html.escape(resumo['nome'])} · orientação (não bloqueia)
            </div>
            <div style="display:flex;gap:6px;">{cartoes}</div>
            <div style="font-size:0.75rem;margin-top:4px;color:#333;">
                {mensagem}
            </div>
        </div>
        """),
        unsafe_allow_html=True,
    )

    if resumo["extras"]:
        st.caption(
            f"➕ {resumo['extras']} item(ns) Extra(s)/Tradicional "
            "não entram na contagem do kit."
        )

    st.caption(
        "ℹ️ Esta contagem é só uma orientação. Você pode escolher "
        "mais ou menos itens e combinamos os detalhes com você."
    )


def nome_exibicao(nome: str) -> str:
    """
    Esconde o prefixo 'G - ', 'P - ' etc. apenas na tela.
    O nome salvo no banco e nas reservas não é alterado.
    """
    return re.sub(
        r"^\s*[GMPEgmpe]\s*-\s*",
        "",
        str(nome)
    ).strip()


def texto_seguro(valor) -> str:
    if valor_vazio(valor):
        return ""
    return str(valor).strip()


def chave_grupo(categoria, subcategoria) -> str:
    """
    Devolve G, M, P, E, OUT (Montessori sem subcategoria)
    ou TRAD (Tradicional / demais).
    """
    cat = texto_seguro(categoria).lower()
    sub = texto_seguro(subcategoria).upper()

    if cat.startswith("montessori"):
        return sub if sub in ORDEM_SUB else "OUT"

    return "TRAD"


CSS_CATALOGO = """
<style>
/* Grade de brinquedos: só afeta linhas que contêm fotos */
div[data-testid="stHorizontalBlock"]:has(.brq-img) {
    flex-wrap: wrap !important;
    gap: 0.5rem !important;
}
div[data-testid="stHorizontalBlock"]:has(.brq-img)
    > div[data-testid="stColumn"],
div[data-testid="stHorizontalBlock"]:has(.brq-img)
    > div[data-testid="column"] {
    flex: 0 0 calc(100% / __N__ - 0.5rem) !important;
    width: calc(100% / __N__ - 0.5rem) !important;
    min-width: calc(100% / __N__ - 0.5rem) !important;
    position: relative;
    cursor: pointer;
}
div[data-testid="stHorizontalBlock"]:has(.brq-img) label p {
    font-size: 0.72rem !important;
    line-height: 1.15 !important;
}
div[data-testid="stHorizontalBlock"]:has(.brq-img)
    div[data-testid="stCheckbox"] {
    margin-top: -0.4rem;
}
/* Os blocos internos do Streamlit (e, nas versões novas, o próprio rótulo
   da caixinha) usam position:relative. Precisam ser static para que a área
   clicável se ajuste ao cartão inteiro (a coluna é quem ancora). */
div[data-testid="stHorizontalBlock"]:has(.brq-img)
    div[data-testid="stElementContainer"],
div[data-testid="stHorizontalBlock"]:has(.brq-img)
    div[data-testid="element-container"],
div[data-testid="stHorizontalBlock"]:has(.brq-img)
    div[data-testid="stVerticalBlock"],
div[data-testid="stHorizontalBlock"]:has(.brq-img)
    div[data-testid="stCheckbox"],
div[data-testid="stHorizontalBlock"]:has(.brq-img)
    div[data-testid="stCheckbox"] label {
    position: static !important;
}
/* Clique na foto: a área do rótulo da caixinha cobre o cartão todo */
div[data-testid="stHorizontalBlock"]:has(.brq-img)
    div[data-testid="stCheckbox"] label::after {
    content: "";
    position: absolute;
    inset: 0;
    z-index: 2;
    cursor: pointer;
}
div[data-testid="stHorizontalBlock"]:has(.brq-img)
    > div:hover .brq-img {
    filter: brightness(0.94);
}
.brq-img {
    width: 100%;
    aspect-ratio: 1 / 1;
    object-fit: contain;
    background: #f6f6f6;
    border-radius: 10px;
    border: 3px solid transparent;
    display: block;
}
.brq-img.sel {
    border-color: #ff4b4b;
    background: #fff5f5;
}
.brq-semfoto {
    display: flex;
    align-items: center;
    justify-content: center;
    color: #999;
    font-size: 0.7rem;
}
@media (max-width: 640px) {
    div[data-testid="stHorizontalBlock"]:has(.brq-img)
        > div[data-testid="stColumn"],
    div[data-testid="stHorizontalBlock"]:has(.brq-img)
        > div[data-testid="column"] {
        flex: 0 0 calc(100% / 3 - 0.5rem) !important;
        width: calc(100% / 3 - 0.5rem) !important;
        min-width: calc(100% / 3 - 0.5rem) !important;
    }
}

/* Nome completo do brinquedo: quebra em até 3 linhas em vez de cortar com "..." */
div[data-testid="stHorizontalBlock"]:has(.brq-img)
    div[data-testid="stCheckbox"] label,
div[data-testid="stHorizontalBlock"]:has(.brq-img)
    div[data-testid="stCheckbox"] label > div,
div[data-testid="stHorizontalBlock"]:has(.brq-img)
    div[data-testid="stCheckbox"] [data-testid="stWidgetLabel"],
div[data-testid="stHorizontalBlock"]:has(.brq-img)
    div[data-testid="stCheckbox"] [data-testid="stMarkdownContainer"],
div[data-testid="stHorizontalBlock"]:has(.brq-img)
    div[data-testid="stCheckbox"] .stMarkdownEllipsis {
    max-width: 100% !important;
    min-width: 0 !important;
    overflow: visible !important;
    text-overflow: clip !important;
    white-space: normal !important;
}
div[data-testid="stHorizontalBlock"]:has(.brq-img)
    div[data-testid="stCheckbox"] label {
    align-items: flex-start !important;
}
div[data-testid="stHorizontalBlock"]:has(.brq-img)
    div[data-testid="stCheckbox"] label p {
    white-space: normal !important;
    overflow: visible !important;
    text-overflow: clip !important;
    overflow-wrap: anywhere;
    display: block !important;
    -webkit-line-clamp: unset !important;
    line-height: 1.15 !important;
}
</style>
"""


def css_catalogo():
    st.markdown(
        CSS_CATALOGO.replace("__N__", str(COLUNAS_POR_LINHA)),
        unsafe_allow_html=True,
    )


def alternar_brinquedo(nome, chave):
    """Callback do checkbox: mantém a seleção mesmo trocando de filtro."""
    selecionados = st.session_state.brinquedos_sel

    if st.session_state.get(chave):
        selecionados.add(nome)
    else:
        selecionados.discard(nome)


def mostrar_card_brinquedo(linha):
    nome = linha["nome"]

    identificador = texto_seguro(
        linha.get("id_brinquedo")
    ) or normalizar_nome(nome)

    chave = f"brq_{identificador}"
    marcado = nome in st.session_state.brinquedos_sel
    classe = "brq-img sel" if marcado else "brq-img"
    url = texto_seguro(linha.get("imagem_url"))

    if url:
        st.markdown(
            f'<img class="{classe}" loading="lazy" '
            f'src="{html.escape(url, quote=True)}" '
            f'alt="{html.escape(nome_exibicao(nome), quote=True)}">',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f'<div class="{classe} brq-semfoto">Sem foto</div>',
            unsafe_allow_html=True,
        )

    st.checkbox(
        nome_exibicao(nome),
        value=marcado,
        key=chave,
        on_change=alternar_brinquedo,
        args=(nome, chave),
    )


def renderizar_grade(df_grupo):
    linhas = df_grupo.to_dict("records")

    for i in range(0, len(linhas), COLUNAS_POR_LINHA):
        bloco = linhas[i:i + COLUNAS_POR_LINHA]
        colunas = st.columns(len(bloco))

        for coluna, linha in zip(colunas, bloco):
            with coluna:
                mostrar_card_brinquedo(linha)


def agrupar_para_resumo(itens):
    """
    itens: lista de dicts com nome, categoria e subcategoria.
    Retorna lista [(titulo_do_grupo, [nomes_para_exibir])].
    """
    grupos = {chave: [] for chave in ORDEM_GRUPOS}

    for item in itens:
        chave = chave_grupo(
            item.get("categoria"),
            item.get("subcategoria")
        )
        grupos[chave].append(
            nome_exibicao(item.get("nome", ""))
        )

    return [
        (TITULOS_GRUPO[chave], sorted(grupos[chave]))
        for chave in ORDEM_GRUPOS
        if grupos[chave]
    ]


def renderizar_catalogo(livres_df):
    """
    Catálogo com kit, busca e filtro. Fica FORA de qualquer st.form
    para atualizar a tela na hora. Retorna (nomes, resumo).
    """
    st.subheader("🎠 Escolha seus brinquedos")

    if livres_df.empty:
        st.info(
            "Todos os brinquedos estão reservados "
            "nessa data."
        )
        st.session_state.brinquedos_sel = set()
        st.session_state.pre_confirm_kit = None
        return [], []

    css_catalogo()

    df_cat = livres_df.copy()

    for campo in ["categoria", "subcategoria", "imagem_url"]:
        if campo not in df_cat.columns:
            df_cat[campo] = ""

    df_cat["grupo"] = [
        chave_grupo(c, s)
        for c, s in zip(df_cat["categoria"], df_cat["subcategoria"])
    ]

    df_cat["ordem_grupo"] = df_cat["grupo"].apply(
        ORDEM_GRUPOS.index
    )

    df_cat = df_cat.sort_values(
        ["ordem_grupo", "nome"]
    ).reset_index(drop=True)

    # Se a data mudou, remove da seleção o que ficou indisponível
    nomes_livres = set(df_cat["nome"])
    st.session_state.brinquedos_sel = (
        st.session_state.brinquedos_sel & nomes_livres
    )
    selecionados = st.session_state.brinquedos_sel

    # Contagem de selecionados por grupo
    selec_por_grupo = {chave: 0 for chave in ORDEM_GRUPOS}
    for _, linha in df_cat.iterrows():
        if linha["nome"] in selecionados:
            selec_por_grupo[linha["grupo"]] += 1

    grupos_existentes = [
        chave for chave in ORDEM_GRUPOS
        if (df_cat["grupo"] == chave).any()
    ]

    # ---- Kit (apenas orientação) ----
    st.markdown("**🎁 Qual kit você pretende fechar?**")

    chave_kit = st.radio(
        "Kit",
        options=list(KITS.keys()),
        format_func=rotulo_kit,
        key="kit_escolhido",
        label_visibility="collapsed",
    )

    if chave_kit != "LIVRE":
        resumo_kit = montar_resumo_kit(chave_kit, selec_por_grupo)
        mostrar_painel_kit(resumo_kit)
        st.session_state.pre_confirm_kit = resumo_kit
    else:
        st.session_state.pre_confirm_kit = None

        if selecionados:
            mostrar_contador_livre(len(selecionados))

    # ---- Busca por nome ----
    busca = st.text_input(
        "🔎 Buscar brinquedo pelo nome",
        key="busca_brinquedo",
        placeholder="Ex.: pikler, mercadinho... (digite e aperte Enter)",
    )

    termo = normalizar_nome(busca)

    # ---- Filtro por tamanho ----
    opcoes_filtro = ["TODOS"] + grupos_existentes

    if st.session_state.get("filtro_brinquedos") not in opcoes_filtro:
        st.session_state["filtro_brinquedos"] = "TODOS"

    def rotulo_filtro(chave):
        if chave == "TODOS":
            total = len(selecionados)
            qtd = len(df_cat)
            texto = f"Todos ({qtd})"
            return f"{texto} ✓{total}" if total else texto

        qtd = int((df_cat["grupo"] == chave).sum())
        texto = f"{TITULOS_FILTRO[chave]} ({qtd})"
        marcados = selec_por_grupo.get(chave, 0)

        if chave_kit != "LIVRE" and chave in ("G", "M", "P"):
            return f"{texto} ✓{marcados}/{KITS[chave_kit][chave]}"

        return f"{texto} ✓{marcados}" if marcados else texto

    filtro = st.radio(
        "Filtrar por tamanho:",
        options=opcoes_filtro,
        format_func=rotulo_filtro,
        horizontal=True,
        key="filtro_brinquedos",
    )

    if selecionados:
        st.caption(
            f"✅ {len(selecionados)} brinquedo(s) selecionado(s). "
            "Toque na foto para escolher ou desmarcar; "
            "os escolhidos ficam com borda vermelha."
        )
    else:
        st.caption(
            "Toque na foto do brinquedo para escolher."
        )

    # ---- O que mostrar: busca (todos os tamanhos) ou filtro ----
    if termo:
        df_view = df_cat[
            df_cat["nome"].apply(
                lambda n: termo in normalizar_nome(nome_exibicao(n))
            )
        ]
        grupos_mostrar = [
            chave for chave in ORDEM_GRUPOS
            if (df_view["grupo"] == chave).any()
        ]
        titulo_sempre = True

        if df_view.empty:
            st.warning(
                f"Nenhum brinquedo disponível com “{busca.strip()}”."
            )
        else:
            st.caption(
                f"🔎 {len(df_view)} resultado(s) para “{busca.strip()}” "
                "(a busca mostra todos os tamanhos). "
                "Apague o texto para voltar ao filtro."
            )
    else:
        df_view = df_cat
        grupos_mostrar = (
            grupos_existentes if filtro == "TODOS" else [filtro]
        )
        titulo_sempre = filtro == "TODOS"

    for chave in grupos_mostrar:
        grupo = df_view[df_view["grupo"] == chave]

        if titulo_sempre or chave == "OUT":
            st.markdown(f"**{TITULOS_GRUPO[chave]}**")

        renderizar_grade(grupo)

    itens = [
        nome for nome in df_cat["nome"]
        if nome in selecionados
    ]

    resumo = [
        {
            "nome": linha["nome"],
            "categoria": texto_seguro(linha["categoria"]),
            "subcategoria": texto_seguro(linha["subcategoria"]),
        }
        for _, linha in df_cat.iterrows()
        if linha["nome"] in selecionados
    ]

    return itens, resumo


# =========================================================
# FUNÇÕES DA IMPORTAÇÃO TEMPORÁRIA DO GOOGLE FORMS
# =========================================================
def ler_excel_google_forms(arquivo):
    """
    Lê o arquivo apenas em memória.
    O arquivo não é salvo no servidor nem no Supabase.
    """
    try:
        excel = pd.ExcelFile(
            arquivo,
            engine="openpyxl"
        )

        nome_aba = None

        for aba in excel.sheet_names:
            if normalizar_titulo_coluna(aba) == normalizar_titulo_coluna(
                "Respostas ao formulário 1"
            ):
                nome_aba = aba
                break

        # Caso a aba tenha outro nome, usa a primeira
        if nome_aba is None:
            nome_aba = excel.sheet_names[0]

        df = pd.read_excel(
            arquivo,
            sheet_name=nome_aba,
            dtype=object,
            engine="openpyxl"
        )

        df.columns = [
            str(coluna).strip()
            for coluna in df.columns
        ]

        df = df.dropna(
            how="all"
        ).reset_index(drop=True)

        return df

    except Exception as erro:
        raise RuntimeError(
            f"Não foi possível ler o Excel: {erro}"
        )


def preparar_lista_google_forms(df_original):
    """
    Cria uma tabela de apoio para pesquisa e seleção.
    Os dados originais permanecem no DataFrame.
    """
    df = df_original.copy()

    coluna_carimbo = localizar_coluna(
        df,
        [
            "Carimbo de data/hora",
            "Timestamp",
        ]
    )

    coluna_nome = localizar_coluna(
        df,
        [
            "Nome completo:",
            "Nome completo",
            "Nome",
        ]
    )

    coluna_telefone = localizar_coluna(
        df,
        [
            "Número de telefone:",
            "Número de telefone",
            "Telefone",
        ]
    )

    coluna_cpf = localizar_coluna(
        df,
        [
            "CPF:",
            "CPF",
        ]
    )

    coluna_data_evento = localizar_coluna(
        df,
        [
            "Data do evento:",
            "Data do evento",
        ]
    )

    df["_forms_indice_original"] = df.index

    if coluna_carimbo:
        df["_forms_carimbo"] = df[
            coluna_carimbo
        ].apply(converter_carimbo_data_hora)
    else:
        df["_forms_carimbo"] = pd.NaT

    def criar_rotulo(linha):
        nome = valor_para_texto(
            obter_valor_linha(
                linha,
                coluna_nome
            )
        )

        telefone = formatar_telefone_importado(
            obter_valor_linha(
                linha,
                coluna_telefone
            )
        )

        data_evento = converter_data_excel(
            obter_valor_linha(
                linha,
                coluna_data_evento
            )
        )

        if data_evento:
            data_texto = data_evento.strftime(
                "%d/%m/%Y"
            )
        else:
            data_texto = "Data não identificada"

        cpf = formatar_cpf_importado(
            obter_valor_linha(
                linha,
                coluna_cpf
            )
        )

        partes = []

        if nome:
            partes.append(nome)
        else:
            partes.append("Cliente sem nome")

        if data_texto:
            partes.append(f"Evento: {data_texto}")

        if telefone:
            partes.append(f"Tel: {telefone}")

        if cpf:
            partes.append(f"CPF: {cpf}")

        return " | ".join(partes)

    df["_forms_rotulo"] = df.apply(
        criar_rotulo,
        axis=1
    )

    df["_forms_pesquisa"] = df[
        "_forms_rotulo"
    ].fillna("").astype(str).apply(
        normalizar_nome
    )

    df = df.sort_values(
        by="_forms_carimbo",
        ascending=False,
        na_position="last"
    ).reset_index(drop=True)

    return df


def carregar_cliente_forms_no_session_state(linha):
    """
    Mapeia os campos do Google Forms para os campos atuais
    do formulário de pré-reserva.
    """
    df_origem = st.session_state.df_google_forms

    coluna_nome = localizar_coluna(
        df_origem,
        ["Nome completo:", "Nome completo", "Nome"]
    )

    coluna_telefone = localizar_coluna(
        df_origem,
        [
            "Número de telefone:",
            "Número de telefone",
            "Telefone",
        ]
    )

    coluna_email = localizar_coluna(
        df_origem,
        [
            "E-mail",
            "Email",
            "Endereço de e-mail",
        ]
    )

    coluna_rg = localizar_coluna(
        df_origem,
        ["RG:", "RG"]
    )

    coluna_cpf = localizar_coluna(
        df_origem,
        ["CPF:", "CPF"]
    )

    coluna_endereco = localizar_coluna(
        df_origem,
        [
            "Endereço do evento:",
            "Endereço do evento",
        ]
    )

    coluna_cidade = localizar_coluna(
        df_origem,
        [
            "Cidade do evento:",
            "Cidade do evento",
            "Cidade",
        ]
    )

    coluna_cep = localizar_coluna(
        df_origem,
        [
            "CEP do evento:",
            "CEP do evento",
            "CEP",
        ]
    )

    coluna_data_evento = localizar_coluna(
        df_origem,
        [
            "Data do evento:",
            "Data do evento",
        ]
    )

    coluna_hora_inicio = localizar_coluna(
        df_origem,
        [
            "Horário previsto do início do evento:",
            "Horário previsto do início do evento",
        ]
    )

    coluna_ocasiao = localizar_coluna(
        df_origem,
        [
            "Ocasião (Festa infantil, festa adulto, chá de bebê, corporativo, etc):",
            "Ocasião",
        ]
    )

    coluna_tema = localizar_coluna(
        df_origem,
        ["Tema:", "Tema"]
    )

    coluna_nome_aniv = localizar_coluna(
        df_origem,
        [
            "Nome do aniversariante (Se houver)",
            "Nome do aniversariante",
        ]
    )

    coluna_idade = localizar_coluna(
        df_origem,
        [
            "Idade da criança ou adulto:",
            "Idade da criança ou adulto",
            "Idade",
        ]
    )

    coluna_como = localizar_coluna(
        df_origem,
        [
            "Como conheceu a Timtim festas?",
            "Como conheceu a TimTim Festas?",
            "Como conheceu a empresa?",
        ]
    )

    coluna_atendimento = localizar_coluna(
        df_origem,
        [
            "O que achou do atendimento inicial?",
            "O que achou do atendimento inicial",
        ]
    )

    nome = valor_para_texto(
        obter_valor_linha(
            linha,
            coluna_nome
        )
    )

    telefone = formatar_telefone_importado(
        obter_valor_linha(
            linha,
            coluna_telefone
        )
    )

    email = valor_para_texto(
        obter_valor_linha(
            linha,
            coluna_email
        )
    )

    rg = formatar_rg_importado(
        obter_valor_linha(
            linha,
            coluna_rg
        )
    )

    cpf = formatar_cpf_importado(
        obter_valor_linha(
            linha,
            coluna_cpf
        )
    )

    endereco = valor_para_texto(
        obter_valor_linha(
            linha,
            coluna_endereco
        )
    )

    cidade = valor_para_texto(
        obter_valor_linha(
            linha,
            coluna_cidade
        )
    )

    cep = formatar_cep_importado(
        obter_valor_linha(
            linha,
            coluna_cep
        )
    )

    data_evento_importada = converter_data_excel(
        obter_valor_linha(
            linha,
            coluna_data_evento
        )
    )

    hora_inicio_importada = converter_hora_excel(
        obter_valor_linha(
            linha,
            coluna_hora_inicio
        )
    )

    ocasiao = valor_para_texto(
        obter_valor_linha(
            linha,
            coluna_ocasiao
        )
    )

    tema = valor_para_texto(
        obter_valor_linha(
            linha,
            coluna_tema
        )
    )

    nome_aniv = valor_para_texto(
        obter_valor_linha(
            linha,
            coluna_nome_aniv
        )
    )

    idade = valor_para_texto(
        obter_valor_linha(
            linha,
            coluna_idade
        )
    )

    como_original = valor_para_texto(
        obter_valor_linha(
            linha,
            coluna_como
        )
    )

    atendimento = valor_para_texto(
        obter_valor_linha(
            linha,
            coluna_atendimento
        )
    )

    opcoes_como = [
        "Indicação",
        "Instagram",
        "Facebook",
        "Google",
        "WhatsApp",
        "Outro",
    ]

    como_normalizado = normalizar_nome(
        como_original
    )

    if "indicacao" in como_normalizado:
        como = "Indicação"
    elif "instagram" in como_normalizado:
        como = "Instagram"
    elif "facebook" in como_normalizado:
        como = "Facebook"
    elif "google" in como_normalizado:
        como = "Google"
    elif "whatsapp" in como_normalizado:
        como = "WhatsApp"
    else:
        como = "Outro"

    if como not in opcoes_como:
        como = "Outro"

    observacoes = []

    if atendimento:
        observacoes.append(
            f"Avaliação do atendimento inicial: {atendimento}"
        )

    if como_original and como == "Outro":
        observacoes.append(
            f"Como conheceu a empresa: {como_original}"
        )

    # Carrega os campos no session_state.
    # Esses dados continuam editáveis.
    st.session_state["form_nome"] = nome
    st.session_state["form_telefone"] = telefone
    st.session_state["form_email"] = email
    st.session_state["form_rg"] = rg
    st.session_state["form_cpf"] = cpf
    st.session_state["form_como"] = como
    st.session_state["form_cep"] = cep
    st.session_state["logradouro"] = endereco
    st.session_state["bairro"] = ""
    st.session_state["cidade"] = cidade
    st.session_state["form_numero"] = ""
    st.session_state["form_complemento"] = ""
    st.session_state["form_observacao"] = "\n".join(
        observacoes
    )
    st.session_state["form_ocasiao"] = ocasiao
    st.session_state["form_tema"] = tema
    st.session_state["form_nome_aniv"] = nome_aniv
    st.session_state["form_idade"] = idade

    st.session_state.aviso_data_passada = ""

    if data_evento_importada:
        if data_evento_importada >= date.today():
            st.session_state["data_evento_publico"] = (
                data_evento_importada
            )
        else:
            st.session_state.aviso_data_passada = (
                "A data do cadastro importado "
                f"({data_evento_importada.strftime('%d/%m/%Y')}) "
                "já passou. Escolha a data correta do evento."
            )

    if hora_inicio_importada:
        st.session_state["form_hora_inicio"] = (
            hora_inicio_importada
        )
    else:
        st.session_state["form_hora_inicio"] = dtime(
            13,
            0
        )

    # Define hora final padrão quatro horas depois,
    # mas continua totalmente editável.
    if hora_inicio_importada:
        total_minutos = min(
            hora_inicio_importada.hour * 60
            + hora_inicio_importada.minute
            + 240,
            23 * 60 + 59
        )

        st.session_state["form_hora_fim"] = dtime(
            total_minutos // 60,
            total_minutos % 60
        )
    else:
        st.session_state["form_hora_fim"] = dtime(
            17,
            0
        )

    st.session_state.cliente_importado = True


def limpar_cliente_importado():
    chaves = [
        "form_nome",
        "form_telefone",
        "form_email",
        "form_rg",
        "form_cpf",
        "form_como",
        "form_cep",
        "logradouro",
        "bairro",
        "cidade",
        "form_numero",
        "form_complemento",
        "form_observacao",
        "form_ocasiao",
        "form_tema",
        "form_nome_aniv",
        "form_idade",
        "form_hora_inicio",
        "form_hora_fim",
        "form_brinquedos",
    ]

    for chave in chaves:
        if chave in st.session_state:
            del st.session_state[chave]

    for chave in list(st.session_state.keys()):
        if str(chave).startswith("brq_"):
            del st.session_state[chave]

    for chave in ["busca_brinquedo", "filtro_brinquedos", "kit_escolhido"]:
        if chave in st.session_state:
            del st.session_state[chave]

    st.session_state.brinquedos_sel = set()
    st.session_state.cliente_importado = False
    st.session_state.forms_registro_selecionado = None


def formatar_data_br(valor) -> str:
    try:
        return datetime.strptime(
            str(valor)[:10],
            "%Y-%m-%d"
        ).strftime("%d/%m/%Y")
    except Exception:
        return str(valor)


# =========================================================
# DIALOG DE CONFIRMAÇÃO
# =========================================================
@st.dialog(
    "Confirmar solicitação",
    width="large"
)
def open_confirm_dialog():
    reg = st.session_state.get(
        "pre_confirm_payload"
    ) or {}

    st.markdown(
        "Confira as informações antes de enviar:"
    )

    colA, colB = st.columns(2)

    with colA:
        st.markdown(
            "**Data do evento:** "
            + formatar_data_br(reg.get("data", ""))
        )

        st.markdown(
            "**Horário:** "
            + (
                f"{str(reg.get('hora_inicio', ''))[:5]} "
                f"às {str(reg.get('hora_fim', ''))[:5]}"
            )
        )

        st.markdown(
            "**Cliente:** "
            + (reg.get("nome") or "")
        )

        st.markdown(
            "**Contato:** "
            + (reg.get("telefone") or "")
        )

        st.markdown(
            "**CPF:** "
            + (reg.get("cpf") or "")
        )

    with colB:
        endereco_confirmacao = " ".join(
            [
                str(reg.get("logradouro") or ""),
                str(reg.get("numero") or ""),
                str(reg.get("bairro") or ""),
                str(reg.get("cidade") or ""),
                str(reg.get("cep") or ""),
            ]
        ).strip()

        st.markdown(
            "**Endereço:** "
            + endereco_confirmacao
        )

    resumo = st.session_state.get("pre_confirm_resumo") or []
    kit_info = st.session_state.get("pre_confirm_kit_dialog")

    if kit_info:
        st.markdown(
            f"**🎁 {kit_info['nome']}** · "
            + " · ".join(
                f"{l['sub']} {l['atual']}/{l['meta']}"
                for l in kit_info["linhas"]
            )
            + f" · Total {kit_info['atual_total']}"
            f"/{kit_info['meta_total']}"
        )

    if resumo:
        st.markdown(
            f"**🎠 Brinquedos selecionados "
            f"({len(resumo)}):**"
        )

        for titulo, nomes in agrupar_para_resumo(resumo):
            st.markdown(f"**{titulo}** · {len(nomes)}")
            st.markdown(
                "\n".join(f"- {n}" for n in nomes)
            )

    elif reg.get("brinquedos"):
        st.markdown(
            "**🎠 Brinquedos selecionados:**"
        )

        itens = [
            item.strip()
            for item in str(
                reg.get("brinquedos")
            ).split(",")
            if item.strip()
        ]

        st.write(", ".join(itens))

    else:
        st.markdown(
            "**🎠 Brinquedos selecionados:**"
        )
        st.write("—")

    if reg.get("observacao"):
        st.markdown(
            "**Observação:**"
        )
        st.write(
            reg.get("observacao")
        )

    colC1, colC2 = st.columns(2)

    confirmar = colC1.button(
        "✅ Confirmar envio",
        type="primary",
        use_container_width=True
    )

    voltar = colC2.button(
        "🔙 Voltar e editar",
        use_container_width=True
    )

    if confirmar:
        id_envio = reg.get("id")
        ids_enviados = st.session_state.ids_enviados

        # Se o mesmo envio já foi iniciado (duplo clique), ignora.
        if id_envio in ids_enviados:
            st.session_state.pre_confirm_payload = None
            st.session_state.show_confirm_dialog = False
            st.rerun()

        # Marca ANTES de gravar para bloquear um segundo clique.
        ids_enviados.add(id_envio)

        try:
            table_insert(
                "pre_reservas",
                [reg]
            )

            st.session_state.assinaturas_enviadas.add(
                st.session_state.get("assinatura_pendente", "")
            )
            st.session_state.pre_confirm_payload = None
            st.session_state.show_confirm_dialog = False
            st.session_state.pre_success = True
            st.session_state.pre_success_msg = (
                "✅ Pré-reserva enviada com sucesso!"
            )

        except Exception as erro:
            # Falhou: libera para tentar de novo.
            ids_enviados.discard(id_envio)
            st.session_state.pre_confirm_payload = None
            st.session_state.show_confirm_dialog = False
            st.session_state.pre_success = True
            st.session_state.pre_success_msg = (
                f"❌ Erro ao enviar: {erro}"
            )

        st.rerun()

    if voltar:
        st.session_state.pre_confirm_payload = None
        st.session_state.show_confirm_dialog = False
        st.rerun()


# =========================================================
# FEEDBACK APÓS CONFIRMAR
# =========================================================
if st.session_state.pre_success:
    mensagem = (
        st.session_state.pre_success_msg
        or "Operação concluída."
    )

    if mensagem.startswith("✅"):
        st.success(mensagem)
        st.balloons()

    elif mensagem.startswith("❌"):
        st.error(mensagem)

    else:
        st.info(mensagem)

    st.session_state.pre_success = False
    st.session_state.pre_success_msg = ""


# =========================================================
# IMPORTAÇÃO ADMINISTRATIVA TEMPORÁRIA
# =========================================================
with st.expander(
    "🔐 Importar cadastro do Google Forms",
    expanded=False
):
    st.caption(
        "Área administrativa. O arquivo é usado apenas "
        "temporariamente para preencher o formulário."
    )

    if not st.session_state.importacao_autorizada:
        senha_digitada = st.text_input(
            "Senha administrativa",
            type="password",
            key="senha_importacao_digitada"
        )

        col_senha1, col_senha2 = st.columns(
            [1, 2]
        )

        with col_senha1:
            entrar_importacao = st.button(
                "🔓 Entrar",
                use_container_width=True
            )

        if entrar_importacao:
            senha_configurada = st.secrets.get(
                "SENHA_IMPORTACAO",
                ""
            )

            if not senha_configurada:
                st.error(
                    "❌ A senha de importação ainda não "
                    "foi configurada nos Secrets."
                )

            elif senha_digitada == senha_configurada:
                st.session_state.importacao_autorizada = True
                st.rerun()

            else:
                st.error(
                    "❌ Senha incorreta."
                )

    else:
        col_admin1, col_admin2 = st.columns(
            [3, 1]
        )

        with col_admin1:
            st.success(
                "✅ Modo de importação autorizado"
            )

        with col_admin2:
            if st.button(
                "🔒 Sair",
                use_container_width=True
            ):
                st.session_state.importacao_autorizada = False
                st.session_state.df_google_forms = None
                st.session_state.arquivo_forms_nome = None
                st.session_state.forms_registro_selecionado = None
                st.rerun()

        arquivo_forms = st.file_uploader(
            "Selecione o Excel baixado do Google Forms",
            type=["xlsx"],
            key="arquivo_google_forms"
        )

        if arquivo_forms is not None:
            nome_arquivo_atual = arquivo_forms.name

            if (
                st.session_state.arquivo_forms_nome
                != nome_arquivo_atual
                or st.session_state.df_google_forms is None
            ):
                try:
                    df_lido = ler_excel_google_forms(
                        arquivo_forms
                    )

                    st.session_state.df_google_forms = df_lido
                    st.session_state.arquivo_forms_nome = (
                        nome_arquivo_atual
                    )

                except Exception as erro:
                    st.error(
                        f"❌ {erro}"
                    )

            df_forms_original = (
                st.session_state.df_google_forms
            )

            if (
                df_forms_original is not None
                and not df_forms_original.empty
            ):
                try:
                    df_forms_lista = (
                        preparar_lista_google_forms(
                            df_forms_original
                        )
                    )

                    st.success(
                        f"✅ {len(df_forms_lista)} resposta(s) "
                        "encontrada(s) no arquivo."
                    )

                    termo_pesquisa = st.text_input(
                        "🔎 Pesquisar por nome, telefone, CPF ou data",
                        key="pesquisa_cliente_forms"
                    )

                    if termo_pesquisa:
                        termo_normalizado = normalizar_nome(
                            termo_pesquisa
                        )

                        df_forms_lista = df_forms_lista[
                            df_forms_lista[
                                "_forms_pesquisa"
                            ].str.contains(
                                termo_normalizado,
                                na=False,
                                regex=False
                            )
                        ]

                    if df_forms_lista.empty:
                        st.warning(
                            "⚠️ Nenhum cliente encontrado "
                            "com essa pesquisa."
                        )

                    else:
                        opcoes_clientes = (
                            df_forms_lista[
                                "_forms_indice_original"
                            ].tolist()
                        )

                        mapa_rotulos = dict(
                            zip(
                                df_forms_lista[
                                    "_forms_indice_original"
                                ],
                                df_forms_lista[
                                    "_forms_rotulo"
                                ]
                            )
                        )

                        indice_escolhido = st.selectbox(
                            "Escolha o cliente para carregar:",
                            options=opcoes_clientes,
                            format_func=lambda indice: (
                                mapa_rotulos.get(
                                    indice,
                                    str(indice)
                                )
                            ),
                            key="cliente_google_forms_escolhido"
                        )

                        cliente_escolhido = (
                            df_forms_original.loc[
                                indice_escolhido
                            ]
                        )

                        st.markdown(
                            "#### Prévia do cadastro"
                        )

                        coluna_nome_preview = localizar_coluna(
                            df_forms_original,
                            ["Nome completo:", "Nome completo"]
                        )

                        coluna_telefone_preview = localizar_coluna(
                            df_forms_original,
                            [
                                "Número de telefone:",
                                "Número de telefone",
                            ]
                        )

                        coluna_data_preview = localizar_coluna(
                            df_forms_original,
                            [
                                "Data do evento:",
                                "Data do evento",
                            ]
                        )

                        nome_preview = valor_para_texto(
                            obter_valor_linha(
                                cliente_escolhido,
                                coluna_nome_preview
                            )
                        )

                        telefone_preview = (
                            formatar_telefone_importado(
                                obter_valor_linha(
                                    cliente_escolhido,
                                    coluna_telefone_preview
                                )
                            )
                        )

                        data_preview = converter_data_excel(
                            obter_valor_linha(
                                cliente_escolhido,
                                coluna_data_preview
                            )
                        )

                        st.write(
                            f"👤 Cliente: {nome_preview or 'Não informado'}"
                        )

                        st.write(
                            f"📞 Telefone: {telefone_preview or 'Não informado'}"
                        )

                        if data_preview:
                            st.write(
                                "📅 Evento: "
                                + data_preview.strftime(
                                    "%d/%m/%Y"
                                )
                            )
                        else:
                            st.warning(
                                "⚠️ A data do evento não pôde "
                                "ser identificada. Confira o "
                                "campo manualmente."
                            )

                        if st.button(
                            "📋 Carregar cliente no formulário",
                            type="primary",
                            use_container_width=True
                        ):
                            carregar_cliente_forms_no_session_state(
                                cliente_escolhido
                            )

                            st.session_state.forms_registro_selecionado = (
                                indice_escolhido
                            )

                            st.rerun()

                except Exception as erro:
                    st.error(
                        "❌ Erro ao preparar os registros "
                        f"do Google Forms: {erro}"
                    )

            elif df_forms_original is not None:
                st.warning(
                    "⚠️ O arquivo não possui registros."
                )


# =========================================================
# AVISO DE CLIENTE IMPORTADO
# =========================================================
if st.session_state.cliente_importado:
    st.success(
        "✅ Dados do Google Forms carregados. "
        "Confira e complete o formulário abaixo."
    )

    if st.button(
        "🧹 Limpar dados importados"
    ):
        limpar_cliente_importado()
        st.rerun()


# =========================================================
# DATA FORA DO FORM
# =========================================================
st.subheader("🎉 Escolha a data do evento")

# Datas anteriores a hoje não podem ser escolhidas
_data_atual = st.session_state.get("data_evento_publico")

if _data_atual is not None and _data_atual < date.today():
    st.session_state["data_evento_publico"] = date.today()

data_evento = st.date_input(
    "Data do evento*",
    value=st.session_state.get(
        "data_evento_publico",
        date.today()
    ),
    min_value=date.today(),
    format="DD/MM/YYYY",
    key="data_evento_publico"
)

if st.session_state.get("aviso_data_passada"):
    st.warning(
        "⚠️ " + st.session_state.aviso_data_passada
    )


# =========================================================
# DISPONIBILIDADE DOS BRINQUEDOS
# =========================================================
reservas_df = carregar_reservas_do_dia(
    data_evento
)

ocupados = ocupados_no_dia(
    reservas_df
)

brinquedos_df = carregar_brinquedos()

if not brinquedos_df.empty:
    brinquedos_df["nome_norm"] = (
        brinquedos_df["nome"].apply(
            normalizar_nome
        )
    )

    livres_df = brinquedos_df[
        ~brinquedos_df["nome_norm"].isin(
            ocupados
        )
    ]

else:
    livres_df = brinquedos_df


# =========================================================
# DADOS DO CLIENTE (logo após a data)
# =========================================================
st.subheader("👤 Seus dados")

col1, col2 = st.columns(2)

with col1:
    nome = st.text_input(
        "Nome do cliente*",
        key="form_nome"
    )

    telefone_raw = st.text_input(
        "Telefone (somente números)*",
        key="form_telefone"
    )

    email = st.text_input(
        "Email",
        key="form_email"
    )

    rg = st.text_input(
        "RG",
        key="form_rg"
    )

    cpf = st.text_input(
        "CPF",
        key="form_cpf"
    )

    opcoes_como = [
        "Indicação",
        "Instagram",
        "Facebook",
        "Google",
        "WhatsApp",
        "Outro",
    ]

    valor_como_atual = st.session_state.get(
        "form_como",
        "Indicação"
    )

    if valor_como_atual not in opcoes_como:
        valor_como_atual = "Outro"

    como = st.selectbox(
        "Como conheceu a empresa?",
        options=opcoes_como,
        index=opcoes_como.index(
            valor_como_atual
        ),
        key="form_como"
    )

with col2:
    cep = st.text_input(
        "CEP",
        key="form_cep"
    )

    buscar = st.button(
        "🔎 Buscar CEP"
    )

    if buscar:
        dados_cep = via_cep(
            cep
        )

        if dados_cep:
            st.session_state["logradouro"] = (
                dados_cep["logradouro"]
            )

            st.session_state["bairro"] = (
                dados_cep["bairro"]
            )

            st.session_state["cidade"] = (
                dados_cep["cidade"]
            )

        else:
            st.warning(
                "⚠️ CEP não encontrado. "
                "Preencha o endereço manualmente."
            )

    logradouro = st.text_input(
        "Logradouro",
        key="logradouro"
    )

    numero = st.text_input(
        "Número",
        key="form_numero"
    )

    complemento = st.text_input(
        "Complemento",
        key="form_complemento"
    )

    bairro = st.text_input(
        "Bairro",
        key="bairro"
    )

    cidade = st.text_input(
        "Cidade",
        key="cidade"
    )

st.subheader("🎉 Informações do Evento")

ocasiao = st.text_input(
    (
        "Ocasião (Festa infantil, festa adulto, "
        "chá de bebê, corporativo, etc):"
    ),
    key="form_ocasiao"
)

tema = st.text_input(
    "Tema:",
    key="form_tema"
)

nome_aniv = st.text_input(
    "Nome do aniversariante (Se houver):",
    key="form_nome_aniv"
)

idade = st.text_input(
    "Idade da criança ou adulto:",
    key="form_idade"
)

observacao = st.text_area(
    "Observação",
    key="form_observacao"
)

st.subheader("⏰ Horário")

col3, col4 = st.columns(2)

with col3:
    hora_inicio = st.time_input(
        "Horário início",
        value=st.session_state.get(
            "form_hora_inicio",
            dtime(13, 0)
        ),
        key="form_hora_inicio"
    )

with col4:
    hora_fim = st.time_input(
        "Horário fim",
        value=st.session_state.get(
            "form_hora_fim",
            dtime(17, 0)
        ),
        key="form_hora_fim"
    )

if hora_fim <= hora_inicio:
    st.warning(
        "⚠️ O horário de fim precisa ser depois do horário de início."
    )


# =========================================================
# BRINQUEDOS (depois dos dados do cliente)
# =========================================================
itens_selecionados, resumo_selecionados = renderizar_catalogo(
    livres_df
)

st.divider()

enviar_clicado = st.button(
    "💾 Enviar solicitação",
    type="primary",
    use_container_width=True
)


# =========================================================
# VALIDAR E PREPARAR PAYLOAD
# =========================================================
if enviar_clicado:
    erros = []

    if not nome:
        erros.append(
            "Informe seu nome."
        )

    if not telefone_raw:
        erros.append(
            "Informe o telefone."
        )

    if not itens_selecionados:
        erros.append(
            "Selecione pelo menos 1 brinquedo."
        )

    if data_evento < date.today():
        erros.append(
            "A data do evento não pode ser anterior a hoje."
        )

    if hora_fim <= hora_inicio:
        erros.append(
            "O horário de fim precisa ser depois do horário de início."
        )

    if erros:
        st.error(
            "⚠️ Corrija os campos:\n\n- "
            + "\n- ".join(erros)
        )

        st.stop()

    telefone = re.sub(
        r"\D",
        "",
        telefone_raw
    )

    brinquedos_texto = ", ".join(
        itens_selecionados
    )

    assinatura = "|".join(
        [
            telefone,
            str(data_evento),
            str(hora_inicio),
            brinquedos_texto,
        ]
    )

    if assinatura in st.session_state.assinaturas_enviadas:
        st.warning(
            "ℹ️ Esta solicitação já foi enviada. "
            "Se precisar alterar algo, altere os dados antes "
            "de enviar novamente."
        )
        st.stop()

    st.session_state.assinatura_pendente = assinatura

    st.session_state.pre_confirm_payload = {
        "id": str(uuid4()),
        "nome": nome.strip(),
        "telefone": telefone,
        "email": email,
        "rg": rg,
        "cpf": cpf,
        "como_conheceu": como,
        "cep": cep,
        "logradouro": logradouro,
        "numero": numero,
        "complemento": complemento,
        "bairro": bairro,
        "cidade": cidade,
        "observacao": observacao,
        "data": str(data_evento),
        "hora_inicio": str(hora_inicio),
        "hora_fim": str(hora_fim),
        "brinquedos": brinquedos_texto,
        "ocasiao": ocasiao,
        "tema": tema,
        "nome_aniv": nome_aniv,
        "idade": idade,
    }

    st.session_state.pre_confirm_resumo = resumo_selecionados

    kit_atual = st.session_state.get("pre_confirm_kit")
    st.session_state.pre_confirm_kit_dialog = kit_atual

    if kit_atual:
        obs_base = (
            st.session_state.pre_confirm_payload.get("observacao")
            or ""
        ).strip()

        linha_kit = f"[Kit pretendido] {kit_atual['texto']}"

        st.session_state.pre_confirm_payload["observacao"] = (
            f"{obs_base}\n{linha_kit}".strip()
        )

    st.session_state.show_confirm_dialog = True

    st.rerun()


# =========================================================
# ABRIR MODAL
# =========================================================
if (
    st.session_state.show_confirm_dialog
    and st.session_state.pre_confirm_payload
):
    open_confirm_dialog()
