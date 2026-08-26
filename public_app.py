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
    rows = table_select(
        "brinquedos",
        select="nome,status",
        where={"status": "Disponível"},
        order=("nome", "asc"),
    )

    if rows:
        return pd.DataFrame(rows)

    return pd.DataFrame(
        columns=["nome", "status"]
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

    if data_evento_importada:
        st.session_state["data_evento_publico"] = (
            data_evento_importada
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
        total_minutos = (
            hora_inicio_importada.hour * 60
            + hora_inicio_importada.minute
            + 240
        ) % (24 * 60)

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

    st.session_state.cliente_importado = False
    st.session_state.forms_registro_selecionado = None


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
            + str(reg.get("data", ""))
        )

        st.markdown(
            "**Horário:** "
            + (
                f"{reg.get('hora_inicio', '')} "
                f"– {reg.get('hora_fim', '')}"
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

    st.markdown(
        "**🎠 Brinquedos selecionados:**"
    )

    if reg.get("brinquedos"):
        itens = [
            item.strip()
            for item in str(
                reg.get("brinquedos")
            ).split(",")
            if item.strip()
        ]

        st.write(
            ", ".join(itens)
        )
    else:
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
        try:
            table_insert(
                "pre_reservas",
                [reg]
            )

            st.session_state.pre_confirm_payload = None
            st.session_state.show_confirm_dialog = False
            st.session_state.pre_success = True
            st.session_state.pre_success_msg = (
                "✅ Pré-reserva enviada com sucesso!"
            )

        except Exception as erro:
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

data_evento = st.date_input(
    "Data do evento*",
    value=st.session_state.get(
        "data_evento_publico",
        date.today()
    ),
    key="data_evento_publico"
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
# FORMULÁRIO PRINCIPAL
# =========================================================
with st.form("form_publico"):
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

        buscar = st.form_submit_button(
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

    st.subheader("🎠 Escolha seus brinquedos")

    if livres_df.empty:
        st.info(
            "Todos os brinquedos estão reservados "
            "nessa data."
        )

        itens_selecionados = []

    else:
        lista_brinquedos = (
            livres_df["nome"].tolist()
        )

        itens_anteriores = st.session_state.get(
            "form_brinquedos",
            []
        )

        itens_anteriores = [
            item
            for item in itens_anteriores
            if item in lista_brinquedos
        ]

        itens_selecionados = st.multiselect(
            "Brinquedos disponíveis*",
            options=lista_brinquedos,
            default=itens_anteriores,
            key="form_brinquedos"
        )

    enviar_clicado = st.form_submit_button(
        "💾 Enviar solicitação"
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
