# supabase_rest.py
import os
import json
import mimetypes
from typing import Any, Dict, List, Optional, Tuple
import requests

# >>> Configure via variáveis de ambiente ou direto aqui:
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://hmrqsjdlixeazdfhrqqh.supabase.co")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImhtcnFzamRsaXhlYXpkZmhycXFoIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjEyMjE3MDUsImV4cCI6MjA3Njc5NzcwNX0.rM9fob3HIEl2YoL7lB7Tj7vUb21B9EzR1zLSR7VLwTM")  # troque pelo seu

# Headers base (PostgREST + RLS com anon key)
def _headers(extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    base = {
        "apikey": SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Prefer": "return=representation"  # retorna os registros inseridos/alterados
    }
    if extra:
        base.update(extra)
    return base

# ---------------------------------
# REST - CRUD genérico em tabelas
# ---------------------------------

def table_select(
    table: str,
    select: str = "*",
    where: Optional[Dict[str, Any]] = None,
    limit: Optional[int] = None,
    order: Optional[Tuple[str, str]] = None,  # ("coluna", "asc"|"desc")
) -> List[Dict[str, Any]]:
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    params = {"select": select}

    # filtros (where) -> PostgREST: col=eq.valor
    if where:
        for col, val in where.items():
            params[col] = f"eq.{val}"

    if limit:
        params["limit"] = str(limit)

    if order:
        col, direc = order
        params["order"] = f"{col}.{direc}"

    r = requests.get(url, headers=_headers(), params=params, timeout=15)
    if r.status_code in (200, 206):
        return r.json()
    raise RuntimeError(f"[select] {table}: {r.status_code} {r.text}")

def table_insert(table: str, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    r = requests.post(url, headers=_headers(), data=json.dumps(rows), timeout=15)
    if r.status_code in (200, 201):
        return r.json() if r.text else []
    raise RuntimeError(f"[insert] {table}: {r.status_code} {r.text}")

def table_upsert(table: str, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    # Para upsert, use Prefer: resolution=merge-duplicates (depende de PK/unique)
    hdrs = _headers({"Prefer": "resolution=merge-duplicates,return=representation"})
    r = requests.post(url, headers=hdrs, data=json.dumps(rows), timeout=15)
    if r.status_code in (200, 201):
        return r.json() if r.text else []
    raise RuntimeError(f"[upsert] {table}: {r.status_code} {r.text}")

def table_update(
    table: str,
    where: Dict[str, Any],
    values: Dict[str, Any]
) -> List[Dict[str, Any]]:
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    params = {}
    for col, val in where.items():
        params[col] = f"eq.{val}"

    r = requests.patch(url, headers=_headers(), params=params, data=json.dumps(values), timeout=15)
    if r.status_code == 200:
        return r.json() if r.text else []
    raise RuntimeError(f"[update] {table}: {r.status_code} {r.text}")

def table_delete(table: str, where: Dict[str, Any]) -> int:
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    params = {}
    for col, val in where.items():
        params[col] = f"eq.{val}"

    r = requests.delete(url, headers=_headers(), params=params, timeout=15)
    if r.status_code in (200, 204):
        # Quando Prefer: return=representation não é usado, pode não vir corpo
        try:
            js = r.json()
            return len(js) if isinstance(js, list) else 0
        except Exception:
            return 0
    raise RuntimeError(f"[delete] {table}: {r.status_code} {r.text}")

# ---------------------------------
# Storage (upload e URL pública)
# ---------------------------------

def storage_upload(bucket: str, local_path: str, dest_path: str) -> Dict[str, Any]:
    """
    Envia arquivo para o bucket. Exige política de storage permitindo upload com anon key.
    """
    url = f"{SUPABASE_URL}/storage/v1/object/{bucket}/{dest_path}"
    mime, _ = mimetypes.guess_type(local_path)
    mime = mime or "application/octet-stream"
    with open(local_path, "rb") as f:
        r = requests.post(url, headers=_headers({"Content-Type": mime}), data=f, timeout=60)
    if r.status_code in (200, 201):
        return r.json() if r.text else {"path": dest_path}
    raise RuntimeError(f"[storage upload] {bucket}/{dest_path}: {r.status_code} {r.text}")

def storage_public_url(bucket: str, path: str) -> str:
    """
    Retorna URL pública (se o bucket estiver como público).
    """
    return f"{SUPABASE_URL}/storage/v1/object/public/{bucket}/{path}"

# ---------------------------------
# Importação de CSV direto para a tabela (opcional)
# ---------------------------------

import csv

def import_csv_to_table(table: str, csv_path: str, normalize_headers: bool = True) -> int:
    """
    Importa um CSV local para a tabela via insert em lote.
    Assume que as colunas do CSV correspondem aos nomes no Supabase.
    """
    rows = []
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if normalize_headers:
                row = {k.strip(): (v if v != "" else None) for k, v in row.items()}
            rows.append(row)

    if not rows:
        return 0

    # Insere em blocos para evitar payloads muito grandes
    BATCH = 500
    total = 0
    for i in range(0, len(rows), BATCH):
        chunk = rows[i:i+BATCH]
        table_insert(table, chunk)
        total += len(chunk)
    return total




