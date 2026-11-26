"""
Calendar & Task Executor - Manage calendar events and to-do lists via system automation
Creates actual calendar events and tasks through Windows/macOS system automation
"""

from __future__ import annotations

import logging
import json
from typing import Dict, Any, List
from datetime import datetime, timedelta
import re

from .base_executor import BaseExecutor
from ..execution.bridge_query import BridgeQuery


class CalendarTaskExecutor(BaseExecutor):
    """
    Executor for managing calendar events and to-do lists via system automation.
    
    Uses PowerShell (Windows) or AppleScript (macOS) to actually create/manage:
    - Calendar events in Outlook/Calendar.app
    - To-do lists in system task managers
    - Reminders and notifications
    
    Makes multiple bridge calls:
    1. Detect operating system
    2. Execute automation command
    """

    def __init__(self, mcp_manager, mcp_registry, model_client, compiler_service=None):
        super().__init__(mcp_manager, mcp_registry)
        self.logger = logging.getLogger(__name__)
        self.executor_name = "CalendarTaskExecutor"
        self.model = model_client
        self.compiler_service = compiler_service

    async def execute_task(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute calendar/task management task via system automation."""
        
        results: Dict[str, Any] = {
            "status": "started",
            "executorUsed": self.executor_name,
            "events_created": [],
            "tasks_created": [],
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
            
            # Initialize BridgeQuery
            query = BridgeQuery(
                api_key=api_key,
                compiler_service=self.compiler_service
            )
            
            # FIRST BRIDGE CALL: Detect operating system
            self.logger.info("🔍 Detecting operating system...")
            os_type = await self._detect_os(query)
            self.logger.info(f"✅ Detected OS: {os_type}")
            
            # Use LLM to classify operation type and extract parameters
            operation = await self._classify_operation(description, user_request)
            self.logger.info(f"📅 Operation: {operation['type']}")
            
            # SECOND BRIDGE CALL: Execute automation command based on operation
            if operation["type"] == "create_event":
                result = await self._create_calendar_event(query, os_type, operation)
                results["events_created"] = [result["event"]]
                results["summary"] = result["summary"]
                
            elif operation["type"] == "create_task":
                result = await self._create_task(query, os_type, operation)
                results["tasks_created"] = [result["task"]]
                results["summary"] = result["summary"]
                
            else:
                raise Exception(f"Operation type '{operation['type']}' not yet supported")
            
            results["status"] = "completed"
            self.logger.info(f"✅ Calendar/Task operation completed")
            
        except Exception as e:
            self.logger.error(f"Calendar/Task operation failed: {str(e)}")
            results["status"] = "error"
            results["error"] = str(e)
            results["summary"] = f"❌ Failed: {str(e)}"

        return results

    async def _detect_os(self, query: BridgeQuery) -> str:
        """
        Detect user's operating system via bridge.
        
        Returns:
            "Windows", "Darwin" (macOS), or "Linux"
        """
        command = 'python3 -c "import platform; print(platform.system())"'
        result = await query.execute_bash(command, timeout=10)
        
        if result["success"]:
            os_name = result["output"].strip()
            return os_name
        else:
            # Fallback to uname
            fallback = await query.execute_bash("uname", timeout=5)
            if fallback["success"]:
                return fallback["output"].strip()
            else:
                raise Exception("Could not detect operating system")

    async def _classify_operation(self, description: str, user_request: str) -> Dict[str, Any]:
        """
        Use LLM to classify the calendar/task operation and extract parameters.
        
        Returns:
            {
                "type": "create_event" | "create_task",
                "parameters": {
                    "title": "Meeting with John",
                    "start_datetime": "2026-02-13 14:00",
                    "end_datetime": "2026-02-13 15:00",
                    "description": "Quarterly review",
                    "priority": "high"
                }
            }
        """
        
        system_prompt = """You are a calendar/task operation classifier.

Analyze the user's request and extract:
1. Operation type (create_event or create_task)
2. All parameters needed for that operation

For create_event:
- title: Event name
- start_datetime: Format "YYYY-MM-DD HH:MM" (parse "tomorrow at 2pm" etc.)
- end_datetime: Format "YYYY-MM-DD HH:MM" (default 1 hour after start)
- description: Optional details

For create_task:
- title: Task description
- priority: "high", "medium", or "low"
- deadline: Optional "YYYY-MM-DD"

Return ONLY valid JSON:
{
    "type": "create_event",
    "parameters": {
        "title": "...",
        "start_datetime": "2026-02-13 14:00",
        "end_datetime": "2026-02-13 15:00"
    }
}"""

        prompt = f"""User request: {user_request}

Task description: {description}

Current date/time: {datetime.now().strftime('%Y-%m-%d %H:%M')}

Classify and extract parameters as JSON:"""

        response = await self.model.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            max_tokens=500,
            temperature=0.2
        )
        
        # Extract JSON
        json_match = re.search(r'\{.*\}', response, re.DOTALL)
        if json_match:
            return json.loads(json_match.group(0))
        else:
            # Fallback
            return {
                "type": "create_event",
                "parameters": {
                    "title": "New Event",
                    "start_datetime": (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d 14:00"),
                    "end_datetime": (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d 15:00")
                }
            }

    async def _create_calendar_event(
        self, 
        query: BridgeQuery, 
        os_type: str, 
        operation: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Create calendar event via system automation.
        
        Executes PowerShell (Windows) or AppleScript (macOS) command.
        """
        
        params = operation.get("parameters", {})
        title = params.get("title", "New Event")
        start_dt = params.get("start_datetime", "")
        end_dt = params.get("end_datetime", "")
        description = params.get("description", "")
        
        # Generate automation command
        if os_type == "Windows":
            command = self._generate_powershell_calendar_event(
                title, start_dt, end_dt, description
            )
        elif os_type == "Darwin":
            command = self._generate_applescript_calendar_event(
                title, start_dt, end_dt, description
            )
        else:
            raise Exception(f"OS '{os_type}' not supported for calendar automation")
        
        self.logger.info(f"📅 Creating calendar event: {title}")
        
        # Execute automation command via bridge
        result = await query.execute_bash(command, timeout=30)
        
        if result["success"]:
            return {
                "event": {
                    "title": title,
                    "start": start_dt,
                    "end": end_dt,
                    "created_via": os_type
                },
                "summary": f"✅ Calendar event '{title}' created successfully"
            }
        else:
            raise Exception(f"Failed to create calendar event: {result.get('error', 'Unknown error')}")

    async def _create_task(
        self, 
        query: BridgeQuery, 
        os_type: str, 
        operation: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Create task/to-do item via system automation.
        """
        
        params = operation.get("parameters", {})
        title = params.get("title", "New Task")
        priority = params.get("priority", "medium")
        deadline = params.get("deadline", "")
        
        # Generate task creation command
        if os_type == "Windows":
            command = self._generate_powershell_task(title, priority, deadline)
        elif os_type == "Darwin":
            command = self._generate_applescript_task(title, priority, deadline)
        else:
            raise Exception(f"OS '{os_type}' not supported for task automation")
        
        self.logger.info(f"📋 Creating task: {title}")
        
        # Execute via bridge
        result = await query.execute_bash(command, timeout=30)
        
        if result["success"]:
            return {
                "task": {
                    "title": title,
                    "priority": priority,
                    "deadline": deadline,
                    "created_via": os_type
                },
                "summary": f"✅ Task '{title}' created successfully"
            }
        else:
            raise Exception(f"Failed to create task: {result.get('error', 'Unknown error')}")

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # PowerShell Command Generation (Windows)
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _generate_powershell_calendar_event(
        self, 
        title: str, 
        start_datetime: str, 
        end_datetime: str,
        description: str
    ) -> str:
        """
        Generate PowerShell command to create Outlook calendar event.
        
        Args:
            title: Event subject
            start_datetime: Format "2026-02-13 14:00"
            end_datetime: Format "2026-02-13 15:00"
            description: Event body
            
        Returns:
            PowerShell command string
        """
        
        # Calculate duration in minutes
        try:
            start = datetime.strptime(start_datetime, "%Y-%m-%d %H:%M")
            end = datetime.strptime(end_datetime, "%Y-%m-%d %H:%M")
            duration = int((end - start).total_seconds() / 60)
        except:
            duration = 60  # Default 1 hour
        
        # Escape single quotes in strings
        title_escaped = title.replace("'", "''")
        description_escaped = description.replace("'", "''")
        
        command = f"""powershell -Command "
$outlook = New-Object -ComObject Outlook.Application
$appointment = $outlook.CreateItem(1)
$appointment.Subject = '{title_escaped}'
$appointment.Start = '{start_datetime}'
$appointment.Duration = {duration}
$appointment.Body = '{description_escaped}'
$appointment.ReminderSet = $true
$appointment.ReminderMinutesBeforeStart = 15
$appointment.Save()
Write-Host 'Calendar event created successfully'
" """
        
        return command

    def _generate_powershell_task(
        self, 
        title: str, 
        priority: str, 
        deadline: str
    ) -> str:
        """
        Generate PowerShell command to create Outlook task.
        
        Uses Outlook COM automation to create task.
        """
        
        # Map priority to Outlook importance (0=Low, 1=Normal, 2=High)
        importance_map = {"low": 0, "medium": 1, "high": 2}
        importance = importance_map.get(priority.lower(), 1)
        
        title_escaped = title.replace("'", "''")
        
        deadline_line = ""
        if deadline:
            deadline_line = f"$task.DueDate = '{deadline}'"
        
        command = f"""powershell -Command "
$outlook = New-Object -ComObject Outlook.Application
$task = $outlook.CreateItem(3)
$task.Subject = '{title_escaped}'
$task.Importance = {importance}
{deadline_line}
$task.Save()
Write-Host 'Task created successfully'
" """
        
        return command

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # AppleScript Command Generation (macOS)
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _generate_applescript_calendar_event(
        self, 
        title: str, 
        start_datetime: str, 
        end_datetime: str,
        description: str
    ) -> str:
        """
        Generate AppleScript command to create Calendar.app event.
        
        Args:
            title: Event summary
            start_datetime: Format "2026-02-13 14:00"
            end_datetime: Format "2026-02-13 15:00"
            description: Event description
            
        Returns:
            osascript command string
        """
        
        # Convert to AppleScript date format
        # "Thursday, February 13, 2026 at 2:00:00 PM"
        try:
            start = datetime.strptime(start_datetime, "%Y-%m-%d %H:%M")
            end = datetime.strptime(end_datetime, "%Y-%m-%d %H:%M")
            
            start_formatted = start.strftime("%A, %B %d, %Y at %I:%M:%S %p")
            end_formatted = end.strftime("%A, %B %d, %Y at %I:%M:%S %p")
        except:
            # Fallback
            start_formatted = "tomorrow at 2:00:00 PM"
            end_formatted = "tomorrow at 3:00:00 PM"
        
        # Escape quotes
        title_escaped = title.replace('"', '\\"')
        description_escaped = description.replace('"', '\\"')
        
        command = f'''osascript -e 'tell application "Calendar"
    tell calendar "Calendar"
        make new event with properties {{summary:"{title_escaped}", start date:date "{start_formatted}", end date:date "{end_formatted}", description:"{description_escaped}"}}
    end tell
end tell' '''
        
        return command

    def _generate_applescript_task(
        self, 
        title: str, 
        priority: str, 
        deadline: str
    ) -> str:
        """
        Generate AppleScript command to create Reminders.app task.
        """
        
        # Map priority to Reminders priority (0=None, 1-4=Low, 5=Medium, 6-9=High)
        priority_map = {"low": 2, "medium": 5, "high": 7}
        priority_value = priority_map.get(priority.lower(), 5)
        
        title_escaped = title.replace('"', '\\"')
        
        deadline_line = ""
        if deadline:
            try:
                deadline_dt = datetime.strptime(deadline, "%Y-%m-%d")
                deadline_formatted = deadline_dt.strftime("%A, %B %d, %Y at 9:00:00 AM")
                deadline_line = f', due date:date "{deadline_formatted}"'
            except:
                pass
        
        command = f'''osascript -e 'tell application "Reminders"
    tell list "Reminders"
        make new reminder with properties {{name:"{title_escaped}", priority:{priority_value}{deadline_line}}}
    end tell
end tell' '''
        
        return command