# TODO
# core/executors/global_chat_search_executor.py
"""
Boundary V2 — Tier 2 Global Chat Search Executor

Purpose: Let agents (and users) search across ALL of a user's past conversations
to retrieve relevant context from previous sessions. Three-step process:

  Step 1 — SEARCH  (database call)
      Build SQL against conversations table. Return titles + IDs + dates +
      message counts. Agent sees: "Conversation X, 83 messages, March 10."

  Step 2 — INSPECT  (LLM reasoning — NO database call)
      Agent reads the returned list and decides which conversations are relevant
      and which message ranges to read. Output is a structured read_plan.

  Step 3 — READ  (database call, potentially multiple times)
      Agent provides conversation_id + start_message + end_message. Backend
      runs windowed ROW_NUMBER query returning exactly those messages. Agent
      can call Read multiple times for different slices of the same conversation.

The agent outputs structured JSON at each step. The Planner prompts the agent
to produce these structured outputs. The executor handles all database I/O.

NOTE: Requires V2 schema from Felix (conversations + messages tables with indexes).
Until then, Step 1 returns graceful stub; Steps 2 and 3 handle accordingly.
"""

import json
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
from .base_executor import BaseExecutor
from core.execution.memory_execution import search_conversations, read_conversation_slice
from comprehensive_formatting_prompts import GLOBAL_CHAT_SEARCH_EXECUTOR_PROMPT

# ── Module-level LLM prompt constants ────────────────────────────────────────

# System prompt for the agent-relevance selection call in search_relevant_agents().
AGENT_SELECTION_SYSTEM_PROMPT = (
    "You are a concise JSON-only assistant. "
    "Output ONLY a valid JSON array of agent ID strings. No markdown, no explanation."
)

# User-turn template for the agent-relevance selection call.
# Placeholders: {query}, {agent_list_text}, {max_agents}
AGENT_SELECTION_PROMPT_TEMPLATE = (
    'You are a memory-routing assistant. The user sent this message to an AI agent:\n\n'
    '"{query}"\n\n'
    'Below is a list of other agents this user has previously interacted with '
    '(id, name, description):\n\n'
    '[\n{agent_list_text}\n]\n\n'
    'Your job: select the agents whose past conversations would most help answer '
    'the current message.\n'
    'Return ONLY a valid JSON array of up to {max_agents} agent IDs, ordered by '
    'relevance (most relevant first).\n'
    'If no agents are relevant, return an empty array [].\n\n'
    'Output format (agent IDs only, no explanation):\n'
    '["<agent_id_1>", "<agent_id_2>", ...]'
)

class GlobalChatSearchExecutor(BaseExecutor):
    """
    Three-step global memory search: Search → Inspect (LLM) → Read.
    """

    def __init__(self, mcp_manager, mcp_registry, model=None, supabase=None):
        super().__init__(mcp_manager, mcp_registry)
        self.model = model
        self.supabase = supabase
        self.logger = logging.getLogger(__name__)
        self.logger.info(
            "✅ Initialized GlobalChatSearchExecutor "
            f"[model={'present' if model else 'None'}, "
            f"supabase={'connected' if supabase else 'NOT CONNECTED — V2 schema pending'}]"
        )

    async def execute_task(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Run the three-step global memory search.

        Expected task_data fields (set by Planner):
            user_id (str):          clerk_user_id — search scoped to this user.
            query.keywords (str):   Space-separated search terms.
            query.date_after (str): ISO date string e.g. "2026-03-01" (optional).
            query.date_before (str):ISO date string e.g. "2026-03-31" (optional).
            query.limit (int):      Max conversations to surface (default 10).

        Returns:
            {
              "status": "completed" | "error",
              "executorUsed": "GlobalChatSearchExecutor",
              "searchQuery": {...},
              "conversationsFound": int,
              "conversations": [...],     ← from Step 1
              "readPlan": [...],          ← from Step 2 (LLM reasoning)
              "retrievedContext": [...],  ← from Step 3 (actual message slices)
              "executorFullResponse": str,← formatted synthesis for Summarizer
              "timestamp": str
            }
        """
        self.logger.info("=" * 70)
        self.logger.info("🌐 STARTING GLOBAL CHAT SEARCH")
        self.logger.info("=" * 70)

        result = {
            "status": "started",
            "executorUsed": "GlobalChatSearchExecutor",
            "artifacts": [],
            "timestamp": datetime.now().isoformat()
        }

        # ── Extract parameters ────────────────────────────────────────────────
        executor_task = task_data.get("executorTask") or task_data
        context = task_data.get("context", {})
        user_id = (
            task_data.get("userId")
            or task_data.get("userEmail")
            or context.get("userId", "anonymous")
        )
        user_request = task_data.get("userRequest") or context.get("userRequest", "")

        query_params = executor_task.get("query", {})
        keywords    = query_params.get("keywords") or executor_task.get("keywords")
        date_after  = query_params.get("date_after") or executor_task.get("date_after")
        date_before = query_params.get("date_before") or executor_task.get("date_before")
        limit       = query_params.get("limit") or executor_task.get("limit") or 10

        self.logger.info(
            f"🔍 Search params: keywords='{keywords}', "
            f"date_after={date_after}, date_before={date_before}, limit={limit}"
        )

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # STEP 1 — SEARCH: hit the conversations table
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        self.logger.info("📋 Step 1: Searching conversations table...")

        search_result = await search_conversations(
            supabase=self.supabase,
            user_id=user_id,
            keywords=keywords,
            date_after=date_after,
            date_before=date_before,
            limit=limit
        )

        if search_result.get("error"):
            result["status"] = "error"
            result["error"] = search_result["error"]
            result["executorFullResponse"] = f"Global search failed: {search_result['error']}"
            return result

        conversations = search_result["conversations"]
        is_stub = search_result.get("_stub", False)

        self.logger.info(f"📋 Step 1 complete: {len(conversations)} conversations found")

        if not conversations:
            if is_stub:
                msg = (
                    f"⚠️ Global chat memory is not yet available. "
                    f"Reason: {search_result.get('_stub_reason', 'V2 schema pending')}. "
                    f"Felix needs to deploy the conversations and messages tables."
                )
            else:
                msg = (
                    f"No conversations found matching keywords='{keywords}'. "
                    f"The user may not have any prior conversations on this topic."
                )
            result.update({
                "status": "completed",
                "searchQuery": {"keywords": keywords, "date_after": date_after},
                "conversationsFound": 0,
                "conversations": [],
                "readPlan": [],
                "retrievedContext": [],
                "executorFullResponse": msg,
                "stepCompleted": True
            })
            return result

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # STEP 2 — INSPECT: LLM decides which conversations to read and what
        #          message ranges are worth retrieving. No database call.
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        self.logger.info("🧠 Step 2: LLM reasoning on conversation list...")

        inspect_prompt = self._build_inspect_prompt(
            user_request=user_request,
            keywords=keywords,
            conversations=conversations
        )

        inspect_response = await self.model.generate(
            prompt=inspect_prompt,
            system_prompt=GLOBAL_CHAT_SEARCH_EXECUTOR_PROMPT,
            max_tokens=2048,
            temperature=0.2
        )

        inspect_text = (
            inspect_response
            if isinstance(inspect_response, str)
            else inspect_response.get("text") or inspect_response.get("content", "")
        )

        read_plan = self._parse_read_plan(inspect_text)
        self.logger.info(
            f"🧠 Step 2 complete: {len(read_plan)} conversation slices to read"
        )

        if not read_plan:
            # LLM found no relevant conversations — return search results only
            self.logger.info("🧠 LLM found no sufficiently relevant conversations")
            formatted = self._format_search_only(conversations, keywords)
            result.update({
                "status": "completed",
                "searchQuery": {"keywords": keywords},
                "conversationsFound": len(conversations),
                "conversations": conversations,
                "readPlan": [],
                "retrievedContext": [],
                "executorFullResponse": formatted,
                "stepCompleted": True
            })
            return result

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # STEP 3 — READ: fetch the specific message ranges the LLM identified
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        self.logger.info(f"📖 Step 3: Reading {len(read_plan)} conversation slices...")

        retrieved_context = []
        for read_item in read_plan:
            conv_id = read_item.get("conversation_id")
            start   = read_item.get("start_message", 1)
            end     = read_item.get("end_message", 50)
            reason  = read_item.get("reason", "")

            if not conv_id:
                self.logger.warning("⚠️ Read plan item missing conversation_id — skipping")
                continue

            self.logger.info(
                f"📖 Reading [{start}:{end}] from conversation {conv_id[:8]}..."
            )

            slice_result = await read_conversation_slice(
                supabase=self.supabase,
                conversation_id=conv_id,
                start_message=start,
                end_message=end
            )

            # Find the title from our earlier search result
            conv_title = next(
                (c["title"] for c in conversations if c["id"] == conv_id),
                "(Unknown conversation)"
            )

            retrieved_context.append({
                "conversation_id": conv_id,
                "conversation_title": conv_title,
                "reason_selected": reason,
                "slice_requested": {"start": start, "end": end},
                "messages": slice_result.get("messages", []),
                "message_count": len(slice_result.get("messages", [])),
                "error": slice_result.get("error")
            })

        self.logger.info(
            f"✅ Step 3 complete: retrieved {len(retrieved_context)} conversation slices"
        )

        # ── Format final output for Summarizer ────────────────────────────────
        formatted = self._format_final_output(
            keywords=keywords,
            conversations=conversations,
            read_plan=read_plan,
            retrieved_context=retrieved_context
        )

        result.update({
            "status": "completed",
            "searchQuery": {
                "keywords": keywords,
                "date_after": date_after,
                "date_before": date_before,
                "limit": limit
            },
            "conversationsFound": len(conversations),
            "conversations": conversations,
            "readPlan": read_plan,
            "retrievedContext": retrieved_context,
            "executorFullResponse": formatted,
            "stepCompleted": True
        })

        return result

    # ── Private helpers ────────────────────────────────────────────────────────

    def _build_inspect_prompt(
        self,
        user_request: str,
        keywords: Optional[str],
        conversations: List[Dict[str, Any]]
    ) -> str:
        """Build the Step 2 LLM prompt: given conversation list, decide what to read."""

        conv_list = "\n".join([
            f"  [{i+1}] ID: {c['id']}\n"
            f"      Title: {c['title']}\n"
            f"      Created: {c.get('created_at', '')[:10]}\n"
            f"      Messages: {c.get('message_count', '?')}"
            for i, c in enumerate(conversations)
        ])

        return f"""## User's Original Request
{user_request}

## Search Keywords Used
{keywords or "(none)"}

## Conversations Found (from Step 1)
{conv_list}

## Your Task — Step 2: Inspect
Read the conversation list above. Decide:
1. Which conversations are actually relevant to the user's request?
2. For each relevant conversation, which message range is worth reading?
   - A conversation with 83 messages probably has relevant content around
     the middle or end, not always at message 1.
   - Keep ranges tight: 20-40 messages per slice is usually enough.

Output a JSON array called "read_plan". Each item:
{{
  "conversation_id": "exact UUID from the list above",
  "start_message": 1,
  "end_message": 40,
  "reason": "one sentence: why this conversation and this range"
}}

If NO conversations are relevant, output an empty array: []

Output ONLY valid JSON. No other text."""

    def _parse_read_plan(self, llm_response: str) -> List[Dict[str, Any]]:
        """Parse the LLM's read plan JSON from Step 2."""
        try:
            # Strip markdown fences if present
            text = llm_response.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()

            parsed = json.loads(text)

            # Handle both {"read_plan": [...]} and [...] directly
            if isinstance(parsed, list):
                return parsed
            if isinstance(parsed, dict) and "read_plan" in parsed:
                return parsed["read_plan"]

            self.logger.warning(
                f"[GlobalChatSearch] Unexpected read_plan structure: {type(parsed)}"
            )
            return []

        except (json.JSONDecodeError, IndexError, KeyError) as e:
            self.logger.warning(
                f"[GlobalChatSearch] Failed to parse read_plan JSON: {e}\n"
                f"Raw response: {llm_response[:300]}"
            )
            return []

    def _format_search_only(
        self,
        conversations: List[Dict[str, Any]],
        keywords: Optional[str]
    ) -> str:
        """Format Step 1 results when LLM decides nothing is relevant enough to read."""
        lines = [
            f"## Global Memory Search — '{keywords}'\n",
            f"Found {len(conversations)} conversations with matching titles, "
            f"but none were assessed as directly relevant to the current request.\n",
            "### Conversation Titles Found\n"
        ]
        for c in conversations:
            lines.append(
                f"- **{c['title']}** "
                f"({c.get('created_at', '')[:10]}, {c.get('message_count', '?')} messages)"
            )
        return "\n".join(lines)

    def _format_final_output(
        self,
        keywords: Optional[str],
        conversations: List[Dict[str, Any]],
        read_plan: List[Dict[str, Any]],
        retrieved_context: List[Dict[str, Any]]
    ) -> str:
        """Format the complete three-step output for the Summarizer."""
        lines = [
            f"## Global Memory Search Results — '{keywords}'\n",
            f"**Searched:** {len(conversations)} conversations found\n",
            f"**Retrieved:** {len(retrieved_context)} relevant slices read\n",
            "\n---\n"
        ]

        for ctx in retrieved_context:
            if ctx.get("error"):
                lines.append(
                    f"### ⚠️ {ctx['conversation_title']}\n"
                    f"Error reading slice: {ctx['error']}\n"
                )
                continue

            lines.append(f"### 📂 {ctx['conversation_title']}")
            lines.append(f"*Reason selected: {ctx['reason_selected']}*\n")

            msgs = ctx.get("messages", [])
            if not msgs:
                lines.append("*(No messages in this slice)*\n")
            else:
                for msg in msgs:
                    role_label = "🧑 User" if msg["role"] == "user" else "🤖 Agent"
                    content = msg.get("content", "").strip()
                    # Truncate very long messages in the formatted output
                    if len(content) > 600:
                        content = content[:597] + "..."
                    lines.append(f"**{role_label}:** {content}\n")

            lines.append("\n---\n")

        return "\n".join(lines)

    async def search_relevant_agents(
        self,
        user_id: str,
        current_agent_id: str,
        query: str,
        context_messages_limit: int = 8,
        max_agents: int = 5
    ) -> List[Dict[str, Any]]:
        """
        LLM-driven cross-agent context retrieval.

        Flow:
          1. Fetch all other active agents for the user from the DB
             (id, name, initial_prompt).
          2. Ask the LLM to pick the top-N (<= max_agents) agents that are
             most relevant to the current user query.
          3. For each selected agent, fetch its most recent messages so the
             caller can prepend them as context.

        Returns a list of dicts (empty list if nothing relevant):
          [
            {
              "agent":    <agent DB row>,
              "messages": [<chronological recent messages>]
            },
            ...
          ]

        Only called from the multi-LLM orchestrator -- never from single-LLM path.
        """
        self.logger.info("[AgentSearch] --- search_relevant_agents() called ---")
        self.logger.info(
            f"[AgentSearch] user_id={user_id!r}  "
            f"current_agent_id={current_agent_id!r}  "
            f"max_agents={max_agents}"
        )
        self.logger.info(f"[AgentSearch] query (first 120 chars): {query[:120]!r}")

        if not self.supabase:
            self.logger.info("[AgentSearch] SKIP: supabase is None")
            return []
        if not self.model:
            self.logger.info("[AgentSearch] SKIP: model is None")
            return []
        if not user_id or not query:
            self.logger.info(f"[AgentSearch] SKIP: user_id={user_id!r} query={bool(query)}")
            return []

        try:
            # ── Step 1: Fetch all other active agents ─────────────────────────
            self.logger.info("[AgentSearch] Step 1: querying agents table...")
            agents_result = (
                self.supabase
                .table("agents")
                .select("id, name, initial_prompt")
                .eq("user_id", user_id)
                .neq("id", current_agent_id)
                .eq("status", "active")
                .execute()
            )
            agents = agents_result.data or []
            self.logger.info(f"[AgentSearch] Step 1 result: {len(agents)} other agent(s) found")

            if not agents:
                self.logger.info("[AgentSearch] No other agents for this user -- returning []")
                return []

            for a in agents:
                self.logger.info(
                    f"[AgentSearch]   candidate: id={a['id'][:8]}...  name={a.get('name')!r}"
                )

            # ── Step 2: Ask the LLM to pick the most relevant agents ──────────
            agent_list_text = "\n".join(
                f'  {{"id": "{a["id"]}", "name": "{a.get("name", "")}", '
                f'"description": "{str(a.get("initial_prompt", ""))[:200]}"}}'
                for a in agents
            )

            self.logger.info(
                f"[AgentSearch] Step 2: calling LLM to select relevant agents "
                f"(model={getattr(self.model, 'model_name', 'unknown')!r})..."
            )

            selection_prompt = AGENT_SELECTION_PROMPT_TEMPLATE.format(
                query=query,
                agent_list_text=agent_list_text,
                max_agents=max_agents
            )

            self.logger.info(
                f"[AgentSearch] LLM prompt (first 300 chars): {selection_prompt[:300]!r}"
            )

            llm_response = await self.model.generate(
                prompt=selection_prompt,
                system_prompt=AGENT_SELECTION_SYSTEM_PROMPT,
                max_tokens=256,
                temperature=0.1
            )

            llm_text = (
                llm_response
                if isinstance(llm_response, str)
                else llm_response.get("text") or llm_response.get("content", "")
            ).strip()

            self.logger.info(f"[AgentSearch] LLM raw response: {llm_text!r}")

            # Parse the LLM's JSON array
            selected_ids: List[str] = []
            try:
                text = llm_text
                if "```" in text:
                    parts = text.split("```")
                    text = parts[1] if len(parts) > 1 else parts[0]
                    if text.startswith("json"):
                        text = text[4:]
                    text = text.split("```")[0].strip()

                parsed = json.loads(text)
                self.logger.info(f"[AgentSearch] Parsed JSON: {parsed!r}")

                if isinstance(parsed, list):
                    valid_ids = {a["id"] for a in agents}
                    selected_ids = [
                        item for item in parsed
                        if isinstance(item, str) and item in valid_ids
                    ][:max_agents]
                    self.logger.info(
                        f"[AgentSearch] Valid selected IDs ({len(selected_ids)}): {selected_ids}"
                    )
                else:
                    self.logger.warning(
                        f"[AgentSearch] LLM returned unexpected JSON type: {type(parsed)}"
                    )
            except (json.JSONDecodeError, IndexError, KeyError) as e:
                self.logger.warning(
                    f"[AgentSearch] Failed to parse LLM agent selection JSON: {e} "
                    f"| Raw: {llm_text[:300]!r}"
                )
                return []

            if not selected_ids:
                self.logger.info("[AgentSearch] LLM selected no relevant agents -- returning []")
                return []

            selected_names = ", ".join(
                next((a.get("name", aid) for a in agents if a["id"] == aid), aid)
                for aid in selected_ids
            )
            self.logger.info(f"[AgentSearch] LLM selected agents: {selected_names!r}")

            # ── Step 3: Fetch recent messages for each selected agent ──────────
            agent_map = {a["id"]: a for a in agents}
            results: List[Dict[str, Any]] = []

            for aid in selected_ids:
                agent_data = agent_map.get(aid)
                if not agent_data:
                    self.logger.warning(f"[AgentSearch] agent_id {aid!r} not in agent_map -- skipping")
                    continue

                self.logger.info(
                    f"[AgentSearch] Step 3: fetching last {context_messages_limit} messages "
                    f"for agent {aid[:8]}... ('{agent_data.get('name')}')"
                )
                msgs_result = (
                    self.supabase
                    .table("messages")
                    .select("role, content")
                    .eq("agent_id", aid)
                    .order("timestamp", desc=True)
                    .limit(context_messages_limit)
                    .execute()
                )
                messages = list(reversed(msgs_result.data or []))
                self.logger.info(
                    f"[AgentSearch]   -> {len(messages)} message(s) fetched "
                    f"for '{agent_data.get('name')}'"
                )
                results.append({
                    "agent": agent_data,
                    "messages": messages
                })

            self.logger.info(
                f"[AgentSearch] Done. Returning {len(results)} result(s) with context."
            )
            return results

        except Exception as e:
            self.logger.error(f"[AgentSearch] EXCEPTION in search_relevant_agents: {e}", exc_info=True)
            return []