"""
Email Executor - Context-aware email composition and sending via system automation
Actually sends emails through Windows/macOS mail clients with attachments
"""

from __future__ import annotations

import logging
import json
import re
from typing import Dict, Any, List
from datetime import datetime

from .base_executor import BaseExecutor
from ..execution.bridge_query import BridgeQuery


class EmailExecutor(BaseExecutor):
    """
    Executor for composing and sending context-aware emails via system automation.
    
    Uses PowerShell (Windows/Outlook) or AppleScript (macOS/Mail.app) to:
    - Compose professional emails
    - Attach files from previous executors or local filesystem
    - Actually send emails through system mail client
    
    Makes multiple bridge calls:
    1. Detect operating system
    2. Execute email sending command
    """

    def __init__(self, mcp_manager, mcp_registry, model_client, compiler_service=None):
        super().__init__(mcp_manager, mcp_registry)
        self.logger = logging.getLogger(__name__)
        self.executor_name = "EmailExecutor"
        self.model = model_client
        self.compiler_service = compiler_service

    async def execute_task(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute email composition and sending task via system automation."""
        
        results: Dict[str, Any] = {
            "status": "started",
            "executorUsed": self.executor_name,
            "email_sent": False,
            "email": {},
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
            
            # Initialize BridgeQuery
            query = BridgeQuery(
                api_key=api_key,
                compiler_service=self.compiler_service
            )
            
            # FIRST BRIDGE CALL: Detect operating system
            self.logger.info("🔍 Detecting operating system...")
            os_type = await self._detect_os(query)
            self.logger.info(f"✅ Detected OS: {os_type}")
            
            # Use LLM to analyze email requirements
            email_spec = await self._analyze_email_requirements(
                description,
                user_request,
                previous_results
            )
            
            self.logger.info(f"📧 Email type: {email_spec['email_type']}, Recipient: {email_spec.get('recipient', 'unknown')}")
            
            # Generate email content using LLM
            email_content = await self._generate_email_content(
                email_spec,
                previous_results
            )
            
            # Find attachments from previous executors
            attachments = self._find_attachments(previous_results, email_spec)
            
            # SECOND BRIDGE CALL: Send email via system automation
            send_result = await self._send_email(
                query,
                os_type,
                email_content,
                attachments
            )
            
            results["email_sent"] = send_result["success"]
            results["email"] = email_content
            results["email"]["attachments"] = attachments
            results["status"] = "completed"
            results["summary"] = send_result["summary"]
            
            self.logger.info(f"✅ Email sent successfully")
            
        except Exception as e:
            self.logger.error(f"Email sending failed: {str(e)}")
            results["status"] = "error"
            results["error"] = str(e)
            results["summary"] = f"❌ Failed to send email: {str(e)}"

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

    async def _analyze_email_requirements(
        self,
        description: str,
        user_request: str,
        previous_results: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Use LLM to analyze what kind of email needs to be composed.
        
        Returns:
            {
                "email_type": "report_email" | "follow_up" | "cold_outreach" | "internal_update",
                "recipient": "email or name",
                "subject_hints": ["keyword1"],
                "tone": "formal" | "casual" | "technical",
                "key_points": ["point1", "point2"]
            }
        """
        
        # Check for files from previous executors
        available_files = []
        for result in previous_results:
            if "outputFiles" in result:
                for file in result["outputFiles"]:
                    available_files.append(file.get("filename", ""))
            if "filesFound" in result:
                available_files.extend(result.get("filesFound", []))
        
        system_prompt = """You are an email composition analyst.

Analyze the user's request and determine:
1. Email type (report_email, follow_up, cold_outreach, internal_update, client_communication)
2. Recipient information
3. Tone (formal, casual, or technical)
4. Key points to include

Return ONLY valid JSON:
{
    "email_type": "report_email",
    "recipient": "john@example.com",
    "subject_hints": ["Q4 results"],
    "tone": "formal",
    "key_points": ["quarterly performance", "next steps"]
}"""

        prompt = f"""User request: {user_request}

Task description: {description}

Available files from previous tasks: {', '.join(available_files) if available_files else 'None'}

Analyze this email request and extract specifications as JSON:"""

        response = await self.model.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            max_tokens=800,
            temperature=0.3
        )
        
        # Extract JSON
        json_match = re.search(r'\{.*\}', response, re.DOTALL)
        if json_match:
            return json.loads(json_match.group(0))
        else:
            # Fallback
            return {
                "email_type": "internal_update",
                "recipient": "colleague",
                "subject_hints": ["update"],
                "tone": "casual",
                "key_points": []
            }

    async def _generate_email_content(
        self,
        email_spec: Dict[str, Any],
        previous_results: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Use LLM to generate the actual email content.
        
        Returns:
            {
                "recipient": "john@example.com",
                "subject": "Q4 Results - Review Requested",
                "body": "email content...",
                "tone": "formal"
            }
        """
        
        tone = email_spec.get("tone", "formal")
        email_type = email_spec.get("email_type", "internal_update")
        
        tone_guides = {
            "formal": "Professional, courteous language. Proper greetings and sign-offs.",
            "casual": "Friendly, conversational tone. Warm but still professional.",
            "technical": "Precise technical language. Focus on accuracy and detail."
        }
        
        system_prompt = f"""You are an expert email composer.

Email Type: {email_type}
Tone: {tone} - {tone_guides.get(tone, '')}

Guidelines:
1. Write clear, concise emails
2. Structure with proper greeting, body, and closing
3. Keep paragraphs short (2-3 sentences)
4. Use bullet points for multiple items
5. End with clear call-to-action if needed

Return ONLY valid JSON:
{{
    "subject": "email subject line",
    "body": "email body with proper greeting and closing"
}}"""

        key_points = "\n".join([f"- {point}" for point in email_spec.get("key_points", [])])
        
        prompt = f"""Compose a {email_type} email.

Recipient: {email_spec.get('recipient', 'recipient')}

Key points to cover:
{key_points if key_points else "- Address the request appropriately"}

Generate email as JSON:"""

        response = await self.model.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            max_tokens=1500,
            temperature=0.7
        )
        
        # Extract JSON
        json_match = re.search(r'\{.*\}', response, re.DOTALL)
        if json_match:
            email_data = json.loads(json_match.group(0))
        else:
            # Fallback
            email_data = {
                "subject": f"{email_type.replace('_', ' ').title()}",
                "body": response
            }
        
        return {
            "recipient": email_spec.get("recipient", ""),
            "subject": email_data.get("subject", ""),
            "body": email_data.get("body", ""),
            "tone": tone,
            "email_type": email_type
        }

    def _find_attachments(
        self,
        previous_results: List[Dict[str, Any]],
        email_spec: Dict[str, Any]
    ) -> List[str]:
        """
        Find attachment file paths from previous executor results.
        
        Returns:
            List of absolute file paths to attach
        """
        
        attachments = []
        
        # Check previous executor outputs for files
        for result in previous_results:
            # Check for outputFiles (from DocsExecutor, SlidesExecutor, etc.)
            if "outputFiles" in result:
                for file in result["outputFiles"]:
                    # These are server files - need to download first
                    # For now, we skip server files and only attach local files
                    pass
            
            # Check for filesFound (from FileSearchExecutor)
            if "filesFound" in result:
                files = result.get("filesFound", [])
                # These are local files - can attach directly
                if files:
                    attachments.extend(files)
            
            # Check for localFiles (from LocalSaveExecutor)
            if "localFiles" in result:
                for file_info in result.get("localFiles", []):
                    local_path = file_info.get("local_path", "")
                    if local_path:
                        attachments.append(local_path)
        
        # Limit to first 5 attachments
        return attachments[:5]

    async def _send_email(
        self,
        query: BridgeQuery,
        os_type: str,
        email_content: Dict[str, Any],
        attachments: List[str]
    ) -> Dict[str, Any]:
        """
        Send email via system automation.
        
        Executes PowerShell (Windows/Outlook) or AppleScript (macOS/Mail.app).
        """
        
        recipient = email_content.get("recipient", "")
        subject = email_content.get("subject", "")
        body = email_content.get("body", "")
        
        if not recipient:
            raise Exception("No recipient specified for email")
        
        # Generate automation command
        if os_type == "Windows":
            command = self._generate_powershell_email(
                recipient, subject, body, attachments
            )
        elif os_type == "Darwin":
            command = self._generate_applescript_email(
                recipient, subject, body, attachments
            )
        else:
            raise Exception(f"OS '{os_type}' not supported for email automation")
        
        self.logger.info(f"📧 Sending email to: {recipient}")
        self.logger.info(f"📎 Attachments: {len(attachments)}")
        
        # Execute automation command via bridge
        result = await query.execute_bash(command, timeout=60)
        
        if result["success"]:
            return {
                "success": True,
                "summary": f"✅ Email sent to {recipient} via {os_type} mail client"
            }
        else:
            raise Exception(f"Failed to send email: {result.get('error', 'Unknown error')}")

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # PowerShell Command Generation (Windows/Outlook)
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _generate_powershell_email(
        self,
        recipient: str,
        subject: str,
        body: str,
        attachments: List[str]
    ) -> str:
        """
        Generate PowerShell command to send email via Outlook.
        
        Args:
            recipient: Email address
            subject: Email subject
            body: Email body text
            attachments: List of file paths to attach
            
        Returns:
            PowerShell command string
        """
        
        # Escape single quotes
        subject_escaped = subject.replace("'", "''")
        body_escaped = body.replace("'", "''")
        recipient_escaped = recipient.replace("'", "''")
        
        # Build attachment lines
        attachment_lines = ""
        for attachment_path in attachments:
            path_escaped = attachment_path.replace("'", "''")
            attachment_lines += f"$mail.Attachments.Add('{path_escaped}') | Out-Null\n"
        
        command = f"""powershell -Command "
$outlook = New-Object -ComObject Outlook.Application
$mail = $outlook.CreateItem(0)
$mail.Subject = '{subject_escaped}'
$mail.Body = '{body_escaped}'
$mail.To = '{recipient_escaped}'
{attachment_lines}$mail.Send()
Write-Host 'Email sent successfully'
" """
        
        return command

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # AppleScript Command Generation (macOS/Mail.app)
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _generate_applescript_email(
        self,
        recipient: str,
        subject: str,
        body: str,
        attachments: List[str]
    ) -> str:
        """
        Generate AppleScript command to send email via Mail.app.
        
        Args:
            recipient: Email address
            subject: Email subject
            body: Email body text
            attachments: List of file paths to attach
            
        Returns:
            osascript command string
        """
        
        # Escape quotes
        subject_escaped = subject.replace('"', '\\"')
        body_escaped = body.replace('"', '\\"')
        recipient_escaped = recipient.replace('"', '\\"')
        
        # Build attachment lines
        attachment_lines = ""
        for attachment_path in attachments:
            path_escaped = attachment_path.replace('"', '\\"')
            attachment_lines += f'\n        make new attachment with properties {{file name:"{path_escaped}" as POSIX file}}'
        
        command = f'''osascript -e 'tell application "Mail"
    set theMessage to make new outgoing message with properties {{subject:"{subject_escaped}", content:"{body_escaped}", visible:false}}
    tell theMessage
        make new to recipient with properties {{address:"{recipient_escaped}"}}{attachment_lines}
    end tell
    send theMessage
end tell' '''
        
        return command