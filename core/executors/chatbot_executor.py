"""
Chatbot Executor - Generates HTML chatbot widgets
Simple executor that creates self-contained chatbot code with embedded Modal serving URL
Uses ScriptExecutionManager like all other executors
"""

from __future__ import annotations

import re
import logging
import os
from typing import Dict, Any, List, Optional
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse

from .base_executor import BaseExecutor
from ..execution.script_manager import ScriptExecutionManager


class ChatbotExecutor(BaseExecutor):
    """Executor for generating chatbot widget HTML."""

    def __init__(self, mcp_manager, mcp_registry, model_client):
        super().__init__(mcp_manager, mcp_registry)
        self.logger = logging.getLogger(__name__)
        self.executor_name = "ChatbotExecutor"
        self.model = model_client
        self.backend_base = (os.getenv("NEXT_PUBLIC_API_URL") or "").rstrip("/")
        self.force_download = (os.getenv("OUTPUT_FORCE_DOWNLOAD", "false").lower() == "true")
        self.script_manager = ScriptExecutionManager()

    # ───────────────────────── URL Helper Methods ─────────────────────────

    def _abs(self, raw: str) -> str:
        """Return an absolute URL for a possibly-relative path, using NEXT_PUBLIC_API_URL as base."""
        if not raw:
            return ""
        if raw.startswith("http://") or raw.startswith("https://"):
            return raw
        base = self.backend_base
        if not base:
            return raw
        return f"{base}{raw if raw.startswith('/') else '/' + raw}"

    def _strip_download_param(self, url: str) -> str:
        """
        Remove `download` ONLY when empty/boolean-like. Keep string filenames.
        This avoids Supabase's "querystring/download must be string" error.
        """
        if not url:
            return url
        p = urlparse(url)
        q = dict(parse_qsl(p.query, keep_blank_values=True))
        if "download" in q:
            v = (q.get("download") or "").strip().lower()
            if v in ("", "true", "1"):
                q.pop("download", None)
        new_query = urlencode(q)
        return urlunparse(p._replace(query=new_query))

    def _ensure_download_filename(self, url: str, filename: str) -> str:
        """
        Ensure `download=<filename>` is present (and not boolean). Preserve other params.
        Use when you explicitly want the browser to download with a specific name.
        """
        if not url:
            return url
        p = urlparse(url)
        q = dict(parse_qsl(p.query, keep_blank_values=True))
        if "download" not in q or q["download"] in ("", "true", "1"):
            q["download"] = filename
        new_query = urlencode(q)
        return urlunparse(p._replace(query=new_query))

    @staticmethod
    def _guess_type_from_name(name: str) -> str:
        name_lower = (name or "").lower()
        if name_lower.endswith(".html") or name_lower.endswith(".htm"):
            return "chatbot_widget"
        if name_lower.endswith(".docx"):
            return "document"
        if name_lower.endswith(".pptx"):
            return "presentation"
        if name_lower.endswith(".xlsx"):
            return "spreadsheet"
        if name_lower.endswith(".pdf"):
            return "pdf"
        if any(name_lower.endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".gif", ".webp")):
            return "image"
        return "file"

    # ───────────────────────── Main Execution ─────────────────────────

    async def execute_task(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute chatbot widget generation task."""
        results: Dict[str, Any] = {
            "status": "started",
            "executorUsed": self.executor_name,
            "artifacts": [],
            "summary": "",
            "executorFullResponse": "",
        }

        try:
            # Extract parameters from task_data
            context = task_data.get("context", {})
            plan = context.get("plan", {})
            user_request = context.get("userRequest", "")
            
            # HARDCODED serving URL (one endpoint serves all customers)
            serving_url = "https://limfuhai--tuner-modelserving-serve.modal.run"
            
            # Get customer_id from DataExecutor results (required for multi-customer serving)
            customer_id = (
                context.get("customerId") or
                plan.get("customerId") or
                self._extract_customer_id_from_previous_results(context) or
                "anonymous"
            )
            
            # Serving URL is hardcoded, always available
            # Just verify we have customer_id
            if not customer_id or customer_id == "anonymous":
                self.logger.warning("No customer_id found, using 'anonymous'")
            
            # Get optional branding parameters - also try extracting from text
            company_name = (
                context.get("companyName") or 
                plan.get("companyName") or 
                self._extract_company_name_from_text(user_request) or
                "AI Assistant"
            )
            
            primary_color = (
                context.get("primaryColor") or 
                plan.get("primaryColor") or 
                self._extract_primary_color_from_text(user_request) or
                "#4A90E2"
            )
            
            self.logger.info(f"Building chatbot widget for: {company_name}")
            self.logger.info(f"Serving URL: {serving_url}")
            self.logger.info(f"Primary Color: {primary_color}")
            
            # Generate Python code that creates the widget
            code = self._generate_widget_code(serving_url, customer_id, company_name, primary_color)
            
            # Execute the code using ScriptExecutionManager (just like DocsExecutor/SlidesExecutor!)
            self.logger.info("Executing chatbot widget creation code...")
            execution_result = await self.script_manager.execute_code_directly(
                code, user_id=task_data.get("userId", "anonymous")
            )

            if execution_result.get("exit_code", 1) != 0:
                raise Exception(f"Code execution failed: {execution_result.get('error')}")

            # Collect created files (ScriptExecutionManager already uploaded to Supabase!)
            output_files: List[Dict[str, Any]] = execution_result.get("output_files", []) or []
            
            # Normalize URLs (same as DocsExecutor/SlidesExecutor)
            normalized_files: List[Dict[str, Any]] = []
            for f in output_files:
                filename = f.get("filename") or f.get("name") or "chatbot_widget.html"
                raw_primary = (
                    f.get("download_url")
                    or f.get("url")
                    or f.get("public_url")
                    or f.get("relative_url")
                    or ""
                )
                abs_primary = self._abs(raw_primary)

                # Handle download parameter
                if self.force_download or ("download=" in abs_primary):
                    final_url = self._ensure_download_filename(abs_primary, filename)
                else:
                    final_url = self._strip_download_param(abs_primary)

                # Store normalized URLs
                f["download_url"] = final_url
                f.setdefault("public_url", abs_primary)
                f.setdefault("type", f.get("type") or self._guess_type_from_name(filename))
                normalized_files.append(f)

            results["outputFiles"] = normalized_files

            self.logger.info(
                "ChatbotExecutor produced %d file(s).",
                len(normalized_files),
            )

            # Build user-facing markdown with links
            md_lines = ["", "### Chatbot Widget Ready! 🎉"]
            md_lines.append("")
            md_lines.append(f"**Serving URL**: {serving_url}")
            md_lines.append(f"**Company Name**: {company_name}")
            md_lines.append(f"**Primary Color**: {primary_color}")
            md_lines.append("")
            
            # Add downloadable link
            if normalized_files:
                md_lines.append("### Created Files")
                for f in normalized_files:
                    filename = f.get("filename", "file")
                    file_type = f.get("type", "")
                    public_url = f.get("download_url") or ""
                    
                    label = (
                        "Chatbot Widget" if file_type == "chatbot_widget" else
                        "Document" if file_type == "document" else
                        "File"
                    )
                    
                    if public_url:
                        md_lines.append(f"- **{filename}** – [Download]({public_url})  ({label})")
                    else:
                        md_lines.append(f"- **{filename}**  ({label})")
                md_lines.append("")
            
            md_lines.append("### Features:")
            md_lines.append("✅ Beautiful, responsive design")
            md_lines.append("✅ Real-time chat interface")
            md_lines.append("✅ Conversation history tracking")
            md_lines.append("✅ Mobile-friendly layout")
            md_lines.append("✅ Customizable branding")
            md_lines.append("")
            md_lines.append("### Next Steps:")
            md_lines.append("1. Download the widget file")
            md_lines.append("2. Open in a text editor to review")
            md_lines.append("3. Deploy to your website")
            md_lines.append("4. Customize colors and text as needed")

            results["executorFullResponse"] = "\n".join(md_lines)
            results["status"] = "completed"
            results["summary"] = f"Generated chatbot widget for {company_name}"
            results["servingUrl"] = serving_url
            results["companyName"] = company_name

        except Exception as e:
            self.logger.error(f"Chatbot executor error: {str(e)}")
            results["status"] = "error"
            results["error"] = str(e)
            results["summary"] = f"Error generating chatbot widget: {str(e)}"
            results["executorFullResponse"] = f"❌ Error: {str(e)}"

        return results
    
    def _generate_widget_code(self, serving_url: str, customer_id: str, company_name: str, primary_color: str) -> str:
        """
        Generate Python code that creates the chatbot HTML widget.
        This is the ONLY place where widget HTML is defined - no separate ChatbotBuilder needed!
        """
        code = f'''
from pathlib import Path

# Create chatbot widget HTML
widget_html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{company_name} - AI Chatbot</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', 'Oxygen', sans-serif;
            background: linear-gradient(135deg, {primary_color} 0%, #667eea 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }}
        
        .chat-container {{
            width: 100%;
            max-width: 600px;
            height: 700px;
            background: white;
            border-radius: 20px;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }}
        
        .chat-header {{
            background: linear-gradient(135deg, {primary_color} 0%, #667eea 100%);
            color: white;
            padding: 20px;
            text-align: center;
        }}
        
        .chat-header h1 {{
            font-size: 24px;
            font-weight: 600;
        }}
        
        .chat-messages {{
            flex: 1;
            overflow-y: auto;
            padding: 20px;
            background: #f5f5f5;
        }}
        
        .message {{
            margin-bottom: 16px;
            display: flex;
            animation: fadeIn 0.3s ease-in;
        }}
        
        @keyframes fadeIn {{
            from {{ opacity: 0; transform: translateY(10px); }}
            to {{ opacity: 1; transform: translateY(0); }}
        }}
        
        .message.user {{
            justify-content: flex-end;
        }}
        
        .message-bubble {{
            max-width: 70%;
            padding: 12px 16px;
            border-radius: 18px;
            word-wrap: break-word;
        }}
        
        .message.user .message-bubble {{
            background: {primary_color};
            color: white;
            border-bottom-right-radius: 4px;
        }}
        
        .message.assistant .message-bubble {{
            background: white;
            color: #333;
            border-bottom-left-radius: 4px;
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
        }}
        
        .chat-input-container {{
            padding: 20px;
            background: white;
            border-top: 1px solid #e0e0e0;
        }}
        
        .chat-input-form {{
            display: flex;
            gap: 10px;
        }}
        
        #messageInput {{
            flex: 1;
            padding: 12px 16px;
            border: 2px solid #e0e0e0;
            border-radius: 24px;
            font-size: 14px;
            outline: none;
            transition: border-color 0.2s;
        }}
        
        #messageInput:focus {{
            border-color: {primary_color};
        }}
        
        #sendButton {{
            padding: 12px 24px;
            background: {primary_color};
            color: white;
            border: none;
            border-radius: 24px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
        }}
        
        #sendButton:hover {{
            background: #3a7bc8;
            transform: translateY(-1px);
        }}
        
        #sendButton:disabled {{
            background: #ccc;
            cursor: not-allowed;
            transform: none;
        }}
        
        .typing-indicator {{
            display: none;
            padding: 12px 16px;
            background: white;
            border-radius: 18px;
            width: 60px;
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
        }}
        
        .typing-indicator.active {{
            display: block;
        }}
        
        .typing-indicator span {{
            display: inline-block;
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: #999;
            margin: 0 2px;
            animation: typing 1.4s infinite;
        }}
        
        .typing-indicator span:nth-child(2) {{
            animation-delay: 0.2s;
        }}
        
        .typing-indicator span:nth-child(3) {{
            animation-delay: 0.4s;
        }}
        
        @keyframes typing {{
            0%, 60%, 100% {{ opacity: 0.3; }}
            30% {{ opacity: 1; }}
        }}
        
        .error-message {{
            position: fixed;
            top: 20px;
            right: 20px;
            background: #ff4444;
            color: white;
            padding: 12px 20px;
            border-radius: 8px;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
            display: none;
            animation: slideIn 0.3s ease-out;
        }}
        
        .error-message.active {{
            display: block;
        }}
        
        @keyframes slideIn {{
            from {{ transform: translateX(100%); }}
            to {{ transform: translateX(0); }}
        }}
        
        @media (max-width: 768px) {{
            .chat-container {{
                height: 100vh;
                max-width: 100%;
                border-radius: 0;
            }}
        }}
    </style>
</head>
<body>
    <div class="error-message" id="errorMessage"></div>
    
    <div class="chat-container">
        <div class="chat-header">
            <h1>{company_name}</h1>
        </div>
        
        <div class="chat-messages" id="chatMessages">
            <div class="message assistant">
                <div class="message-bubble">
                    Hello! I'm here to help. What can I assist you with today?
                </div>
            </div>
        </div>
        
        <div class="chat-input-container">
            <form class="chat-input-form" id="chatForm">
                <input 
                    type="text" 
                    id="messageInput" 
                    placeholder="Type your message..." 
                    autocomplete="off"
                    required
                />
                <button type="submit" id="sendButton">Send</button>
            </form>
        </div>
    </div>
    
    <script>
        const SERVING_URL = '{serving_url}';
        const CUSTOMER_ID = '{customer_id}';
        const chatMessages = document.getElementById('chatMessages');
        const chatForm = document.getElementById('chatForm');
        const messageInput = document.getElementById('messageInput');
        const sendButton = document.getElementById('sendButton');
        const errorMessage = document.getElementById('errorMessage');
        
        let conversationHistory = [];
        
        function addMessage(role, content) {{
            const messageDiv = document.createElement('div');
            messageDiv.className = `message ${{role}}`;
            
            const bubbleDiv = document.createElement('div');
            bubbleDiv.className = 'message-bubble';
            bubbleDiv.textContent = content;
            
            messageDiv.appendChild(bubbleDiv);
            chatMessages.appendChild(messageDiv);
            
            // Scroll to bottom
            chatMessages.scrollTop = chatMessages.scrollHeight;
            
            // Add to history
            conversationHistory.push({{
                role: role,
                content: content
            }});
        }}
        
        function showTypingIndicator() {{
            const indicator = document.createElement('div');
            indicator.className = 'message assistant';
            indicator.id = 'typingIndicator';
            
            const bubble = document.createElement('div');
            bubble.className = 'typing-indicator active';
            bubble.innerHTML = '<span></span><span></span><span></span>';
            
            indicator.appendChild(bubble);
            chatMessages.appendChild(indicator);
            chatMessages.scrollTop = chatMessages.scrollHeight;
        }}
        
        function removeTypingIndicator() {{
            const indicator = document.getElementById('typingIndicator');
            if (indicator) {{
                indicator.remove();
            }}
        }}
        
        function showError(message) {{
            errorMessage.textContent = message;
            errorMessage.classList.add('active');
            setTimeout(() => {{
                errorMessage.classList.remove('active');
            }}, 5000);
        }}
        
        async function sendMessage(userMessage) {{
            // Add user message to chat
            addMessage('user', userMessage);
            
            // Disable input
            messageInput.disabled = true;
            sendButton.disabled = true;
            
            // Show typing indicator
            showTypingIndicator();
            
            try {{
                // Call Modal serving endpoint
                const response = await fetch(SERVING_URL, {{
                    method: 'POST',
                    headers: {{
                        'Content-Type': 'application/json',
                    }},
                    body: JSON.stringify({{
                        customer_id: CUSTOMER_ID,
                        messages: conversationHistory
                    }})
                }});
                
                if (!response.ok) {{
                    throw new Error(`Server error: ${{response.status}}`);
                }}
                
                const data = await response.json();
                const assistantMessage = data.response || data.message || 'No response received';
                
                // Remove typing indicator
                removeTypingIndicator();
                
                // Add assistant response
                addMessage('assistant', assistantMessage);
                
            }} catch (error) {{
                console.error('Error:', error);
                removeTypingIndicator();
                showError('Failed to get response. Please try again.');
                
                // Remove failed message from history
                conversationHistory.pop();
            }} finally {{
                // Re-enable input
                messageInput.disabled = false;
                sendButton.disabled = false;
                messageInput.focus();
            }}
        }}
        
        chatForm.addEventListener('submit', async (e) => {{
            e.preventDefault();
            
            const message = messageInput.value.trim();
            if (!message) return;
            
            // Clear input
            messageInput.value = '';
            
            // Send message
            await sendMessage(message);
        }});
        
        // Focus input on load
        messageInput.focus();
    </script>
</body>
</html>
"""

# Write the HTML file
output_file = Path("index.html")
output_file.write_text(widget_html, encoding="utf-8")

print(f"Chatbot widget created: {{output_file}}")
print(f"Serving URL: {serving_url}")
print(f"Company: {company_name}")
'''
        return code
    
    def _extract_serving_url_from_previous_results(self, context: Dict[str, Any]) -> str:
        """Extract serving URL from previous executor results (DataExecutor)."""
        previous_results = context.get("previousResults", [])
        
        for result in previous_results:
            if result.get("executorUsed") == "DataExecutor":
                serving_url = result.get("servingUrl")
                if serving_url:
                    self.logger.info(f"Found serving URL from DataExecutor: {serving_url}")
                    return serving_url
        
        return ""
    
    def _extract_customer_id_from_previous_results(self, context: Dict[str, Any]) -> str:
        """Extract customer ID from previous executor results (DataExecutor)."""
        previous_results = context.get("previousResults", [])
        
        for result in previous_results:
            if result.get("executorUsed") == "DataExecutor":
                customer_id = result.get("customerId")
                if customer_id:
                    self.logger.info(f"Found customer ID from DataExecutor: {customer_id}")
                    return customer_id
        
        return ""
    
    def _extract_serving_url_from_text(self, text: str) -> str:
        """Extract serving URL from user request text (for MVP testing)."""
        if not text:
            return ""
        
        patterns = [
            r'servingUrl:\s*(https://[^\s\n]+)',
            r'serving\s+URL:\s*(https://[^\s\n]+)',
            r'serving_url:\s*(https://[^\s\n]+)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                url = match.group(1).rstrip('.,;')
                self.logger.info(f"Extracted serving URL from text: {url}")
                return url
        
        return ""
    
    def _extract_company_name_from_text(self, text: str) -> Optional[str]:
        """Extract company name from user request text."""
        if not text:
            return None
        
        patterns = [
            r'companyName:\s*([^\n•]+)',
            r'company\s+name:\s*([^\n•]+)',
            r'company_name:\s*([^\n•]+)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                name = match.group(1).strip().rstrip('.,;')
                self.logger.info(f"Extracted company name from text: {name}")
                return name
        
        return None
    
    def _extract_primary_color_from_text(self, text: str) -> Optional[str]:
        """Extract primary color from user request text."""
        if not text:
            return None
        
        patterns = [
            r'primaryColor:\s*(#[0-9A-Fa-f]{6})',
            r'primary\s+color:\s*(#[0-9A-Fa-f]{6})',
            r'primary_color:\s*(#[0-9A-Fa-f]{6})',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                color = match.group(1)
                self.logger.info(f"Extracted primary color from text: {color}")
                return color
        
        return None