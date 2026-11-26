"""
Auditor Execution - the auditor agent's tool (Boundary V4)
=========================================================

The auditor reads the ledger and appends verdicts. It does nothing else to it:
it never edits a directive and never rewrites LIVE.md. Its verdicts go into
its own dated, append-only files (e.g. 2026-11-18_1604_auditor.md) as
"## VERDICT D-0042" blocks, which the ledger agent applies afterwards.

One rule is enforced here in code rather than left to the model: a
"confirmed" verdict that cites no evidence ID is recorded as "unverifiable".
No evidence, no confirmation.

The ledger format and the read are shared with the ledger agent's tool
(ledger_execution.LEDGER_COMMON), so the format is defined once.
"""

from typing import Any, Dict

from .ledger_execution import compose, parse_result  # noqa: F401  (parse_result re-exported for the executor)

_AUDITOR_OPS = r'''

def op_append_verdicts():
    ds, _ = replay()
    accepted, rejected, blocks = [], [], []
    for item in P.get("verdicts") or []:
        if not isinstance(item, dict):
            rejected.append({"item": str(item)[:200], "reason": "not an object"})
            continue
        did = one_line(item.get("directive_id"))
        verdict = one_line(item.get("verdict")).lower()
        evidence = one_line(item.get("evidence"))
        note = one_line(item.get("note"))
        if did not in ds:
            rejected.append({"directive_id": did, "reason": "no such directive"})
            continue
        if verdict not in VERDICTS:
            rejected.append({"directive_id": did, "reason": "verdict must be one of " + ", ".join(VERDICTS)})
            continue
        if verdict == "confirmed" and not evidence:
            verdict = "unverifiable"
            note = ("Downgraded from confirmed: no evidence ID was cited. " + note).strip()
        blocks.append("\n".join(["## VERDICT " + did, "verdict: " + verdict, "evidence: " + evidence,
                                 "checks_run: " + one_line(item.get("checks_run")), "checked: " + STAMP,
                                 "note: " + note]))
        accepted.append({"directive_id": did, "verdict": verdict, "evidence": evidence, "note": note})
    if not blocks:
        out({"ok": False, "error": "No valid verdict to append", "rejected": rejected})
        return
    name = write_blocks("auditor", blocks)
    out({"ok": True, "op": "append_verdicts", "file": name, "appended": accepted, "rejected": rejected})


dispatch({"read": op_read, "append_verdicts": op_append_verdicts})
'''


def build_auditor_code(op: str, params: Dict[str, Any]) -> str:
    """The auditor's tool: op is read or append_verdicts."""
    return compose(_AUDITOR_OPS, op, params)