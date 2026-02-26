# supabase_rest.py  — cliente REST leve para o APP EXTERNO (público)
# ---------------------------------------------------------------
# - Lê SUPABASE_URL / SUPABASE_KEY dos secrets/ambiente
# - SELECT: normal
# - INSERT/UPDATE/UPSERT/DELETE: Prefer=return=minimal  (evita SELECT pós-escrita e conflitos com RLS)
# ---------------------------------------------------------------

import os
import json
import mimetypes
from typing import Any, Dict, List, Optional, Tuple

import requests


# =========================
# Config de ambiente
# =========================
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_KEY")  # ANON key (pública), não use service_role aqui!

if not SUPABASE_URL or not SUPABASE_ANON_KEY:
    raise RuntimeError(
        "SUPABASE_URL e/ou SUPABASE_KEY não definidos. "
        "Configure-os nos Secrets do Streamlit (App → Settings → Secrets) ou como variáveis de ambiente."
    )


# =========================
# Headers base
# =========================
def _headers(extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    base = {
        "apikey": SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        # Padrão seguro. Para SELECT isso não interfere; para escrita, sobrescrevemos para "return=minimal".
        "Prefer": "return=representation",
    }
    if extra:
        base.update(extra)
    return base


# =========================
# Helpers HTTP
# =========================
def _raise(r: requests.Response, op: str, table: str):
    """Levanta erro com mensagem completa do PostgREST."""
    try:
        # Muitas vezes o PostgREST devolve JSON com 'message', 'hint', etc.
        detail = r.text
    except Exception:
        detail = f"status={r.status_code}"
    raise RuntimeError(f"[{op}] {table}: {r.status_code} {detail}")


# =========================
# SELECT
# =========================
def table_select(
    table: str,
    select: str = "*",
    where: Optional[Dict[str, Any]] = None,
    limit: Optional[int] = None,
    order: Optional[Tuple[str, str]] = None,  # ("coluna", "asc" | "desc")
) -> List[Dict[str, Any]]:
    """
    Leitura simples via PostgREST.
    Ex.: table_select("brinquedos", select="nome,valor", where={"status":"Disponível"}, order=("nome","asc"))
    """
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    params: Dict[str, str] = {"select": select}

    if where:
        # PostgREST: col=eq.<valor>
        for col, val in where.items():
            params[col] = f"eq.{val}"

    if limit is not None:
        params["limit"] = str(limit)

    if order is not None:
        col, direc = order
        params["order"] = f"{col}.{direc}"

    r = requests.get(url, headers=_headers(), params=params, timeout=20)
    if r.status_code in (200, 206):
        return r.json() if r.text else []
    _raise(r, "select", table)


# =========================
# INSERT  (Prefer: return=minimal)
# =========================
def table_insert(table: str, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Insere linhas.
    => Prefer: return=minimal evita SELECT pós-insert (que seria bloqueado pela RLS se você não abriu SELECT para 'anon').
    """
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    hdrs = _headers({"Prefer": "return=minimal"})
    r = requests.post(url, headers=hdrs, data=json.dumps(rows), timeout=25)
    if r.status_code in (200, 201, 204):
        # 'minimal' normalmente não retorna corpo
        return []
    _raise(r, "insert", table)


# =========================
# UPSERT  (Prefer: resolution=merge-duplicates + return=minimal)
# =========================
def table_upsert(table: str, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Upsert (merge-duplicates) com retorno mínimo (não tenta ler após escrever).
    Requer PK/unique no Postgres para identificar duplicidade.
    """
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    hdrs = _headers({"Prefer": "resolution=merge-duplicates,return=minimal"})
    r = requests.post(url, headers=hdrs, data=json.dumps(rows), timeout=25)
    if r.status_code in (200, 201, 204):
        return []
    _raise(r, "upsert", table)


# =========================
# UPDATE  (Prefer: return=minimal)
# =========================
def table_update(
    table: str,
    where: Dict[str, Any],
    values: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """
    Atualiza linhas que casem com 'where'.
    Retorno mínimo para não acionar SELECT pós-update.
    """
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    params: Dict[str, str] = {}
    for col, val in where.items():
        params[col] = f"eq.{val}"

    hdrs = _headers({"Prefer": "return=minimal"})
    r = requests.patch(url, headers=hdrs, params=params, data=json.dumps(values), timeout=25)
    if r.status_code in (200, 204):
        return []
    _raise(r, "update", table)


# =========================
# DELETE  (Prefer: return=minimal)
# =========================
def table_delete(table: str, where: Dict[str, Any]) -> int:
    """
    Deleta linhas. Retorna a contagem estimada (ou 0).
    """
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    params: Dict[str, str] = {}
    for col, val in where.items():
        params[col] = f"eq.{val}"

    hdrs = _headers({"Prefer": "return=minimal"})
    r = requests.delete(url, headers=hdrs, params=params, timeout=20)
    if r.status_code in (200, 204):
        # como é 'minimal', pode não haver corpo
        try:
            js = r.json()
            return len(js) if isinstance(js, list) else 0
        except Exception:
            return 0
    _raise(r, "delete", table)


# =========================
# STORAGE (opcional)
# =========================
def storage_upload(bucket: str, local_path: str, dest_path: str) -> Dict[str, Any]:
    """
    Upload para Storage. É preciso que o bucket permita upload com ANON key (policies no Storage).
    """
    url = f"{SUPABASE_URL}/storage/v1/object/{bucket}/{dest_path}"
    mime, _ = mimetypes.guess_type(local_path)
    mime = mime or "application/octet-stream"
    with open(local_path, "rb") as f:
        r = requests.post(url, headers=_headers({"Content-Type": mime}), data=f, timeout=60)
    if r.status_code in (200, 201):
        return r.json() if r.text else {"path": dest_path}
    _raise(r, "storage_upload", f"{bucket}/{dest_path}")


def storage_public_url(bucket: str, path: str) -> str:
    """
    Retorna a URL pública do objeto (se o bucket estiver como público).
    """
    return f"{SUPABASE_URL}/storage/v1/object/public/{bucket}/{path}"
