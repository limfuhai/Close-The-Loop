"""
Task Executor - Create tasks in classic Outlook
Uses PowerShell COM automation with Base64 encoding

Every value from the LLM reaches PowerShell inside a base64-encoded JSON
blob, so none of it can become code. Outlook only: IMAP mailboxes have no
task list. (V4's directives and LIVE.md are Boundary's own task list.)
"""

from __future__ import annotations

import base64
import json
import logging
from datetime import datetime
from typing import Any, Dict

from .base_executor import BaseExecutor
from ..execution.bridge_query import BridgeQuery
from ..execution.llm_utils import llm_json


class TaskExecutor(BaseExecutor):
    """Executor for creating tasks in user's Outlook via bridge."""

    def __init__(self, mcp_manager, mcp_registry, model_client):
        super().__init__(mcp_manager, mcp_registry)
        self.logger = logging.getLogger(__name__)
        self.executor_name = "TaskExecutor"
        self.model = model_client

    async def execute_task(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute task creation on user's local Outlook."""

        results: Dict[str, Any] = {
            "status": "started",
            "executorUsed": self.executor_name,
            "tasksCreated": [],
            "summary": "",
        }

        try:
            api_key = task_data.get("apiKey")
            if not api_key:
                raise Exception("No API key provided - bridge access requires authentication")

            description = task_data.get("description", "")
            context = task_data.get("context", {}) or {}
            user_request = context.get("userRequest", "")
            current_date = task_data.get("currentDate", datetime.now().strftime("%Y-%m-%d"))

            self.logger.info(f"✅ Task: {description}")
            self.logger.info(f"📆 Current date: {current_date}")

            system_prompt = f"""You are a task parameter extractor for Outlook automation.

**CURRENT CONTEXT:**
- Today's date: {current_date}

Extract task parameters from the user's request.

**Examples:**
- "Create task to finish report by Friday" → {{"title": "Finish report", "dueDate": "YYYY-MM-DD", "priority": "normal", "notes": ""}}
- "Add high priority task: Call client tomorrow" → {{"title": "Call client", "dueDate": "YYYY-MM-DD", "priority": "high", "notes": ""}}

**Output JSON format:**
{{
    "title": "Task Title",
    "dueDate": "YYYY-MM-DD",
    "priority": "normal",
    "notes": ""
}}

**Priority levels:** "high", "normal" (default), "low"

**Important:**
- Parse relative dates ("tomorrow", "next week") from the current date: {current_date}
- dueDate is an empty string if not specified

Return ONLY valid JSON."""

            prompt = f"""User request: {user_request}

Task description: {description}

Extract task parameters as JSON:"""

            self.logger.info("🤖 Extracting task parameters from LLM...")
            response = await self.model.generate(
                prompt=prompt,
                system_prompt=system_prompt,
                max_tokens=400,
                temperature=0.3,
            )
            params = llm_json(response)

            title = str(params.get("title") or "New Task")
            due_date = str(params.get("dueDate") or "").strip()
            priority = str(params.get("priority") or "normal").lower()
            notes = str(params.get("notes") or "")
            priority_value = {"high": 2, "normal": 1, "low": 0}.get(priority, 1)

            if due_date:
                try:
                    datetime.strptime(due_date[:10], "%Y-%m-%d")
                    due_date = due_date[:10]
                except ValueError:
                    self.logger.warning(f"⚠️ Ignoring unreadable due date: {due_date}")
                    due_date = ""

            self.logger.info(f"✅ Parameters: title='{title}', dueDate={due_date}, priority={priority}")

            command = self._build_task_command({
                "title": title,
                "dueDate": due_date,
                "priority": priority_value,
                "notes": notes,
            })

            query = BridgeQuery(api_key=api_key)
            self.logger.info("🌉 Creating task via Outlook...")
            result = await query.execute_bash(command=command, timeout=30)

            output = (result.get("output") or "").strip()
            if not result["success"] or "created successfully" not in output.lower():
                raise Exception(f"Failed to create task: {result.get('error') or output}")

            results["tasksCreated"] = [{
                "title": title,
                "dueDate": due_date,
                "priority": priority,
                "notes": notes,
                "status": "created",
            }]
            results["status"] = "completed"
            results["summary"] = f"✅ Created task '{title}'" + (f" due {due_date}" if due_date else "")
            self.logger.info("✅ Task created successfully")

        except Exception as e:
            self.logger.error(f"❌ Task creation failed: {e}")
            results["status"] = "error"
            results["error"] = str(e)
            results["summary"] = f"❌ Failed: {e}"

        return results

    def _build_task_command(self, params: Dict[str, Any]) -> str:
        payload = base64.b64encode(json.dumps(params, ensure_ascii=False).encode("utf-8")).decode("ascii")
        # The reminder goes off at 9am on the due date. (Outlook treats an
        # unset due date as 1 January 4501, so the old "if ($task.DueDate)"
        # test was always true.)
        script = f"""
$ErrorActionPreference = 'Stop'
$P = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{payload}')) | ConvertFrom-Json
$outlook = New-Object -ComObject Outlook.Application
$task = $outlook.CreateItem(3)
$task.Subject = [string]$P.title
$task.Importance = [int]$P.priority
$task.Status = 0
if ($P.notes) {{ $task.Body = [string]$P.notes }}
if ($P.dueDate) {{
    $due = [datetime]::ParseExact([string]$P.dueDate, 'yyyy-MM-dd', $null)
    $task.DueDate = $due
    $task.ReminderSet = $true
    $task.ReminderTime = $due.AddHours(9)
}}
$task.Save()
Write-Output 'Task created successfully'
""".strip()
        encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
        return f"powershell.exe -NoProfile -EncodedCommand {encoded}"