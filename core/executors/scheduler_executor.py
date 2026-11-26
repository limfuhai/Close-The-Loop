"""
Scheduler Executor - Boundary V4's scheduler agent ("owns when")
===============================================================

Prompts plus one tool (core/execution/scheduler_execution.py). Sets, lists and
cancels wake-ups on the user's computer through the bridge. At the chosen time
Windows Task Scheduler wakes the agent with the message it left itself.

Callers that know exactly what they want (the ledger agent) pass
task_data["schedulerTask"], e.g.
    {"action": "schedule", "message": "...", "delay_minutes": 30}
    {"action": "schedule", "message": "...", "local_time": "09:00", "day_offset": 1,
     "directive_id": "D-0042", "kind": "check"}
    {"action": "list"}
    {"action": "cancel", "wakeup_id": "W-1a2b3c4d"}
Otherwise an LLM reads the schedulerTask from the task description.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict

from .base_executor import BaseExecutor
from ..execution.bridge_query import BridgeQuery
from ..execution.llm_utils import llm_json
from ..execution.scheduler_execution import build_scheduler_code, parse_result

SERVER_URL = os.getenv("BOUNDARY_SERVER_URL", "http://localhost:8770")

EXTRACT_PROMPT = """You turn a scheduling instruction into JSON for Boundary's scheduler.

Current time: {now}. The user's own computer runs on its own local time zone, which may differ from the server's.

Actions:
- "schedule": set a wake-up. At that time the agent wakes and receives "message" as if the user had typed it.
- "list": show pending wake-ups.
- "cancel": remove one wake-up (put its ID, like W-1a2b3c4d, in "wakeup_id").

Time for "schedule" (use exactly one way):
- Relative ("in 5 minutes", "in 2 hours"): "delay_minutes".
- A clock time ("at 9am tomorrow", "Friday 3pm"): "local_time" as "HH:MM" (24-hour) plus either "day_offset" (0 = today, 1 = tomorrow) or "local_date" ("YYYY-MM-DD"). These are read on the user's computer, in its own time zone.

The message:
- A complete, standalone instruction to the agent's future self, in the user's words where possible.
- Include every specific the future run needs (email addresses, names, subjects, wording, file paths), because it will see only this message and the recent chat.
- Say what to do, not that it is a reminder: "Send an email to li@example.com saying ..." rather than "Remember the email".

Output exactly this shape:
{"action": "schedule", "message": "", "delay_minutes": null, "local_time": "", "day_offset": null, "local_date": "", "wakeup_id": ""}

Return ONLY valid JSON."""


class SchedulerExecutor(BaseExecutor):
    """Sets, lists and cancels wake-ups on the user's computer."""

    def __init__(self, mcp_manager, mcp_registry, model_client):
        super().__init__(mcp_manager, mcp_registry)
        self.logger = logging.getLogger(__name__)
        self.executor_name = "SchedulerExecutor"
        self.model = model_client

    async def execute_task(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        results: Dict[str, Any] = {
            "status": "started",
            "executorUsed": self.executor_name,
            "wakeups": [],
            "summary": "",
        }
        try:
            api_key = task_data.get("apiKey")
            agent_id = task_data.get("agentId") or ""

            spec = task_data.get("schedulerTask")
            if isinstance(spec, str):
                try:
                    spec = json.loads(spec)
                except json.JSONDecodeError:
                    spec = None
            if not isinstance(spec, dict):
                spec = await self._extract(task_data)
            action = str(spec.get("action") or "schedule").lower()
            self.logger.info(f"⏰ Scheduler action={action} spec={spec}")

            if action == "schedule":
                message = str(spec.get("message") or "").strip()
                if not message:
                    raise ValueError("A wake-up needs a message: the instruction the woken agent will act on.")
                if not agent_id:
                    raise ValueError("No agent to wake: this chat has no agent ID.")
                params: Dict[str, Any] = {
                    "api_key": api_key,
                    "api_base": SERVER_URL,
                    "agent_id": agent_id,
                    "message": message,
                    "directive_id": spec.get("directive_id") or "",
                    "kind": spec.get("kind") or "",
                }
                for key in ("delay_minutes", "run_at", "local_time", "local_date", "day_offset"):
                    if spec.get(key) not in (None, ""):
                        params[key] = spec[key]
            elif action == "cancel":
                params = {"wakeup_id": spec.get("wakeup_id") or ""}
            elif action == "list":
                params = {}
            else:
                raise ValueError(f"Unknown scheduler action '{action}': use schedule, cancel or list")

            code = build_scheduler_code(action, params)
            bridge = BridgeQuery(api_key=api_key, server_url=SERVER_URL)
            raw = await bridge.execute_python(code, timeout=30, label=f"scheduler-{action}")
            if not raw.get("output"):
                raise RuntimeError(raw.get("error") or "No reply from the bridge. Is it running?")
            data = parse_result(raw.get("output", ""))
            if not data.get("ok"):
                raise RuntimeError(data.get("error") or "The scheduler script failed")

            results["scheduler"] = data
            if action == "schedule":
                results["wakeups"] = [data]
                text = (f"✅ Wake-up {data['wakeup_id']} set for {data['run_at_local']} "
                        f"(local time on the user's computer, now {data['now_local']}). "
                        f"When it fires, agent {agent_id} wakes with this message:\n{data['message']}")
                if data.get("directive_id"):
                    text += f"\nLinked to directive {data['directive_id']} ({data.get('kind') or 'check'})."
                if data.get("note"):
                    text += f"\nNote: {data['note']}"
                if not data.get("bridge_path_known"):
                    text += ("\nNote: bridge.py's location could not be found, so if the bridge window is closed "
                             "at that time the agent will wake without access to the computer.")
                results["summary"] = f"✅ Wake-up {data['wakeup_id']} set for {data['run_at_local']}"
            elif action == "cancel":
                text = f"✅ Wake-up {data['wakeup_id']} cancelled."
                results["summary"] = text
            else:
                items = data.get("wakeups", [])
                results["wakeups"] = items
                lines = [f"- {w.get('wakeup_id')} at {w.get('run_at_local')} [{w.get('task_state')}]"
                         f"{' directive ' + w['directive_id'] if w.get('directive_id') else ''}: "
                         f"{str(w.get('message', ''))[:160]}" for w in items]
                text = f"{len(items)} pending wake-up(s):\n" + ("\n".join(lines) if lines else "(none)")
                results["summary"] = f"✅ {len(items)} pending wake-up(s)"

            results["executorFullResponse"] = text + "\n\nRaw result:\n" + json.dumps(data, ensure_ascii=False, indent=2)
            results["status"] = "completed"
            self.logger.info(results["summary"])

        except Exception as e:
            self.logger.error(f"❌ Scheduler failed: {e}")
            results["status"] = "error"
            results["error"] = str(e)
            results["summary"] = f"❌ Failed: {e}"
            results["executorFullResponse"] = f"Scheduler failed: {e}"

        return results

    async def _extract(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        context = task_data.get("context", {}) or {}
        now = f"{task_data.get('currentDate', '')} {task_data.get('currentTime', '')} (server clock, UTC)"
        system_prompt = EXTRACT_PROMPT.replace("{now}", now)
        prompt = (f"User request: {context.get('userRequest', '')}\n\n"
                  f"Task description: {task_data.get('description', '')}\n\n"
                  f"Requirements: {task_data.get('requirements', [])}\n\n"
                  f"Return the JSON:")
        response = await self.model.generate(
            prompt=prompt, system_prompt=system_prompt, max_tokens=800, temperature=0.2)
        try:
            spec = llm_json(response)
        except Exception:
            spec = None
        return spec if isinstance(spec, dict) else {}