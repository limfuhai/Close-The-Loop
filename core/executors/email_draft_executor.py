"""
Email Draft Executor - Save an email draft in the user's selected mail account

IMAP accounts (QQ, 163, 126, Gmail, company mail) get the draft saved
straight into the server's Drafts folder, so it appears in the user's mail
app and web mail. Microsoft accounts save through classic Outlook.

Drafts are the safe default for V4: nothing leaves the mailbox until a
person, or a directive with earned authority, sends it.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from .base_executor import BaseExecutor
from ..execution import mail_client
from ..execution.email_compose import compose


class EmailDraftExecutor(BaseExecutor):
    """Executor for saving email drafts in the user's selected account via the bridge."""

    def __init__(self, mcp_manager, mcp_registry, model_client):
        super().__init__(mcp_manager, mcp_registry)
        self.logger = logging.getLogger(__name__)
        self.executor_name = "EmailDraftExecutor"
        self.model = model_client

    async def execute_task(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        results: Dict[str, Any] = {
            "status": "started",
            "executorUsed": self.executor_name,
            "emailsDrafted": [],
            "summary": "",
        }

        try:
            api_key = task_data.get("apiKey")
            account = task_data.get("mailAccount")
            self.logger.info(f"✉️ Task: {task_data.get('description', '')}")

            mail_client.resolve_account(account)

            params = await compose(self.model, task_data, intent="draft")
            self.logger.info(
                f"✅ Parameters: to={params['to'] or '(from original)'}, "
                f"subject={params['subject'] or '(from original)'}, "
                f"reply={bool(params['reply_to_message_id'])}"
            )

            data = await mail_client.run(api_key, account, "draft", params)

            body = params["body"]
            draft_info = {
                "MessageID": data.get("MessageID", ""),
                "from": data.get("account", ""),
                "to": data.get("To", params["to"]),
                "cc": data.get("Cc", params["cc"]),
                "subject": data.get("Subject", params["subject"]),
                "body_preview": body[:200] + "..." if len(body) > 200 else body,
                "attachments": params["attachments"],
                "isReply": bool(params["reply_to_message_id"]),
                "inReplyTo": params["reply_to_message_id"],
                "status": "draft_created",
            }

            results["emailsDrafted"] = [draft_info]
            results["status"] = "completed"
            results["summary"] = f"✅ Created email draft to {draft_info['to']} with subject '{draft_info['subject']}'"
            self.logger.info(results["summary"])

        except Exception as e:
            self.logger.error(f"❌ Email drafting failed: {e}")
            results["status"] = "error"
            results["error"] = str(e)
            results["summary"] = f"❌ Failed: {e}"

        return results