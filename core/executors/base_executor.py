# react/core/executors/base_executor.py

import logging
from typing import Dict, Any, List, Optional
from abc import ABC, abstractmethod
from datetime import datetime

class BaseExecutor(ABC):
    """Base class for all specialized executor agents."""
    
    def __init__(self, mcp_manager, mcp_registry):
        self.mcp_manager = mcp_manager
        self.mcp_registry = mcp_registry
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        
    @abstractmethod
    async def execute_task(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the task and return results with artifacts."""
        pass
    
    async def invoke_mcp_tool(self, server_id: str, tool_name: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Helper method to invoke MCP tools."""
        try:
            # Use the MCP client to invoke the tool
            result = await self.mcp_manager.client.invoke_tool(
                server_id=server_id,
                tool_name=tool_name,
                arguments=parameters
            )
            
            return {
                "success": True,
                "result": result,
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            self.logger.error(f"MCP tool invocation failed: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }
    
    def create_artifact(self, artifact_type: str, title: str, content: Any, metadata: Dict[str, Any] = None) -> Dict[str, Any]:
        """Create a standardized artifact structure."""
        return {
            "id": f"{artifact_type}_{datetime.now().timestamp()}",
            "type": artifact_type,
            "title": title,
            "content": content,
            "metadata": metadata or {},
            "created_at": datetime.now().isoformat()
        }