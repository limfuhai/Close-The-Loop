"""
core/execution/email_compose.py

Shared by EmailDraftExecutor and EmailSenderExecutor: asks the LLM for the
message's recipient, subject, body and attachments, and for the Message-ID
of the email being replied to, if any.

The sending account is never the LLM's choice. It comes from the account
the user selected (task_data["mailAccount"]).
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from .llm_utils import llm_json


def _previous(previous_results: List[Dict[str, Any]]):
    email_content = None
    for result in reversed(previous_results):
        if "emailContent" in result:
            email_content = result["emailContent"]
            break
    emails_from_reader: List[Dict[str, Any]] = []
    for result in reversed(previous_results):
        if result.get("executorUsed") == "EmailReaderExecutor":
            emails_from_reader = result.get("emailsRead", []) or []
            break
    return email_content, emails_from_reader


def _attachment_list(params: Dict[str, Any]) -> List[str]:
    paths = params.get("attachments") or []
    if isinstance(paths, str):
        paths = [paths]
    legacy = params.get("attachment_path")
    if legacy:
        paths = list(paths) + [legacy]
    return [str(p) for p in paths if p]


async def compose(model, task_data: Dict[str, Any], intent: str) -> Dict[str, Any]:
    """intent is "send" or "draft". Returns mail_client parameters."""
    description = task_data.get("description", "")
    context = task_data.get("context", {}) or {}
    user_request = context.get("userRequest", "")
    previous_results = context.get("previousResults", []) or []
    account = task_data.get("mailAccount") or {}

    email_content, emails_from_reader = _previous(previous_results)

    verb = "SEND an email immediately" if intent == "send" else "create an email DRAFT"
    system_prompt = f"""You extract email parameters. The user wants to {verb}.
The email goes out from the user's selected account ({account.get('address', 'their account')}).
Never choose or change the sending account.

**Replies:**
- If the user wants to reply to an email the reader agent found, set "replyToMessageID"
  to that email's exact "MessageID" value (copy it character for character).
- For a reply you may leave "to" and "subject" empty; they are taken from the original.

**New emails:** fill "to" with the recipient address(es) the user gave.

**Examples:**
- "Email john@example.com about the meeting" → {{"to": "john@example.com", "cc": "", "subject": "Meeting", "body": "...", "attachments": [], "replyToMessageID": ""}}
- "Reply to that email saying I'll come" → {{"to": "", "cc": "", "subject": "", "body": "...", "attachments": [], "replyToMessageID": "<MessageID from the reader>"}}

**Output JSON format:**
{{
    "to": "recipient@example.com",
    "cc": "",
    "subject": "Email Subject",
    "body": "Email body...",
    "attachments": [],
    "replyToMessageID": ""
}}

- "attachments" is a list of full local file paths, only if the user asked to attach files.
- If a previous agent wrote content meant for this email, use it as the body.

Return ONLY valid JSON."""

    context_info = ""
    if email_content:
        context_info += f"\n\nPrevious agent generated this content:\n{email_content}"
    if emails_from_reader:
        shown = [
            {k: e.get(k) for k in ("MessageID", "From", "SenderEmail", "Subject", "ReceivedTime")}
            | {"Body": (e.get("Body") or "")[:600]}
            for e in emails_from_reader[:5]
        ]
        context_info += f"\n\nEmails the reader agent found:\n{json.dumps(shown, ensure_ascii=False, indent=2)}"

    prompt = f"""User request: {user_request}

Task description: {description}{context_info}

Extract email parameters as JSON:"""

    response = await model.generate(
        prompt=prompt,
        system_prompt=system_prompt,
        max_tokens=1200,
        temperature=0.3,
    )
    params = llm_json(response)

    to = str(params.get("to") or "").strip()
    cc = str(params.get("cc") or "").strip()
    subject = str(params.get("subject") or "").strip()
    body = str(params.get("body") or "")
    reply_id = str(params.get("replyToMessageID") or "").strip()

    # Older prompt placeholders, still honoured
    if "{USE_PREVIOUS_CONTENT}" in body and email_content:
        body = email_content
    if "{FROM_PREVIOUS_EMAIL}" in to or to == "{USE_PREVIOUS_CONTENT}":
        to = (emails_from_reader[0].get("SenderEmail", "") if emails_from_reader else "")
    if "{PREVIOUS_SUBJECT}" in subject and emails_from_reader:
        subject = "Re: " + (emails_from_reader[0].get("Subject") or "")

    # A reply ID must be one the reader actually returned, or at least look
    # like a Message-ID. An invented one would fail later anyway.
    if reply_id and "@" not in reply_id:
        reply_id = ""

    if not reply_id and not to:
        raise ValueError("No recipient email address specified")

    return {
        "to": to,
        "cc": cc,
        "subject": subject,
        "body": body,
        "attachments": _attachment_list(params),
        "reply_to_message_id": reply_id,
    }