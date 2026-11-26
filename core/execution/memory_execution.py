# core/execution/memory_execution.py
"""
Shared execution layer for Boundary V2 memory operations.
Both InChatMemoryExecutor and GlobalChatSearchExecutor call functions from here.

Supabase schema expected (Felix to confirm/build):
  conversations(id, user_id, title, created_at)
  messages(id, conversation_id, role, content, created_at)

All functions are written against this schema. If tables don't exist yet,
functions return graceful stubs so executors don't crash before Felix ships.
"""

import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


# ============================================================================
# TIER 1 — IN-CHAT MEMORY
# Used by InChatMemoryExecutor and by sub-agents checking shared context.
# ============================================================================

async def fetch_conversation_messages(
    supabase,
    conversation_id: str,
    start_message: Optional[int] = None,
    end_message: Optional[int] = None
) -> Dict[str, Any]:
    """
    Fetch all messages from a conversation, ordered chronologically.

    If start_message/end_message are provided, returns only that slice
    (1-indexed, inclusive). Used by GlobalChatSearchExecutor's Read step.

    Args:
        supabase:        The Supabase client from the orchestrator.
        conversation_id: UUID of the target conversation.
        start_message:   Optional start position (1-indexed).
        end_message:     Optional end position (1-indexed, inclusive).

    Returns:
        {
          "conversation_id": str,
          "message_count": int,
          "messages": [
            {"position": int, "role": str, "content": str, "created_at": str},
            ...
          ],
          "fetched_at": str (ISO),
          "error": str | None
        }
    """
    if not supabase:
        logger.warning("[MemoryExec] Supabase client not available — returning stub")
        return _stub_messages(conversation_id)

    try:
        result = (
            supabase
            .table("messages")
            .select("id, role, content, created_at")
            .eq("conversation_id", conversation_id)
            .order("created_at", desc=False)
            .execute()
        )

        rows = result.data or []
        total = len(rows)

        # Apply windowing if requested (1-indexed, inclusive)
        if start_message is not None and end_message is not None:
            s = max(0, start_message - 1)          # convert to 0-indexed
            e = min(total, end_message)             # end is exclusive for slicing
            rows = rows[s:e]

        messages = [
            {
                "position": i + (start_message if start_message else 1),
                "role": row.get("role", "unknown"),
                "content": row.get("content", ""),
                "created_at": row.get("created_at", "")
            }
            for i, row in enumerate(rows)
        ]

        logger.info(
            f"[MemoryExec] Fetched {len(messages)} messages from conversation {conversation_id[:8]}..."
        )

        return {
            "conversation_id": conversation_id,
            "message_count": total,
            "messages": messages,
            "fetched_at": datetime.now().isoformat(),
            "error": None
        }

    except Exception as e:
        logger.error(f"[MemoryExec] fetch_conversation_messages failed: {e}")
        # If the table doesn't exist yet, return informative stub
        if "does not exist" in str(e).lower() or "relation" in str(e).lower():
            logger.warning(
                "[MemoryExec] messages table not found — V2 persistence not yet built. "
                "Felix needs to create: messages(id, conversation_id, role, content, created_at)"
            )
            return _stub_messages(conversation_id, reason="V2 schema not yet deployed")
        return {
            "conversation_id": conversation_id,
            "message_count": 0,
            "messages": [],
            "fetched_at": datetime.now().isoformat(),
            "error": str(e)
        }


async def fetch_agent_messages(
    supabase,
    agent_id: str,
    max_messages: Optional[int] = None
) -> Dict[str, Any]:
    """
    Fetch messages for a given agent_id from the Supabase `messages` table,
    ordered chronologically (oldest first).

    This uses the *actual* schema in production (messages.agent_id) rather than
    the planned V2 conversations schema (messages.conversation_id).

    Args:
        supabase:     The Supabase client.
        agent_id:     The agent whose conversation thread we're reading.
        max_messages: If set, return only the N most recent messages.

    Returns:
        {
          "agent_id":      str,
          "message_count": int,          # total rows in DB
          "messages": [
            {"position": int, "role": str, "content": str, "created_at": str},
            ...
          ],
          "fetched_at": str (ISO),
          "error": None | str,
          "_stub": bool  (only present when returning stub)
        }
    """
    if not supabase:
        logger.warning("[MemoryExec] Supabase client not available — returning stub")
        return {
            "agent_id": agent_id,
            "message_count": 0,
            "messages": [],
            "fetched_at": datetime.now().isoformat(),
            "error": None,
            "_stub": True,
            "_stub_reason": "Supabase not available"
        }

    try:
        query = (
            supabase
            .table("messages")
            .select("role, content, timestamp")
            .eq("agent_id", agent_id)
            .order("timestamp", desc=False)
        )
        result = query.execute()
        rows = result.data or []
        total = len(rows)

        # Trim to N most-recent if requested
        if max_messages and isinstance(max_messages, int) and max_messages < total:
            rows = rows[-max_messages:]

        messages = [
            {
                "position": i + 1,
                "role": row.get("role", "unknown"),
                "content": row.get("content", ""),
                "created_at": row.get("timestamp", "")
            }
            for i, row in enumerate(rows)
        ]

        logger.info(
            f"[MemoryExec] Fetched {len(messages)} messages for agent {agent_id[:8]}..."
        )

        return {
            "agent_id": agent_id,
            "message_count": total,
            "messages": messages,
            "fetched_at": datetime.now().isoformat(),
            "error": None
        }

    except Exception as e:
        logger.error(f"[MemoryExec] fetch_agent_messages failed: {e}")
        return {
            "agent_id": agent_id,
            "message_count": 0,
            "messages": [],
            "fetched_at": datetime.now().isoformat(),
            "error": str(e)
        }


# ============================================================================
# TIER 2 — GLOBAL CHAT SEARCH
# Step 1: search_conversations — returns list of matching conversation headers
# Step 3: read_conversation_slice — returns specific message range (calls fetch above)
# (Step 2 is LLM reasoning in the executor — no database call)
# ============================================================================

async def search_conversations(
    supabase,
    user_id: str,
    keywords: Optional[str] = None,
    date_after: Optional[str] = None,
    date_before: Optional[str] = None,
    limit: int = 10
) -> Dict[str, Any]:
    """
    Search conversation titles for the given user using PostgreSQL full-text search.

    The conversations table must have a GIN index on tsvector(title) for
    performance at scale. Felix to add this index.

    Args:
        supabase:    Supabase client.
        user_id:     clerk_user_id — we only search conversations belonging to this user.
        keywords:    Space-separated keywords to match against title tsvector.
        date_after:  ISO date string, e.g. "2026-03-01".
        date_before: ISO date string, e.g. "2026-03-31".
        limit:       Max conversations to return (agent will pick relevant subset).

    Returns:
        {
          "conversations": [
            {
              "id": str,
              "title": str,
              "created_at": str,
              "message_count": int
            },
            ...
          ],
          "total_found": int,
          "query_params": {...},
          "searched_at": str (ISO),
          "error": str | None
        }
    """
    if not supabase:
        logger.warning("[MemoryExec] Supabase client not available — returning stub")
        return _stub_conversations(keywords)

    try:
        # Build query against conversations table
        # messages count joined via a separate count query (Supabase doesn't do subquery joins natively)
        query = (
            supabase
            .table("conversations")
            .select("id, title, created_at")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(limit)
        )

        # Date filters
        if date_after:
            query = query.gte("created_at", date_after)
        if date_before:
            query = query.lte("created_at", date_before)

        result = query.execute()
        rows = result.data or []

        # For each conversation, get message count separately
        # (simple N+1 is fine here — result set is already limited to `limit`)
        conversations = []
        for row in rows:
            conv_id = row["id"]

            # Title keyword filter — done in Python since Supabase REST doesn't
            # expose tsvector search directly (Felix can add an RPC for this later)
            if keywords:
                title_lower = (row.get("title") or "").lower()
                kw_list = keywords.lower().split()
                if not any(kw in title_lower for kw in kw_list):
                    continue  # Skip non-matching titles

            # Get message count for this conversation
            count_result = (
                supabase
                .table("messages")
                .select("id", count="exact")
                .eq("conversation_id", conv_id)
                .execute()
            )
            msg_count = count_result.count if hasattr(count_result, "count") else 0

            conversations.append({
                "id": conv_id,
                "title": row.get("title", "(Untitled)"),
                "created_at": row.get("created_at", ""),
                "message_count": msg_count
            })

        logger.info(
            f"[MemoryExec] Found {len(conversations)} conversations "
            f"matching keywords='{keywords}' for user {user_id[:8]}..."
        )

        return {
            "conversations": conversations,
            "total_found": len(conversations),
            "query_params": {
                "keywords": keywords,
                "date_after": date_after,
                "date_before": date_before,
                "limit": limit
            },
            "searched_at": datetime.now().isoformat(),
            "error": None
        }

    except Exception as e:
        logger.error(f"[MemoryExec] search_conversations failed: {e}")
        if "does not exist" in str(e).lower() or "relation" in str(e).lower():
            logger.warning(
                "[MemoryExec] conversations table not found — V2 persistence not yet built. "
                "Felix needs to create: conversations(id, user_id, title, created_at)"
            )
            return _stub_conversations(keywords, reason="V2 schema not yet deployed")
        return {
            "conversations": [],
            "total_found": 0,
            "query_params": {"keywords": keywords},
            "searched_at": datetime.now().isoformat(),
            "error": str(e)
        }


async def read_conversation_slice(
    supabase,
    conversation_id: str,
    start_message: int,
    end_message: int
) -> Dict[str, Any]:
    """
    Read a specific range of messages from a conversation.
    Thin wrapper around fetch_conversation_messages with windowing.
    Agents call this multiple times to read different sections of a long conversation.

    Args:
        supabase:        Supabase client.
        conversation_id: Target conversation UUID.
        start_message:   1-indexed start position (inclusive).
        end_message:     1-indexed end position (inclusive).

    Returns: Same shape as fetch_conversation_messages.
    """
    logger.info(
        f"[MemoryExec] Reading slice [{start_message}:{end_message}] "
        f"from conversation {conversation_id[:8]}..."
    )
    return await fetch_conversation_messages(
        supabase=supabase,
        conversation_id=conversation_id,
        start_message=start_message,
        end_message=end_message
    )


# ============================================================================
# STUBS — returned when tables don't exist yet
# ============================================================================

def _stub_messages(conversation_id: str, reason: str = "Supabase not available") -> Dict[str, Any]:
    return {
        "conversation_id": conversation_id,
        "message_count": 0,
        "messages": [],
        "fetched_at": datetime.now().isoformat(),
        "error": None,
        "_stub": True,
        "_stub_reason": reason
    }


def _stub_conversations(keywords: Optional[str], reason: str = "Supabase not available") -> Dict[str, Any]:
    return {
        "conversations": [],
        "total_found": 0,
        "query_params": {"keywords": keywords},
        "searched_at": datetime.now().isoformat(),
        "error": None,
        "_stub": True,
        "_stub_reason": reason
    }