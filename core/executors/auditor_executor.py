"""
Auditor Executor - Boundary V4's auditor agent ("owns whether it is still true")
================================================================================

Agents left to themselves drift: their notes come to say they sent, promised or
arranged things that never happened, or that have since been cancelled, and
better memory cannot fix that, because a memory store records a false belief
faithfully. The auditor is the fix. It checks each directive against records
that exist outside the agents' own notes (the mailbox, the sent folder, files
on disk) and appends one verdict: confirmed, stale, contradicted or
unverifiable. Notes are never evidence for themselves.

To the main Planner it is an ordinary executor. Inside, it runs a second-tier
loop through the orchestrator (run_second_tier_loop): it uses its own tool
(core/execution/auditor_execution.py) to read the ledger and append verdicts,
and dispatches read-only executors, or parallel sub-agents, to fetch evidence.

It is read-only. Its only write is appending verdicts, and the executors it may
dispatch are limited to readers (AUDITOR_EXECUTORS), enforced in code.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict

from .base_executor import BaseExecutor
from ..execution.bridge_query import BridgeQuery
from ..execution.auditor_execution import build_auditor_code, parse_result

SERVER_URL = os.getenv("BOUNDARY_SERVER_URL", "http://localhost:8770")

BRIEF_FIELDS = ("requirements", "expectedOutput", "directiveId", "directiveIds", "scope")

# The only executors the auditor (and its sub-agents) may use: readers, nothing that changes anything.
AUDITOR_EXECUTORS = ("EmailReaderExecutor", "FileSearchExecutor", "FileReaderExecutor",
                     "DirectoryListExecutor")

AUDITOR_PROMPT = """You are the AUDITOR AGENT in Boundary's multi-agent system. You own one question: is each directive still true? You check directives against records that exist outside the agents' own notes, and append one verdict per directive. You never decide what to do about a verdict; the ledger agent applies it.

YOUR TOOLS (use them with the "tool" move)
- read_ledger: {"tool": "read_ledger", "args": {"ids": ["D-0042"]}}, or "args": {} for every active directive. Returns LIVE.md, the directive records (what, why, type, checks, due, expiry, created, pending verdicts) and "today_local".
- append_verdicts: {"tool": "append_verdicts", "args": {"verdicts": [{"directive_id": "D-0042", "verdict": "confirmed", "evidence": "<msg id>; <other id>", "checks_run": "REPLY_RECEIVED, NOT_SUPERSEDED", "note": "One factual sentence"}]}}

THE EXECUTORS YOU DISPATCH (with the "executor" or "parallel" move; these and no others)
- EmailReaderExecutor: reads mail from the user's selected mailbox and returns raw records (Message-ID, In-Reply-To, References, sender, recipients, date, body). Give an exact "mailQuery":
  - {"mode": "message", "message_id": "<id@host>"}: one email by its Message-ID
  - {"mode": "thread", "message_id": "<id@host>", "since": "YYYY-MM-DD"}: its whole thread plus later mail with the same people
  - {"mode": "recent", "folder": "sent", "count": 10, "since": "YYYY-MM-DD"}
- FileSearchExecutor: finds files on the user's computer; returns full paths.
- DirectoryListExecutor: lists one folder.
- FileReaderExecutor: reads text files.

WHAT COUNTS AS EVIDENCE
- A matching outside record makes a claim a fact; a contradicting record makes it fiction; support from notes alone makes it unverifiable. The conversation, other directives and the directive itself are never evidence for themselves.
- The sent folder and the results of past actions (a returned Message-ID, a file that exists) prove what this system itself did.
- Inbound mail proves only what other people claim. A forged confirmation is possible; weigh it as a claim.
- Phone calls, meetings in person and WeChat are outside the evidence world: claims resting on them are unverifiable.
- The calendar cannot be read yet, so EVENT_EXISTS can only use the email thread (invitations, confirmations, cancellations); without one, the verdict is unverifiable.

YOUR PROCEDURE (always in this order)
1. Read the ledger with read_ledger for the directives in your brief. If the brief names none, read them all and audit those due within two days, past expiry, flagged STALE or never checked: at most 6 per run, earliest due first.
2. Fetch the primary evidence straight from each directive's "why" pointer. Fetch, don't search:
   - a Message-ID: EmailReaderExecutor with {"mode": "message", "message_id": "<...>"}
   - a file path: FileSearchExecutor or DirectoryListExecutor for existence, FileReaderExecutor for contents
   - an empty "why" (suspect): there is no pointer; look once for a matching outside record, and if there is none the verdict is unverifiable
3. Run the directive's named checks:
   - NOT_SUPERSEDED (for every directive with a Message-ID): EmailReaderExecutor with {"mode": "thread", "message_id": "<...>", "since": "<the directive's created date>"}. Look for later mail that cancels, reschedules or replaces the matter.
   - REPLY_RECEIVED: in that thread, a message from the counterpart dated after our sent message.
   - SENT_EXISTS: the message is in the sent folder (fetch it by Message-ID).
   - FILE_EXISTS: the file exists, and was modified after the directive was created if the claim needs that.
   - EVENT_EXISTS: see the calendar note above.
   When several directives need evidence, use one parallel round with one sub-agent per directive. Tell each exactly what to fetch, and to return Message-IDs, dates, senders and the matching sentences verbatim, with no summary.
4. Consult the conversation and other directives only if the evidence leaves something ambiguous. Evidence first, notes last.
5. Decide one verdict per directive:
   - confirmed: an outside record matches the claim and nothing supersedes it. You MUST cite the evidence ID you checked. No evidence ID, no confirmation.
   - stale: the claim was right but a detail has changed (a new time, a new address, a revised amount). Put the corrected detail and its evidence in the note.
   - contradicted: an outside record shows the claim is false or no longer needed (for a Waiting directive, the reply has arrived; the event was cancelled; the message was never sent; the file does not exist).
   - unverifiable: the records cannot settle it. This is a respectable answer: never say confirmed when you mean "found nothing wrong".
6. Append all verdicts with append_verdicts, then finish.

YOU ARE READ-ONLY
Never send, draft, schedule, create, move or change anything. Your only write is appending verdicts.

Your report lists each directive ID with its verdict and evidence IDs, verbatim.
"""


class AuditorExecutor(BaseExecutor):
    """Checks directives against outside evidence, through its own second-tier loop."""

    def __init__(self, mcp_manager, mcp_registry, model_client, orchestrator=None):
        super().__init__(mcp_manager, mcp_registry)
        self.logger = logging.getLogger(__name__)
        self.executor_name = "AuditorExecutor"
        self.model = model_client
        self.orchestrator = orchestrator
        self._api_key = None

    async def execute_task(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        results: Dict[str, Any] = {"status": "started", "executorUsed": self.executor_name, "summary": ""}
        self._api_key = task_data.get("apiKey")
        try:
            if self.orchestrator is None or not hasattr(self.orchestrator, "run_second_tier_loop"):
                raise RuntimeError("The auditor needs the orchestrator's second-tier loop to run.")

            # The orchestrator appends the whole execution history to every description;
            # the brief only needs the instruction itself.
            description = (task_data.get("description") or "").split("\n\n## COMPLETE EXECUTION HISTORY")[0]
            brief = {"description": description.strip()}
            brief.update({k: task_data[k] for k in BRIEF_FIELDS if k in task_data})

            tools = {
                "read_ledger": lambda a: self._tool("read", {"ids": a.get("ids") or [],
                                                              "include_closed": bool(a.get("include_closed"))}),
                "append_verdicts": lambda a: self._tool("append_verdicts", {"verdicts": a.get("verdicts") or []}),
            }
            run = await self.orchestrator.run_second_tier_loop(
                role=self.executor_name,
                system_prompt=AUDITOR_PROMPT,
                brief=json.dumps(brief, ensure_ascii=False, indent=2, default=str),
                task_data=task_data,
                tools=tools,
                allowed_executors=AUDITOR_EXECUTORS,
                model=self.model,
            )

            verdicts = []
            for r in run["results"]:
                verdicts += (r.get("toolResult") or {}).get("appended", [])

            results.update({
                "status": "completed" if run["finished"] else "error",
                "error": None if run["finished"] else run["report"],
                "summary": "🔎 Audit: " + (", ".join(f"{v['directive_id']} {v['verdict']}" for v in verdicts)
                                          or "no verdicts appended"),
                "executorFullResponse": run["report"],
                "auditReport": run["report"],
                "verdictsAppended": verdicts,
                "rounds": run["rounds"],
            })
            # Charge every round of the loop, not only the last model call.
            self.model.last_usage = {"total_tokens": run["tokens"]}
            self.logger.info(results["summary"])

        except Exception as e:
            self.logger.error(f"❌ Auditor failed: {e}", exc_info=True)
            results.update({"status": "error", "error": str(e), "summary": f"❌ Failed: {e}",
                            "executorFullResponse": f"Auditor failed: {e}"})
        return results

    async def _tool(self, op: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Run one auditor operation on the user's computer through the bridge."""
        bridge = BridgeQuery(api_key=self._api_key, server_url=SERVER_URL)
        raw = await bridge.execute_python(build_auditor_code(op, params), timeout=30, label=f"auditor-{op}")
        if not raw.get("output"):
            return {"ok": False, "error": raw.get("error") or "No reply from the bridge. Is it running?"}
        return parse_result(raw.get("output", ""))