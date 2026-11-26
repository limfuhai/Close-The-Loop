"""
Email Sender Executor - Send email from the user's selected mail account

IMAP/SMTP accounts (QQ, 163, 126, Gmail, company mail) send over SMTP and
make sure a copy lands in the Sent folder, which V4 treats as proof of what
was sent. Microsoft accounts send through classic Outlook.

The sending account is the one the user marked as current in Boundary's
Email Accounts panel. If it can't be used, sending stops with an error.
It never falls back to another account.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from .base_executor import BaseExecutor
from ..execution import mail_client
from ..execution.email_compose import compose


class EmailSenderExecutor(BaseExecutor):
    """Executor for sending email from the user's selected account via the bridge."""

    def __init__(self, mcp_manager, mcp_registry, model_client):
        super().__init__(mcp_manager, mcp_registry)
        self.logger = logging.getLogger(__name__)
        self.executor_name = "EmailSenderExecutor"
        self.model = model_client

    async def execute_task(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        results: Dict[str, Any] = {
            "status": "started",
            "executorUsed": self.executor_name,
            "emailsSent": [],
            "summary": "",
        }

        try:
            api_key = task_data.get("apiKey")
            account = task_data.get("mailAccount")
            self.logger.info(f"📤 Task: {task_data.get('description', '')}")

            # Check the account before spending an LLM call
            mail_client.resolve_account(account)

            params = await compose(self.model, task_data, intent="send")
            self.logger.info(
                f"✅ Parameters: to={params['to'] or '(from original)'}, "
                f"subject={params['subject'] or '(from original)'}, "
                f"reply={bool(params['reply_to_message_id'])}"
            )
            self.logger.warning(f"⚠️ EMAIL WILL BE SENT IMMEDIATELY FROM {account.get('address')}")

            data = await mail_client.run(api_key, account, "send", params)

            body = params["body"]
            sent_info = {
                "MessageID": data.get("MessageID", ""),
                "from": data.get("account", ""),
                "to": data.get("To", params["to"]),
                "cc": data.get("Cc", params["cc"]),
                "subject": data.get("Subject", params["subject"]),
                "body_preview": body[:200] + "..." if len(body) > 200 else body,
                "attachments": params["attachments"],
                "isReply": bool(params["reply_to_message_id"]),
                "inReplyTo": params["reply_to_message_id"],
                "sentCopy": data.get("SentCopy", ""),
                "status": "sent",
            }
            if data.get("Refused"):
                sent_info["refused"] = data["Refused"]

            results["emailsSent"] = [sent_info]
            results["status"] = "completed"
            results["summary"] = f"✅ Email sent to {sent_info['to']} with subject '{sent_info['subject']}'"
            if data.get("Refused"):
                results["summary"] += f" (refused by server for: {', '.join(data['Refused'])})"
            self.logger.info(results["summary"])

        except Exception as e:
            self.logger.error(f"❌ Email sending failed: {e}")
            results["status"] = "error"
            results["error"] = str(e)
            results["summary"] = f"❌ Failed: {e}"

        return results