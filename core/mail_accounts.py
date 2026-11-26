"""
core/mail_accounts.py

The user's email accounts for the local agents, behind the Email Accounts
panel. Plugged into compiler.py the same way as message.py and agent.py:

    from mail_accounts import router as mail_accounts_router, init as mail_accounts_init
    mail_accounts_init(self.supabase)
    app.include_router(mail_accounts_router)

Endpoints (all need the Clerk login token):
    GET    /api/mail-accounts                 list accounts (never the codes)
    POST   /api/mail-accounts                 add an account
    POST   /api/mail-accounts/{id}/current    make it the current account
    DELETE /api/mail-accounts/{id}            remove it

Authorization codes live encrypted in Supabase Vault. The mail_accounts
table holds only the Vault id. Nothing here ever sends a code back to the
browser; only load_current_account() reads one, for the orchestrator.
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any, Dict, Optional

import jwt
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)
router = APIRouter()
_supabase = None

TABLE = "mail_accounts"
PUBLIC_FIELDS = "id, address, provider, label, display_name, imap_host, imap_port, smtp_host, smtp_port, is_current, created_at"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _mail_client():
    """Imported on first use, not at the top of the file: compiler.py adds the
    project root to Python's path only after its own imports have run, so
    `core.execution` can't be found yet while compiler.py is still loading.
    The orchestrator imports core.executors the same way, for the same reason."""
    from core.execution import mail_client
    return mail_client


def init(supabase_client) -> None:
    global _supabase
    _supabase = supabase_client


def _user_id(request: Request) -> Optional[str]:
    """Clerk user id from the login token, read the same way as compiler.py.
    (Signature verification is on the Week 4 list for the whole app.)"""
    try:
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return None
        payload = jwt.decode(auth.split(" ", 1)[1], options={"verify_signature": False})
        return payload.get("sub")
    except Exception:
        return None


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"success": False, "error": message})


def _ready(request: Request):
    user_id = _user_id(request)
    if not user_id:
        return None, _error(401, "Not authenticated")
    if _supabase is None:
        return None, _error(500, "Database not configured")
    return user_id, None


# ── endpoints ────────────────────────────────────────────────────────────

@router.get("/api/mail-accounts")
async def list_accounts(request: Request):
    user_id, err = _ready(request)
    if err:
        return err
    try:
        rows = (_supabase.table(TABLE).select(PUBLIC_FIELDS)
                .eq("clerk_user_id", user_id).order("created_at").execute()).data or []
        # Belt and braces: never let Vault ids or user ids reach the browser
        rows = [{k: v for k, v in row.items() if k not in ("secret_id", "clerk_user_id")}
                for row in rows]
        return {"success": True, "accounts": rows}
    except Exception as e:
        logger.error(f"[MailAccounts] list failed: {e}")
        return _error(500, "Could not load email accounts")


@router.post("/api/mail-accounts")
async def add_account(request: Request):
    user_id, err = _ready(request)
    if err:
        return err
    try:
        body = await request.json()
    except Exception:
        return _error(400, "Invalid request")

    address = str(body.get("address") or "").strip().lower()
    if not EMAIL_RE.match(address):
        return _error(400, "Please enter a valid email address.")

    mc = _mail_client()
    provider = str(body.get("provider") or "").strip().lower() or mc.guess_provider(address)
    if provider not in set(mc.PROVIDERS) | {mc.MICROSOFT, "custom"}:
        return _error(400, f"Unknown provider: {provider}")

    auth_code = str(body.get("auth_code") or "").strip()
    if provider != mc.MICROSOFT and not auth_code:
        return _error(400, "Please enter the authorization code (授权码) or app password.")

    row: Dict[str, Any] = {
        "clerk_user_id": user_id,
        "address": address,
        "provider": provider,
        "label": str(body.get("label") or "").strip()[:40],
        "display_name": str(body.get("display_name") or "").strip()[:80],
    }
    if provider == "custom":
        try:
            row["imap_host"] = str(body.get("imap_host") or "").strip()
            row["smtp_host"] = str(body.get("smtp_host") or "").strip()
            row["imap_port"] = int(body.get("imap_port") or 993)
            row["smtp_port"] = int(body.get("smtp_port") or 465)
        except ValueError:
            return _error(400, "Server ports must be numbers.")
        if not (row["imap_host"] and row["smtp_host"]):
            return _error(400, "A custom mail server needs both an IMAP and an SMTP server address.")

    try:
        existing = (_supabase.table(TABLE).select("id, address, is_current")
                    .eq("clerk_user_id", user_id).execute()).data or []
        if any(r.get("address") == address for r in existing):
            return _error(409, f"{address} is already added. Delete it first to change its code.")

        if auth_code:
            secret = _supabase.rpc("mail_secret_save", {
                "p_secret": auth_code,
                "p_name": f"boundary-mail-{uuid.uuid4()}",
            }).execute()
            row["secret_id"] = secret.data

        row["is_current"] = not any(r.get("is_current") for r in existing)
        created = _supabase.table(TABLE).insert(row).execute().data or []
        account = {k: v for k, v in (created[0] if created else row).items()
                   if k not in ("secret_id", "clerk_user_id")}
        logger.info(f"[MailAccounts] Added {provider} account for user {user_id[:12]}...")
        return {"success": True, "account": account}
    except Exception as e:
        logger.error(f"[MailAccounts] add failed: {e}")
        return _error(500, "Could not save the email account")


@router.post("/api/mail-accounts/{account_id}/current")
async def set_current(account_id: str, request: Request):
    user_id, err = _ready(request)
    if err:
        return err
    try:
        found = (_supabase.table(TABLE).select("id").eq("id", account_id)
                 .eq("clerk_user_id", user_id).execute()).data or []
        if not found:
            return _error(404, "Email account not found")
        _supabase.table(TABLE).update({"is_current": False}).eq("clerk_user_id", user_id).execute()
        _supabase.table(TABLE).update({"is_current": True}).eq("id", account_id) \
            .eq("clerk_user_id", user_id).execute()
        return {"success": True}
    except Exception as e:
        logger.error(f"[MailAccounts] set current failed: {e}")
        return _error(500, "Could not change the current account")


@router.delete("/api/mail-accounts/{account_id}")
async def delete_account(account_id: str, request: Request):
    user_id, err = _ready(request)
    if err:
        return err
    try:
        found = (_supabase.table(TABLE).select("id, secret_id, is_current").eq("id", account_id)
                 .eq("clerk_user_id", user_id).execute()).data or []
        if not found:
            return _error(404, "Email account not found")
        account = found[0]
        _supabase.table(TABLE).delete().eq("id", account_id).eq("clerk_user_id", user_id).execute()
        if account.get("secret_id"):
            try:
                _supabase.rpc("mail_secret_delete", {"p_id": account["secret_id"]}).execute()
            except Exception as e:
                logger.warning(f"[MailAccounts] could not delete Vault secret: {e}")

        # If the current account was removed, the oldest remaining one takes over
        if account.get("is_current"):
            rest = (_supabase.table(TABLE).select("id").eq("clerk_user_id", user_id)
                    .order("created_at").limit(1).execute()).data or []
            if rest:
                _supabase.table(TABLE).update({"is_current": True}).eq("id", rest[0]["id"]).execute()
        return {"success": True}
    except Exception as e:
        logger.error(f"[MailAccounts] delete failed: {e}")
        return _error(500, "Could not delete the email account")


# ── for the orchestrator ─────────────────────────────────────────────────

def load_current_account(supabase_client, clerk_user_id: str) -> Optional[Dict[str, Any]]:
    """The user's current account, with its authorization code, in the shape
    mail_client expects. None if the user has no account yet."""
    if supabase_client is None:
        # Local mode: the account comes from .env
        import os
        address = os.getenv("MAIL_ADDRESS", "").strip()
        if not address:
            return None
        account = {"address": address, "auth_code": os.getenv("MAIL_AUTH_CODE", "").strip(),
                   "provider": os.getenv("MAIL_PROVIDER", "").strip().lower(),
                   "display_name": os.getenv("MAIL_DISPLAY_NAME", "").strip(), "label": ""}
        for key in ("imap_host", "imap_port", "smtp_host", "smtp_port"):
            value = os.getenv("MAIL_" + key.upper(), "").strip()
            if value:
                account[key] = int(value) if key.endswith("port") else value
        return account
    if not clerk_user_id:
        return None
    rows = (supabase_client.table(TABLE).select("*").eq("clerk_user_id", clerk_user_id)
            .eq("is_current", True).limit(1).execute()).data or []
    if not rows:
        return None
    row = rows[0]
    account = {
        "address": row["address"],
        "provider": row["provider"],
        "display_name": row.get("display_name") or "",
        "label": row.get("label") or "",
    }
    for key in ("imap_host", "imap_port", "smtp_host", "smtp_port"):
        if row.get(key):
            account[key] = row[key]
    if row.get("secret_id"):
        secret = supabase_client.rpc("mail_secret_read", {"p_id": row["secret_id"]}).execute()
        account["auth_code"] = secret.data or ""
    return account