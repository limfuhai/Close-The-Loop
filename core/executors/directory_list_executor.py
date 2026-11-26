"""
Directory List Executor - List directory contents on user's local machine
Uses LLM to extract directory path from natural language descriptions
"""

from __future__ import annotations

import logging
from typing import Dict, Any

from .base_executor import BaseExecutor
from ..execution.bridge_query import BridgeQuery


class DirectoryListExecutor(BaseExecutor):
    """Executor for listing directory contents on user's local machine via bridge."""

    def __init__(self, mcp_manager, mcp_registry, model_client):
        super().__init__(mcp_manager, mcp_registry)
        self.logger = logging.getLogger(__name__)
        self.executor_name = "DirectoryListExecutor"
        self.model = model_client

    async def execute_task(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute directory listing task on user's local machine."""
        
        results: Dict[str, Any] = {
            "status": "started",
            "executorUsed": self.executor_name,
            "directoryContents": {},
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
            
            # USE LLM TO EXTRACT DIRECTORY PATH FROM NATURAL LANGUAGE
            system_prompt = """You are a directory path extractor.

The user wants to list a directory. Extract the directory path from their request.

Examples:
- "List my Desktop" → ~/Desktop
- "What's in Documents?" → ~/Documents
- "Show Downloads folder" → ~/Downloads
- "List home directory" → ~
- "What's in my Pictures?" → ~/Pictures

Return ONLY the directory path. No explanation."""

            prompt = f"""User request: {user_request}

Task description: {description}

Extract the directory path:"""

            self.logger.info(f"🤖 Asking LLM to extract directory path...")
            
            response = await self.model.generate(
                prompt=prompt,
                system_prompt=system_prompt,
                max_tokens=100,
                temperature=0.2
            )
            
            # Clean the path
            directory_path = response.strip().replace('`', '').strip()
            
            self.logger.info(f"✅ Extracted path: {directory_path}")
            
            # Initialize BridgeQuery
            query = BridgeQuery(
                api_key=api_key
            )
            
            # List directory via bridge
            self.logger.info(f"🌉 Listing directory via bridge...")
            listing = await query.list_directory(
                directory_path=directory_path,
                show_hidden=False,
                timeout=10
            )
            
            if listing["success"]:
                results["directoryContents"] = {
                    "path": listing["directory_path"],
                    "files": listing["files"],
                    "directories": listing["directories"],
                    "total_items": listing["total_items"]
                }
                results["status"] = "completed"
                
                # Format nice summary
                files_count = len(listing["files"])
                dirs_count = len(listing["directories"])
                results["summary"] = f"✅ Listed {directory_path}\n\n📁 {dirs_count} directories\n📄 {files_count} files"
                
                self.logger.info(f"✅ Directory listing completed: {listing['total_items']} items")
            else:
                error_msg = listing.get("error", "Unknown error")
                raise Exception(f"Directory listing failed: {error_msg}")
            
        except Exception as e:
            self.logger.error(f"❌ Directory listing failed: {str(e)}")
            results["status"] = "error"
            results["error"] = str(e)
            results["summary"] = f"❌ Failed: {str(e)}"

        return results