"""
File Search Executor - Search for files on user's local machine
Uses LLM to extract search pattern and path from natural language descriptions
"""

from __future__ import annotations

import logging
from typing import Dict, Any
import json

from .base_executor import BaseExecutor
from ..execution.bridge_query import BridgeQuery


class FileSearchExecutor(BaseExecutor):
    """Executor for searching files on user's local machine via bridge."""

    def __init__(self, mcp_manager, mcp_registry, model_client):
        super().__init__(mcp_manager, mcp_registry)
        self.logger = logging.getLogger(__name__)
        self.executor_name = "FileSearchExecutor"
        self.model = model_client

    async def execute_task(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute file search task on user's local machine."""
        
        results: Dict[str, Any] = {
            "status": "started",
            "executorUsed": self.executor_name,
            "filesFound": [],
            "summary": "",
        }

        try:
            # Extract parameters
            api_key = task_data.get("apiKey")
            if not api_key:
                raise Exception("No API key provided - bridge access requires authentication")
            
            description = task_data.get("description", "")
            context = task_data.get("context", {})
            user_request = context.get("userRequest", "")
            
            self.logger.info(f"📋 Task: {description}")
            
            # USE LLM TO EXTRACT SEARCH PATTERN AND PATH
            system_prompt = """You are a file search parameter extractor.

The user wants to search for files. Extract the search pattern and directory path.

Examples:
- "Find PDFs in Documents" → {"pattern": "*.pdf", "path": "~/Documents"}
- "Search for Excel files" → {"pattern": "*.xlsx", "path": "~"}
- "Find all images on Desktop" → {"pattern": "*.{jpg,png,gif}", "path": "~/Desktop"}
- "Search Downloads for Word docs" → {"pattern": "*.docx", "path": "~/Downloads"}

Return ONLY JSON with "pattern" and "path" keys."""

            prompt = f"""User request: {user_request}

Task description: {description}

Extract search parameters as JSON:"""

            self.logger.info(f"🤖 Asking LLM to extract search parameters...")
            
            response = await self.model.generate(
                prompt=prompt,
                system_prompt=system_prompt,
                max_tokens=200,
                temperature=0.2
            )
            
            # Parse JSON response
            import re
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                params = json.loads(json_match.group(0))
                search_pattern = params.get("pattern", "*")
                search_path = params.get("path", "~")
            else:
                # Fallback
                search_pattern = "*"
                search_path = "~"
            
            self.logger.info(f"✅ Pattern: {search_pattern}, Path: {search_path}")
            
            # Initialize BridgeQuery
            query = BridgeQuery(
                api_key=api_key
            )
            
            # Search files via bridge
            self.logger.info(f"🌉 Searching files via bridge...")
            files = await query.search_files(
                pattern=search_pattern,
                search_path=search_path,
                max_results=50,
                timeout=30
            )
            
            if files:
                results["filesFound"] = files
                results["status"] = "completed"
                results["summary"] = f"✅ Found {len(files)} file(s) matching '{search_pattern}' in {search_path}"
                
                self.logger.info(f"✅ File search completed: {len(files)} files found")
            else:
                results["filesFound"] = []
                results["status"] = "error"  # ✅ Changed!
                results["error"] = f"No files found matching '{search_pattern}' in {search_path}. Check the path exists and pattern is correct."
                results["summary"] = f"❌ No files found matching '{search_pattern}' in {search_path}"
                
                self.logger.warning(f"⚠️ No files found")
            
        except Exception as e:
            self.logger.error(f"❌ File search failed: {str(e)}")
            results["status"] = "error"
            results["error"] = str(e)
            results["summary"] = f"❌ Failed: {str(e)}"

        return results