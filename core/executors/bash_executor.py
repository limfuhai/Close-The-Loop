"""
Bash Executor - Execute bash commands on user's local machine
Uses LLM to generate bash commands from natural language descriptions
"""

from __future__ import annotations

import logging
from typing import Dict, Any

from .base_executor import BaseExecutor
from ..execution.bridge_query import BridgeQuery


class BashExecutor(BaseExecutor):
    """Executor for executing bash commands on user's local machine via bridge."""

    def __init__(self, mcp_manager, mcp_registry, model_client):
        super().__init__(mcp_manager, mcp_registry)
        self.logger = logging.getLogger(__name__)
        self.executor_name = "BashExecutor"
        self.model = model_client

    async def execute_task(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute bash command task on user's local machine."""
        
        results: Dict[str, Any] = {
            "status": "started",
            "executorUsed": self.executor_name,
            "bashOutput": "",
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
            
            # USE LLM TO GENERATE BASH COMMAND FROM NATURAL LANGUAGE
            system_prompt = """You are a bash command generator.

The user wants to execute a bash command. Analyze their request and generate ONLY the bash command - nothing else.

Examples:
- "Get my username" → whoami
- "List Desktop files" → ls ~/Desktop  
- "Check current directory" → pwd
- "Find all PDFs" → find ~ -name "*.pdf" -type f
- "Count files in Documents" → find ~/Documents -type f | wc -l

Return ONLY the bash command. No explanation. No markdown. No extra text."""

            prompt = f"""User request: {user_request}

Task description: {description}

Generate the bash command to execute:"""

            self.logger.info(f"🤖 Asking LLM to generate bash command...")
            
            response = await self.model.generate(
                prompt=prompt,
                system_prompt=system_prompt,
                max_tokens=200,
                temperature=0.2
            )
            
            # Clean the command (remove markdown, extra whitespace)
            command = response.strip()
            command = command.replace('```bash', '').replace('```', '').strip()
            
            self.logger.info(f"✅ Generated command: {command}")
            
            # Initialize BridgeQuery
            query = BridgeQuery(
                api_key=api_key
            )
            
            # Execute bash command via bridge
            self.logger.info(f"🌉 Executing command via bridge...")
            result = await query.execute_bash(
                command=command,
                timeout=30
            )
            
            if result["success"]:
                output = result["output"].strip()
                results["bashOutput"] = output
                results["bashError"] = result.get("error")
                results["exitCode"] = result.get("exit_code", 0)
                results["status"] = "completed"
                results["summary"] = f"✅ Command: {command}\n\nOutput:\n{output}"
                
                self.logger.info(f"✅ Command completed successfully")
                self.logger.info(f"Output: {output[:200]}...")
            else:
                error_msg = result.get("error", "Unknown error")
                raise Exception(f"Command failed: {error_msg}")
            
        except Exception as e:
            self.logger.error(f"❌ Bash execution failed: {str(e)}")
            results["status"] = "error"
            results["error"] = str(e)
            results["summary"] = f"❌ Failed: {str(e)}"

        return results