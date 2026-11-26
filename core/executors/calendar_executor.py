"""
Calendar Executor - Create calendar events in classic Outlook
Uses PowerShell COM automation with Base64 encoding

Every value from the LLM (title, time, location, attendees) reaches
PowerShell inside a base64-encoded JSON blob, so none of it can become code.
Outlook only: IMAP mailboxes (QQ, 163, Gmail) have no calendar to write to.
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


class CalendarExecutor(BaseExecutor):
    """Executor for creating calendar events in user's Outlook via bridge."""

    def __init__(self, mcp_manager, mcp_registry, model_client):
        super().__init__(mcp_manager, mcp_registry)
        self.logger = logging.getLogger(__name__)
        self.executor_name = "CalendarExecutor"
        self.model = model_client

    async def execute_task(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute calendar event creation task on user's local Outlook."""

        results: Dict[str, Any] = {
            "status": "started",
            "executorUsed": self.executor_name,
            "eventsCreated": [],
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

            self.logger.info(f"📅 Task: {description}")
            self.logger.info(f"📆 Current date: {current_date}")

            system_prompt = f"""You are a calendar event parameter extractor for Outlook automation.

**CURRENT CONTEXT:**
- Today's date: {current_date}

Extract calendar event parameters from the user's request.

**Examples:**
- "Schedule meeting tomorrow at 2pm for 1 hour" → {{"title": "Meeting", "start": "YYYY-MM-DD 14:00", "duration": 60, "location": "", "attendees": ""}}
- "Create event 'Team Standup' on Monday 10am" → {{"title": "Team Standup", "start": "YYYY-MM-DD 10:00", "duration": 30, "location": "", "attendees": ""}}

**Output JSON format:**
{{
    "title": "Event Title",
    "start": "YYYY-MM-DD HH:MM",
    "duration": 60,
    "location": "",
    "attendees": ""
}}

**Important:**
- Parse relative dates ("tomorrow", "next Monday") from the current date: {current_date}
- Duration in minutes (default 60 if not specified)
- Attendees as semicolon-separated emails (optional)

Return ONLY valid JSON."""

            prompt = f"""User request: {user_request}

Task description: {description}

Extract calendar event parameters as JSON:"""

            self.logger.info("🤖 Extracting event parameters from LLM...")
            response = await self.model.generate(
                prompt=prompt,
                system_prompt=system_prompt,
                max_tokens=500,
                temperature=0.3,
            )
            params = llm_json(response)

            title = str(params.get("title") or "New Event")
            start = str(params.get("start") or "").strip()
            location = str(params.get("location") or "")
            attendees = str(params.get("attendees") or "")
            try:
                duration = int(params.get("duration") or 60)
            except (TypeError, ValueError):
                duration = 60

            if not start:
                raise Exception("No start time specified for calendar event")
            try:
                datetime.strptime(start, "%Y-%m-%d %H:%M")
            except ValueError:
                raise Exception(f"Start time '{start}' is not in YYYY-MM-DD HH:MM form")

            self.logger.info(f"✅ Parameters: title='{title}', start={start}, duration={duration}min")

            command = self._build_calendar_command({
                "title": title,
                "start": start,
                "duration": duration,
                "location": location,
                "attendees": attendees,
            })

            query = BridgeQuery(api_key=api_key)
            self.logger.info("🌉 Creating calendar event via Outlook...")
            result = await query.execute_bash(command=command, timeout=30)

            output = (result.get("output") or "").strip()
            if not result["success"] or "created successfully" not in output.lower():
                raise Exception(f"Failed to create event: {result.get('error') or output}")

            results["eventsCreated"] = [{
                "title": title,
                "start": start,
                "duration_minutes": duration,
                "location": location,
                "attendees": attendees,
                "status": "created",
            }]
            results["status"] = "completed"
            results["summary"] = f"✅ Created calendar event '{title}' at {start}"
            self.logger.info("✅ Event created successfully")

        except Exception as e:
            self.logger.error(f"❌ Calendar event creation failed: {e}")
            results["status"] = "error"
            results["error"] = str(e)
            results["summary"] = f"❌ Failed: {e}"

        return results

    def _build_calendar_command(self, params: Dict[str, Any]) -> str:
        payload = base64.b64encode(json.dumps(params, ensure_ascii=False).encode("utf-8")).decode("ascii")
        script = f"""
$ErrorActionPreference = 'Stop'
$P = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{payload}')) | ConvertFrom-Json
$outlook = New-Object -ComObject Outlook.Application
$appointment = $outlook.CreateItem(1)
$appointment.Subject = [string]$P.title
$appointment.Start = [datetime]::ParseExact([string]$P.start, 'yyyy-MM-dd HH:mm', $null)
$appointment.Duration = [int]$P.duration
$appointment.Location = [string]$P.location
if ($P.attendees) {{
    foreach ($email in ([string]$P.attendees -split '[;,]')) {{
        if ($email.Trim()) {{ [void]$appointment.Recipients.Add($email.Trim()) }}
    }}
    $appointment.MeetingStatus = 1
}}
$appointment.ReminderSet = $true
$appointment.ReminderMinutesBeforeStart = 15
$appointment.Save()
Write-Output 'Event created successfully'
""".strip()
        encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
        return f"powershell.exe -NoProfile -EncodedCommand {encoded}"