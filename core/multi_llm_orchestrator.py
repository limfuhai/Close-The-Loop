import os
import json
import aiohttp
import logging
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
import uuid
import asyncio
from comprehensive_formatting_prompts import (
    SUMMARIZER_ENHANCED_PROMPT,
    PLANNER_ENHANCED_PROMPT,
    EXECUTOR_ENHANCED_PROMPT,
    SHEETS_EXECUTOR_PROMPT,
    SLIDES_EXECUTOR_PROMPT,
    DOCS_EXECUTOR_PROMPT,
    WEB_SEARCH_EXECUTOR_PROMPT,
    TUNER_WORKFLOW_DETECTION,
    EMAIL_READER_EXECUTOR_PROMPT,
    EMAIL_DRAFT_EXECUTOR_PROMPT,
    EMAIL_SENDER_EXECUTOR_PROMPT,
    CALENDAR_EXECUTOR_PROMPT,
    TASK_EXECUTOR_PROMPT,
    COMMON_APPLIED_EXECUTOR_PROMPT,
    FILE_ORGANIZER_EXECUTOR_PROMPT,
    IN_CHAT_MEMORY_EXECUTOR_PROMPT,
    GLOBAL_CHAT_SEARCH_EXECUTOR_PROMPT,
    PARALLEL_PLANNER_ADDITION           
)

FORMATTING_ADDON = ""  # Empty string since we no longer need special formatting

# Executors that read or write the user's mailbox get task_data["mailAccount"]
MAIL_EXECUTORS = {"EmailReaderExecutor", "EmailDraftExecutor", "EmailSenderExecutor"}

# ── Boundary V4: second-tier loops ──
# The AuditorExecutor and LedgerExecutor are ordinary executors to the main Planner.
# Inside execute_task they call run_second_tier_loop, planning beneath the main
# Planner, which makes them second-tier Planners. They may not dispatch each other.
SECOND_TIER_AGENTS = {"AuditorExecutor", "LedgerExecutor"}
SECOND_TIER_MAX_ROUNDS = 8
SECOND_TIER_MAX_TOKENS = 8192

SECOND_TIER_LOOP_RULES = """
HOW YOU WORK
You work in rounds, at most {max_rounds}. In each round you choose ONE move, then see its raw result in the next round. You never invent results: everything you report must come from a tool's or an executor's output.

HOW TO REPLY
Write a few sentences of reasoning, then exactly ONE ```json block as the last thing in your reply. Four shapes:

Use one of your own tools:
```json
{"tool": "tool_name", "explanation": "...", "args": {}}
```

Dispatch one executor:
```json
{"nextExecutor": "ExecutorName", "explanation": "...", "executorTask": {"description": "...", "requirements": ["..."], "expectedOutput": "..."}}
```
Executor-specific fields (such as "mailQuery" or "schedulerTask") go inside "executorTask".

Dispatch up to 4 sub-agents in parallel, for independent pieces of work. Each returns its raw results to you:
```json
{"parallel": true, "explanation": "...", "subTasks": [{"subTaskId": "d0042", "description": "Complete brief, including exactly which identifiers to return verbatim", "suggestedExecutor": "EmailReaderExecutor"}]}
```

Finish:
```json
{"taskComplete": true, "report": "What you did and found, citing every identifier verbatim"}
```

RULES
- Never repeat a move that succeeded. If a move fails twice, finish and report the failure.
- Whenever a result is evidence, ask for raw records and exact identifiers (Message-IDs, file paths, wake-up IDs), never summaries.
- Finish as soon as the brief is done.
"""

class ModelAPIClient:
    """
    Model client for the Summarizer, Planner and Executors.

    Uses the same failover chain as the chat path (MODEL_CHAIN in
    api_client.py): DeepSeek Flash first, then the Kimi models. Each request
    goes to the first model; on an error or empty reply it moves to the next.
    The api_key / model_name / base_url arguments are kept so existing calls
    still work, but the chain decides the model.
    """

    def __init__(self, api_key: str = None, model_name: str = None, base_url: str = None):
        from api_client import MODEL_CHAIN
        self.chain = [m for m in MODEL_CHAIN if m.get("api_key")]
        self.model_name = self.chain[0]["model"] if self.chain else (model_name or "")
        self.logger = logging.getLogger(f"{__name__}.ModelAPIClient")
        if not self.chain:
            raise ValueError("MODEL_CHAIN in api_client.py has no usable models")

    @staticmethod
    def _messages(prompt: str, system_prompt: str = None,
                  conversation_history: List[Dict[str, str]] = None) -> List[Dict[str, str]]:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        for msg in conversation_history or []:
            # Providers accept only these roles in history
            if msg.get("role") in ("user", "assistant") and msg.get("content"):
                messages.append({"role": msg["role"], "content": msg["content"]})
        messages.append({"role": "user", "content": prompt})
        return messages

    async def _post(self, session, provider: Dict[str, Any], payload: Dict[str, Any], timeout: int):
        """One request to one provider, retried once after a rate limit (429)."""
        from api_client import RATE_LIMIT_WAIT_SECONDS
        headers = {
            "Authorization": f"Bearer {provider['api_key']}",
            "Content-Type": "application/json",
        }
        body = {**payload, "model": provider["model"]}
        for attempt in range(2):
            async with session.post(
                f"{provider['base_url']}/chat/completions",
                json=body,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as response:
                if response.status == 429 and attempt == 0:
                    self.logger.warning(f"{provider['name']} rate limited, retrying once")
                    await asyncio.sleep(RATE_LIMIT_WAIT_SECONDS)
                    continue
                if response.status != 200:
                    error_text = await response.text()
                    raise Exception(f"{provider['name']} error ({response.status}): {error_text[:300]}")
                return await response.json()

    async def generate(self, prompt: str, system_prompt: str = None, temperature: float = 0.7,
                      max_tokens: int = 8196, conversation_history: List[Dict[str, str]] = None) -> Dict[str, Any]:
        """Returns {"text", "content", "usage", "model"}; raises if every model fails."""
        payload = {
            "messages": self._messages(prompt, system_prompt, conversation_history),
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        errors = []
        async with aiohttp.ClientSession() as session:
            for provider in self.chain:
                try:
                    result = await self._post(session, provider, payload, timeout=180)
                    content = result["choices"][0]["message"].get("content") or ""
                    if not content.strip():
                        raise Exception(f"{provider['name']} returned an empty reply")
                    if provider is not self.chain[0]:
                        self.logger.warning(f"Served by fallback: {provider['name']}")
                    return {
                        "text": content,
                        "content": content,
                        "usage": result.get("usage", {}),
                        "model": provider["name"],
                    }
                except Exception as e:
                    self.logger.error(f"{provider['name']} failed: {e}")
                    errors.append(str(e))
        raise Exception("All models failed: " + " | ".join(errors))

    async def generate_with_tools(
        self,
        prompt: str,
        tools: List[Dict[str, Any]],
        system_prompt: str = None,
        temperature: float = 0.3,
        max_tokens: int = 1024
    ) -> Dict[str, Any]:
        """
        Generate a response with tool calling support
        Returns the full message object including any tool_calls.
        """
        payload = {
            "messages": self._messages(prompt, system_prompt),
            "max_tokens": max_tokens,
            "temperature": temperature,
            "tools": tools,
            "tool_choice": "auto",
        }
        async with aiohttp.ClientSession() as session:
            for provider in self.chain:
                try:
                    result = await self._post(session, provider, payload, timeout=30)
                    message = result["choices"][0]["message"]
                    return {
                        "content": message.get("content"),
                        "tool_calls": message.get("tool_calls"),
                        "finish_reason": result["choices"][0].get("finish_reason"),
                        "usage": result.get("usage", {})
                    }
                except Exception as e:
                    self.logger.error(f"{provider['name']} tool call failed: {e}")
        return {"content": None, "tool_calls": None, "finish_reason": "error", "usage": {}}

class ModelAPIClientWrapper:
    """
    Wrapper that converts dictionary responses from ModelAPIClient back to strings.
    """
    
    def __init__(self, api_client):
        self.api_client = api_client
        self.last_usage = {}
    
    async def generate(self, prompt: str, max_tokens: int = 4096, 
                      temperature: float = 0.7, system_prompt: str = None,
                      conversation_history: List[Dict[str, str]] = None):
        """Generate a response with conversation history support."""
        response = await self.api_client.generate(
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            system_prompt=system_prompt,
            conversation_history=conversation_history
        )
        
        # Extract and return only the text field
        if isinstance(response, dict):
            self.last_usage = response.get("usage", {})
            return response.get("text") or response.get("content", "")
        else:
            self.last_usage = {}
            return response

# ============================================================================
# TOOL DEFINITIONS FOR DB CONTEXT SEARCH
# ============================================================================

MESSAGE_SEARCH_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_past_messages",
            "description": (
                "Search the user's past conversation messages stored in the database. "
                "Use this when the user references previous conversations, asks about "
                "something discussed before, or when historical context would help "
                "give a better answer. Do NOT call this for general knowledge questions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "A keyword to search for in past messages (matches the keywords array)"
                    },
                    "title": {
                        "type": "string",
                        "description": "A partial title to search for (case-insensitive partial match)"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results to return (default: 5)"
                    }
                },
                "required": []
            }
        }
    }
]

CONTEXT_SEARCH_SYSTEM_PROMPT = (
    "You are a context-assessment assistant. Your ONLY job is to decide whether "
    "the user's message needs context from their past conversations. "
    "If it does, call the search_past_messages tool with the most relevant "
    "keyword or title. If not, respond with exactly: NO_SEARCH_NEEDED"
)


class TaskState:
    """Manages the state of a task throughout the agent workflow."""
    
    def __init__(self, task_id: str, user_request: str, user_id: str = "anonymous"):
        self.task_id = task_id
        self.user_request = user_request
        self.user_id = user_id
        self.created_at = datetime.now().isoformat()
        self.updated_at = self.created_at
        self.status = "initialized"
        self.plan = None
        self.execution_results = []
        self.summaries = []
        self.current_step = 0
        self.total_steps = 0
        self.completed = False
        self.token_usage = {
            "planner": 0,
            "executor": 0,
            "summarizer": 0
        }
        
    def update_status(self, status: str):
        self.status = status
        self.updated_at = datetime.now().isoformat()
        
    def set_plan(self, plan: Dict[str, Any]):
        self.plan = plan
        if "steps" in plan:
            self.total_steps = len(plan["steps"])
        self.update_status("planned")
        
    def add_execution_result(self, result: Dict[str, Any]):
        self.execution_results.append(result)
        if "stepCompleted" in result and result["stepCompleted"]:
            self.current_step += 1
        self.update_status("executing" if self.current_step < self.total_steps else "executed")
        
    def add_summary(self, summary: Dict[str, Any]):
        self.summaries.append(summary)
        
    def mark_completed(self):
        self.completed = True
        self.update_status("completed")
        
    def to_dict(self) -> Dict[str, Any]:
        """Convert task state to dictionary for storage or transmission."""
        return {
            "task_id": self.task_id,
            "user_request": self.user_request,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "status": self.status,
            "plan": self.plan,
            "execution_results": self.execution_results,
            "summaries": self.summaries,
            "current_step": self.current_step,
            "total_steps": self.total_steps,
            "completed": self.completed,
            "token_usage": self.token_usage
        }
        
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TaskState':
        """Create a TaskState instance from a dictionary."""
        task = cls(data["task_id"], data["user_request"])
        task.created_at = data["created_at"]
        task.updated_at = data["updated_at"]
        task.status = data["status"]
        task.plan = data["plan"]
        task.execution_results = data["execution_results"]
        task.summaries = data["summaries"]
        task.current_step = data["current_step"]
        task.total_steps = data["total_steps"]
        task.completed = data["completed"]
        task.token_usage = data["token_usage"]
        return task

class SubTaskState:
    """
    State container for a single parallel sub-agent's work. (Boundary V3)
 
    Deliberately lighter than the parent TaskState:
      - Tracks its own plan, execution_results, summaries
      - Carries sub_task_id + parent_task_id for lineage
      - Initialized with a suggested_executor from the parent Planner
    """
 
    def __init__(
        self,
        sub_task_id: str,
        parent_task_id: str,
        description: str,
        suggested_executor: str,
        user_id: str = "anonymous"
    ):
        self.sub_task_id = sub_task_id
        self.parent_task_id = parent_task_id
        self.description = description
        self.suggested_executor = suggested_executor
        self.user_id = user_id
 
        self.created_at = datetime.now().isoformat()
        self.updated_at = self.created_at
        self.status = "initialized"
        self.plan = None
        self.execution_results = []
        self.summaries = []
        self.current_step = 0
        self.total_steps = 0
        self.completed = False
        self.error = None
        self.token_usage = {"planner": 0, "executor": 0, "summarizer": 0}
 
    def update_status(self, status: str):
        self.status = status
        self.updated_at = datetime.now().isoformat()
 
    def set_plan(self, plan: Dict[str, Any]):
        self.plan = plan
        if "steps" in plan:
            self.total_steps = len(plan["steps"])
        self.update_status("planned")
 
    def add_execution_result(self, result: Dict[str, Any]):
        self.execution_results.append(result)
        if result.get("stepCompleted"):
            self.current_step += 1
        self.update_status(
            "executing" if self.current_step < self.total_steps else "executed"
        )
 
    def add_summary(self, summary: Dict[str, Any]):
        self.summaries.append(summary)
 
    def mark_completed(self):
        self.completed = True
        self.update_status("completed")
 
    def mark_failed(self, error: str):
        self.error = error
        self.status = "failed"
        self.updated_at = datetime.now().isoformat()
 
    def to_dict(self) -> Dict[str, Any]:
        return {
            "sub_task_id": self.sub_task_id,
            "parent_task_id": self.parent_task_id,
            "description": self.description,
            "suggested_executor": self.suggested_executor,
            "status": self.status,
            "plan": self.plan,
            "execution_results": self.execution_results,
            "summaries": self.summaries,
            "current_step": self.current_step,
            "total_steps": self.total_steps,
            "completed": self.completed,
            "error": self.error,
            "token_usage": self.token_usage,
            "created_at": self.created_at,
            "updated_at": self.updated_at
        }

class MultiLLMOrchestrator:
    """Orchestrates the flow between different specialized LLM agents."""
    
    def __init__(self, api_keys: Dict[str, str], clerk_user_id: str, supabase_client, logger, tools=None, mcp_manager=None, mcp_registry=None, compiler_service=None):
        """Initialize with API keys for each agent type and token tracking infrastructure."""
        self.logger = logger
        self.clerk_user_id = clerk_user_id
        self.supabase = supabase_client
        self.conversation_history = []  # ADDED: Store conversation history
        
        # ADDED: Conversation history optimization settings
        self.max_history_messages = 10  # Maximum messages to keep in history
        self.history_token_limit = 2000  # Maximum tokens for history
        self.enable_auto_summarization = True  # Auto-summarize long histories
        
        # All three agents use the failover chain in api_client.py (MODEL_CHAIN)
        self.summarizer = ModelAPIClient()
        self.planner = ModelAPIClient()
        self.executor = ModelAPIClient()

        # The selected email account is loaded once per request, on first use
        self._mail_account_loaded = False
        self._mail_account = None
        
        self.tools = tools
        self.mcp_manager = mcp_manager
        self.mcp_registry = mcp_registry
        self.compiler_service = compiler_service  # NEW: Store compiler reference for bridge
        self.task_states = {}
        self.artifact_threshold_lines = 15
        self.artifact_threshold_chars = 1500

        self.executor_registry = {
            "SheetsExecutor": None,
            "SlidesExecutor": None,
            "DocsExecutor": None,
            "WebSearchExecutor": None,
            "ProjectSearchExecutor": None,
            "CodingExecutor": None,
            "TestingExecutor": None,
            "WebsiteBuildExecutor": None,
            "FrontendAppExecutor": None,
            "BackendAppExecutor": None,
            "DataExecutor": None,
            "ChatbotExecutor": None,
            "FileSearchExecutor": None,
            "FileReaderExecutor": None,
            "DirectoryListExecutor": None,
            "BashExecutor": None,
            "EmailReaderExecutor": None,
            "EmailDraftExecutor": None,
            "EmailSenderExecutor": None,
            "CalendarExecutor": None,
            "TaskExecutor": None,
            "FileOrganizerExecutor": None,
            "InChatMemoryExecutor": None,
            "SchedulerExecutor": None,
            "AuditorExecutor": None,
            "LedgerExecutor": None
        }
    
    def _estimate_tokens(self, text: str) -> int:
        """Estimate token count for text (rough approximation: 1 token ≈ 4 characters)."""
        return len(text) // 4
    
    def _get_mail_account(self) -> Optional[Dict[str, Any]]:
        """The user's current email account with its authorization code, or None.
        Loaded from Supabase once per request and reused for every email step."""
        if not self._mail_account_loaded:
            self._mail_account_loaded = True
            try:
                from mail_accounts import load_current_account
                self._mail_account = load_current_account(self.supabase, self.clerk_user_id)
                if self._mail_account:
                    self.logger.info(
                        f"[Orchestrator] 📮 Using mail account {self._mail_account['address']} "
                        f"({self._mail_account['provider']})"
                    )
                else:
                    self.logger.info("[Orchestrator] 📮 No mail account selected for this user")
            except Exception as e:
                self.logger.error(f"[Orchestrator] Could not load mail account: {e}")
                self._mail_account = None
        return self._mail_account
    
    def _optimize_conversation_history(self, history: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """
        Intelligently optimize conversation history to reduce token usage.
        Frontend doesn't need to change - this happens automatically in backend.
        
        Optimizations:
        1. Limit to last N messages
        2. Remove messages exceeding token limit
        3. Optionally summarize very long histories
        
        Returns optimized history list.
        """
        if not history:
            return []
        
        # Step 1: Limit to max_history_messages (keep most recent)
        if len(history) > self.max_history_messages:
            self.logger.info(
                f"[Orchestrator] 📉 History reduced from {len(history)} to {self.max_history_messages} messages"
            )
            history = history[-self.max_history_messages:]
        
        # Step 2: Check total token count
        total_tokens = sum(self._estimate_tokens(msg.get('content', '')) for msg in history)
        
        if total_tokens > self.history_token_limit:
            self.logger.info(
                f"[Orchestrator] 📉 History tokens ({total_tokens}) exceeds limit ({self.history_token_limit})"
            )
            
            # Keep removing oldest messages until under limit
            while total_tokens > self.history_token_limit and len(history) > 2:
                removed_msg = history.pop(0)
                removed_tokens = self._estimate_tokens(removed_msg.get('content', ''))
                total_tokens -= removed_tokens
                self.logger.info(f"[Orchestrator] 🗑️ Removed 1 old message ({removed_tokens} tokens)")
            
            self.logger.info(
                f"[Orchestrator] ✅ Optimized history: {len(history)} messages, ~{total_tokens} tokens"
            )
        
        return history
    
    def _extract_response(self, response):
        """Extract text content and usage data from API response."""
        if isinstance(response, dict):
            text = response.get("text") or response.get("content", "")
            usage = response.get("usage", {})
            return text, usage
        else:
            return response, {}

    async def get_user_token_balance(self) -> dict:
        """Query Supabase to get user's token allocation and remaining balance."""
        try:
            if not self.supabase:
                self.logger.error("Supabase client not initialized")
                return {"error": "Database not available"}
            
            result = self.supabase.table('users').select('email, token_allocation, tokens_remaining').eq('clerk_user_id', self.clerk_user_id).execute()
            
            if not result.data or len(result.data) == 0:
                self.logger.error(f"No user found with Clerk ID")
                return {"error": "User not found"}
            
            user_data = result.data[0]
            self.logger.info(f"[Orchestrator] User {user_data['email']} has {user_data['tokens_remaining']} tokens remaining")
            
            return {
                "email": user_data['email'],
                "token_allocation": user_data['token_allocation'],
                "tokens_remaining": user_data['tokens_remaining']
            }
            
        except Exception as e:
            self.logger.error(f"[Orchestrator] Error querying user token balance: {str(e)}")
            return {"error": str(e)}

    async def update_token_consumption(self, tokens_consumed: int) -> bool:
        """Update user's tokens_remaining after API call completes."""
        try:
            if not self.supabase:
                self.logger.error("[Orchestrator] Supabase client not initialized")
                return False
            
            balance = await self.get_user_token_balance()
            if "error" in balance:
                return False
            
            new_remaining = balance['tokens_remaining'] - tokens_consumed
            
            result = self.supabase.table('users').update({
                'tokens_remaining': new_remaining
            }).eq('clerk_user_id', self.clerk_user_id).execute()
            
            self.logger.info(f"[Orchestrator] ✅ Updated user {balance['email']}: consumed {tokens_consumed} tokens, {new_remaining} remaining")
            return True
            
        except Exception as e:
            self.logger.error(f"[Orchestrator] Error updating token consumption: {str(e)}")
            return False

    async def _enrich_with_db_context(self, user_request: str, user_id: str) -> str:
        """
        Search for cross-agent context via GlobalChatSearchExecutor and prepend
        any found memory to the user request before the LLM pipeline starts.

        This method is ONLY called from the multi-LLM paths (stream_task /
        start_task), so DB-context learning is gated behind multi-LLM being
        enabled -- single-LLM chat messages are never enriched here.
        """
        agent_id = getattr(self, "agent_id", None)

        self.logger.info("[ContextSearch] *** Starting cross-agent context search ***")
        self.logger.info(f"[ContextSearch] user_id={user_id!r}  agent_id={agent_id!r}")
        self.logger.info(f"[ContextSearch] query (first 120 chars): {user_request[:120]!r}")

        if not self.supabase:
            self.logger.info("[ContextSearch] SKIP: supabase client is None")
            return user_request

        if not user_id or user_id == "anonymous":
            self.logger.info(f"[ContextSearch] SKIP: user_id is {user_id!r} (anonymous or empty)")
            return user_request

        # ── Gate: only search DB context when the agent has multi-agent enabled ──
        if agent_id:
            try:
                flag_result = (
                    self.supabase
                    .table("agents")
                    .select("prefer_multi_agent")
                    .eq("id", agent_id)
                    .single()
                    .execute()
                )
                prefer_multi = (flag_result.data or {}).get("prefer_multi_agent", False)
                self.logger.info(
                    f"[ContextSearch] agent {agent_id[:8]}... prefer_multi_agent={prefer_multi!r}"
                )
                if not prefer_multi:
                    self.logger.info(
                        "[ContextSearch] SKIP: prefer_multi_agent is off for this agent -- "
                        "LLM will not read DB context"
                    )
                    return user_request
            except Exception as flag_err:
                # If we can't read the flag, play it safe and skip enrichment
                self.logger.warning(
                    f"[ContextSearch] Could not read prefer_multi_agent flag: {flag_err} "
                    "-- skipping DB context search"
                )
                return user_request
        else:
            self.logger.info(
                "[ContextSearch] SKIP: no agent_id set -- cannot verify multi-agent flag"
            )
            return user_request

        try:
            from core.executors.global_chat_search_executor import GlobalChatSearchExecutor

            self.logger.info("[ContextSearch] Building GlobalChatSearchExecutor...")
            search_executor = GlobalChatSearchExecutor(
                mcp_manager=None,
                mcp_registry=None,
                model=ModelAPIClientWrapper(self.executor),
                supabase=self.supabase
            )
            self.logger.info("[ContextSearch] Executor built. Calling search_relevant_agents()...")

            # Returns a list of up to 5 relevant agents (LLM-ranked)
            matches = await search_executor.search_relevant_agents(
                user_id=user_id,
                current_agent_id=agent_id or "",
                query=user_request
            )

            self.logger.info(f"[ContextSearch] search_relevant_agents() returned {len(matches)} match(es)")

            if not matches:
                self.logger.info("[ContextSearch] No cross-agent context found -- using original request")
                return user_request

            agent_names = ", ".join(m["agent"].get("name", "?") for m in matches)
            self.logger.info(f"[ContextSearch] Matched agents: {agent_names}")

            # Build a context block for each selected agent
            context_block = "[[Cross-agent memory retrieved -- most relevant agents listed first]]\n\n"
            for match in matches:
                agent_name = match["agent"].get("name", "Unknown Agent")
                messages   = match["messages"]
                self.logger.info(
                    f"[ContextSearch]   agent='{agent_name}'  messages={len(messages)}"
                )
                context_block += f"--- Agent: '{agent_name}' ---\n"
                if messages:
                    for msg in messages:
                        role_label = "User" if msg.get("role") == "user" else "Assistant"
                        context_block += f"{role_label}: {msg.get('content', '')}\n"
                else:
                    context_block += "(no recent messages found)\n"
                context_block += "\n"

            context_block += "[[End of cross-agent memory]]\n\n"
            self.logger.info(
                f"[ContextSearch] Context block built ({len(context_block)} chars). "
                "Prepending to user request."
            )
            return context_block + user_request

        except Exception as e:
            self.logger.error(f"[ContextSearch] ERROR in _enrich_with_db_context: {e}", exc_info=True)
            return user_request


    def _get_executor(self, executor_name: str):
        """Get or create an executor instance."""
        if executor_name not in self.executor_registry:
            executor_name = "DocsExecutor"
        
        if self.executor_registry[executor_name] is None:
            wrapped_executor = ModelAPIClientWrapper(self.executor)
            
            if executor_name == "SheetsExecutor":
                from core.executors.sheets_executor import SheetsExecutor
                self.executor_registry[executor_name] = SheetsExecutor(None, None, wrapped_executor)
            elif executor_name == "SlidesExecutor":
                from core.executors.slides_executor import SlidesExecutor
                self.executor_registry[executor_name] = SlidesExecutor(None, None, wrapped_executor)
            elif executor_name == "DocsExecutor":
                from core.executors.docs_executor import DocsExecutor
                self.executor_registry[executor_name] = DocsExecutor(None, None, wrapped_executor, compiler_service=self.compiler_service)
            elif executor_name == "WebSearchExecutor":
                from core.executors.web_search_executor import WebSearchExecutor
                self.executor_registry[executor_name] = WebSearchExecutor(None, None, wrapped_executor)
            elif executor_name == "ProjectSearchExecutor":
                from core.executors.project_search_executor import ProjectSearchExecutor
                self.executor_registry[executor_name] = ProjectSearchExecutor(None, None, wrapped_executor)
            elif executor_name == "CodingExecutor":
                from core.executors.coding_executor import CodeEditorExecutor
                self.executor_registry[executor_name] = CodeEditorExecutor(None, None, wrapped_executor)
            elif executor_name == "TestingExecutor":
                from core.executors.testing_executor import TestingExecutor
                self.executor_registry[executor_name] = TestingExecutor(None, None, wrapped_executor)
            elif executor_name == "WebsiteBuildExecutor":
                from core.executors.website_build_executor import WebsiteBuildExecutor
                self.executor_registry[executor_name] = WebsiteBuildExecutor(None, None, wrapped_executor)
            elif executor_name == "FrontendAppExecutor":
                from core.executors.frontend_app_build_executor import FrontendAppExecutor
                self.executor_registry[executor_name] = FrontendAppExecutor(None, None, wrapped_executor)
            elif executor_name == "BackendAppExecutor":
                from core.executors.backend_app_build_executor import BackendAppExecutor
                self.executor_registry[executor_name] = BackendAppExecutor(None, None, wrapped_executor)
            elif executor_name == "DataExecutor":
                from core.executors.data_executor import DataExecutor
                self.executor_registry[executor_name] = DataExecutor(None, None, wrapped_executor)
            elif executor_name == "ChatbotExecutor":
                from core.executors.chatbot_executor import ChatbotExecutor
                self.executor_registry[executor_name] = ChatbotExecutor(None, None, wrapped_executor)
            elif executor_name == "FileSearchExecutor":
                from core.executors.file_search_executor import FileSearchExecutor
                self.executor_registry[executor_name] = FileSearchExecutor(None, None, wrapped_executor)
            elif executor_name == "FileReaderExecutor":
                from core.executors.file_reader_executor import FileReaderExecutor
                self.executor_registry[executor_name] = FileReaderExecutor(None, None, wrapped_executor)
            elif executor_name == "DirectoryListExecutor":
                from core.executors.directory_list_executor import DirectoryListExecutor
                self.executor_registry[executor_name] = DirectoryListExecutor(None, None, wrapped_executor)
            elif executor_name == "BashExecutor":
                from core.executors.bash_executor import BashExecutor
                self.executor_registry[executor_name] = BashExecutor(None, None, wrapped_executor)
            elif executor_name == "EmailReaderExecutor":
                from core.executors.email_reader_executor import EmailReaderExecutor
                self.executor_registry[executor_name] = EmailReaderExecutor(None, None, wrapped_executor)
            elif executor_name == "EmailDraftExecutor":
                from core.executors.email_draft_executor import EmailDraftExecutor
                self.executor_registry[executor_name] = EmailDraftExecutor(None, None, wrapped_executor)
            elif executor_name == "EmailSenderExecutor":
                from core.executors.email_sender_executor import EmailSenderExecutor
                self.executor_registry[executor_name] = EmailSenderExecutor(None, None, wrapped_executor)
            elif executor_name == "CalendarExecutor":
                from core.executors.calendar_executor import CalendarExecutor
                self.executor_registry[executor_name] = CalendarExecutor(None, None, wrapped_executor)
            elif executor_name == "TaskExecutor":
                from core.executors.task_executor import TaskExecutor
                self.executor_registry[executor_name] = TaskExecutor(None, None, wrapped_executor)
            elif executor_name == "FileOrganizerExecutor":
                from core.executors.file_organizer_executor import FileOrganizerExecutor
                self.executor_registry[executor_name] = FileOrganizerExecutor(None, None, wrapped_executor)
            elif executor_name == "InChatMemoryExecutor":
                from core.executors.in_chat_memory_executor import InChatMemoryExecutor
                self.executor_registry[executor_name] = InChatMemoryExecutor(None, None, wrapped_executor, supabase=self.supabase)
            elif executor_name == "GlobalChatSearchExecutor":
                from core.executors.global_chat_search_executor import GlobalChatSearchExecutor
                self.executor_registry[executor_name] = GlobalChatSearchExecutor(None, None, wrapped_executor, supabase=self.supabase)
            elif executor_name == "SchedulerExecutor":
                from core.executors.scheduler_executor import SchedulerExecutor
                self.executor_registry[executor_name] = SchedulerExecutor(None, None, wrapped_executor)
            elif executor_name == "AuditorExecutor":
                from core.executors.auditor_executor import AuditorExecutor
                self.executor_registry[executor_name] = AuditorExecutor(None, None, wrapped_executor, orchestrator=self)
            elif executor_name == "LedgerExecutor":
                from core.executors.ledger_executor import LedgerExecutor
                self.executor_registry[executor_name] = LedgerExecutor(None, None, wrapped_executor, orchestrator=self)

        return self.executor_registry[executor_name]

    async def start_task(self, user_request: str, conversation_history: List[Dict[str, str]] = None, user_id: str = "anonymous", agent_id: str = None) -> Dict[str, Any]:
        """Initialize a new task based on user request with conversation history support.
        
        Backend automatically optimizes history - frontend doesn't need to change!
        """
        # Store agent_id for cross-agent context scoping
        self.agent_id = agent_id or ""

        # Automatically optimize conversation history (NO FRONTEND CHANGES NEEDED!)
        if conversation_history:
            original_length = len(conversation_history)
            conversation_history = self._optimize_conversation_history(conversation_history)
            
            if len(conversation_history) < original_length:
                self.logger.info(
                    f"[Orchestrator] 💡 Auto-optimized: {original_length} → {len(conversation_history)} messages"
                )
        
        # Store optimized conversation history
        self.conversation_history = conversation_history or []
        
        # ── Tool Calling: Enrich with DB context if needed ──
        user_request = await self._enrich_with_db_context(user_request, user_id)
        
        task_id = f"task_{datetime.now().strftime('%Y%m%d%H%M%S')}_{id(user_request)}"
        task_state = TaskState(task_id, user_request, user_id)
        self.task_states[task_id] = task_state
        
        initial_summary = await self._run_summarizer_initial(task_state)
        task_state.add_summary(initial_summary)
        
        await self._continue_task(task_state)
        
        return task_state.to_dict()

    async def _continue_task(self, task_state: TaskState) -> None:
        """Continue processing the task through the relay loop until completion."""
        while not task_state.completed:
            plan_result = await self._run_planner(task_state)
            
            if plan_result.get("taskComplete", False):
                task_state.mark_completed()
                final_summary = await self._run_summarizer_final(task_state)
                task_state.add_summary(final_summary)
                self.final_summary_text = final_summary["content"]
                break
                
            task_state.set_plan(plan_result)
            execution_result = await self._run_executor(task_state)
            task_state.add_execution_result(execution_result)
            progress_summary = await self._run_summarizer_progress(task_state)
            task_state.add_summary(progress_summary)
            self.task_states[task_state.task_id] = task_state
    
    async def _run_summarizer_initial(self, task_state: TaskState) -> Dict[str, Any]:
        """Run the summarizer to process initial user request WITH conversation history."""
        system_prompt = """You are the Initial Summarizer agent in a multi-agent system. Your CRITICAL responsibilities are:

1. **CONVERSATION CONTEXT**: If conversation history is provided, understand the ongoing context
2. **DATA EXTRACTION FIRST**: Extract and preserve ALL data from uploaded files into structured text format
3. **CREATE DATA APPENDIX**: Organize extracted data into clearly labeled sections
4. **PRESERVE EXACT VALUES**: Maintain precise numbers, names, dates, and specifications
5. **IDENTIFY KEY OBJECTIVES**: Understand what the user wants to accomplish

Your output becomes the foundation for all subsequent agent work.""" + SUMMARIZER_ENHANCED_PROMPT + "\n\n" + TUNER_WORKFLOW_DETECTION

        # Build context from conversation history
        history_context = ""
        if self.conversation_history:
            history_context = "\n\n## Conversation History\n"
            for msg in self.conversation_history[-5:]:  # Last 5 messages for context
                role = msg.get("role", "unknown")
                content = msg.get("content", "")[:200]  # Truncate for brevity
                history_context += f"**{role.capitalize()}**: {content}...\n"

        prompt = f"""{history_context}

## Current User Request
{task_state.user_request}

## Your Task
Create a comprehensive summary considering the conversation history above and the current request."""

        response = await self.summarizer.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            max_tokens=4096,
            temperature=0.3,
            conversation_history=self.conversation_history  # ADDED: Pass history to API
        )

        text, usage = self._extract_response(response)
        tokens = usage.get("total_tokens", 0)
        if tokens > 0:
            success = await self.update_token_consumption(tokens)
            if success:
                self.logger.info(f"[Orchestrator] ✅ Summarizer (initial) consumed {tokens} tokens")

        task_state.token_usage["summarizer"] += tokens

        return {
            "type": "initial_summary",
            "content": text,
            "summarizerFullResponse": text,
            "timestamp": datetime.now().isoformat()
        }
        
    async def _run_planner(self, task_state: TaskState) -> Dict[str, Any]:
        """Run the planner WITH conversation history context."""
        if not task_state.plan:
            system_prompt = """You are the Planner agent in a multi-agent system. Consider any conversation history to understand the full context of the user's request.""" + FORMATTING_ADDON + PLANNER_ENHANCED_PROMPT + "\n\n" + TUNER_WORKFLOW_DETECTION

            latest_summary = task_state.summaries[-1]["content"]
            prompt = f"""## Problem Statement
{latest_summary}

## Your Task
Create a detailed plan to address this request, taking into account any previous conversation context."""

        else:
            system_prompt = """You are the Planner agent reviewing execution results.""" + FORMATTING_ADDON + PLANNER_ENHANCED_PROMPT + "\n\n" + TUNER_WORKFLOW_DETECTION
            latest_execution = task_state.execution_results[-1]
            latest_summary = task_state.summaries[-1]["content"]
            
            prompt = f"""## Original Plan
{json.dumps(task_state.plan, indent=2)}

## Latest Execution Results
{json.dumps(latest_execution, indent=2)}

## Summarizer's Analysis
{latest_summary}

## Your Task
Evaluate and decide next steps."""

        response = await self.planner.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            max_tokens=4096,
            temperature=0.5,
            conversation_history=self.conversation_history  # ADDED: Pass history
        )
        
        text, usage = self._extract_response(response)
        tokens = usage.get("total_tokens", 0)
        if tokens > 0:
            success = await self.update_token_consumption(tokens)
            if success:
                self.logger.info(f"[Orchestrator] ✅ Planner consumed {tokens} tokens")

        task_state.token_usage["planner"] += tokens

        try:
            if "```json" in text:
                json_text = text.split("```json")[1].split("```")[0].strip()
                plan_data = json.loads(json_text)
            else:
                plan_data = json.loads(text)
                
            plan_data["plannerResponse"] = text
            plan_data["usage"] = usage

            if "nextExecutor" not in plan_data:
                if "document" in text.lower() or "report" in text.lower():
                    plan_data["nextExecutor"] = "DocsExecutor"
                elif "spreadsheet" in text.lower() or "sheets" in text.lower():
                    plan_data["nextExecutor"] = "SheetsExecutor"
                elif "presentation" in text.lower() or "slides" in text.lower():
                    plan_data["nextExecutor"] = "SlidesExecutor"
                elif "search" in text.lower() or "research" in text.lower():
                    plan_data["nextExecutor"] = "WebSearchExecutor"
                else:
                    plan_data["nextExecutor"] = "DocsExecutor"
            return plan_data
            
        except json.JSONDecodeError:
            self.logger.warning("Planner response was not valid JSON, wrapping it")
            return {
                "taskComplete": "true" in text.lower() and "complete" in text.lower(),
                "plannerResponse": text,
                "usage": usage,
                "steps": [{"number": 1, "description": "Execute the plan as described in the text"}]
            }
    
    async def _run_executor(self, task_state: TaskState) -> Dict[str, Any]:
        """Run the executor to perform actions based on the current plan."""
        
        executor_name = task_state.plan.get("nextExecutor", "DocsExecutor")
        executor_task = task_state.plan.get("executorTask", {})
        
        try:
            executor = self._get_executor(executor_name)
            
            if not executor:
                raise Exception(f"Failed to instantiate {executor_name}")
            
            task_data = {
                "description": executor_task.get("description", "Execute the plan"),
                "requirements": executor_task.get("requirements", []),
                "expectedOutput": executor_task.get("expectedOutput", "Complete the task"),
                "apiKey": self.clerk_user_id,
                "userId": task_state.user_id,  # Pass user ID to executors
                "userEmail": task_state.user_id,  # ← ADD THIS (user_id IS the email!)
                "currentDate": datetime.now().strftime("%Y-%m-%d"),  # ← ADD THIS
                "currentTime": datetime.now().strftime("%H:%M:%S"),  # ← ADD THIS
                "context": {
                    "userRequest": task_state.user_request,
                    "previousResults": task_state.execution_results,
                    "plan": task_state.plan,
                    "initialSummary": task_state.summaries[0]["content"] if task_state.summaries else "",
                    "conversationHistory": self.conversation_history  # ADDED: Pass to executor
                }
            }

            # Boundary V4: the agent a scheduled wake-up should wake
            task_data["agentId"] = getattr(self, "agent_id", "") or ""
            # Boundary V4: pass every other field the plan gave (schedulerTask, mailQuery,
            # occasion, directiveIds, ...) straight through to the executor
            for key, value in executor_task.items():
                task_data.setdefault(key, value)

            # The user's selected email account (Email Accounts panel), for the
            # executors that touch the mailbox. Never the login email.
            if executor_name in MAIL_EXECUTORS:
                task_data["mailAccount"] = self._get_mail_account()
            # ⚡ INJECT EXECUTION HISTORY INTO DESCRIPTION ⚡
            # This makes execution context available to ALL executors without modifying each one
            if task_state.execution_results:
                execution_history = json.dumps(task_state.execution_results, indent=2)
                task_data["description"] += f"\n\n## COMPLETE EXECUTION HISTORY (for context):\n{execution_history}"
            
            result = await executor.execute_task(task_data)

            # ✨ TUNER WORKFLOW INTERCEPTION ✨
            workflow_type = task_state.plan.get("workflowType")
            tuner_phase = task_state.plan.get("tunerPhase")
            
            if workflow_type == "tuner":
                self.logger.info(f"🔄 Tuner workflow detected - Phase: {tuner_phase}")
                
                # PHASE 1: Document Gathering (ProjectSearchExecutor)
                if tuner_phase == "gathering" and executor_name == "ProjectSearchExecutor":
                    # Accumulate gathered content
                    if not hasattr(task_state, 'tuner_gathered_content'):
                        task_state.tuner_gathered_content = []
                    
                    # Extract content from search results
                    search_results = result.get("searchResults", [])
                    for item in search_results:
                        task_state.tuner_gathered_content.append(item.get("content", ""))
                    
                    self.logger.info(f"📚 Gathered {len(search_results)} document chunks (Total: {len(task_state.tuner_gathered_content)})")
                
                # PHASE 2: Training Data Generation (DataExecutor)
                elif tuner_phase == "data_generation" and executor_name == "DataExecutor":
                    self.logger.info("🚀 DataExecutor completed - Triggering Modal finetuning")
                    
                    try:
                        # Note: modal_client should be passed to orchestrator from compiler
                        # For now, this is a placeholder - adjust based on your setup
                        # Option 1: Pass modal_client in __init__
                        # Option 2: Import from a shared module
                        # Option 3: Get from a dependency injection container
                        
                        if hasattr(self, 'modal_client'):
                            # Extract JSONL file from execution result
                            jsonl_file = result.get("jsonlFile")
                            if not jsonl_file:
                                raise Exception("DataExecutor did not produce JSONL file")
                            
                            local_path = jsonl_file.get("local_path")
                            customer_id = task_data.get("userId", "anonymous")
                            
                            # Upload training data to R2
                            self.logger.info("📤 Uploading training data to R2...")
                            r2_url = await self.modal_client.upload_training_data(local_path, customer_id)
                            
                            # Trigger Modal finetuning
                            self.logger.info("🔥 Triggering Modal finetuning...")
                            job_info = await self.modal_client.trigger_finetuning(
                                training_data_url=r2_url,
                                customer_id=customer_id,
                                base_model="Qwen/Qwen2.5-32B-Instruct"
                            )
                            
                            # Store job in database (requires compiler_service reference)
                            if hasattr(self, 'compiler_service'):
                                await self.compiler_service.store_tuner_job(customer_id, job_info)
                            
                            # Add Tuner job info to result
                            result["tunerJob"] = {
                                "job_id": job_info["job_id"],
                                "status": "training",
                                "eta_hours": 2.5,
                                "message": "✅ Finetuning started! Your model will be ready in 2-3 hours. Come back later and ask 'check my tuner status' or 'finalize my tuner'."
                            }
                            
                            self.logger.info(f"✅ Modal job started: {job_info['job_id']}")
                        else:
                            self.logger.warning("⚠️ modal_client not available - cannot trigger finetuning")
                            result["tunerJob"] = {
                                "status": "error",
                                "message": "Modal client not configured. Please contact support."
                            }
                    
                    except Exception as e:
                        self.logger.error(f"Failed to trigger Modal finetuning: {str(e)}")
                        result["tunerJob"] = {
                            "status": "error",
                            "message": f"Failed to start training: {str(e)}"
                        }
                
                # PHASE 3: Finalization (ChatbotExecutor)
                elif tuner_phase == "widget_generation" and executor_name == "ChatbotExecutor":
                    self.logger.info("🎨 ChatbotExecutor - Widget generation complete")
                    # Nothing special needed, result already contains widget file

            if hasattr(executor, 'model') and hasattr(executor.model, 'last_usage'):
                tokens = executor.model.last_usage.get("total_tokens", 0)
                if tokens > 0:
                    success = await self.update_token_consumption(tokens)
                    if success:
                        self.logger.info(f"[Orchestrator] ✅ {executor_name} consumed {tokens} tokens")
                        task_state.token_usage["executor"] += tokens
            
            # Build execution result with required fields
            execution_result = {
                "step": task_state.current_step + 1,
                "stepDescription": executor_task.get("description", ""),
                "executionDetails": result.get("executorFullResponse", ""),
                "executorFullResponse": result.get("executorFullResponse", ""),
                "stepCompleted": result.get("status") == "completed",
                "timestamp": datetime.now().isoformat(),
                "executorUsed": executor_name,
                "error": result.get("error") if result.get("status") == "error" else None
            }

            # Preserve ALL fields from executor result
            for key, value in result.items():
                if key not in execution_result:
                    execution_result[key] = value  # ← filesFound, fileContents, etc. all preserved!

            return execution_result
            
        except Exception as e:
            self.logger.error(f"Executor {executor_name} failed: {str(e)}")
            return {
                "step": task_state.current_step + 1,
                "stepDescription": executor_task.get("description", ""),
                "executionDetails": f"Execution failed: {str(e)}",
                "executorFullResponse": f"Error occurred: {str(e)}",
                "stepCompleted": False,
                "timestamp": datetime.now().isoformat(),
                "error": str(e),
                "executorUsed": executor_name
            }

    def _format_previous_results(self, execution_results: List[Dict[str, Any]]) -> str:
        """Format previous execution results for the prompt."""
        if not execution_results:
            return "No previous execution results."
        
        formatted = []
        for i, result in enumerate(execution_results):
            formatted.append(f"### Step {i + 1}: {result.get('stepDescription', 'Unknown step')}")
            formatted.append(f"Executor Used: {result.get('executorUsed', 'Unknown')}")
            formatted.append(f"Status: {'Completed' if result.get('stepCompleted') else 'Failed'}")
            formatted.append(f"Details: {result.get('executionDetails', 'No details')[:500]}...")
            formatted.append("")
        
        return "\n".join(formatted)
    
    def _format_existing_artifacts(self, execution_results: List[Dict[str, Any]]) -> str:
        """Format existing artifacts with their links."""
        all_artifacts = []
        
        for result in execution_results:
            if 'artifacts' in result and result['artifacts']:
                for artifact in result['artifacts']:
                    url = "URL not available"
                    if 'data' in artifact:
                        if 'url' in artifact['data']:
                            url = artifact['data']['url']
                        elif 'documentId' in artifact['data']:
                            url = f"https://docs.google.com/document/d/{artifact['data']['documentId']}/edit"
                        elif 'spreadsheetId' in artifact['data']:
                            url = f"https://docs.google.com/spreadsheets/d/{artifact['data']['spreadsheetId']}/edit"
                        elif 'presentationId' in artifact['data']:
                            url = f"https://docs.google.com/presentation/d/{artifact['data']['presentationId']}/edit"
                    elif 'url' in artifact:
                        url = artifact['url']
                    
                    all_artifacts.append(f"- **{artifact.get('title', 'Untitled')}**: {url}")
        
        return "\n".join(all_artifacts) if all_artifacts else "No artifacts created yet."

    def _extract_executor_artifacts(self, response: str, executor_name: str) -> List[Dict[str, Any]]:
        """Extract artifacts from executor response based on JSON format."""
        artifacts = []
        import re
        import json
        import time
        
        json_pattern = r'```json\s*\n(.*?)\n```'
        matches = re.findall(json_pattern, response, re.DOTALL)
        
        for match in matches:
            try:
                data = json.loads(match)
                
                if "artifact" in data and "googleWorkspaceLink" in data:
                    artifact = data["artifact"]
                    
                    artifact_record = {
                        "id": f"{executor_name.lower()}_{int(time.time() * 1000)}",
                        "type": artifact.get("type", "unknown"),
                        "title": artifact.get("title", "Untitled"),
                        "data": {
                            "url": data["googleWorkspaceLink"],
                            "content": artifact.get("content", {})
                        },
                        "executorUsed": executor_name
                    }
                    
                    url = data["googleWorkspaceLink"]
                    if "/document/d/" in url:
                        doc_id = url.split("/document/d/")[1].split("/")[0]
                        artifact_record["data"]["documentId"] = doc_id
                    elif "/spreadsheets/d/" in url:
                        sheet_id = url.split("/spreadsheets/d/")[1].split("/")[0]
                        artifact_record["data"]["spreadsheetId"] = sheet_id
                    elif "/presentation/d/" in url:
                        pres_id = url.split("/presentation/d/")[1].split("/")[0]
                        artifact_record["data"]["presentationId"] = pres_id
                    
                    artifacts.append(artifact_record)
                    
            except json.JSONDecodeError:
                self.logger.warning(f"Failed to parse JSON artifact in {executor_name} response")
            except Exception as e:
                self.logger.error(f"Error extracting artifact: {str(e)}")
        
        return artifacts
    
    async def _run_summarizer_progress(self, task_state: TaskState) -> Dict[str, Any]:
        """Run the summarizer to process progress after execution."""
        system_prompt = """You are the Summarizer agent providing a progress update.""" + FORMATTING_ADDON + SUMMARIZER_ENHANCED_PROMPT + "\n\n" + TUNER_WORKFLOW_DETECTION

        latest_execution = task_state.execution_results[-1]
        step_num = task_state.current_step
        total_steps = task_state.total_steps
        
        artifacts_text = ""
        if 'artifacts' in latest_execution and latest_execution['artifacts']:
            artifacts_text = "\n## Artifacts Created in This Step\n"
            for artifact in latest_execution['artifacts']:
                artifacts_text += f"\n- **{artifact.get('title', 'Untitled')}**"
                artifacts_text += f"\n  - Type: {artifact.get('type', 'Unknown')}"
                
                if 'data' in artifact:
                    if 'documentId' in artifact['data']:
                        url = f"https://docs.google.com/document/d/{artifact['data']['documentId']}/edit"
                        artifacts_text += f"\n  - URL: {url}"
                    elif 'spreadsheetId' in artifact['data']:
                        url = f"https://docs.google.com/spreadsheets/d/{artifact['data']['spreadsheetId']}/edit"
                        artifacts_text += f"\n  - URL: {url}"
                    elif 'presentationId' in artifact['data']:
                        url = f"https://docs.google.com/presentation/d/{artifact['data']['presentationId']}/edit"
                        artifacts_text += f"\n  - URL: {url}"
                    elif 'url' in artifact['data']:
                        url = artifact['data']['url']
                        artifacts_text += f"\n  - URL: {url}"
                elif 'url' in artifact:
                    url = artifact['url']
                    artifacts_text += f"\n  - URL: {url}"
        
        # _run_summarizer_progress (NEW):
        prompt = f"""## Original User Request
{task_state.user_request}

## Current Progress
- Steps completed: {step_num} of {total_steps}
- Completed step description: {latest_execution.get("stepDescription", "N/A")}

## COMPLETE EXECUTION HISTORY (RAW JSON DATA)
Use ONLY the data from this JSON. If you see 'emailsRead', 'filesFound', or other custom fields,
extract the exact names, emails, subjects, and details. DO NOT make up or invent any information.

{json.dumps(task_state.execution_results, indent=2)}  # ← NOW gets full JSON!

{artifacts_text}

## Your Task
Analyze these execution results and create a progress summary.

CRITICAL: Use exact data from the JSON above. Do NOT invent sender names, email addresses, 
file names, or any other details. If data is in 'emailsRead' or other custom fields, 
reference it precisely."""

        response = await self.summarizer.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            max_tokens=4096,
            temperature=0.4,
            conversation_history=self.conversation_history  # ADDED: Pass history
        )
        
        text, usage = self._extract_response(response)
        tokens = usage.get("total_tokens", 0)
        if tokens > 0:
            success = await self.update_token_consumption(tokens)
            if success:
                self.logger.info(f"[Orchestrator] ✅ Summarizer (progress) consumed {tokens} tokens")

        task_state.token_usage["summarizer"] += tokens
        
        return {
            "type": "progress_summary",
            "content": text,
            "summarizerFullResponse": text,
            "usage": usage,
            "timestamp": datetime.now().isoformat()
        }
    
    async def _execute_mcp_tools(self, executor_response: str) -> List[Dict[str, Any]]:
        """Parse and execute any MCP tool requests in the executor response."""
        artifacts = []
        import re
        tool_requests = re.findall(r'MCP_TOOL_REQUEST:\s*({[^}]+})', executor_response, re.DOTALL)
        
        for request_str in tool_requests:
            try:
                request = json.loads(request_str)
                tool_name = request.get('tool')
                action = request.get('action')
                parameters = request.get('parameters', {})
                
                if self.mcp_registry:
                    if self.mcp_manager and self.mcp_manager.client:
                        result = await self.mcp_manager.client.invoke_tool(
                            tool_name, 
                            action,
                            parameters
                        )
                        
                        if 'powerpoint' in tool_name:
                            artifacts.append({
                                'id': f'ppt_{datetime.now().timestamp()}',
                                'type': 'powerpoint',
                                'title': parameters.get('title', 'Generated Presentation'),
                                'data': result
                            })
                        elif 'chart' in action or 'visualization' in action:
                            artifacts.append({
                                'id': f'chart_{datetime.now().timestamp()}',
                                'type': 'chart',
                                'title': parameters.get('title', 'Data Visualization'),
                                'data': result
                            })
                            
            except Exception as e:
                self.logger.error(f"Failed to execute MCP tool: {str(e)}")
                
        return artifacts

    async def _run_summarizer_final(self, task_state: TaskState) -> Dict[str, Any]:
        """Run the summarizer to create final response for the user."""
        system_prompt = """You are the Final Summarizer presenting the complete results to the user.""" + FORMATTING_ADDON + SUMMARIZER_ENHANCED_PROMPT + "\n\n" + TUNER_WORKFLOW_DETECTION

        steps_completed = []
        all_artifacts = []
        
        for i, result in enumerate(task_state.execution_results):
            steps_completed.append(f"Step {i+1}: {result.get('stepDescription', 'Execution step')}")
            
            if 'artifacts' in result and result['artifacts']:
                for artifact in result['artifacts']:
                    artifact_info = {
                        'step': i + 1,
                        'executor': result.get('executorUsed', 'Unknown'),
                        'artifact': artifact
                    }
                    all_artifacts.append(artifact_info)
        
        artifacts_text = ""
        if all_artifacts:
            artifacts_text = "\n## Created Artifacts\n"
            for item in all_artifacts:
                artifact = item['artifact']
                if 'data' in artifact and 'url' in artifact['data']:
                    url = artifact['data']['url']
                elif 'url' in artifact:
                    url = artifact['url']
                else:
                    url = "URL not available"
                
                artifacts_text += f"\n- **{artifact.get('title', 'Untitled')}** ({artifact.get('type', 'Unknown type')})"
                artifacts_text += f"\n  - Full URL: {url}"
                artifacts_text += f"\n  - Created by: {item['executor']}"
                
                if 'data' in artifact:
                    if 'documentId' in artifact['data']:
                        artifacts_text += f"\n  - Document ID: {artifact['data']['documenId']}"
                        artifacts_text += f"\n  - Google Docs URL: https://docs.google.com/document/d/{artifact['data']['documentId']}/edit"
                    elif 'spreadsheetId' in artifact['data']:
                        artifacts_text += f"\n  - Spreadsheet ID: {artifact['data']['spreadsheetId']}"
                        artifacts_text += f"\n  - Google Sheets URL: https://docs.google.com/spreadsheets/d/{artifact['data']['spreadsheetId']}/edit"
                    elif 'presentationId' in artifact['data']:
                        artifacts_text += f"\n  - Presentation ID: {artifact['data']['presentationId']}"
                        artifacts_text += f"\n  - Google Slides URL: https://docs.google.com/presentation/d/{artifact['data']['presentationId']}/edit"
    
        prompt = f"""## Original User Request
{task_state.user_request}

## Steps Completed
{chr(10).join(steps_completed)}

## COMPLETE EXECUTION HISTORY (RAW JSON DATA)
Use ONLY the data from this JSON. If you see 'emailsRead', 'filesFound', or other custom fields,
extract the exact names, emails, subjects, and details. DO NOT make up or invent any information.

{json.dumps(task_state.execution_results, indent=2)}

{artifacts_text}

## Planner's Completion Assessment
{task_state.plan.get("explanation", "Task completed successfully")}

## Your Task
Create a comprehensive final response to the user.

CRITICAL: Use exact data from the JSON above. Do NOT invent sender names, email addresses,
file names, or any other details. If data is in 'emailsRead' or other custom fields,
reference it precisely."""

        response = await self.summarizer.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            max_tokens=4096,
            temperature=0.5,
            conversation_history=self.conversation_history  # ADDED: Pass history
        )
        
        text, usage = self._extract_response(response)
        tokens = usage.get("total_tokens", 0)
        if tokens > 0:
            success = await self.update_token_consumption(tokens)
            if success:
                self.logger.info(f"[Orchestrator] ✅ Summarizer (final) consumed {tokens} tokens")

        task_state.token_usage["summarizer"] += tokens
        
        return {
            "type": "final_summary",
            "content": text,
            "summarizerFullResponse": text,
            "usage": usage,
            "timestamp": datetime.now().isoformat()
        }


    async def check_tuner_status_and_finalize(
        self, 
        customer_id: str, 
        modal_client,
        compiler_service
    ) -> Dict[str, Any]:
        """
        Check Tuner job status and prepare for finalization if complete.
        
        Args:
            customer_id: Clerk user ID
            modal_client: ModalTunerClient instance
            compiler_service: CompilerService instance for DB access
            
        Returns:
            Dict with status info and serving_url if ready
        """
        try:
            # Get customer's most recent job from database
            job = await compiler_service.get_tuner_job(customer_id)
            
            if not job:
                return {
                    "status": "no_job",
                    "message": "No Tuner job found. Please start a new training first."
                }
            
            job_id = job["job_id"]
            stored_status = job["status"]
            
            # If already completed in DB, return serving URL
            if stored_status == "completed":
                serving_url = job.get("serving_url")
                return {
                    "status": "ready",
                    "serving_url": serving_url,
                    "message": "✅ Your model is trained and deployed! Ready to generate widget."
                }
            
            # If failed, inform user
            if stored_status == "failed":
                return {
                    "status": "failed",
                    "message": "❌ Training failed. Please try again or contact support."
                }
            
            # Otherwise, poll Modal for current status
            status_info = await modal_client.check_job_status(job_id)
            modal_status = status_info["status"]
            
            # Update database with latest status
            if modal_status != stored_status:
                await compiler_service.update_tuner_job_status(job_id, modal_status)
            
            if modal_status == "completed":
                # Deploy serving function
                model_path = f"/data/models/{customer_id}"
                serving_url = await modal_client.deploy_serving(customer_id, model_path)
                
                # Update database with serving URL
                await compiler_service.update_tuner_job_status(
                    job_id, 
                    "completed", 
                    serving_url=serving_url
                )
                
                return {
                    "status": "ready",
                    "serving_url": serving_url,
                    "message": "✅ Training complete and model deployed! Ready to generate widget."
                }
            
            elif modal_status == "training":
                progress = status_info.get("progress_percent", 0)
                return {
                    "status": "training",
                    "progress": progress,
                    "message": f"⏳ Still training... {progress}% complete. Check back in 1-2 hours."
                }
            
            elif modal_status == "failed":
                error = status_info.get("error", "Unknown error")
                await compiler_service.update_tuner_job_status(job_id, "failed")
                return {
                    "status": "failed",
                    "message": f"❌ Training failed: {error}"
                }
            
            else:
                return {
                    "status": "unknown",
                    "message": f"Job status: {modal_status}"
                }
                
        except Exception as e:
            self.logger.error(f"Error checking Tuner status: {str(e)}")
            return {
                "status": "error",
                "message": f"Error checking status: {str(e)}"
            }


    async def generate_response(self, user_request: str, conversation_history: List[Dict[str, str]] = None) -> str:
        """Process a user request and return the final response with conversation history support."""
        task_result = await self.start_task(user_request, conversation_history)
        
        final_summaries = [s for s in task_result["summaries"] if s["type"] == "final_summary"]
        if final_summaries:
            return final_summaries[-1]["content"]
        else:
            return "Task processing completed, but no final summary was generated."

    async def _run_subtask_loop(
        self,
        sub_state: SubTaskState,
        parent_context: str,
        max_cycles: int = 5
    ) -> SubTaskState:
        """
        Run a complete Summarizer → Planner → Executor → Summarizer cycle
        for a single V3 sub-agent. Structurally identical to the parent loop.
        Every existing Executor works unchanged — we wrap SubTaskState into
        a temporary TaskState when calling _run_executor().
 
        Args:
            sub_state:      The SubTaskState for this sub-agent.
            parent_context: Parent Planner's analysis + overall goal.
            max_cycles:     Safety cap (default 5) — prevents infinite loops.
 
        Returns:
            Completed SubTaskState with all results populated.
        """
        cycle = 0
 
        try:
            # ── Sub-agent Initial Summarizer ─────────────────────────────
            sub_initial_prompt = f"""## Parent Task Context
{parent_context}
 
## Your Assigned Sub-Task
{sub_state.description}
 
## Your Role
You are a sub-agent working on ONE piece of a larger parallel task.
Focus ONLY on your assigned sub-task. Do not attempt work outside your scope.
Extract key objectives and data requirements for your specific piece."""
 
            sub_initial_response = await self.summarizer.generate(
                prompt=sub_initial_prompt,
                system_prompt=(
                    "You are a Sub-Agent Initial Summarizer. You are working on one "
                    "piece of a parallelised task. Summarize ONLY your assigned sub-task. "
                    "Be concise — your output feeds into a sub-agent Planner."
                ),
                max_tokens=2048,
                temperature=0.3
            )
 
            text, usage = self._extract_response(sub_initial_response)
            tokens = usage.get("total_tokens", 0)
            if tokens > 0:
                await self.update_token_consumption(tokens)
                sub_state.token_usage["summarizer"] += tokens
 
            sub_state.add_summary({
                "type": "sub_initial_summary",
                "content": text,
                "timestamp": datetime.now().isoformat()
            })
 
            self.logger.info(
                f"[V3] Sub-agent '{sub_state.sub_task_id}' — initial summary done"
            )
 
            # ── Sub-agent Planner → Executor → Summarizer loop ──────────
            while not sub_state.completed and cycle < max_cycles:
                cycle += 1
                latest_summary = sub_state.summaries[-1]["content"]
 
                # Sub-agent Planner
                if not sub_state.plan:
                    planner_prompt = f"""## Sub-Task Objective
{sub_state.description}
 
## Initial Analysis
{latest_summary}
 
## Suggested Executor
The parent Planner suggested: {sub_state.suggested_executor}
You may use a different executor if more appropriate.
 
## Your Task
Create a plan to complete this sub-task. Return JSON:
{{
  "taskComplete": false,
  "explanation": "Why this executor",
  "nextExecutor": "{sub_state.suggested_executor}",
  "executorTask": {{
    "description": "Exactly what the executor should do",
    "requirements": ["requirement 1", "requirement 2"],
    "expectedOutput": "What should be produced"
  }}
}}"""
                else:
                    latest_execution = sub_state.execution_results[-1]
                    planner_prompt = f"""## Sub-Task Objective
{sub_state.description}
 
## Latest Execution Result
{json.dumps(latest_execution, indent=2)}
 
## Summarizer's Analysis
{latest_summary}
 
## Your Task
Evaluate: is this sub-task complete? Return JSON:
{{
  "taskComplete": true/false,
  "explanation": "Assessment"
}}
If not complete, add nextExecutor + executorTask as before."""
 
                sub_plan_response = await self.planner.generate(
                    prompt=planner_prompt,
                    system_prompt=(
                        "You are a Sub-Agent Planner. Output ONLY valid JSON. "
                        "Plan execution for your assigned sub-task only. "
                        "Never do work outside your sub-task scope."
                    ),
                    max_tokens=2048,
                    temperature=0.4
                )
 
                plan_text, plan_usage = self._extract_response(sub_plan_response)
                tokens = plan_usage.get("total_tokens", 0)
                if tokens > 0:
                    await self.update_token_consumption(tokens)
                    sub_state.token_usage["planner"] += tokens
 
                # Parse sub-agent plan JSON
                try:
                    if "```json" in plan_text:
                        json_text = plan_text.split("```json")[1].split("```")[0].strip()
                        sub_plan = json.loads(json_text)
                    else:
                        sub_plan = json.loads(plan_text)
                except json.JSONDecodeError:
                    self.logger.warning(
                        f"[V3] Sub-agent '{sub_state.sub_task_id}' Planner "
                        f"returned non-JSON — treating as incomplete"
                    )
                    sub_plan = {"taskComplete": False, "nextExecutor": sub_state.suggested_executor}
 
                if sub_plan.get("taskComplete", False):
                    sub_state.mark_completed()
                    self.logger.info(
                        f"[V3] Sub-agent '{sub_state.sub_task_id}' — Planner marked complete"
                    )
                    break
 
                sub_state.set_plan(sub_plan)
 
                # ── Wrap SubTaskState → temporary TaskState for _run_executor ─
                from multi_llm_orchestrator import TaskState
                temp_task = TaskState(
                    task_id=f"{sub_state.parent_task_id}__{sub_state.sub_task_id}",
                    user_request=sub_state.description,
                    user_id=sub_state.user_id
                )
                temp_task.plan = sub_state.plan
                temp_task.execution_results = list(sub_state.execution_results)
                temp_task.summaries = list(sub_state.summaries)
                temp_task.current_step = sub_state.current_step
                temp_task.total_steps = sub_state.total_steps
 
                execution_result = await self._run_executor(temp_task)
                sub_state.add_execution_result(execution_result)
 
                # Sub-agent Progress Summarizer
                sub_progress_prompt = f"""## Sub-Task Objective
{sub_state.description}
 
## Execution Result
{json.dumps(execution_result, indent=2)}
 
## Your Task
Summarize what was accomplished for this sub-task. Be concise — 
this feeds back into the sub-agent's next planning cycle."""
 
                sub_progress_response = await self.summarizer.generate(
                    prompt=sub_progress_prompt,
                    system_prompt=(
                        "You are a Sub-Agent Progress Summarizer. "
                        "Summarize ONLY your sub-task's execution result. Be concise."
                    ),
                    max_tokens=1024,
                    temperature=0.3
                )
 
                prog_text, prog_usage = self._extract_response(sub_progress_response)
                tokens = prog_usage.get("total_tokens", 0)
                if tokens > 0:
                    await self.update_token_consumption(tokens)
                    sub_state.token_usage["summarizer"] += tokens
 
                sub_state.add_summary({
                    "type": "sub_progress_summary",
                    "content": prog_text,
                    "timestamp": datetime.now().isoformat()
                })
 
                self.logger.info(
                    f"[V3] Sub-agent '{sub_state.sub_task_id}' — cycle {cycle} done"
                )
 
            # ── Sub-agent Final Summarizer ───────────────────────────────
            if not sub_state.completed:
                sub_state.mark_completed()
 
            all_results_text = json.dumps(sub_state.execution_results, indent=2)
            sub_final_prompt = f"""## Sub-Task Objective
{sub_state.description}
 
## All Execution Results
{all_results_text}
 
## Your Task
Write a final summary of everything accomplished in this sub-task.
This will be merged with other sub-agents' outputs by the parent Final Summarizer."""
 
            sub_final_response = await self.summarizer.generate(
                prompt=sub_final_prompt,
                system_prompt=(
                    "You are a Sub-Agent Final Summarizer. "
                    "Write a clear, complete summary of your sub-task's results."
                ),
                max_tokens=2048,
                temperature=0.4
            )
 
            final_text, final_usage = self._extract_response(sub_final_response)
            tokens = final_usage.get("total_tokens", 0)
            if tokens > 0:
                await self.update_token_consumption(tokens)
                sub_state.token_usage["summarizer"] += tokens
 
            sub_state.add_summary({
                "type": "sub_final_summary",
                "content": final_text,
                "timestamp": datetime.now().isoformat()
            })
 
            self.logger.info(
                f"[V3] ✅ Sub-agent '{sub_state.sub_task_id}' fully complete "
                f"({cycle} cycle(s))"
            )
 
        except Exception as e:
            error_msg = str(e)
            self.logger.error(
                f"[V3] ❌ Sub-agent '{sub_state.sub_task_id}' failed: {error_msg}"
            )
            sub_state.mark_failed(error_msg)
 
        return sub_state

    async def _run_parallel_subtasks(
        self,
        sub_states: list,
        parent_context: str
    ) -> list:
        """
        Run all sub-tasks concurrently via asyncio.gather() (the barrier).
        All sub-agents must complete before any results are forwarded.
 
        Returns list of completed SubTaskState objects in original order.
        """
        self.logger.info(
            f"[V3] Launching {len(sub_states)} parallel sub-agents via asyncio.gather()"
        )
        completed = await asyncio.gather(
            *[self._run_subtask_loop(s, parent_context) for s in sub_states],
            return_exceptions=True
        )
        # gather() can return exceptions instead of raising them
        # Mark any exception results as failed SubTaskStates
        processed = []
        for i, item in enumerate(completed):
            if isinstance(item, Exception):
                sub_states[i].mark_failed(str(item))
                processed.append(sub_states[i])
            else:
                processed.append(item)
        return processed
 
    def _merge_subtask_results(
        self,
        completed_states: list,
        parent_task_state
    ) -> None:
        """
        Tag each sub-agent's execution results and summaries with sub-task
        lineage metadata, then append them to the parent TaskState.
 
        The existing _run_summarizer_final() already dumps
        json.dumps(task_state.execution_results) into its prompt, so the
        Final Summarizer sees all sub-agent work with zero additional changes.
        """
        for sub_state in completed_states:
            if not isinstance(sub_state, SubTaskState):
                continue
 
            for result in sub_state.execution_results:
                tagged = {
                    **result,
                    "_subTaskId": sub_state.sub_task_id,
                    "_subTaskDescription": sub_state.description,
                    "_subTaskStatus": sub_state.status
                }
                parent_task_state.execution_results.append(tagged)
 
            for summary in sub_state.summaries:
                tagged = {
                    **summary,
                    "_subTaskId": sub_state.sub_task_id,
                    "_subTaskDescription": sub_state.description
                }
                parent_task_state.summaries.append(tagged)
 
        self.logger.info(
            f"[V3] Merged results from {len(completed_states)} sub-agents "
            f"into parent task state"
        )
    # ========================================================================
    # BOUNDARY V4: SECOND-TIER LOOPS
    # Each round the agent's LLM uses one of its own tools, dispatches one
    # executor, dispatches a parallel round of sub-agents, or finishes.
    # ========================================================================

    @staticmethod
    def clip(obj: Any, limit: int = 6000) -> str:
        """JSON text of obj, cut to `limit` characters so prompts stay bounded."""
        try:
            text = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, default=str)
        except Exception:
            text = str(obj)
        return text if len(text) <= limit else text[:limit] + f"... [clipped {len(text) - limit} chars]"

    @staticmethod
    def parse_json_block(text: str) -> Optional[Dict[str, Any]]:
        """The JSON in an LLM reply: the last ```json block that parses to an object,
        else the outermost {...}. None when there is no usable JSON."""
        if not text:
            return None
        import re
        for block in reversed(re.findall(r"```json\s*(.*?)```", text, re.DOTALL)):
            try:
                obj = json.loads(block.strip())
                if isinstance(obj, dict):
                    return obj
            except json.JSONDecodeError:
                continue
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            try:
                obj = json.loads(text[start:end + 1])
                if isinstance(obj, dict):
                    return obj
            except json.JSONDecodeError:
                pass
        return None

    @staticmethod
    def _truthy(value: Any) -> bool:
        return value is True or (isinstance(value, str) and value.strip().lower() == "true")

    async def run_second_tier_loop(self, role: str, system_prompt: str, brief: str,
                                   task_data: Dict[str, Any], tools: Dict[str, Any],
                                   allowed_executors=None, model=None) -> Dict[str, Any]:
        """Run one second-tier agent's loop until it finishes or hits the round limit.
        `tools` maps tool names to async functions taking an args dict.
        Returns {"finished", "report", "rounds", "results", "tokens"}."""
        model = model or ModelAPIClientWrapper(self.executor)
        context = task_data.get("context", {}) or {}
        user_request = context.get("userRequest", "")
        history = context.get("conversationHistory") or []
        allowed = set(allowed_executors) if allowed_executors is not None else None
        full_prompt = system_prompt + SECOND_TIER_LOOP_RULES.replace("{max_rounds}", str(SECOND_TIER_MAX_ROUNDS))

        results: List[Dict[str, Any]] = []
        tokens, failures, rounds = 0, 0, 0
        report, finished = "", False
        self.logger.info(f"[V4] ⚙️ {role} starts its loop")

        while rounds < SECOND_TIER_MAX_ROUNDS:
            rounds += 1
            reply = await model.generate(
                prompt=self._second_tier_round_prompt(brief, user_request, results, rounds),
                system_prompt=full_prompt,
                max_tokens=SECOND_TIER_MAX_TOKENS,
                temperature=0.3,
                conversation_history=history,
            )
            text = reply.get("text", "") if isinstance(reply, dict) else (reply or "")
            tokens += int((getattr(model, "last_usage", {}) or {}).get("total_tokens", 0) or 0)

            move = self.parse_json_block(text)
            if move is None:
                failures += 1
                self.logger.warning(f"[V4] {role} round {rounds}: no parsable JSON ({failures})")
                results.append(self._second_tier_record(role, "(no move)", "Your last reply held no valid JSON. "
                                                        "Reply with exactly one ```json block.", ok=False))
                if failures >= 2:
                    report = "Stopped: two replies in a row held no valid JSON."
                    break
                continue
            failures = 0

            if self._truthy(move.get("taskComplete")):
                report = str(move.get("report") or move.get("explanation") or "Finished.")
                finished = True
                break
            if move.get("tool"):
                results.append(await self._second_tier_tool(role, move, tools))
            elif self._truthy(move.get("parallel")) and move.get("subTasks"):
                results.extend(await self._second_tier_parallel(role, move, user_request, brief, allowed))
            elif move.get("nextExecutor"):
                results.append(await self._second_tier_executor(move, results, user_request, allowed))
            else:
                results.append(self._second_tier_record(role, "(unclear move)",
                                                        "The JSON matched none of the four shapes.", ok=False))
        else:
            report = report or f"Stopped at the {SECOND_TIER_MAX_ROUNDS}-round limit before finishing."

        self.logger.info(f"[V4] {role} finished after {rounds} round(s): {report[:200]}")
        return {"finished": finished, "report": report, "rounds": rounds, "results": results, "tokens": tokens}

    def _second_tier_round_prompt(self, brief: str, user_request: str,
                                  results: List[Dict[str, Any]], n: int) -> str:
        lines, step = [], 0
        for r in results:
            if r.get("_subTaskId"):
                continue  # a sub-agent's own steps are folded into its round
            step += 1
            status = "done" if r.get("stepCompleted") else "FAILED: " + str(r.get("error") or "")[:200]
            lines.append(f"{step}. {r.get('executorUsed', '?')}: {str(r.get('stepDescription', ''))[:200]} [{status}]")
        raw = "\n\n".join(f"[{i}] {self.clip(r, 6000)}" for i, r in enumerate(results[-10:], 1)) or "None yet."
        return f"""## Your Brief
{brief}

## Original User Request
{user_request or "(none)"}

## Moves So Far
{chr(10).join(lines) if lines else "None yet."}

## Raw Results So Far (most recent last)
{raw}

## Server Time (UTC)
{datetime.now().strftime("%Y-%m-%d %H:%M")}

## Your Task
Round {n} of at most {SECOND_TIER_MAX_ROUNDS}. Choose your next move or finish. Reply with brief reasoning, then exactly one ```json block."""

    @staticmethod
    def _second_tier_record(label: str, description: str, details: str, ok: bool,
                            error: Optional[str] = None) -> Dict[str, Any]:
        return {
            "executorUsed": label,
            "stepDescription": description,
            "executionDetails": details,
            "stepCompleted": ok,
            "error": None if ok else (error or details),
            "timestamp": datetime.now().isoformat(),
        }

    def _second_tier_refusal(self, name: str, allowed) -> str:
        if name in SECOND_TIER_AGENTS:
            return f"{name} runs its own loop and can only be chosen by the main Planner."
        if allowed is not None and name not in allowed:
            return f"{name} is not one of your executors. Yours: {', '.join(sorted(allowed))}."
        return ""

    async def _second_tier_tool(self, role: str, move: Dict[str, Any], tools: Dict[str, Any]) -> Dict[str, Any]:
        name = str(move.get("tool"))
        args = move.get("args") if isinstance(move.get("args"), dict) else {}
        label = f"{role}.{name}"
        if name not in tools:
            return self._second_tier_record(label, f"tool {name}",
                                            f"Unknown tool '{name}'. Your tools: {', '.join(tools)}", ok=False)
        try:
            out = await tools[name](args)
        except Exception as e:
            out = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        record = self._second_tier_record(label, f"tool {name}: {move.get('explanation', '')}"[:300],
                                          self.clip(out, 4000), ok=bool(out.get("ok")),
                                          error=None if out.get("ok") else out.get("error"))
        record["toolResult"] = out
        return record

    async def _second_tier_executor(self, move: Dict[str, Any], results: List[Dict[str, Any]],
                                    user_request: str, allowed) -> Dict[str, Any]:
        name = str(move.get("nextExecutor"))
        task = move.get("executorTask") if isinstance(move.get("executorTask"), dict) else {}
        refusal = self._second_tier_refusal(name, allowed)
        if refusal:
            return self._second_tier_record(name, task.get("description", name), refusal, ok=False)
        plan = {"nextExecutor": name, "executorTask": task, "explanation": move.get("explanation", "")}
        try:
            return await self.dispatch_executor(plan, list(results), user_request)
        except Exception as e:
            return self._second_tier_record(name, task.get("description", name), f"Dispatch failed: {e}", ok=False)

    async def _second_tier_parallel(self, role: str, move: Dict[str, Any], user_request: str,
                                    brief: str, allowed) -> List[Dict[str, Any]]:
        specs = [s for s in (move.get("subTasks") or []) if isinstance(s, dict)][:4]
        for spec in specs:
            refusal = self._second_tier_refusal(str(spec.get("suggestedExecutor", "")), allowed)
            if refusal:
                return [self._second_tier_record("ParallelSubAgents", "parallel round", refusal, ok=False)]
        plan = {"subTasks": specs, "explanation": move.get("explanation", "")}
        try:
            return await self.dispatch_parallel(plan, user_request, f"{role} brief:\n{brief}\n\n")
        except Exception as e:
            return [self._second_tier_record("ParallelSubAgents", "parallel round", f"Dispatch failed: {e}", ok=False)]

    async def dispatch_executor(self, plan: Dict[str, Any], prior_results: List[Dict[str, Any]],
                                user_request: str) -> Dict[str, Any]:
        """Run one executor for a second-tier loop, exactly as the main loop would."""
        state = TaskState(f"task_{datetime.now().strftime('%Y%m%d%H%M%S')}_dispatch",
                          user_request, self.clerk_user_id)
        state.plan = plan
        state.execution_results = [r for r in prior_results if isinstance(r, dict)]
        return await self._run_executor(state)

    async def dispatch_parallel(self, plan: Dict[str, Any], user_request: str,
                                brief_prefix: str = "") -> List[Dict[str, Any]]:
        """Run a round of V3 sub-agents for a second-tier loop. Returns their raw
        execution results (tagged with their sub-task) followed by one round result."""
        specs = (plan.get("subTasks") or [])[:4]
        parent_task_id = f"task_{datetime.now().strftime('%Y%m%d%H%M%S')}_parallel"
        sibling_tasks = "\n".join(
            f"  - [{st.get('subTaskId', f'sub_{i}')}]: {st.get('description', '')}"
            for i, st in enumerate(specs)
        )
        parent_context = (
            f"{brief_prefix}"
            f"Original user request: {user_request}\n\n"
            f"Reasoning for this round:\n{plan.get('explanation', '')}\n\n"
            f"Total parallel sub-tasks: {len(specs)}\n\n"
            f"All parallel sub-tasks (including yours):\n{sibling_tasks}\n\n"
            f"You can see what your sibling sub-agents are assigned to do. "
            f"If your task depends on another sub-agent's output, use "
            f"InChatMemoryExecutor to check the shared conversation thread "
            f"for their committed results before proceeding."
        )
        sub_states = [
            SubTaskState(
                sub_task_id=spec.get("subTaskId", f"sub_{i}"),
                parent_task_id=parent_task_id,
                description=spec.get("description", ""),
                suggested_executor=spec.get("suggestedExecutor", "DocsExecutor"),
                user_id=self.clerk_user_id,
            )
            for i, spec in enumerate(specs)
        ]
        completed = await self._run_parallel_subtasks(sub_states, parent_context)

        results: List[Dict[str, Any]] = []
        summaries = []
        for s in completed:
            if not isinstance(s, SubTaskState):
                continue
            for r in s.execution_results:
                results.append({**r, "_subTaskId": s.sub_task_id,
                                "_subTaskDescription": s.description, "_subTaskStatus": s.status})
            finals = [x for x in s.summaries if x.get("type") == "sub_final_summary"]
            summaries.append(f"[{s.sub_task_id}] ({s.status}) "
                             f"{finals[-1]['content'] if finals else (s.error or '')}")

        details = "\n\n".join(summaries)
        results.append({
            "executorUsed": "ParallelSubAgents",
            "stepDescription": "Parallel round: " + ", ".join(st.get("subTaskId", f"sub_{i}")
                                                              for i, st in enumerate(specs)),
            "executionDetails": details,
            "executorFullResponse": details,
            "stepCompleted": bool(summaries),
            "error": None if summaries else "No sub-agent returned a result",
            "timestamp": datetime.now().isoformat(),
        })
        return results
    async def stream_task(self, user_request: str, conversation_history: List[Dict[str, str]] = None, user_id: str = "anonymous", agent_id: str = None):
        """Stream results as each agent completes their work WITH conversation history support.
        
        Args:
            user_request: The user's current request
            conversation_history: Optional list of previous messages for context
            agent_id: The current agent's ID — used to exclude it from cross-agent search
        
        Backend automatically optimizes history - frontend doesn't need to change!
        """
        # Store agent_id for cross-agent context scoping
        self.agent_id = agent_id or ""

        # Automatically optimize conversation history (NO FRONTEND CHANGES NEEDED!)
        if conversation_history:
            original_length = len(conversation_history)
            conversation_history = self._optimize_conversation_history(conversation_history)
            
            if len(conversation_history) < original_length:
                self.logger.info(
                    f"[Orchestrator] 💡 Auto-optimized: {original_length} → {len(conversation_history)} messages"
                )
        
        # Store optimized conversation history in instance for use by agents
        self.conversation_history = conversation_history or []
        
        # ── Enrich with cross-agent DB context (multi-LLM only) ──
        yield {"agentRole": "context", "token": "Checking for relevant past conversations...\n"}
        user_request = await self._enrich_with_db_context(user_request, user_id)
        
        # Create a unique task ID
        task_id = f"task_{datetime.now().strftime('%Y%m%d%H%M%S')}_{id(user_request)}"
        
        # Initialize task state (now with enriched request)
        task_state = TaskState(task_id, user_request, user_id)
        self.task_states[task_id] = task_state
        
        # Stream initial summary from summarizer
        yield {"agentRole": "summarizer", "token": "Processing your request...\n"}
        
        initial_summary = await self._run_summarizer_initial(task_state)
        task_state.add_summary(initial_summary)
        
        if "usage" in initial_summary:
            yield {"type": "usage", "usage": initial_summary["usage"], "agent": "summarizer"}

        summary_artifacts = self._analyze_for_artifacts(initial_summary["content"], "summarizer")
        if summary_artifacts["artifacts"]:
            yield {"agentRole": "summarizer", "artifacts": summary_artifacts["artifacts"]}

        text = summary_artifacts["content"]
        chunk_size = 30
        for i in range(0, len(text), chunk_size):
            chunk = text[i:i+chunk_size]
            yield {"agentRole": "summarizer", "token": chunk}
            await asyncio.sleep(0.2)
        
        # Continue with planner
        yield {"agentRole": "planner", "token": "\n\nCreating a plan...\n"}
        
        plan_result = await self._run_planner(task_state)
        
        if "usage" in plan_result:
            yield {"type": "usage", "usage": plan_result["usage"], "agent": "planner"}
        
        planner_artifacts = self._analyze_for_artifacts(plan_result.get("plannerResponse", ""), "planner")
        if planner_artifacts["artifacts"]:
            yield {"agentRole": "planner", "artifacts": planner_artifacts["artifacts"]}

        text = planner_artifacts["content"]
        chunk_size = 30
        for i in range(0, len(text), chunk_size):
            chunk = text[i:i+chunk_size]
            yield {"agentRole": "planner", "token": chunk}
            await asyncio.sleep(0.2)
        # ═══════════════════════════════════════════════════════════════
        # V3 PARALLEL PATH — intercept BEFORE sequential while loop
        # ═══════════════════════════════════════════════════════════════
        if plan_result.get("parallel", False) and plan_result.get("subTasks"):
            sub_tasks_spec = plan_result.get("subTasks", [])
            num_subs = len(sub_tasks_spec)
            planner_text = plan_result.get("plannerResponse", "")

            self.logger.info(
                f"[V3] Parallel mode detected — {num_subs} sub-tasks"
            )

            yield {
                "agentRole": "planner",
                "token": f"\n\nDecomposing into {num_subs} parallel sub-agents...\n"
            }
            yield {
                "type": "parallel_start",
                "subTasks": [
                    {
                        "subTaskId": st.get("subTaskId", f"sub_{i}"),
                        "description": st.get("description", "")
                    }
                    for i, st in enumerate(sub_tasks_spec)
                ]
            }

            task_state.set_plan(plan_result)

            sibling_tasks = "\n".join([
                f"  - [{st.get('subTaskId', f'sub_{i}')}]: {st.get('description', '')}"
                for i, st in enumerate(sub_tasks_spec)
            ])

            parent_context = (
                f"Original user request: {task_state.user_request}\n\n"
                f"Parent Planner's analysis:\n{planner_text}\n\n"
                f"Total parallel sub-tasks: {num_subs}\n\n"
                f"All parallel sub-tasks (including yours):\n{sibling_tasks}\n\n"
                f"You can see what your sibling sub-agents are assigned to do. "
                f"If your task depends on another sub-agent's output, use "
                f"InChatMemoryExecutor to check the shared conversation thread "
                f"for their committed results before proceeding."
            )

            # Create SubTaskStates
            sub_states = []
            for i, spec in enumerate(sub_tasks_spec):
                sub_id = spec.get("subTaskId", f"sub_{i}")
                sub_states.append(SubTaskState(
                    sub_task_id=sub_id,
                    parent_task_id=task_state.task_id,
                    description=spec.get("description", ""),
                    suggested_executor=spec.get("suggestedExecutor", "DocsExecutor"),
                    user_id=task_state.user_id
                ))

            # Announce each sub-agent start
            for sub_state in sub_states:
                yield {
                    "type": "sub_agent_start",
                    "subTaskId": sub_state.sub_task_id,
                    "description": sub_state.description,
                    "token": f"\n[Sub-agent '{sub_state.sub_task_id}'] Starting: {sub_state.description}\n"
                }

            # ── THE BARRIER — all sub-agents run concurrently ──────────
            completed_states = await self._run_parallel_subtasks(
                sub_states, parent_context
            )
            # ──────────────────────────────────────────────────────────

            # Stream completion events
            for state in completed_states:
                if not isinstance(state, SubTaskState):
                    continue
                if state.completed:
                    final_sums = [
                        s for s in state.summaries
                        if s.get("type") == "sub_final_summary"
                    ]
                    final_text = final_sums[-1]["content"] if final_sums else "Completed."
                    yield {
                        "type": "sub_agent_complete",
                        "subTaskId": state.sub_task_id,
                        "status": "completed",
                        "token": f"\n[Sub-agent '{state.sub_task_id}'] ✅ Complete\n"
                    }
                    for i in range(0, len(final_text), chunk_size):
                        yield {
                            "agentRole": "executor",
                            "subTaskId": state.sub_task_id,
                            "token": final_text[i:i+chunk_size]
                        }
                        await asyncio.sleep(0.2)
                else:
                    yield {
                        "type": "sub_agent_complete",
                        "subTaskId": state.sub_task_id,
                        "status": "failed",
                        "error": state.error,
                        "token": f"\n[Sub-agent '{state.sub_task_id}'] ❌ Failed: {state.error}\n"
                    }

            yield {"type": "parallel_complete", "subTaskCount": num_subs}

            # Merge all sub-agent results into parent TaskState
            valid_states = [s for s in completed_states if isinstance(s, SubTaskState)]
            self._merge_subtask_results(valid_states, task_state)

            # Final Summarizer — sees all merged sub-agent work
            yield {
                "agentRole": "summarizer",
                "token": "\n\nAll sub-agents complete. Preparing final synthesis...\n"
            }
            task_state.mark_completed()
            final_summary = await self._run_summarizer_final(task_state)
            task_state.add_summary(final_summary)
            self.final_summary_text = final_summary["content"]

            if "usage" in final_summary:
                yield {"type": "usage", "usage": final_summary["usage"], "agent": "summarizer"}

            final_text = final_summary["content"]
            for i in range(0, len(final_text), chunk_size):
                yield {"agentRole": "summarizer", "token": final_text[i:i+chunk_size]}
                await asyncio.sleep(0.2)

            return  # parallel path complete — skip sequential while loop
        # Continue until task is complete
        while not task_state.completed:
            if plan_result.get("taskComplete", False):
                task_state.mark_completed()
                
                yield {"agentRole": "summarizer", "token": "\n\nPreparing final summary...\n"}
                final_summary = await self._run_summarizer_final(task_state)
                task_state.add_summary(final_summary)
                self.final_summary_text = final_summary["content"]
                
                if "usage" in final_summary:
                    yield {"type": "usage", "usage": final_summary["usage"], "agent": "summarizer"}
                
                final_artifacts = self._analyze_for_artifacts(final_summary["content"], "summarizer")
                if final_artifacts["artifacts"]:
                    yield {"agentRole": "summarizer", "artifacts": final_artifacts["artifacts"]}

                text = final_artifacts["content"]
                chunk_size = 30
                for i in range(0, len(text), chunk_size):
                    chunk = text[i:i+chunk_size]
                    yield {"agentRole": "summarizer", "token": chunk}
                    await asyncio.sleep(0.2)
                break
            
            task_state.set_plan(plan_result)
            
            yield {"agentRole": "executor", "token": "\n\nExecuting the plan...\n"}
            execution_result = await self._run_executor(task_state)
            task_state.add_execution_result(execution_result)

            if "artifacts" in execution_result and execution_result["artifacts"]:
                yield {"agentRole": "executor", "artifacts": execution_result["artifacts"]}

            execution_artifacts = self._analyze_for_artifacts(execution_result.get("executionDetails", ""), "executor")
            if execution_artifacts["artifacts"]:
                yield {"agentRole": "executor", "artifacts": execution_artifacts["artifacts"]}

            text = execution_artifacts["content"]
            chunk_size = 30
            for i in range(0, len(text), chunk_size):
                chunk = text[i:i+chunk_size]
                yield {"agentRole": "executor", "token": chunk}
                await asyncio.sleep(0.2)
            
            yield {"agentRole": "summarizer", "token": "\n\nAnalyzing progress...\n"}
            progress_summary = await self._run_summarizer_progress(task_state)
            task_state.add_summary(progress_summary)
            
            if "usage" in progress_summary:
                yield {"type": "usage", "usage": progress_summary["usage"], "agent": "summarizer"}
            
            progress_artifacts = self._analyze_for_artifacts(progress_summary["content"], "summarizer")
            if progress_artifacts["artifacts"]:
                yield {"agentRole": "summarizer", "artifacts": progress_artifacts["artifacts"]}

            text = progress_artifacts["content"]
            chunk_size = 30
            for i in range(0, len(text), chunk_size):
                chunk = text[i:i+chunk_size]
                yield {"agentRole": "summarizer", "token": chunk}
                await asyncio.sleep(0.2)
            
            yield {"agentRole": "planner", "token": "\n\nEvaluating next steps...\n"}
            plan_result = await self._run_planner(task_state)
            
            if "usage" in plan_result:
                yield {"type": "usage", "usage": plan_result["usage"], "agent": "planner"}
            
            planner_artifacts = self._analyze_for_artifacts(plan_result.get("plannerResponse", ""), "planner")
            if planner_artifacts["artifacts"]:
                yield {"agentRole": "planner", "artifacts": planner_artifacts["artifacts"]}

            text = planner_artifacts["content"]
            chunk_size = 30
            for i in range(0, len(text), chunk_size):
                chunk = text[i:i+chunk_size]
                yield {"agentRole": "planner", "token": chunk}
                await asyncio.sleep(0.2)
    
    # ========================================================================
    # TOOL CALLING: DB CONTEXT SEARCH
    # ========================================================================

    async def _search_messages_db(
        self,
        user_id: str,
        keyword: Optional[str] = None,
        title: Optional[str] = None,
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Query Supabase messages table for past conversations.
        Always scoped to the authenticated user.
        """
        if not self.supabase:
            self.logger.warning("[ToolCall] Supabase not available for message search")
            return []

        try:
            query = (
                self.supabase.table("messages")
                .select("role, title, keywords, content, timestamp")
                .eq("user_id", user_id)
            )

            if title:
                query = query.ilike("title", f"%{title}%")

            if keyword:
                query = query.contains("keywords", [keyword])

            query = query.order("timestamp", desc=True).limit(limit)
            result = query.execute()

            self.logger.info(
                f"[ToolCall] search_past_messages returned {len(result.data)} results "
                f"(keyword={keyword}, title={title})"
            )
            return result.data

        except Exception as e:
            self.logger.error(f"[ToolCall] DB search failed: {e}")
            return []


    def _analyze_for_artifacts(self, response: str, agent_role: str) -> dict:
        """Analyzes agent response and extracts potential artifacts."""
        import re
        import time
        
        artifacts = []
        modified_content = response

        # FIXED: Planner and Summarizer should NOT create new artifacts
        # They should only reference existing Executor artifacts via markers
        if agent_role in ["planner", "summarizer"]:
            return {
                "content": response,
                "artifacts": []
            }
        
        code_pattern = r'```(\w+)?\n(.*?)```'
        code_matches = re.finditer(code_pattern, response, re.DOTALL)
        
        for match in code_matches:
            language = match.group(1) or 'plaintext'
            code_content = match.group(2).strip()
            
            line_count = len(code_content.split('\n'))
            if line_count >= self.artifact_threshold_lines:
                artifact_id = f"{agent_role}_code_{int(time.time() * 1000)}"
                
                title_match = re.search(r'^(?:#|//|/\*)\s*(.+?)(?:\*/)?$', code_content, re.MULTILINE)
                title = title_match.group(1).strip() if title_match else f"{language.capitalize()} Implementation"
                
                artifact = {
                    "id": artifact_id,
                    "type": "code",
                    "language": language,
                    "title": title,
                    "content": code_content,
                    "lines": line_count,
                    "agentRole": agent_role
                }
                artifacts.append(artifact)
                
                marker = f"[ARTIFACT:{artifact_id}:code:{title}]"
                modified_content = modified_content.replace(match.group(0), marker, 1)
        
        doc_pattern = r'(?:^|\n)(#{1,3}\s+.+?)(?=\n#{1,3}\s+|\Z)'
        doc_matches = list(re.finditer(doc_pattern, response, re.MULTILINE | re.DOTALL))
        
        for i, match in enumerate(doc_matches):
            section_content = match.group(0).strip()
            if len(section_content) >= self.artifact_threshold_chars:
                artifact_id = f"{agent_role}_doc_{int(time.time() * 1000)}_{i}"
                
                title_match = re.search(r'^#{1,3}\s+(.+?)$', section_content, re.MULTILINE)
                title = title_match.group(1).strip() if title_match else "Documentation"
                
                artifact = {
                    "id": artifact_id,
                    "type": "markdown",
                    "title": title,
                    "content": section_content,
                    "chars": len(section_content),
                    "agentRole": agent_role
                }
                artifacts.append(artifact)
                
                marker = f"[ARTIFACT:{artifact_id}:markdown:{title}]"
                modified_content = modified_content.replace(match.group(0), marker, 1)
        
        slide_pattern = r'(?:Slide\s+\d+:|##\s+Slide\s+\d+).*?(?=(?:Slide\s+\d+:|##\s+Slide\s+\d+)|$)'
        slide_matches = list(re.finditer(slide_pattern, response, re.DOTALL))
        
        if len(slide_matches) >= 3:
            slides = []
            for idx, match in enumerate(slide_matches):
                slides.append({
                    "number": idx + 1,
                    "content": match.group(0).strip()
                })
            
            artifact_id = f"{agent_role}_pres_{int(time.time() * 1000)}"
            title = "Presentation"
            
            title_match = re.search(r'^#\s+(.+?)$', response, re.MULTILINE)
            if title_match:
                title = title_match.group(1).strip()
            
            full_content = "\n\n".join([s["content"] for s in slides])
            artifact = {
                "id": artifact_id,
                "type": "presentation",
                "title": title,
                "content": full_content,
                "slides": slides,
                "agentRole": agent_role
            }
            artifacts.append(artifact)
            
            for match in slide_matches:
                modified_content = modified_content.replace(match.group(0), "", 1)
            modified_content = modified_content.strip() + f"\n\n[ARTIFACT:{artifact_id}:presentation:{title}]"
        
        return {
            "content": modified_content,
            "artifacts": artifacts
        }