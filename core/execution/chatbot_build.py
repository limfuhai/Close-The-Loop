# chatbot_build.py
"""
Chatbot Widget Building Execution Module
Handles the pipeline for building self-contained chatbot HTML widgets.
Creates beautiful, functional chatbot interfaces with embedded Modal serving URLs.
"""

import os
import logging
import subprocess
import tempfile
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, List

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class ChatbotBuilder:
    """
    Main orchestrator for chatbot widget building functionality.
    Manages the pipeline from serving URL to deployable HTML widget.
    """
    
    def __init__(self, output_base_dir: str = "generated_chatbots"):
        """
        Initialize the Chatbot Builder.
        
        Args:
            output_base_dir: Base directory for generated chatbot widgets
        """
        self.output_base_dir = Path(output_base_dir)
        self.output_base_dir.mkdir(exist_ok=True)
        logger.info(f"Initialized Chatbot Builder with output directory: {self.output_base_dir}")
    
    def build_chatbot(
        self, 
        serving_url: str,
        company_name: str = "AI Assistant",
        primary_color: str = "#4A90E2"
    ) -> Dict[str, Any]:
        """
        Execute chatbot builder code and create HTML widget.
        
        Args:
            serving_url: Modal endpoint URL for the finetuned model
            company_name: Name to display in chatbot header
            primary_color: Hex color for branding
            
        Returns:
            Dictionary with build results and file paths
        """
        try:
            # Generate widget filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            widget_name = f"chatbot_widget_{timestamp}.html"
            widget_path = self.output_base_dir / widget_name
            
            logger.info(f"Building chatbot widget: {widget_name}")
            
            # Generate the widget code
            code = self._generate_widget_code(serving_url, company_name, primary_color)
            
            # Execute the code to create the widget file
            result = self._execute_generator(code, self.output_base_dir)
            
            if result['success']:
                # Find the created HTML file
                created_files = result['files']
                html_file = None
                
                for file_path in created_files:
                    if file_path.endswith('.html'):
                        html_file = self.output_base_dir / Path(file_path).name
                        break
                
                if html_file and html_file.exists():
                    logger.info(f"Chatbot widget created: {html_file}")
                    
                    # Read file size
                    file_size = html_file.stat().st_size
                    
                    return {
                        'status': 'success',
                        'widget_name': html_file.name,
                        'widget_path': str(html_file),
                        'file_size': file_size,
                        'serving_url': serving_url,
                        'company_name': company_name,
                        'message': f"Chatbot widget '{html_file.name}' successfully created!",
                        'instructions': self._generate_usage_instructions(html_file.name, serving_url)
                    }
                else:
                    return {
                        'status': 'error',
                        'error': 'No HTML file was created',
                        'message': 'Widget generation failed - no HTML output'
                    }
            else:
                return {
                    'status': 'error',
                    'error': result.get('error', 'Unknown error'),
                    'message': f"Failed to create chatbot widget: {result.get('error', 'Unknown error')}"
                }
                
        except Exception as e:
            logger.error(f"Error building chatbot widget: {str(e)}")
            return {
                'status': 'error',
                'error': str(e),
                'message': f"Error building chatbot widget: {str(e)}"
            }
    
    def _generate_widget_code(
        self, 
        serving_url: str, 
        company_name: str,
        primary_color: str
    ) -> str:
        """
        Generate Python code that creates the chatbot HTML widget.
        
        Args:
            serving_url: Modal endpoint URL
            company_name: Company/bot name
            primary_color: Branding color
            
        Returns:
            Python code as string
        """
        code = f'''
import os
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
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
        }}
        
        #sendButton:hover {{
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(74, 144, 226, 0.4);
        }}
        
        #sendButton:disabled {{
            opacity: 0.6;
            cursor: not-allowed;
        }}
        
        .typing-indicator {{
            display: none;
            padding: 12px 16px;
            background: white;
            border-radius: 18px;
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
            width: fit-content;
        }}
        
        .typing-indicator.active {{
            display: block;
        }}
        
        .typing-indicator span {{
            display: inline-block;
            width: 8px;
            height: 8px;
            background: {primary_color};
            border-radius: 50%;
            margin: 0 2px;
            animation: bounce 1.4s infinite ease-in-out both;
        }}
        
        .typing-indicator span:nth-child(1) {{ animation-delay: -0.32s; }}
        .typing-indicator span:nth-child(2) {{ animation-delay: -0.16s; }}
        
        @keyframes bounce {{
            0%, 80%, 100% {{ transform: scale(0); }}
            40% {{ transform: scale(1); }}
        }}
        
        .error-message {{
            color: #d32f2f;
            font-size: 12px;
            margin-top: 8px;
            display: none;
        }}
        
        .error-message.active {{
            display: block;
        }}
    </style>
</head>
<body>
    <div class="chat-container">
        <div class="chat-header">
            <h1>{company_name}</h1>
        </div>
        
        <div class="chat-messages" id="chatMessages">
            <div class="message assistant">
                <div class="message-bubble">
                    Hello! I'm your {company_name} assistant. How can I help you today?
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
            <div class="error-message" id="errorMessage"></div>
        </div>
    </div>
    
    <script>
        const SERVING_URL = '{serving_url}';
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
            conversationHistory.push({{ role, content }});
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
output_file = Path("chatbot_widget.html")
output_file.write_text(widget_html, encoding="utf-8")

print(f"Chatbot widget created: {{output_file}}")
print(f"Serving URL: {serving_url}")
print(f"Company: {company_name}")
'''
        
        return code
    
    def _execute_generator(self, code: str, output_dir: Path) -> Dict[str, Any]:
        """
        Execute the generator code to create chatbot widget.
        
        Args:
            code: Python code to execute
            output_dir: Directory to run the code in
            
        Returns:
            Execution result with success status and created files
        """
        try:
            # Create a temporary file for the code
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
                f.write(code)
                temp_file = f.name
            
            # Execute the code in the output directory
            result = subprocess.run(
                ['python', temp_file],
                cwd=str(output_dir),
                capture_output=True,
                text=True,
                timeout=30
            )
            
            # Clean up temp file
            os.unlink(temp_file)
            
            if result.returncode == 0:
                # Scan for created files
                created_files = [
                    f.name for f in output_dir.glob('*.html')
                ]
                logger.info(f"Generator created {len(created_files)} file(s)")
                
                return {
                    'success': True,
                    'files': created_files,
                    'output': result.stdout
                }
            else:
                logger.error(f"Generator failed: {result.stderr}")
                return {
                    'success': False,
                    'error': result.stderr or result.stdout,
                    'files': []
                }
                
        except subprocess.TimeoutExpired:
            logger.error("Generator execution timed out")
            return {
                'success': False,
                'error': 'Execution timed out after 30 seconds',
                'files': []
            }
        except Exception as e:
            logger.error(f"Generator execution error: {str(e)}")
            return {
                'success': False,
                'error': str(e),
                'files': []
            }
    
    def _generate_usage_instructions(self, widget_name: str, serving_url: str) -> str:
        """
        Generate usage instructions for the chatbot widget.
        
        Args:
            widget_name: Name of the created widget file
            serving_url: Modal serving URL
            
        Returns:
            Usage instructions as string
        """
        instructions = f"""
## Chatbot Widget Usage Instructions

### File Created
**{widget_name}** - Self-contained HTML chatbot widget

### How to Deploy

**Option 1: Direct Embedding**
1. Download the HTML file
2. Copy the entire HTML code
3. Paste into your website's HTML
4. The chatbot will appear as a full-page interface

**Option 2: iframe Embedding**
1. Upload the HTML file to your web server
2. Embed using iframe in your website:
   ```html
   <iframe src="/{widget_name}" width="100%" height="700px" style="border: none;"></iframe>
   ```

**Option 3: Popup/Modal**
1. Use JavaScript to load the widget in a modal dialog
2. Trigger on button click or page load
3. Provides non-intrusive chat experience

### Technical Details
- **Serving URL**: {serving_url}
- **Communication**: POST requests with JSON payload
- **Conversation History**: Maintained client-side
- **Styling**: Fully customizable CSS included
- **Mobile Responsive**: Works on all screen sizes

### Customization
You can customize the widget by editing:
- Colors in the `<style>` section
- Company name in the header
- Welcome message
- Button text and styling

### API Format
The widget sends requests to {serving_url} with this format:
```json
{{
  "messages": [
    {{"role": "user", "content": "Hello"}},
    {{"role": "assistant", "content": "Hi! How can I help?"}}
  ]
}}
```

Expected response format:
```json
{{
  "response": "Assistant's reply here"
}}
```
"""
        return instructions


# Convenience function for simple chatbot building
def build_chatbot_widget(
    serving_url: str,
    company_name: str = "AI Assistant",
    primary_color: str = "#4A90E2"
) -> Dict[str, Any]:
    """
    Build a chatbot widget from serving URL.
    
    Args:
        serving_url: Modal endpoint URL for the model
        company_name: Name to display in chatbot
        primary_color: Hex color for branding
        
    Returns:
        Build result dictionary
    """
    builder = ChatbotBuilder()
    return builder.build_chatbot(serving_url, company_name, primary_color)