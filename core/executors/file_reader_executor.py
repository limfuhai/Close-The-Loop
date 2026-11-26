"""
File Reader Executor - Read file contents from user's local machine
Gets file paths from previous results or uses LLM to extract from description
"""

from __future__ import annotations

import logging
from typing import Dict, Any, List

from .base_executor import BaseExecutor
from ..execution.bridge_query import BridgeQuery


class FileReaderExecutor(BaseExecutor):
    """Executor for reading file contents from user's local machine via bridge."""

    def __init__(self, mcp_manager, mcp_registry, model_client):
        super().__init__(mcp_manager, mcp_registry)
        self.logger = logging.getLogger(__name__)
        self.executor_name = "FileReaderExecutor"
        self.model = model_client

    async def execute_task(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute file reading task on user's local machine."""
        
        results: Dict[str, Any] = {
            "status": "started",
            "executorUsed": self.executor_name,
            "fileContents": [],
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
            previous_results = context.get("previousResults", [])
            
            self.logger.info(f"📋 Task: {description}")
            
            # FIND FILE PATHS FROM PREVIOUS RESULTS (FileSearchExecutor output)
            file_paths = []
            for result in reversed(previous_results):
                if result.get("executorUsed") == "FileSearchExecutor":
                    files_found = result.get("filesFound", [])
                    if files_found:
                        file_paths.extend(files_found)
                        self.logger.info(f"📂 Found {len(files_found)} files from FileSearchExecutor")
                        break
            
            # If no files from previous results, use LLM to extract from description
            if not file_paths:
                system_prompt = """You are a file path extractor.

The user wants to read a file. Extract the file path from their request.

Examples:
- "Read ~/Desktop/report.pdf" → ~/Desktop/report.pdf
- "Open my TODO.txt file" → ~/TODO.txt
- "Read the document in Documents" → ~/Documents/document.txt

Return ONLY the file path. If multiple files, return comma-separated paths."""

                prompt = f"""User request: {user_request}

Task description: {description}

Extract file path(s):"""

                self.logger.info(f"🤖 No files from previous results, asking LLM...")
                
                response = await self.model.generate(
                    prompt=prompt,
                    system_prompt=system_prompt,
                    max_tokens=200,
                    temperature=0.2
                )
                
                # Parse paths
                paths_text = response.strip().replace('`', '')
                file_paths = [p.strip() for p in paths_text.split(',') if p.strip()]
                
                self.logger.info(f"✅ Extracted {len(file_paths)} file path(s)")
            
            if not file_paths:
                raise Exception("No file paths found in previous results or description")
            
            # Limit to first 5 files
            file_paths = file_paths[:5]
            
            # Initialize BridgeQuery
            query = BridgeQuery(
                api_key=api_key,
            )
            
            # Read each file via bridge
            file_contents = []
            for file_path in file_paths:
                self.logger.info(f"📖 Reading: {file_path}")
                
                file_result = await query.read_file(
                    file_path=file_path,
                    max_chars=10000,
                    timeout=30
                )
                
                if file_result["success"]:
                    file_contents.append({
                        "filepath": file_path,
                        "content": file_result["content"],
                        "encoding": file_result.get("encoding", "utf-8"),
                        "size": file_result.get("size", 0)
                    })
                    self.logger.info(f"✅ Read {file_result.get('size', 0)} bytes")
                else:
                    self.logger.warning(f"⚠️ Failed to read {file_path}: {file_result.get('error')}")
            
            if file_contents:
                results["fileContents"] = file_contents
                results["status"] = "completed"
                results["summary"] = f"✅ Read {len(file_contents)} file(s) successfully"
                
                self.logger.info(f"✅ File reading completed: {len(file_contents)} files")
            else:
                # Don't throw exception - set error status so Summarizer sees it
                results["fileContents"] = []
                results["status"] = "error"
                results["error"] = "Failed to read any files. All file read attempts failed."
                results["summary"] = f"❌ Failed to read any files"
                
                self.logger.warning(f"⚠️ Failed to read any files")
            
        except Exception as e:
            self.logger.error(f"❌ File reading failed: {str(e)}")
            results["status"] = "error"
            results["error"] = str(e)
            results["summary"] = f"❌ Failed: {str(e)}"

        return results