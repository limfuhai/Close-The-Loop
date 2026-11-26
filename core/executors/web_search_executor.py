# react/core/executors/web_search_executor.py

import os
import json
import re
from typing import Dict, Any, List, Optional
from datetime import datetime
from .base_executor import BaseExecutor
import aiohttp


class WebSearchExecutor(BaseExecutor):
    """Executor for web searches using Brave Search API (capped to max 10 queries/results)."""

    def __init__(self, mcp_manager, mcp_registry, model=None):
        super().__init__(mcp_manager, mcp_registry)
        self.model = model
        self.api_key = os.getenv("BRAVE_SEARCH_API_KEY")
        if not self.api_key:
            self.logger.warning("BRAVE_SEARCH_API_KEY not found in environment")
        
        self.logger.info(
            "✅ Initialized WebSearchExecutor%s",
            f" with model={model.__class__.__name__ if model else 'None'} and Brave API key={'present' if self.api_key else 'MISSING'}",
        )

    async def execute_task(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute web search using LLM/Planner-provided queries with a contextual fallback (max 10)."""
        self.logger.info("=" * 80)
        self.logger.info("🔍 STARTING WEB SEARCH EXECUTION")
        self.logger.info("=" * 80)
        
        results = {
            "status": "started",
            "executorUsed": "WebSearchExecutor",
            "artifacts": [],
            "summary": "",
            "timestamp": datetime.now().isoformat(),
        }

        if not self.api_key:
            self.logger.error("❌ Brave Search API key not configured!")
            results["status"] = "error"
            results["error"] = "Brave Search API key not configured"
            return results

        try:
            # Hard caps
            FANOUT_MAX = 10
            PER_QUERY_MAX = 10
            self._max_results = PER_QUERY_MAX

            self.logger.info(f"📊 Configuration: MAX_QUERIES={FANOUT_MAX}, MAX_RESULTS_PER_QUERY={PER_QUERY_MAX}")
            
            # Log received task data
            self.logger.info("📥 Received task_data:")
            self.logger.info(f"   - Keys: {list(task_data.keys())}")
            
            # FIXED: Handle both task_data structures
            executor_task = task_data.get('executorTask')
            if executor_task:
                self.logger.info(f"   - executorTask present with keys: {list(executor_task.keys())}")
            else:
                self.logger.info("   - executorTask: NOT PRESENT, using task_data directly")
                # Use task_data directly as executorTask
                executor_task = task_data
            
            if 'context' in task_data:
                self.logger.info(f"   - context keys: {list(task_data['context'].keys())}")

            # 1) Try to use LLM to generate queries from planner's instructions
            queries = await self._generate_queries_with_llm(task_data, max_queries=FANOUT_MAX)
            
            # 2) If LLM failed, fall back to extraction methods
            if not queries:
                self.logger.warning("⚠️  LLM query generation failed, falling back to extraction methods")
                queries = self._gather_candidate_queries(task_data, max_queries=FANOUT_MAX)

            # As a final guard, if nothing usable, short-circuit with an actionable error
            if not queries:
                self.logger.error("❌ No search queries could be generated!")
                results["status"] = "error"
                results["error"] = (
                    "No search queries found. Provide queries JSON like "
                    '{"queries":[{"query":"your topic 2025"}, {"query":"another facet"}]} '
                    "in task_data or context.executorResponse."
                )
                return results

            self.logger.info(f"✅ Generated {len(queries)} search queries:")
            for i, q in enumerate(queries, 1):
                self.logger.info(f"   {i}. '{q}'")

            # 2) Execute searches (fan-out up to 10)
            self.logger.info("🚀 Executing searches...")
            all_results = []
            for idx, q in enumerate(queries[:FANOUT_MAX], 1):
                self.logger.info(f"🔎 Query {idx}/{len(queries[:FANOUT_MAX])}: '{q}'")
                search_results = await self._execute_search(q)
                result_count = len(search_results or [])
                self.logger.info(f"   ✓ Received {result_count} results")
                
                all_results.append({
                    "query": q,
                    "results": (search_results or [])[:PER_QUERY_MAX],
                })

            # 3) Produce a structured, *non-opinionated* results doc (no synthesis of claims)
            self.logger.info("📝 Formatting results document...")
            report = self._format_results_document(all_results)

            total_results = sum(len(r['results']) for r in all_results)
            self.logger.info(f"✅ Search complete: {len(all_results)} queries, {total_results} total results")

            artifacts = [
                self.create_artifact(
                    "web_search_results",
                    "Web Search Results",
                    {
                        "content": report,
                        "raw_results": all_results,
                        "raw_queries": queries,
                        "summary": (
                            f"Executed {len(all_results)} queries "
                            f"with {total_results} results (≤ 10x10)."
                        ),
                    },
                    {"type": "document", "format": "markdown"},
                )
            ]

            results["artifacts"] = artifacts
            results["status"] = "completed"
            results["summary"] = f"Completed {len(all_results)} web searches (max 10 queries × 10 results)."
            results["executorFullResponse"] = f"Successfully executed {len(all_results)} searches with {total_results} total results. See artifacts for detailed results."
            
            self.logger.info("=" * 80)
            self.logger.info("✅ WEB SEARCH EXECUTION COMPLETED SUCCESSFULLY")
            self.logger.info("=" * 80)

        except Exception as e:
            self.logger.error("=" * 80)
            self.logger.error(f"❌ Web search executor error: {str(e)}")
            self.logger.error("=" * 80)
            import traceback
            self.logger.error(traceback.format_exc())
            
            results["status"] = "error"
            results["error"] = str(e)
            results["summary"] = f"Error performing web search: {str(e)}"

        return results

    # -------------------------
    # LLM-based query generation
    # -------------------------
    async def _generate_queries_with_llm(self, task_data: Dict[str, Any], max_queries: int = 10) -> List[str]:
        """Use LLM to generate search queries from planner's instructions."""
        if not self.model:
            self.logger.warning("⚠️  No model available for LLM query generation")
            return []
        
        try:
            self.logger.info("🤖 Attempting LLM-based query generation...")
            
            # Import the prompt
            try:
                from comprehensive_formatting_prompts import WEB_SEARCH_EXECUTOR_PROMPT
                self.logger.info("✅ Loaded WEB_SEARCH_EXECUTOR_PROMPT")
            except ImportError:
                self.logger.error("❌ Failed to import WEB_SEARCH_EXECUTOR_PROMPT")
                return []
            
            # FIXED: Handle both task_data structures
            executor_task = task_data.get("executorTask", task_data)
            description = executor_task.get("description", "")
            requirements = executor_task.get("requirements", [])
            user_prompt = task_data.get("query") or task_data.get("userPrompt", "")
            
            # Get planner's response if available
            planner_response = task_data.get("context", {}).get("plannerResponse", "")
            user_request = task_data.get("context", {}).get("userRequest", "")
            
            llm_context = f"""
# Planner's Instructions for Web Search:

## User's Original Request:
{user_request or user_prompt}

## Task Description:
{description}

## Requirements:
{chr(10).join(f"- {r}" for r in requirements) if requirements else "None specified"}

## Planner's Full Context:
{planner_response if planner_response else "Not available"}

---

Based on the above instructions, generate {max_queries} specific search queries for Brave Search API.
Output ONLY a JSON object with this structure:
{{
  "queries": [
    {{"query": "specific search query 1"}},
    {{"query": "specific search query 2"}},
    {{"query": "specific search query 3"}}
  ]
}}

Make queries specific and focused. Include year (2024 or 2025) if relevant.
"""
            
            self.logger.info("📤 Sending prompt to LLM...")
            self.logger.debug(f"LLM context preview: {llm_context[:300]}...")
            
            # FIXED: Use generate() not agenerate_response()
            response = await self.model.generate(
                prompt=llm_context,
                system_prompt=WEB_SEARCH_EXECUTOR_PROMPT,
                temperature=0.7,
                max_tokens=1024
            )
            
            self.logger.info(f"📥 Received LLM response: {response[:200]}...")
            
            # Extract JSON from response
            parsed = self._extract_search_instructions(response)
            if parsed and "queries" in parsed:
                queries = self._normalize_queries(parsed["queries"])
                self.logger.info(f"✅ LLM generated {len(queries)} queries")
                return queries[:max_queries]
            else:
                self.logger.warning("⚠️  LLM response did not contain valid queries JSON")
                return []
                
        except Exception as e:
            self.logger.error(f"❌ LLM query generation failed: {str(e)}")
            import traceback
            self.logger.error(traceback.format_exc())
            return []

    # -------------------------
    # Query gathering & fallback
    # -------------------------
    def _gather_candidate_queries(self, task_data: Dict[str, Any], max_queries: int = 10) -> List[str]:
        """
        Priority:
        1) Direct queries in task_data["queries"] or task_data["executorTask"]["queries"]
        2) JSON in context.executorResponse (```json ... ``` or inline)
        3) Contextual fallback built from description/requirements/userPrompt
        """
        self.logger.info("🔍 Gathering queries using fallback extraction methods...")
        
        # 1) Direct queries on task_data
        direct = self._normalize_queries(task_data.get("queries"))
        if direct:
            self.logger.info(f"✅ Found {len(direct)} direct queries in task_data")
            return direct[:max_queries]

        # 2) Planner-packed executorTask.queries
        executor_task = task_data.get("executorTask", task_data)  # FIXED: Use task_data if no executorTask
        direct2 = self._normalize_queries(executor_task.get("queries"))
        if direct2:
            self.logger.info(f"✅ Found {len(direct2)} queries in executorTask")
            return direct2[:max_queries]

        # 3) JSON embedded in LLM response
        llm_response = task_data.get("context", {}).get("executorResponse", "")
        if llm_response:
            self.logger.info("🔍 Attempting to extract queries from executorResponse...")
            parsed = self._extract_search_instructions(llm_response)
            if parsed and "queries" in parsed:
                from_llm = self._normalize_queries(parsed["queries"])
                if from_llm:
                    self.logger.info(f"✅ Extracted {len(from_llm)} queries from executorResponse")
                    return from_llm[:max_queries]

        # 4) Contextual fallback from description/requirements/userPrompt
        self.logger.info("🔄 Using contextual fallback to generate queries...")
        desc = (executor_task.get("description") or "").strip()
        reqs = executor_task.get("requirements") or []
        user_prompt = (task_data.get("query") or task_data.get("userPrompt") or "").strip()
        
        # ADDED: Also try context.userRequest
        if not user_prompt:
            user_prompt = task_data.get("context", {}).get("userRequest", "").strip()
            self.logger.info(f"   Using userRequest from context: '{user_prompt[:50]}...'")

        fallback = self._compose_contextual_fallback(desc, reqs, user_prompt, max_queries=max_queries)
        if fallback:
            self.logger.info(f"✅ Generated {len(fallback)} contextual fallback queries")
        else:
            self.logger.warning("⚠️  Failed to generate any fallback queries")
        
        return fallback[:max_queries]

    def _normalize_queries(self, candidate: Any) -> List[str]:
        """Accept list[str] or list[dict{query:str,...}] and return clean list[str]."""
        out: List[str] = []
        if isinstance(candidate, list):
            for item in candidate:
                if isinstance(item, str):
                    q = item.strip()
                    if q:
                        out.append(q)
                elif isinstance(item, dict) and isinstance(item.get("query"), str):
                    q = item["query"].strip()
                    if q:
                        out.append(q)
        return self._dedupe_preserve(out)

    def _compose_contextual_fallback(
        self,
        description: str,
        requirements: List[str],
        user_prompt: str,
        max_queries: int = 10,
    ) -> List[str]:
        """
        Build specific, topical queries from available text.
        - No 'executive summary'/'overview' fillers.
        - Add current/previous year if absent (2025/2024).
        - Emit breadth + depth + freshness variations.
        """
        # Prefer rich text: description + requirements + user_prompt
        corpus = " ".join([t for t in [description, " ".join(requirements or []), user_prompt] if t]).strip()
        
        self.logger.info(f"   Building from corpus: '{corpus[:100]}...'")
        
        if not corpus:
            self.logger.warning("   No corpus available for contextual fallback!")
            return []  # do not emit generic queries

        years = ["2025", "2024"]
        has_year = any(y in corpus for y in years)
        year_suffix = "" if has_year else f" {years[0]}"

        # Extract coarse keywords (naive but effective)
        tokens = [t.lower() for t in re.findall(r"[A-Za-z0-9\-]{3,}", corpus)]
        stop = {"the","and","with","from","that","this","into","your","about","between","based","their","there","here","such"}
        keywords = [t for t in tokens if t not in stop][:8]
        focus = " ".join(keywords[:6]) if keywords else corpus

        # Strategy: breadth (use corpus), depth (keywords), freshness (trend/outlook)
        q1 = (corpus + year_suffix).strip()
        q2 = (focus + ("" if has_year else f" {years[0]}")).strip()
        q3 = (focus + f" {years[-1]} trend").strip()

        queries = self._dedupe_preserve([q for q in [q1, q2, q3] if q])[:max_queries]
        self.logger.info(f"   Generated {len(queries)} queries: {queries}")
        return queries

    def _dedupe_preserve(self, items: List[str]) -> List[str]:
        seen = set()
        out = []
        for it in items:
            k = it.lower().strip()
            if k and k not in seen:
                seen.add(k)
                out.append(it.strip())
        return out

    # -------------------------
    # LLM/JSON extraction
    # -------------------------
    def _extract_search_instructions(self, llm_response: str) -> Optional[Dict[str, Any]]:
        """Extract search queries JSON from an LLM response."""
        if not llm_response:
            return None
        try:
            # Look for fenced ```json blocks first
            json_matches = re.findall(r'```json\s*\n(.*?)\n```', llm_response, re.DOTALL)
            if json_matches:
                for match in json_matches:
                    try:
                        cleaned = re.sub(r',\s*([}\]])', r'\1', match.strip())
                        return json.loads(cleaned)
                    except json.JSONDecodeError:
                        continue

            # Fallback: inline "queries":[...]
            if '"queries"' in llm_response:
                start = llm_response.find('"queries"')
                brace_start = llm_response.find('[', start)
                if brace_start > 0:
                    depth = 0
                    i = brace_start
                    while i < len(llm_response):
                        ch = llm_response[i]
                        if ch == '[':
                            depth += 1
                        elif ch == ']':
                            depth -= 1
                            if depth == 0:
                                try:
                                    queries_str = llm_response[brace_start:i+1]
                                    return {"queries": json.loads(queries_str)}
                                except Exception:
                                    pass
                                break
                        i += 1
        except Exception as e:
            self.logger.error(f"Failed to extract search instructions: {e}")
        return None

    # -------------------------
    # Brave API call
    # -------------------------
    async def _execute_search(self, query: str) -> List[Dict[str, Any]]:
        """Execute a single search query (ask Brave for ≤ 10 results)."""
        self.logger.info(f"   🌐 Calling Brave Search API for: '{query}'")
        
        headers = {
            "Accept": "application/json",
            "X-Subscription-Token": self.api_key,
        }
        params = {
            "q": query,
            "count": min(getattr(self, "_max_results", 10), 10),
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://api.search.brave.com/res/v1/web/search",
                    headers=headers,
                    params=params,
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        results = data.get("web", {}).get("results", [])
                        self.logger.info(f"   ✅ Brave API returned {len(results)} results")
                        return results
                    else:
                        self.logger.error(f"   ❌ Search API error: HTTP {response.status}")
                        error_text = await response.text()
                        self.logger.error(f"   Error response: {error_text[:200]}")
                        return []
        except Exception as e:
            self.logger.error(f"   ❌ Search request failed: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            return []

    # -------------------------
    # Formatting (no synthesis)
    # -------------------------
    def _format_results_document(self, all_results: List[Dict[str, Any]]) -> str:
        """
        Produce a markdown doc with sections per query and top 10 results.
        Intentionally avoids synthesizing claims; leaves that to Summarizer.
        """
        self.logger.info("📄 Formatting results into markdown document...")
        
        report = "# Web Search Results\n\n"
        report += f"**Search completed at**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        report += "---\n\n"
        
        for item in all_results:
            query = item.get("query", "")
            results = item.get("results", []) or []

            report += f"## Search Query: {query}\n\n"
            if not results:
                report += "_No results found for this query._\n\n---\n\n"
                continue

            report += f"### Top Results ({len(results[:10])} results)\n\n"
            for i, r in enumerate(results[:10], 1):
                title = r.get("title", "No title")
                url = r.get("url", "#")
                desc = r.get("description") or r.get("snippet") or ""
                report += f"**{i}. {title}**\n"
                report += f"- **Source**: {url}\n"
                if desc:
                    report += f"- **Description**: {desc}\n"
                report += "\n"
            report += "---\n\n"
        
        self.logger.info(f"✅ Formatted document: {len(report)} characters")
        return report
