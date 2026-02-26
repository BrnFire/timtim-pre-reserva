import streamlit as st
import pandas as pd
import requests
import re
from datetime import date, time as dtime
from supabase_rest import table_select, table_insert

st.set_page_config(page_title="Solicite sua Festa | TimTim Festas", page_icon="🎈", layout="centered")

# ---------------------------
# Estilos e cabeçalho
# ---------------------------
st.markdown("<h2 style='text-align:center'>🎈 Solicite seu orçamento</h2>", unsafe_allow_html=True)
st.caption("Preencha seus dados e escolha a data e os brinquedos. Nós confirmaremos por WhatsApp/E-mail.")

# ---------------------------
# Utilitários
# ---------------------------
def normalizar_nome(txt: str) -> str:
    if not isinstance(txt, str):
        return ""
    import unicodedata
    t = unicodedata.normalize("NFKD", txt).encode("ascii", "ignore").decode("utf-8")
    t = re.sub(r"[^a-zA-Z0-9]+", " ", t)
    return t.strip().lower()

def via_cep(cep: str):
    try:
        cep_num = re.sub(r"\D", "", cep)[:8]
        if len(cep_num) != 8:
            return None
        r = requests.get(f"https://viacep.com.br/ws/{cep_num}/json/", timeout=8)
        if r.status_code == 200 and "erro" not in r.json():
            j = r.json()
            return {
                "logradouro": j.get("logradouro", ""),
                "bairro": j.get("bairro", ""),
                "cidade": j.get("localidade", "")
            }
    except Exception:
        pass
    return None

def carregar_brinquedos_ativos():
    # Usa sua tabela 'brinquedos' como hoje
    rows = table_select("brinquedos", select="nome,categoria,status,valor", where={"status": "Disponível"})
    df = pd.DataFrame(rows) if rows else pd.DataFrame(columns=["nome","categoria","status","valor"])
    # padroniza
    if "nome" not in df.columns: df["nome"] = ""
    if "categoria" not in df.columns: df["categoria"] = "Tradicional"
    if "valor" not in df.columns: df["valor"] = 0.0
    return df

def carregar_reservas_do_dia(d: date):
    rows = table_select("reservas", select="data,brinquedos", where={"data": str(d)})
    df = pd.DataFrame(rows) if rows else pd.DataFrame(columns=["data","brinquedos"])
    return df

def ocupados_no_dia(reservas_df: pd.DataFrame) -> set[str]:
    # Lógica igual à sua (por nome). Se "Pula-Pula 01" está na string daquele dia, ele é considerado ocupado.
    ocupados = set()
    for _, r in reservas_df.iterrows():
        for pedaco in str(r.get("brinquedos","")).split(","):
            nome = pedaco.strip()
            if not nome: 
                continue
            n = normalizar_nome(nome)
            if n:
                ocupados.add(n)
    return ocupados

# ---------------------------
# Formulário
# ---------------------------
with st.form("form_publico"):
    st.subheader("👤 Seus dados")
    col1, col2 = st.columns(2)
    with col1:
        nome = st.text_input("Nome do cliente*", max_chars=120)
        telefone = st.text_input("Telefone (somente números)*", max_chars=11)
        email = st.text_input("Email")
        rg = st.text_input("RG")
        cpf = st.text_input("CPF")
        como = st.text_input("Como conheceu a empresa?")  # alterada a label conforme pedido
    with col2:
        cep = st.text_input("CEP", max_chars=9, placeholder="00000-000")
        if st.form_submit_button("Buscar CEP"):
            dados = via_cep(cep)
            if dados:
                st.session_state["logradouro"] = dados["logradouro"]
                st.session_state["bairro"] = dados["bairro"]
                st.session_state["cidade"] = dados["cidade"]
                st.success("Endereço preenchido automaticamente!")
            else:
                st.warning("Não foi possível buscar o CEP. Preencha manualmente.")

        logradouro = st.text_input("Logradouro", value=st.session_state.get("logradouro",""))
        numero = st.text_input("Número")
        complemento = st.text_input("Complemento")
        bairro = st.text_input("Bairro", value=st.session_state.get("bairro",""))
        cidade = st.text_input("Cidade", value=st.session_state.get("cidade",""))
    observacao = st.text_area("Observação (opcional)")

    st.subheader("🎉 Dados do evento")
    data_evento = st.date_input("Data*", value=date.today())
    c3, c4 = st.columns(2)
    with c3:
        hora_inicio = st.time_input("Horário início", value=dtime(hour=13, minute=0))
    with c4:
        hora_fim = st.time_input("Horário fim", value=dtime(hour=17, minute=0))

    st.subheader("🎠 Escolha seus brinquedos")
    # Disponibilidade por DIA (igual ao seu app interno)
    brinquedos_df = carregar_brinquedos_ativos()
    reservas_df = carregar_reservas_do_dia(data_evento)
    ocup = ocupados_no_dia(reservas_df)
    # filtra os livres
    if not brinquedos_df.empty:
        brinquedos_df["nome_norm"] = brinquedos_df["nome"].apply(normalizar_nome)
        livres = brinquedos_df[~brinquedos_df["nome_norm"].isin(ocup)].copy()
    else:
        livres = brinquedos_df.copy()

    if livres.empty:
        st.info("Nesta data todos os brinquedos estão reservados. Experimente outra data.")
        itens_selecionados = []
    else:
        lista = sorted(livres["nome"].tolist(), key=str.lower)
        itens_selecionados = st.multiselect("Brinquedos disponíveis para a data escolhida*", options=lista)

    enviado = st.form_submit_button("💾 Enviar solicitação")

# ---------------------------
# Gravação (INSERT apenas em tabelas 'pre_*')
# ---------------------------
if enviado:
    # validações mínimas
    erros = []
    if not (nome and telefone and data_evento and itens_selecionados):
        if not nome: erros.append("Informe seu nome.")
        if not telefone: erros.append("Informe o telefone.")
        if not data_evento: erros.append("Informe a data do evento.")
        if not itens_selecionados: erros.append("Selecione pelo menos 1 brinquedo.")
    if erros:
        st.error("⚠️ Corrija os campos:\n- " + "\n- ".join(erros))
        st.stop()

    # monta o registro principal
    registro = {
        "nome": nome.strip(),
        "telefone": re.sub(r"\D", "", telefone),
        "email": email.strip(),
        "rg": rg.strip(),
        "cpf": cpf.strip(),
        "como_conheceu": como.strip(),
        "cep": cep.strip(),
        "logradouro": logradouro.strip(),
        "numero": numero.strip(),
        "complemento": complemento.strip(),
        "bairro": bairro.strip(),
        "cidade": cidade.strip(),
        "observacao": observacao.strip(),
        "data": str(data_evento),
        "hora_inicio": str(hora_inicio) if hora_inicio else None,
        "hora_fim": str(hora_fim) if hora_fim else None,
    }

    try:
        # 1) cria pre_reserva
        created = table_insert("pre_reservas", [registro])   # Prefer: return=representation já está no seu supabase_rest
        pre_id = created[0]["id"]

        # 2) cria os itens
        itens_rows = [{"pre_reserva_id": pre_id, "brinquedo": nome_b, "quantidade": 1} for nome_b in itens_selecionados]
        if itens_rows:
            table_insert("pre_reserva_itens", itens_rows)

        st.success("✅ Solicitação enviada! Em breve entraremos em contato para confirmar.")
        st.balloons()

        # opcional: limpa estado
        st.session_state.clear()

    except Exception as e:
        st.error(f"❌ Erro ao enviar sua solicitação: {e}")
