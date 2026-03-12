import re
from uuid import uuid4
from datetime import date, time as dtime

import pandas as pd
import requests
import streamlit as st

from supabase_rest import table_select, table_insert


# =========================
# CONFIG
# =========================
st.set_page_config(
    page_title="Solicite sua Festa | TimTim Festas",
    page_icon="🎈",
    layout="centered",
)

st.markdown("<h2 style='text-align:center'>🎈 Cadastro</h2>", unsafe_allow_html=True)


# =========================
# FUNÇÕES AUXILIARES
# =========================
def normalizar_nome(txt: str) -> str:
    if not isinstance(txt, str):
        return ""
    import unicodedata
    t = unicodedata.normalize("NFKD", txt).encode("ascii", "ignore").decode("utf-8")
    t = re.sub(r"[^a-zA-Z0-9]+", " ", t)
    return t.strip().lower()


def via_cep(cep: str):
    try:
        cep_num = re.sub(r"\D", "", str(cep))[:8]
        if len(cep_num) != 8:
            return None
        r = requests.get(f"https://viacep.com.br/ws/{cep_num}/json/", timeout=8)
        if r.status_code == 200 and "erro" not in r.json():
            j = r.json()
            return {
                "logradouro": j.get("logradouro", ""),
                "bairro": j.get("bairro", ""),
                "cidade": j.get("localidade", ""),
            }
    except:
        pass
    return None


def carregar_brinquedos():
    rows = table_select(
        "brinquedos",
        select="nome,status",
        where={"status": "Disponível"},
        order=("nome", "asc"),
    )
    return pd.DataFrame(rows) if rows else pd.DataFrame(columns=["nome", "status"])


def carregar_reservas_do_dia(d):
    rows = table_select("reservas", select="data,brinquedos", where={"data": str(d)})
    return pd.DataFrame(rows) if rows else pd.DataFrame(columns=["data", "brinquedos"])


def ocupados_no_dia(df):
    ocupados = set()
    for _, r in df.iterrows():
        for pedaco in str(r.get("brinquedos", "")).split(","):
            nome = pedaco.strip()
            if nome:
                ocupados.add(normalizar_nome(nome))
    return ocupados


# =========================
# DATA FORA DO FORM
# =========================
st.subheader("🎉 Escolha a data do evento")

data_evento = st.date_input(
    "Data do evento*",
    value=date.today(),
    key="data_evento_publico"
)

reservas_df = carregar_reservas_do_dia(data_evento)
ocupados = ocupados_no_dia(reservas_df)

brinquedos_df = carregar_brinquedos()

if not brinquedos_df.empty:
    brinquedos_df["nome_norm"] = brinquedos_df["nome"].apply(normalizar_nome)
    livres_df = brinquedos_df[~brinquedos_df["nome_norm"].isin(ocupados)]
else:
    livres_df = brinquedos_df


# =========================
# FORM
# =========================
with st.form("form_publico"):

    st.subheader("👤 Seus dados")

    col1, col2 = st.columns(2)

    with col1:
        nome = st.text_input("Nome do cliente*")
        telefone_raw = st.text_input("Telefone (somente números)*")
        email = st.text_input("Email")
        rg = st.text_input("RG")
        cpf = st.text_input("CPF")

        # 🔥 LISTA COMO PEDIDO
        como = st.selectbox(
            "Como conheceu a empresa?",
            ["Indicação", "Instagram", "Facebook", "Google", "WhatsApp", "Outro"]
        )

    with col2:
        cep = st.text_input("CEP")
        buscar = st.form_submit_button("🔎 Buscar CEP")

        if buscar:
            dados = via_cep(cep)
            if dados:
                st.session_state["logradouro"] = dados["logradouro"]
                st.session_state["bairro"] = dados["bairro"]
                st.session_state["cidade"] = dados["cidade"]

        logradouro = st.text_input("Logradouro", value=st.session_state.get("logradouro", ""))
        numero = st.text_input("Número")
        complemento = st.text_input("Complemento")
        bairro = st.text_input("Bairro", value=st.session_state.get("bairro", ""))
        cidade = st.text_input("Cidade", value=st.session_state.get("cidade", ""))
        
        st.subheader("🎉 Informações do Evento")

        ocasiao = st.text_input("Ocasião (Festa infantil, festa adulto, chá de bebê, corporativo, etc):")
        tema = st.text_input("Tema:")
        nome_aniv = st.text_input("Nome do aniversariante (Se houver):")
        idade = st.text_input("Idade da criança ou adulto:")


    observacao = st.text_area("Observação")

    st.subheader("⏰ Horário")

    col3, col4 = st.columns(2)
    with col3:
        hora_inicio = st.time_input("Horário início", value=dtime(13, 0))
    with col4:
        hora_fim = st.time_input("Horário fim", value=dtime(17, 0))

    st.subheader("🎠 Escolha seus brinquedos")

    if livres_df.empty:
        st.info("Todos os brinquedos estão reservados nessa data.")
        itens_selecionados = []
    else:
        lista = livres_df["nome"].tolist()
        itens_selecionados = st.multiselect(
            "Brinquedos disponíveis*",
            options=lista
        )

    enviado = st.form_submit_button("💾 Enviar solicitação")


# =========================
# ENVIO
# =========================
if enviado:

    erros = []
    if not nome:
        erros.append("Informe seu nome.")
    if not telefone_raw:
        erros.append("Informe o telefone.")
    if not itens_selecionados:
        erros.append("Selecione pelo menos 1 brinquedo.")

    if erros:
        st.error("⚠️ Corrija os campos:\n\n- " + "\n- ".join(erros))
        st.stop()

    telefone = re.sub(r"\D", "", telefone_raw)

    # 🔥 Junta brinquedos igual seu app interno
    brinquedos_texto = ", ".join(itens_selecionados)

    registro = {
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
        "brinquedos": brinquedos_texto,  # 🔥 SALVA TUDO EM UMA COLUNA
                # ⭐ Novos campos
        "ocasiao": ocasiao,
        "tema": tema,
        "nome_aniv": nome_aniv,
        "idade": idade

    }

    try:
        table_insert("pre_reservas", [registro])
        st.success("✅ Solicitação enviada com sucesso!")
        st.balloons()
    except Exception as e:
        st.error(f"Erro ao enviar: {e}")
