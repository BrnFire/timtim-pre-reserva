import re
from uuid import uuid4
from datetime import date, time as dtime

import pandas as pd
import requests
import streamlit as st

# --- Nosso cliente REST leve (arquivo ao lado) ---
# Certifique-se de ter supabase_rest.py no mesmo diretório, com table_insert return=minimal
from supabase_rest import table_select, table_insert


# =========================
# Configuração básica
# =========================
st.set_page_config(
    page_title="Solicite sua Festa | TimTim Festas",
    page_icon="🎈",
    layout="centered",
)

st.markdown(
    """
    <style>
      .stForm { background: #fff; border-radius: 10px; padding: 1rem 1.25rem; border: 1px solid #EEE; }
      .label-strong { font-weight: 600; }
      .ok-badge { color:#2ecc71; }
      .warn-badge { color:#f39c12; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown("<h2 style='text-align:center'>🎈 Solicite seu orçamento</h2>", unsafe_allow_html=True)
st.caption("Preencha seus dados, escolha a data do evento e selecione os brinquedos disponíveis.")


# =========================
# Utilitários
# =========================
def normalizar_nome(txt: str) -> str:
    """Normaliza nome para comparação simples (sem acento/pontuação), igual ao seu fluxo atual."""
    if not isinstance(txt, str):
        return ""
    import unicodedata

    t = unicodedata.normalize("NFKD", txt).encode("ascii", "ignore").decode("utf-8")
    t = re.sub(r"[^a-zA-Z0-9]+", " ", t)
    return t.strip().lower()


def via_cep(cep: str):
    """Busca logradouro/bairro/cidade no ViaCEP. Retorna dict ou None."""
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
    except Exception:
        pass
    return None


def carregar_brinquedos_ativos() -> pd.DataFrame:
    """Lê 'brinquedos' (status=Disponível) para a vitrine do cliente."""
    rows = table_select(
        "brinquedos",
        select="nome,categoria,status,valor",
        where={"status": "Disponível"},
        order=("nome", "asc"),
    )
    df = pd.DataFrame(rows) if rows else pd.DataFrame(columns=["nome", "categoria", "status", "valor"])
    if "nome" not in df.columns:
        df["nome"] = ""
    if "categoria" not in df.columns:
        df["categoria"] = "Tradicional"
    if "valor" not in df.columns:
        df["valor"] = 0.0
    return df


def carregar_reservas_do_dia(d: date) -> pd.DataFrame:
    """Lê 'reservas' da data (modo simples por dia, como seu fluxo interno atual)."""
    rows = table_select("reservas", select="data,brinquedos", where={"data": str(d)})
    return pd.DataFrame(rows) if rows else pd.DataFrame(columns=["data", "brinquedos"])


def ocupados_no_dia(reservas_df: pd.DataFrame) -> set[str]:
    """Extrai nomes ocupados (normalizados) com base na coluna textual 'brinquedos'."""
    ocupados = set()
    for _, r in reservas_df.iterrows():
        for pedaco in str(r.get("brinquedos", "")).split(","):
            nome = pedaco.strip()
            if not nome:
                continue
            n = normalizar_nome(nome)
            if n:
                ocupados.add(n)
    return ocupados


# =========================
# Formulário público
# =========================
with st.form("form_publico"):
    st.subheader("👤 Seus dados")

    col1, col2 = st.columns(2)
    with col1:
        nome = st.text_input("Nome do cliente*", max_chars=120)
        telefone_raw = st.text_input("Telefone (somente números)*", max_chars=11, placeholder="11999999999")
        email = st.text_input("Email")
        rg = st.text_input("RG")
        cpf = st.text_input("CPF")
        como = st.text_input("Como conheceu a empresa?")  # conforme seu pedido de label

    with col2:
        st.markdown("<span class='label-strong'>Endereço</span>", unsafe_allow_html=True)
        cep = st.text_input("CEP", max_chars=9, placeholder="00000-000")
        buscar_cep = st.form_submit_button("🔎 Buscar CEP")
        if buscar_cep:
            dados = via_cep(cep)
            if dados:
                st.session_state["logradouro"] = dados["logradouro"]
                st.session_state["bairro"] = dados["bairro"]
                st.session_state["cidade"] = dados["cidade"]
                st.success("Endereço preenchido automaticamente!")
            else:
                st.warning("Não foi possível buscar o CEP. Preencha manualmente.")

        logradouro = st.text_input("Logradouro", value=st.session_state.get("logradouro", ""))
        numero = st.text_input("Número")
        complemento = st.text_input("Complemento")
        bairro = st.text_input("Bairro", value=st.session_state.get("bairro", ""))
        cidade = st.text_input("Cidade", value=st.session_state.get("cidade", ""))

    observacao = st.text_area("Observação (opcional)")

    st.subheader("🎉 Dados do evento")
    data_evento = st.date_input("Data*", value=date.today())
    c3, c4 = st.columns(2)
    with c3:
        hora_inicio = st.time_input("Horário início", value=dtime(hour=13, minute=0))
    with c4:
        hora_fim = st.time_input("Horário fim", value=dtime(hour=17, minute=0))

    st.subheader("🎠 Escolha seus brinquedos")
    brinquedos_df = carregar_brinquedos_ativos()
    reservas_df = carregar_reservas_do_dia(data_evento)
    ocup = ocupados_no_dia(reservas_df)

    if not brinquedos_df.empty:
        brinquedos_df["nome_norm"] = brinquedos_df["nome"].apply(normalizar_nome)
        livres_df = brinquedos_df[~brinquedos_df["nome_norm"].isin(ocup)].copy()
    else:
        livres_df = brinquedos_df.copy()

    if livres_df.empty:
        st.info("🤷‍♀️ Nesta data todos os brinquedos estão reservados. Experimente outra data.")
        itens_selecionados = []
    else:
        lista = sorted(livres_df["nome"].tolist(), key=str.lower)
        itens_selecionados = st.multiselect(
            "Brinquedos disponíveis para a data escolhida*",
            options=lista,
        )

    enviado = st.form_submit_button("💾 Enviar solicitação")


# =========================
# Envio (INSERT nas tabelas 'pre_*')
# =========================
if enviado:
    # --- Validações mínimas ---
    erros = []
    if not nome:
        erros.append("Informe seu nome.")
    if not telefone_raw:
        erros.append("Informe o telefone.")
    if not data_evento:
        erros.append("Informe a data do evento.")
    if not itens_selecionados:
        erros.append("Selecione pelo menos 1 brinquedo.")

    if erros:
        st.error("⚠️ Corrija os campos:\n\n- " + "\n- ".join(erros))
        st.stop()

    # --- Normalizações ---
    telefone = re.sub(r"\D", "", str(telefone_raw))

    # --- Gere o ID aqui (evita depender de retorno do insert) ---
    pre_id = str(uuid4())

    # --- Monta payload para pre_reservas ---
    registro = {
        "id": pre_id,  # usamos o mesmo id para relacionar os itens
        "nome": nome.strip(),
        "telefone": telefone,
        "email": (email or "").strip(),
        "rg": (rg or "").strip(),
        "cpf": (cpf or "").strip(),
        "como_conheceu": (como or "").strip(),
        "cep": (cep or "").strip(),
        "logradouro": (logradouro or "").strip(),
        "numero": (numero or "").strip(),
        "complemento": (complemento or "").strip(),
        "bairro": (bairro or "").strip(),
        "cidade": (cidade or "").strip(),
        "observacao": (observacao or "").strip(),
        "data": str(data_evento),  # YYYY-MM-DD
        "hora_inicio": str(hora_inicio) if hora_inicio else None,  # HH:MM:SS
        "hora_fim": str(hora_fim) if hora_fim else None,          # HH:MM:SS
    }

    try:
        # 1) Insere a pré-reserva (sem depender de retorno — return=minimal)
        table_insert("pre_reservas", [registro])

        # 2) Insere os itens associados
        itens_rows = [{"pre_reserva_id": pre_id, "brinquedo": nome_b, "quantidade": 1} for nome_b in itens_selecionados]
        if itens_rows:
            table_insert("pre_reserva_itens", itens_rows)

        # Feedback
        st.success("✅ Solicitação enviada! Em breve entraremos em contato para confirmar.")
        st.balloons()

        # Opcional: limpar estado de endereço para próximos envios
        for k in ("logradouro", "bairro", "cidade"):
            st.session_state.pop(k, None)

    except Exception as e:
        st.error(f"❌ Erro ao enviar sua solicitação: {e}")
``
