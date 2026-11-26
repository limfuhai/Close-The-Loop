"""
Ledger Execution - the ledger agent's tool, and the ledger format (Boundary V4)
==============================================================================

The ledger is one flat folder on the user's computer, ~/Boundary/ledger:
  - dated, append-only files named time-then-role, such as
    2026-11-18_1530_ledger.md (written by the ledger agent) and
    2026-11-18_1604_auditor.md (written by the auditor). Old files are never edited.
  - LIVE.md: one status line per active directive. The only file ever rewritten,
    and only by the ledger agent.

Each file holds blocks:
  ## D-0042            a directive: author, type, what, why, checks, due, expiry, authority, ...
  ## VERDICT D-0042    an auditor verdict: confirmed, stale, contradicted or unverifiable
  ## UPDATE D-0042     the ledger applying a verdict, closing or expiring a directive

The current state is rebuilt by replaying every file in order, so the dated
files stay the single source of truth. The clerical work (next ID, file names,
append-only writes, LIVE.md) is done here in code, never by an LLM.

LEDGER_COMMON (the format, the replay and the read) is shared with the auditor's
tool, auditor_execution.py, so the format is defined once. Every value travels
inside one base64 block, so nothing an LLM writes can become code. Standard
library only.
"""

import base64
import json
from typing import Any, Dict

RESULT_MARKER = "BOUNDARY_RESULT:"

# The format and the replay, shared by the ledger's and the auditor's tools.
LEDGER_COMMON = r'''
import base64, datetime, json, re
from pathlib import Path

P = json.loads(base64.b64decode("__PAYLOAD__").decode("utf-8"))
LEDGER = Path.home() / "Boundary" / "ledger"
TYPES = ["Event", "Done", "Waiting", "Promised", "Document", "Deadline"]
CHECKS = ["EVENT_EXISTS", "REPLY_RECEIVED", "NOT_SUPERSEDED", "FILE_EXISTS", "SENT_EXISTS"]
VERDICTS = ["confirmed", "stale", "contradicted", "unverifiable"]
DEFAULT_DAYS = {"Event": 7, "Done": 3, "Waiting": 7, "Promised": 7, "Document": 7, "Deadline": 7}
FIELDS = ["author", "type", "what", "why", "checks", "due", "expiry", "authority", "created", "supersedes", "source"]
UPDATABLE = ["status", "authority", "expiry", "last_checked", "last_verdict", "closed_reason"]
NOW = datetime.datetime.now().replace(microsecond=0)
TODAY = NOW.date()
STAMP = NOW.strftime("%Y-%m-%dT%H:%M")
DAY = datetime.timedelta(days=1)


def out(result):
    print("BOUNDARY_RESULT:" + json.dumps(result))


def one_line(value):
    if isinstance(value, (list, tuple)):
        value = "; ".join(str(v) for v in value)
    return re.sub(r"\s+", " ", str(value if value is not None else "")).strip()


def parse_date(text):
    try:
        return datetime.date.fromisoformat(str(text).strip()[:10])
    except Exception:
        return None


def files_in_order():
    if not LEDGER.exists():
        return []
    files = [p for p in LEDGER.glob("*.md") if p.name != "LIVE.md"]
    return sorted(files, key=lambda p: (p.name[:15], p.stat().st_mtime_ns, p.name))


def blocks_of(path):
    blocks, current = [], None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            current = {"_header": line[3:].strip(), "_file": path.name}
            blocks.append(current)
        elif current is not None and ":" in line:
            key, _, value = line.partition(":")
            current[key.strip().lower()] = value.strip()
    return blocks


def replay():
    ds, max_id = {}, 0
    for path in files_in_order():
        for b in blocks_of(path):
            head = b["_header"].split()
            if len(head) == 1 and re.fullmatch(r"D-\d{4,}", head[0]):
                did = head[0]
                max_id = max(max_id, int(did[2:]))
                d = {k: b.get(k, "") for k in FIELDS}
                d.update({"id": did, "file": b["_file"], "status": "active", "last_checked": "",
                          "last_verdict": "", "closed_reason": "", "pending": [],
                          "history": ["written " + b.get("created", "")]})
                ds[did] = d
                old = d["supersedes"]
                if old in ds and ds[old]["status"] != "closed":
                    ds[old]["status"] = "closed"
                    ds[old]["closed_reason"] = "superseded by " + did
                    ds[old]["history"].append("superseded by " + did)
            elif len(head) == 2 and head[1] in ds and head[0] == "VERDICT":
                v = {k: b.get(k, "") for k in ("verdict", "evidence", "checks_run", "checked", "note")}
                v["file"] = b["_file"]
                ds[head[1]]["pending"].append(v)
                ds[head[1]]["history"].append("verdict %s %s" % (v["verdict"], v["checked"]))
            elif len(head) == 2 and head[1] in ds and head[0] == "UPDATE":
                d = ds[head[1]]
                for k in UPDATABLE:
                    if b.get(k):
                        d[k] = b[k]
                d["pending"] = []
                d["history"].append("update %s %s" % (b.get("status", ""), b.get("applied", "")))
    return ds, max_id


def view(d):
    v = {k: d.get(k, "") for k in ["id", "status", "author", "type", "what", "why", "checks", "due", "expiry",
                                     "authority", "created", "supersedes", "source", "last_checked",
                                     "last_verdict", "closed_reason", "file"]}
    exp, due = parse_date(d.get("expiry")), parse_date(d.get("due"))
    v["suspect"] = not d.get("why")
    v["expired"] = bool(exp and exp < TODAY and d.get("author") != "human")
    v["due_within_2_days"] = bool(due and due <= TODAY + 2 * DAY)
    v["pending_verdicts"] = d.get("pending", [])
    v["history"] = d.get("history", [])[-6:]
    return v


def new_file(role):
    LEDGER.mkdir(parents=True, exist_ok=True)
    stem = NOW.strftime("%Y-%m-%d_%H%M") + "_" + role
    path, n = LEDGER / (stem + ".md"), 2
    while path.exists():
        path, n = LEDGER / ("%s_%d.md" % (stem, n)), n + 1
    return path


def write_blocks(role, blocks):
    path = new_file(role)
    path.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")
    return path.name


def op_read():
    ds, _ = replay()
    ids = [one_line(i) for i in (P.get("ids") or [])]
    if ids:
        chosen = [ds[i] for i in ids if i in ds]
        missing = [i for i in ids if i not in ds]
    else:
        statuses = ("active", "stale", "closed") if P.get("include_closed") else ("active", "stale")
        chosen = [d for d in ds.values() if d["status"] in statuses]
        missing = []
    live_path = LEDGER / "LIVE.md"
    live = live_path.read_text(encoding="utf-8") if live_path.exists() else "(no LIVE.md yet: the ledger is empty)"
    out({"ok": True, "op": "read", "folder": str(LEDGER), "today_local": TODAY.isoformat(),
         "now_local": NOW.strftime("%Y-%m-%d %H:%M"), "live": live,
         "directives": [view(d) for d in sorted(chosen, key=lambda x: x["id"])], "missing_ids": missing})


def dispatch(ops):
    try:
        op = ops.get(P.get("op"))
        if op is None:
            out({"ok": False, "error": "Unknown op: use " + ", ".join(ops)})
        else:
            op()
    except Exception as e:
        out({"ok": False, "error": "%s: %s" % (type(e).__name__, e)})
'''

# The ledger agent's own operations.
_LEDGER_OPS = r'''

def build_live(ds):
    rows = sorted((d for d in ds.values() if d["status"] in ("active", "stale")), key=lambda d: d["id"])
    lines = ["# LIVE",
             "Active directives, one line each. Rewritten by Boundary's ledger agent after every change; "
             "the dated files are the record.",
             "Updated " + NOW.strftime("%Y-%m-%d %H:%M"), ""]
    for d in rows:
        last = d["last_verdict"] or ("checked " + d["last_checked"] if d["last_checked"] else "never checked")
        parts = [d["id"], d["type"] or "?", "due " + (d["due"] or "-"), "expiry " + (d["expiry"] or "-"),
                 d["author"] or "agent", d["authority"] or "-", "last: " + last]
        if d["status"] == "stale":
            parts.append("STALE: awaiting correction")
        if d["pending"]:
            parts.append("%d verdict(s) to apply" % len(d["pending"]))
        if not d["why"]:
            parts.append("SUSPECT: no why")
        parts.append(d["file"])
        lines.append(" | ".join(parts))
    if not rows:
        lines.append("(no active directives)")
    LEDGER.mkdir(parents=True, exist_ok=True)
    text = "\n".join(lines) + "\n"
    (LEDGER / "LIVE.md").write_text(text, encoding="utf-8")
    return text


def op_write_directives():
    ds, max_id = replay()
    written, rejected, blocks = [], [], []
    next_id = max_id + 1
    for item in P.get("directives") or []:
        if not isinstance(item, dict):
            rejected.append({"item": str(item)[:200], "reason": "not an object"})
            continue
        what = one_line(item.get("what"))
        dtype = one_line(item.get("type")).capitalize()
        checks = [c.upper() for c in re.split(r"[,;\s]+", one_line(item.get("checks"))) if c]
        bad_checks = [c for c in checks if c not in CHECKS]
        supersedes = one_line(item.get("supersedes"))
        reason = ""
        if not what:
            reason = "missing 'what'"
        elif dtype not in TYPES:
            reason = "'type' must be one of " + ", ".join(TYPES)
        elif bad_checks:
            reason = "unknown checks " + ", ".join(bad_checks) + "; use " + ", ".join(CHECKS)
        elif supersedes and supersedes not in ds:
            reason = "supersedes unknown directive " + supersedes
        if reason:
            rejected.append({"what": what, "reason": reason})
            continue
        author = "human" if one_line(item.get("author")).lower() == "human" else "agent"
        # Agent-authored directives always start reversible-only; wider authority is earned by outcome.
        authority = "full" if author == "human" else "reversible-only"
        due = parse_date(item.get("due"))
        expiry = parse_date(item.get("expiry")) or ((due + DAY) if due else TODAY + DEFAULT_DAYS[dtype] * DAY)
        did = "D-%04d" % next_id
        next_id += 1
        rec = {"author": author, "type": dtype, "what": what, "why": one_line(item.get("why")),
               "checks": ", ".join(checks), "due": due.isoformat() if due else "", "expiry": expiry.isoformat(),
               "authority": authority, "created": STAMP, "supersedes": supersedes,
               "source": one_line(item.get("source"))}
        blocks.append("\n".join(["## " + did] + ["%s: %s" % (k, rec[k]) for k in FIELDS if rec[k] or k == "why"]))
        written.append(dict(rec, id=did, suspect=not rec["why"]))
    if not blocks:
        out({"ok": False, "error": "No valid directive to write", "rejected": rejected})
        return
    name = write_blocks("ledger", blocks)
    ds, _ = replay()
    out({"ok": True, "op": "write_directives", "file": name, "written": written, "rejected": rejected,
         "live": build_live(ds), "today_local": TODAY.isoformat()})


def op_apply():
    ds, _ = replay()
    blocks, applied, needs_correction, ask_counterpart, expired = [], [], [], [], []
    for did in sorted(ds):
        d = ds[did]
        if d["status"] == "closed":
            continue
        upd = None
        if d["pending"]:
            v = d["pending"][-1]
            verdict = v["verdict"]
            short = "%s %s" % (verdict, NOW.strftime("%m-%d"))
            if verdict == "confirmed":
                upd = {"status": "active", "last_checked": TODAY.isoformat(), "last_verdict": short}
            elif verdict == "stale":
                upd = {"status": "stale", "last_checked": TODAY.isoformat(), "last_verdict": short}
                needs_correction.append(dict(view(d), verdict_note=v["note"], verdict_evidence=v["evidence"]))
            elif verdict == "contradicted":
                upd = {"status": "closed", "last_checked": TODAY.isoformat(), "last_verdict": short,
                       "closed_reason": "contradicted: " + (v["note"] or v["evidence"])[:200]}
            elif verdict == "unverifiable":
                upd = {"status": "active", "authority": "reversible-only", "last_checked": TODAY.isoformat(),
                       "last_verdict": short}
                due = parse_date(d["due"])
                if due and due <= TODAY + 2 * DAY:
                    ask_counterpart.append(view(d))
            applied.append({"directive_id": did, "verdict": verdict})
        exp = parse_date((upd or {}).get("expiry") or d["expiry"])
        confirmed_now = bool(upd and upd.get("last_verdict", "").startswith("confirmed"))
        if confirmed_now and exp and exp <= TODAY:
            upd["expiry"] = (TODAY + DEFAULT_DAYS.get(d["type"], 7) * DAY).isoformat()
        elif d["author"] != "human" and exp and exp < TODAY and not (upd and upd["status"] == "closed"):
            upd = dict(upd or {}, status="closed",
                       closed_reason="expired %s without re-confirmation" % exp.isoformat())
            expired.append(did)
        if upd:
            blocks.append("\n".join(["## UPDATE " + did] + ["%s: %s" % (k, one_line(v)) for k, v in upd.items()]
                                    + ["applied: " + STAMP]))
    name = write_blocks("ledger", blocks) if blocks else ""
    ds, _ = replay()
    out({"ok": True, "op": "apply", "file": name, "applied": applied, "needs_correction": needs_correction,
         "ask_counterpart": ask_counterpart, "expired": expired, "live": build_live(ds),
         "today_local": TODAY.isoformat()})


def op_close():
    ds, _ = replay()
    items = P.get("closures") or ([{"directive_id": P.get("directive_id"), "reason": P.get("reason"),
                                     "evidence": P.get("evidence")}] if P.get("directive_id") else [])
    closed, rejected, blocks = [], [], []
    for item in items:
        did = one_line(item.get("directive_id"))
        reason = one_line(item.get("reason"))
        if did not in ds or ds[did]["status"] == "closed":
            rejected.append({"directive_id": did, "reason": "no such open directive"})
            continue
        if not reason:
            rejected.append({"directive_id": did, "reason": "a closing reason is required"})
            continue
        evidence = one_line(item.get("evidence"))
        text = "fulfilled: " + reason + ((" (" + evidence + ")") if evidence else "")
        blocks.append("\n".join(["## UPDATE " + did, "status: closed", "closed_reason: " + text,
                                 "applied: " + STAMP]))
        closed.append(did)
    if not blocks:
        out({"ok": False, "error": "Nothing closed", "rejected": rejected})
        return
    name = write_blocks("ledger", blocks)
    ds, _ = replay()
    out({"ok": True, "op": "close", "file": name, "closed": closed, "rejected": rejected, "live": build_live(ds)})


dispatch({"read": op_read, "write_directives": op_write_directives, "apply": op_apply, "close": op_close})
'''


def compose(ops_source: str, op: str, params: Dict[str, Any]) -> str:
    """Python code for BridgeQuery.execute_python: the shared format, then one tool's ops.
    All values ride in one base64 block."""
    payload = dict(params or {})
    payload["op"] = op
    blob = base64.b64encode(json.dumps(payload, ensure_ascii=False).encode("utf-8")).decode("ascii")
    return LEDGER_COMMON.replace("__PAYLOAD__", blob) + "\n" + ops_source


def build_ledger_code(op: str, params: Dict[str, Any]) -> str:
    """The ledger agent's tool: op is read, write_directives, apply or close."""
    return compose(_LEDGER_OPS, op, params)


def parse_result(output: str) -> Dict[str, Any]:
    """The script's last BOUNDARY_RESULT line, as a dict."""
    for line in reversed((output or "").splitlines()):
        line = line.strip()
        if line.startswith(RESULT_MARKER):
            try:
                return json.loads(line[len(RESULT_MARKER):])
            except json.JSONDecodeError:
                break
    return {"ok": False, "error": "The ledger script returned no result", "raw": (output or "")[-500:]}