# core/executors/in_chat_memory_executor.py
"""
Boundary V2 — Tier 1 In-Chat Memory Executor

Purpose: Give agents (especially V3 sub-agents) a "show me everything" view of
the current conversation as persisted in Supabase. Sub-agents running in parallel
each write their results to the shared conversation thread as they complete; any
sub-agent that needs to know what another has done calls this executor.

For regular (non-parallel) agents, this executor answers requests like:
"Go back and check what we decided earlier in this conversation."

Supabase query (single call):
  SELECT role, content, timestamp
  FROM messages
  WHERE agent_id = :agent_id
  ORDER BY timestamp ASC

The agent decides when to poll (polling pattern, not websockets).
Supabase transactional consistency guarantees: once a sub-agent's INSERT
commits, the next SELECT from any connection sees it immediately.
"""

import json
import logging
from typing import Dict, Any
from datetime import datetime
from .base_executor import BaseExecutor
from core.execution.memory_execution import fetch_agent_messages
from comprehensive_formatting_prompts import IN_CHAT_MEMORY_EXECUTOR_PROMPT

# ── Module-level prompt constants ─────────────────────────────────────────────

# Header rendered at the top of the fetched memory block sent to the LLM.
MEMORY_HEADER_TEMPLATE = (
    "## Conversation Memory — {count} messages (of {total} total)\n"
    "Agent ID: {agent_id}\n"
)

# Stub message when V2 schema is not yet deployed.
MEMORY_STUB_NOT_AVAILABLE = (
    "⚠️ In-chat memory is not yet available. "
    "Reason: {reason}. "
    "The messages table needs to be reachable before this executor functions."
)

# Message when the conversation is empty.
MEMORY_EMPTY_CONVERSATION = (
    "No messages found for agent {agent_id}. "
    "The conversation may be empty or the agent ID may be incorrect."
)


class InChatMemoryExecutor(BaseExecutor):
    """
    Fetch the full message history of the current agent's conversation from Supabase.

    Primary use case: V3 sub-agents reading the shared conversation thread
    to see what parallel sibling agents have already contributed.

    Uses messages.agent_id (the actual production schema) rather than the
    planned V2 messages.conversation_id.
    """

    def __init__(self, mcp_manager, mcp_registry, model=None, supabase=None):
        super().__init__(mcp_manager, mcp_registry)
        self.model = model
        self.supabase = supabase
        self.logger = logging.getLogger(__name__)
        self.logger.info(
            "✅ Initialized InChatMemoryExecutor "
            f"[supabase={'connected' if supabase else 'NOT CONNECTED'}]"
        )

    async def execute_task(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Fetch conversation messages and format them for agent consumption.

        Expected task_data fields (set by Planner):
            agent_id (str):          The agent whose thread we should read.
                                     Planner gets this from the request context.
                                     Also accepted as 'conversation_id' for
                                     backwards compatibility.
            max_messages (int, opt): Limit results to the N most recent
                                     messages. Default: all.

        Returns:
            {
              "status": "completed" | "error",
              "executorUsed": "InChatMemoryExecutor",
              "agentId": str,
              "messageCount": int,          ← total messages in DB
              "messagesRead": [...],         ← structured for LLM consumption
              "executorFullResponse": str,   ← formatted for Summarizer
              "timestamp": str
            }
        """
        self.logger.info("=" * 70)
        self.logger.info("🧠 STARTING IN-CHAT MEMORY FETCH")
        self.logger.info("=" * 70)

        result = {
            "status": "started",
            "executorUsed": "InChatMemoryExecutor",
            "artifacts": [],
            "timestamp": datetime.now().isoformat()
        }

        # ── Extract parameters ────────────────────────────────────────────────
        executor_task = task_data.get("executorTask") or task_data
        context       = task_data.get("context", {})

        # Accept both agent_id and legacy conversation_id
        agent_id = (
            executor_task.get("agent_id")
            or executor_task.get("conversation_id")
            or task_data.get("agent_id")
            or task_data.get("conversation_id")
            or context.get("agent_id")
            or context.get("agentId")
        )
        max_messages = (
            executor_task.get("max_messages")
            or task_data.get("max_messages")
        )

        if not agent_id:
            self.logger.error("❌ No agent_id provided in task_data")
            result["status"] = "error"
            result["error"] = (
                "agent_id is required. "
                "Planner must include 'agent_id' in executorTask."
            )
            result["executorFullResponse"] = result["error"]
            return result

        self.logger.info(f"📖 Fetching messages for agent: {agent_id[:8]}...")

        # ── Database fetch ────────────────────────────────────────────────────
        fetch_result = await fetch_agent_messages(
            supabase=self.supabase,
            agent_id=agent_id,
            max_messages=max_messages
        )

        if fetch_result.get("error"):
            self.logger.error(f"❌ Fetch error: {fetch_result['error']}")
            result["status"] = "error"
            result["error"] = fetch_result["error"]
            result["executorFullResponse"] = f"Memory fetch failed: {fetch_result['error']}"
            return result

        messages    = fetch_result["messages"]
        total_count = fetch_result["message_count"]

        # ── Format for LLM consumption ────────────────────────────────────────
        if not messages:
            if fetch_result.get("_stub"):
                formatted = MEMORY_STUB_NOT_AVAILABLE.format(
                    reason=fetch_result.get("_stub_reason", "Supabase not available")
                )
            else:
                formatted = MEMORY_EMPTY_CONVERSATION.format(agent_id=agent_id)
        else:
            header = MEMORY_HEADER_TEMPLATE.format(
                count=len(messages),
                total=total_count,
                agent_id=agent_id
            )
            lines = [header]
            for msg in messages:
                role_label = "🧑 User" if msg["role"] == "user" else "🤖 Agent"
                ts      = str(msg.get("created_at", ""))[:16]   # trim to minute
                content = msg.get("content", "").strip()
                lines.append(f"**[{msg['position']}] {role_label}** ({ts})\n{content}\n")
            formatted = "\n".join(lines)

        self.logger.info(f"✅ Memory fetch complete: {len(messages)} messages returned")

        result.update({
            "status": "completed",
            "agentId": agent_id,
            "messageCount": total_count,
            "messagesRead": messages,
            "executorFullResponse": formatted,
            "stepCompleted": True
        })

        return result