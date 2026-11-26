"""
Email Reader Executor - Read email from the user's selected mail account

Works with any IMAP mailbox (QQ, 163, 126, Gmail, company mail) and, for
Microsoft accounts, classic Outlook. The mailbox is the one the user marked
as current in Boundary's Email Accounts panel (task_data["mailAccount"]),
never a guess from the login email.

Returns raw records, not summaries: Message-ID, In-Reply-To, References,
sender, recipients, date and body. V4's auditor cites these as evidence.

Callers that already know exactly what they want (the auditor, the ledger
agent) can skip the LLM by passing task_data["mailQuery"], e.g.
    {"mode": "message", "message_id": "<...>"}
    {"mode": "thread", "message_id": "<...>", "since": "2026-11-10"}
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict

from .base_executor import BaseExecutor
from ..execution import mail_client
from ..execution.llm_utils import llm_json


class EmailReaderExecutor(BaseExecutor):
    """Executor for reading email from the user's selected account via the bridge."""

    def __init__(self, mcp_manager, mcp_registry, model_client):
        super().__init__(mcp_manager, mcp_registry)
        self.logger = logging.getLogger(__name__)
        self.executor_name = "EmailReaderExecutor"
        self.model = model_client

    async def execute_task(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        results: Dict[str, Any] = {
            "status": "started",
            "executorUsed": self.executor_name,
            "emailsRead": [],
            "summary": "",
        }

        try:
            api_key = task_data.get("apiKey")
            account = task_data.get("mailAccount")
            description = task_data.get("description", "")
            context = task_data.get("context", {}) or {}
            user_request = context.get("userRequest", "")
            current_date = task_data.get("currentDate", datetime.now().strftime("%Y-%m-%d"))
            current_time = task_data.get("currentTime", datetime.now().strftime("%H:%M:%S"))

            self.logger.info(f"📧 Task: {description}")

            query = task_data.get("mailQuery")
            if not isinstance(query, dict):
                query = await self._extract_query(user_request, description, current_date, current_time)
            action, params = self._to_action(query, current_date)
            self.logger.info(f"✅ Mail query: action={action}, params={params}")

            data = await mail_client.run(api_key, account, action, params)
            emails = data.get("emails", [])

            results["emailsRead"] = emails
            results["account"] = data.get("account", "")
            results["status"] = "completed"
            if action == "get":
                results["summary"] = (f"✅ Found the email {params.get('message_id')}"
                                      if emails else f"⚠️ No email with ID {params.get('message_id')} was found")
            elif action == "thread":
                results["summary"] = f"✅ Found {len(emails)} email(s) in the thread and with its participants"
            else:
                results["summary"] = f"✅ Read {len(emails)} email(s) from {data.get('folder', 'Inbox')}"
            self.logger.info(results["summary"])

        except mail_client.MailError as e:
            self.logger.error(f"❌ Email reading failed: {e}")
            results["status"] = "error"
            results["error"] = str(e)
            results["summary"] = f"❌ Failed: {e}"
        except Exception as e:
            self.logger.error(f"❌ Email reading failed: {e}")
            results["status"] = "error"
            results["error"] = str(e)
            results["summary"] = f"❌ Failed: {e}"

        return results

    async def _extract_query(self, user_request: str, description: str,
                             current_date: str, current_time: str) -> Dict[str, Any]:
        system_prompt = f"""You extract email-reading parameters.

**CURRENT CONTEXT:**
- Today's date: {current_date}
- Current time: {current_time}

**Modes:**
- "recent"  = the latest emails
- "unread"  = only unread emails
- "today"   = emails received today ({current_date})
- "from"    = emails from one sender (put the address or name in "sender")
- "message" = one specific email by its Message-ID (put it in "message_id")
- "thread"  = an email's whole thread plus later mail with the same people
              (put its Message-ID in "message_id"; optional "since" date)

**Folder:** "inbox" (default) or "sent".

**Examples:**
- "Read my last 5 emails" → {{"mode": "recent", "count": 5, "folder": "inbox"}}
- "Show unread emails" → {{"mode": "unread", "count": 10, "folder": "inbox"}}
- "Emails from li@example.com" → {{"mode": "from", "sender": "li@example.com", "count": 10, "folder": "inbox"}}
- "What did I send today?" → {{"mode": "today", "count": 20, "folder": "sent"}}
- "Open email <abc@qq.com>" → {{"mode": "message", "message_id": "<abc@qq.com>"}}

**Output JSON format:**
{{"mode": "recent", "count": 5, "folder": "inbox", "sender": "", "message_id": "", "since": ""}}

**CRITICAL - Date Awareness:**
- Current date is {current_date}, NOT any date from your training data.
- "since" must be YYYY-MM-DD.

Return ONLY valid JSON."""

        prompt = f"""User request: {user_request}

Task description: {description}

Extract email reading parameters as JSON:"""

        self.logger.info("🤖 Extracting parameters from LLM...")
        response = await self.model.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            max_tokens=300,
            temperature=0.2,
        )
        return llm_json(response)

    @staticmethod
    def _to_action(query: Dict[str, Any], current_date: str):
        mode = str(query.get("mode") or "recent").lower()
        folder = "sent" if str(query.get("folder") or "").lower() == "sent" else "inbox"
        try:
            count = int(query.get("count") or 5)
        except (TypeError, ValueError):
            count = 5

        if mode in ("message", "get") and query.get("message_id"):
            return "get", {"message_id": query["message_id"]}
        if mode == "thread" and query.get("message_id"):
            params = {"message_id": query["message_id"]}
            if query.get("since"):
                params["since"] = query["since"]
            if query.get("participants"):
                params["participants"] = query["participants"]
            return "thread", params

        params: Dict[str, Any] = {"count": count, "folder": folder}
        if mode == "unread":
            params["unread"] = True
        if mode == "today":
            params["since"] = current_date
        elif query.get("since"):
            params["since"] = query["since"]
        if query.get("sender"):
            params["sender"] = query["sender"]
        return "read", params