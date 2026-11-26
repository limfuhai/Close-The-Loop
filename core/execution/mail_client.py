"""
core/execution/mail_client.py

One door to the user's mailbox for every email executor.

    result = await mail_client.run(api_key, account, "read", {"count": 5})

`account` is the mail account the user selected in Boundary's Email Accounts
panel. The orchestrator puts it in task_data["mailAccount"]:

    {
        "address":   "someone@qq.com",
        "provider":  "qq",            # qq, 163, 126, yeah, sina, 139, aliyun,
                                      # exmail, gmail, outlook, or custom
        "auth_code": "xxxxxxxxxxxx",  # QQ/163 授权码 or Gmail app password
        "display_name": "",           # optional
        # only for provider "custom":
        "imap_host": "...", "imap_port": 993, "smtp_host": "...", "smtp_port": 465,
    }

Actions:
    read    recent mail          count, folder ("inbox"/"sent"), unread, since, sender
    get     one message by ID    message_id
    thread  NOT_SUPERSEDED       message_id, since, participants, limit
    send    send now             to, cc, subject, body, attachments, reply_to_message_id
    draft   save to Drafts       same as send
    folders list folders         (diagnostics)

IMAP/SMTP accounts run mail_remote_script.py on the user's machine.
Microsoft accounts run outlook_remote_script.ps1 through classic Outlook.
"""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Any, Dict

from .bridge_query import BridgeQuery

logger = logging.getLogger(__name__)

_HERE = Path(__file__).resolve().parent
_IMAP_SCRIPT = (_HERE / "mail_remote_script.py").read_text(encoding="utf-8")
_OUTLOOK_SCRIPT = (_HERE / "outlook_remote_script.ps1").read_text(encoding="utf-8")

PROVIDERS: Dict[str, Dict[str, Any]] = {
    "qq":      {"imap_host": "imap.qq.com",        "imap_port": 993, "smtp_host": "smtp.qq.com",        "smtp_port": 465},
    "exmail":  {"imap_host": "imap.exmail.qq.com", "imap_port": 993, "smtp_host": "smtp.exmail.qq.com", "smtp_port": 465},
    "163":     {"imap_host": "imap.163.com",       "imap_port": 993, "smtp_host": "smtp.163.com",       "smtp_port": 465},
    "126":     {"imap_host": "imap.126.com",       "imap_port": 993, "smtp_host": "smtp.126.com",       "smtp_port": 465},
    "yeah":    {"imap_host": "imap.yeah.net",      "imap_port": 993, "smtp_host": "smtp.yeah.net",      "smtp_port": 465},
    "sina":    {"imap_host": "imap.sina.com",      "imap_port": 993, "smtp_host": "smtp.sina.com",      "smtp_port": 465},
    "139":     {"imap_host": "imap.139.com",       "imap_port": 993, "smtp_host": "smtp.139.com",       "smtp_port": 465},
    "aliyun":  {"imap_host": "imap.aliyun.com",    "imap_port": 993, "smtp_host": "smtp.aliyun.com",    "smtp_port": 465},
    "gmail":   {"imap_host": "imap.gmail.com",     "imap_port": 993, "smtp_host": "smtp.gmail.com",     "smtp_port": 465},
}

DOMAIN_TO_PROVIDER = {
    "qq.com": "qq", "foxmail.com": "qq", "vip.qq.com": "qq",
    "163.com": "163", "126.com": "126", "yeah.net": "yeah",
    "sina.com": "sina", "sina.cn": "sina", "139.com": "139", "aliyun.com": "aliyun",
    "gmail.com": "gmail", "googlemail.com": "gmail",
    "outlook.com": "outlook", "hotmail.com": "outlook", "live.com": "outlook", "msn.com": "outlook",
}

MICROSOFT = "outlook"


class MailError(Exception):
    """A mail operation failed. The message is written for the user."""


def guess_provider(address: str) -> str:
    domain = (address or "").split("@")[-1].lower()
    return DOMAIN_TO_PROVIDER.get(domain, "custom")


def resolve_account(account: Dict[str, Any] | None) -> Dict[str, Any]:
    """Check the selected account and fill in its server settings."""
    if not account or not account.get("address"):
        raise MailError(
            "No email account is selected. Add one in Boundary's Email Accounts "
            "panel and mark it as current."
        )
    resolved = dict(account)
    provider = (resolved.get("provider") or guess_provider(resolved["address"])).lower()
    resolved["provider"] = provider
    if provider == MICROSOFT:
        return resolved
    if not resolved.get("auth_code"):
        raise MailError(f"No authorization code is saved for {resolved['address']}.")
    preset = PROVIDERS.get(provider)
    if preset:
        for key, value in preset.items():
            resolved.setdefault(key, value)
            if not resolved.get(key):
                resolved[key] = value
    elif not (resolved.get("imap_host") and resolved.get("smtp_host")):
        raise MailError(
            f"{resolved['address']} uses a custom mail server, but no IMAP/SMTP "
            "server is saved for it."
        )
    return resolved


def _b64_json(obj: Dict[str, Any]) -> str:
    return base64.b64encode(json.dumps(obj, ensure_ascii=False).encode("utf-8")).decode("ascii")


def build_code(account: Dict[str, Any], action: str, params: Dict[str, Any]) -> str:
    """Python code for the bridge's "python" command type."""
    payload = _b64_json({**params, "action": action, "account": account})
    if account["provider"] == MICROSOFT:
        script = (
            "$P = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('"
            + payload + "')) | ConvertFrom-Json\n" + _OUTLOOK_SCRIPT
        )
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        return _OUTLOOK_WRAPPER.replace("__ENCODED_PS__", encoded)
    return _IMAP_SCRIPT.replace("__BOUNDARY_PARAMS__", payload)


# Runs on the user's machine: starts PowerShell with the Outlook script and
# turns its base64 output back into ASCII JSON.
_OUTLOOK_WRAPPER = r'''
import base64, json, subprocess, sys
try:
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand",
                        "__ENCODED_PS__"], capture_output=True, text=True, timeout=27)
    lines = [l.strip() for l in (r.stdout or "").splitlines() if l.strip()]
    data = json.loads(base64.b64decode(lines[-1]).decode("utf-8"))
except Exception as e:
    err = ""
    try:
        err = (r.stderr or "")[-400:]
    except Exception:
        pass
    data = {"ok": False, "error": "Outlook script failed: %s %s" % (e, err)}
sys.stdout.write(json.dumps(data, ensure_ascii=True))
'''


async def run(api_key: str, account: Dict[str, Any] | None, action: str,
              params: Dict[str, Any] | None = None, timeout: int = 30) -> Dict[str, Any]:
    """Run one mail action on the user's machine. Raises MailError on failure."""
    if not api_key:
        raise MailError("No API key provided - bridge access requires authentication")
    resolved = resolve_account(account)
    code = build_code(resolved, action, params or {})

    query = BridgeQuery(api_key=api_key)
    logger.info(f"📮 Mail action '{action}' for {resolved['address']} ({resolved['provider']})")
    result = await query.execute_python(code, timeout=timeout, label=f"mail:{action}")

    output = (result.get("output") or "").strip()
    if not output:
        detail = result.get("error") or "no output"
        raise MailError(f"The mail script returned nothing ({str(detail)[-300:]}). Is the bridge running?")
    try:
        data = json.loads(output.splitlines()[-1])
    except json.JSONDecodeError:
        raise MailError(f"The mail script returned unreadable output: {output[:200]}")
    if not data.get("ok"):
        raise MailError(data.get("error") or "Unknown mail error")
    return data