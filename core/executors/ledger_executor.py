"""
Ledger Executor - Boundary V4's ledger agent ("owns what and why")
==================================================================

The ledger agent writes directives: concrete future actions an agent sets for
itself, each resting on exact evidence (a Message-ID, a file path) so that the
auditor can check it later. It never decides whether a directive is true; it
applies the auditor's verdicts as they stand. This is how agents author their
own future work without a human checking each instruction: every instruction
is written to be verified.

To the main Planner it is an ordinary executor. Inside, it runs a second-tier
loop through the orchestrator (run_second_tier_loop): it uses its own tool
(core/execution/ledger_execution.py) to read, write, apply and close
directives, and dispatches other executors, above all the SchedulerExecutor,
which sets each directive's check and expiry wake-ups.

It is called on three occasions, named in task_data["occasion"]:
  post_task          after a task, to record what the task left owed
  apply              after an audit, to apply the auditor's verdicts
  human_instruction  when the user gives a standing instruction
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict

from .base_executor import BaseExecutor
from ..execution.bridge_query import BridgeQuery
from ..execution.ledger_execution import build_ledger_code, parse_result

SERVER_URL = os.getenv("BOUNDARY_SERVER_URL", "http://localhost:8770")

BRIEF_FIELDS = ("requirements", "expectedOutput", "occasion", "directiveId", "directiveIds",
                "auditorRan", "taskResults", "finalSummary")

# The executors the ledger agent (and its sub-agents) dispatch.
LEDGER_EXECUTORS = ("SchedulerExecutor", "EmailReaderExecutor", "FileSearchExecutor",
                    "FileReaderExecutor", "DirectoryListExecutor")

LEDGER_PROMPT = """You are the LEDGER AGENT (also called the directive agent) in Boundary's multi-agent system. You own what is owed and why. You write directives: concrete future actions, each resting on exact evidence, so that the auditor can check them later. You never decide whether a directive is true; you apply the auditor's verdicts as they stand.

YOUR TOOLS (use them with the "tool" move)
- read_ledger: {"tool": "read_ledger", "args": {"ids": ["D-0042"]}}, or "args": {} for every active directive. Returns LIVE.md, the directive records and "today_local" (the date on the user's computer).
- write_directives: {"tool": "write_directives", "args": {"directives": [ {...}, ... ]}}. The store assigns the IDs, writes a new dated file and rewrites LIVE.md.
- apply_verdicts: {"tool": "apply_verdicts", "args": {}}. Applies every pending auditor verdict and closes expired agent-authored directives. Returns "needs_correction", "ask_counterpart" and "expired".
- close_directive: {"tool": "close_directive", "args": {"directive_id": "D-0042", "reason": "follow-up drafted", "evidence": "<msg id>"}}.

THE DIRECTIVE FORMAT (the fields of each object in "directives")
- "what": ONE concrete action that a future agent can carry out ("Draft a follow-up to li@example.com about the contract if no reply has arrived").
- "type": one of Event, Done, Waiting, Promised, Document, Deadline.
- "why": exact pointers, verbatim: "sent msg <id@host>", "inbox msg <id@host>", "file C:\\Users\\name\\Documents\\report.docx". Never a description. If no pointer can be found, leave it empty: the directive is then suspect from birth.
- "checks": the named checks that confirm it. Waiting: REPLY_RECEIVED, NOT_SUPERSEDED. Promised: SENT_EXISTS, NOT_SUPERSEDED. Done: SENT_EXISTS. Document: FILE_EXISTS. Event: EVENT_EXISTS, NOT_SUPERSEDED. Deadline: REPLY_RECEIVED, NOT_SUPERSEDED.
- "due": "YYYY-MM-DD" when the action falls due, if known. "expiry": optional; the store applies a default per type.
- "author": "agent" for what you infer yourself, "human" for an instruction the user gave. Agent-authored directives start at authority "reversible-only" and lapse at expiry unless re-confirmed; human-authored ones get "full" and do not decay.
- "supersedes": the old ID, when this directive corrects a stale one.
- "source": a few words on where it came from.
One directive covers one action. Old files are never edited.

THE EXECUTORS YOU DISPATCH (with the "executor" or "parallel" move)
- SchedulerExecutor: sets a wake-up on the user's computer. At that time the agent wakes with the message, as if the user had typed it. "schedulerTask": {"action": "schedule", "message": "...", "local_date": "YYYY-MM-DD", "local_time": "09:00", "directive_id": "D-0042", "kind": "check"}; or "delay_minutes" for short delays; {"action": "list"}; {"action": "cancel", "wakeup_id": "W-1a2b3c4d"}.
- EmailReaderExecutor: reads mail from the user's selected mailbox and returns raw records (Message-ID, In-Reply-To, References, sender, recipients, date, body). "mailQuery": {"mode": "message", "message_id": "<id@host>"}; {"mode": "thread", "message_id": "<id@host>", "since": "YYYY-MM-DD"}; {"mode": "recent", "folder": "sent", "count": 5}.
- FileSearchExecutor, DirectoryListExecutor and FileReaderExecutor: find files, list folders, and read text files on the user's computer.

YOUR BRIEF NAMES ONE OF THREE OCCASIONS
A. "post_task": decide what the finished task left owed in the future.
   - Typical directives: we sent something that awaits a reply (Waiting); we promised something (Promised); a deadline was mentioned (Deadline); a meeting was arranged (Event); a document must be produced (Document).
   - You may also infer directives yourself from evidence (for example, a counterpart who has replied late before). A self-initiated directive still needs a "why" pointing at evidence.
   - Write nothing when nothing is owed. If the task only set a wake-up, that wake-up already carries the obligation: write no directive for it. If the task carried out an existing directive's action, close that directive instead of writing a new one.
   - If the brief shows the auditor ran in this task, handle occasion B first.
   - At most 3 new directives per review.
B. "apply": use apply_verdicts. Then:
   - for each directive in "needs_correction" (stale): write a corrected directive with "supersedes" set to the old ID, using the auditor's note and evidence, and schedule its wake-ups;
   - for each in "ask_counterpart" (unverifiable and due within two days): schedule a wake-up within the hour with "kind": "ask", whose message asks the woken agent to DRAFT a short check-in email to the counterpart about that directive ("Just checking we're still on for Thursday at 3pm?");
   - contradicted and expired directives are already closed by the store.
C. "human_instruction": record the user's standing instruction with "author": "human", in the user's own words where possible.

GETTING THE POINTERS
Take Message-IDs, file paths and dates verbatim from the raw task results in your brief. If a pointer is missing, dispatch EmailReaderExecutor or FileSearchExecutor and ask for the identifier verbatim.

AFTER WRITING DIRECTIVES, SCHEDULE THEIR WAKE-UPS
For every new directive, set two wake-ups with SchedulerExecutor (a parallel round works well):
- a check at its next check date (the due date, or about half-way to expiry if there is none), "kind": "check";
- a check at its expiry, "kind": "expiry".
Each carries "directive_id" and a message such as: "Audit directive D-0042 (Waiting: draft a follow-up to li@example.com if no reply on the contract). If the auditor confirms it and it is due, carry out its action within its authority (reversible-only means draft, never send), then have the ledger agent record the outcome."
Use "local_date" with "local_time" (the user's computer's time zone; read_ledger gives "today_local"), or "delay_minutes".

Your report lists every directive ID you wrote, corrected or closed, and every wake-up ID you scheduled.
"""


class LedgerExecutor(BaseExecutor):
    """Writes and maintains directives, through its own second-tier loop."""

    def __init__(self, mcp_manager, mcp_registry, model_client, orchestrator=None):
        super().__init__(mcp_manager, mcp_registry)
        self.logger = logging.getLogger(__name__)
        self.executor_name = "LedgerExecutor"
        self.model = model_client
        self.orchestrator = orchestrator
        self._api_key = None

    async def execute_task(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        results: Dict[str, Any] = {"status": "started", "executorUsed": self.executor_name, "summary": ""}
        self._api_key = task_data.get("apiKey")
        try:
            if self.orchestrator is None or not hasattr(self.orchestrator, "run_second_tier_loop"):
                raise RuntimeError("The ledger agent needs the orchestrator's second-tier loop to run.")

            # The orchestrator appends the whole execution history to every description;
            # the brief only needs the instruction itself.
            description = (task_data.get("description") or "").split("\n\n## COMPLETE EXECUTION HISTORY")[0]
            brief = {"description": description.strip()}
            brief.update({k: task_data[k] for k in BRIEF_FIELDS if k in task_data})
            brief.setdefault("occasion", "post_task")

            tools = {
                "read_ledger": lambda a: self._tool("read", {"ids": a.get("ids") or [],
                                                              "include_closed": bool(a.get("include_closed"))}),
                "write_directives": lambda a: self._tool("write_directives", {"directives": a.get("directives") or []}),
                "apply_verdicts": lambda a: self._tool("apply", {}),
                "close_directive": lambda a: self._tool("close", a),
            }
            run = await self.orchestrator.run_second_tier_loop(
                role=self.executor_name,
                system_prompt=LEDGER_PROMPT,
                brief=json.dumps(brief, ensure_ascii=False, indent=2, default=str),
                task_data=task_data,
                tools=tools,
                allowed_executors=LEDGER_EXECUTORS,
                model=self.model,
            )

            written, closed, wakeups = [], [], []
            for r in run["results"]:
                tool_out = r.get("toolResult") or {}
                written += [w.get("id") for w in tool_out.get("written", [])]
                closed += tool_out.get("closed", [])
                wakeups += [w.get("wakeup_id") for w in r.get("wakeups", []) if isinstance(w, dict)]

            results.update({
                "status": "completed" if run["finished"] else "error",
                "error": None if run["finished"] else run["report"],
                "summary": f"📒 Ledger: wrote {written or 'none'}, closed {closed or 'none'}, "
                           f"scheduled {wakeups or 'no'} wake-ups",
                "executorFullResponse": run["report"],
                "ledgerReport": run["report"],
                "directivesWritten": written,
                "directivesClosed": closed,
                "wakeupsScheduled": wakeups,
                "rounds": run["rounds"],
            })
            # Charge every round of the loop, not only the last model call.
            self.model.last_usage = {"total_tokens": run["tokens"]}
            self.logger.info(results["summary"])

        except Exception as e:
            self.logger.error(f"❌ Ledger agent failed: {e}", exc_info=True)
            results.update({"status": "error", "error": str(e), "summary": f"❌ Failed: {e}",
                            "executorFullResponse": f"Ledger agent failed: {e}"})
        return results

    async def _tool(self, op: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Run one ledger operation on the user's computer through the bridge."""
        bridge = BridgeQuery(api_key=self._api_key, server_url=SERVER_URL)
        raw = await bridge.execute_python(build_ledger_code(op, params), timeout=30, label=f"ledger-{op}")
        if not raw.get("output"):
            return {"ok": False, "error": raw.get("error") or "No reply from the bridge. Is it running?"}
        return parse_result(raw.get("output", ""))