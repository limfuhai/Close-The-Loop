from storage import OutputStorage
from dotenv import load_dotenv
from comprehensive_formatting_prompts import SINGLE_LLM_ENHANCED_PROMPT
from multi_llm_orchestrator import MultiLLMOrchestrator
from file_handler import FileHandler
from api_client import moonshot_api_key
from supabase import create_client, Client
import jwt
from urllib.parse import quote
from svix.webhooks import Webhook
import time
import stripe
import httpx
import uvicorn
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from fastapi import FastAPI, UploadFile, File, Form, Request, Body, HTTPException
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any  # ADDED: List import
import mimetypes
import json
from datetime import datetime
import uuid
import logging
import asyncio
import sys
import os
from message import router as message_router, init as message_init, save_message_to_db, get_messages_for_agent
from agent import router as agent_router, init as agent_init
from mail_accounts import router as mail_accounts_router, init as mail_accounts_init
print("\n" + "*" * 80)
print("*" + " " * 78 + "*")
print("*" + " PYTHON BACKEND STARTING ".center(78) + "*")
print("*" + " " * 78 + "*")
print("*" * 80 + "\n")
# Bridge commands added to top of file
bridge_pending_commands = {}
bridge_command_results = {}

# Add server directory to path to find modules
current_dir = Path(__file__).resolve().parent  # core directory
server_dir = current_dir.parent  # server directory
if str(server_dir) not in sys.path:
    sys.path.append(str(server_dir))


class MessageHandler:
    def __init__(self, model, tokenizer):
        self.model = model
        self.tokenizer = tokenizer
        self.logger = logging.getLogger(__name__)
        self.file_handler = FileHandler(uploads_dir="uploads")

        # Artifact detection system
        self.artifact_threshold_lines = 15
        self.artifact_threshold_chars = 1500

        # ADDED: Conversation history optimization settings
        self.max_history_messages = 10  # Maximum messages to keep in history
        self.history_token_limit = 2000  # Maximum tokens for history

    def _estimate_tokens(self, text: str) -> int:
        """Estimate token count for text (rough approximation: 1 token Ã¢â€°Ë† 4 characters)."""
        return len(text) // 4

    def _optimize_conversation_history(self, history: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """
        Intelligently optimize conversation history to reduce token usage.
        Frontend doesn't need to change - this happens automatically in backend.

        Returns optimized history list.
        """
        if not history:
            return []

        # Step 1: Limit to max_history_messages (keep most recent)
        if len(history) > self.max_history_messages:
            self.logger.info(
                f"[MessageHandler] Ã°Å¸â€œâ€° History reduced from {len(history)} to {self.max_history_messages} messages"
            )
            history = history[-self.max_history_messages:]

        # Step 2: Check total token count
        total_tokens = sum(self._estimate_tokens(
            msg.get('content', '')) for msg in history)

        if total_tokens > self.history_token_limit:
            self.logger.info(
                f"[MessageHandler] Ã°Å¸â€œâ€° History tokens ({total_tokens}) exceeds limit ({self.history_token_limit})"
            )

            # Keep removing oldest messages until under limit
            while total_tokens > self.history_token_limit and len(history) > 2:
                removed_msg = history.pop(0)
                removed_tokens = self._estimate_tokens(
                    removed_msg.get('content', ''))
                total_tokens -= removed_tokens
                self.logger.info(
                    f"[MessageHandler] Ã°Å¸â€”â€˜Ã¯Â¸Â Removed 1 old message ({removed_tokens} tokens)")

            self.logger.info(
                f"[MessageHandler] Ã¢Å“â€¦ Optimized history: {len(history)} messages, ~{total_tokens} tokens"
            )

        return history

    async def handle_message(self, message_data: dict) -> dict:
        try:
            print(f"HANDLE_MESSAGE RAW INPUT: {message_data}")

            # Ensure message_data is a dictionary
            if isinstance(message_data, str):
                try:
                    message_data = json.loads(message_data)
                    print(
                        f"Converted string message_data to dict: {message_data}")
                except json.JSONDecodeError:
                    print("Failed to decode message_data string to JSON")
                    raise ValueError(
                        "Invalid message format: Expected JSON object")

            message_type = message_data.get('type')
            print(f"TRACKING: Message type detected: {message_type}")

            # Extract content, handling string case
            content = message_data.get('content', {})
            if isinstance(content, str):
                try:
                    # Try to parse JSON string
                    content = json.loads(content)
                    print(f"Parsed content JSON string into dict: {content}")
                except json.JSONDecodeError:
                    # If not valid JSON, keep as is
                    print(f"Content is a non-JSON string: {content[:100]}...")

            # Also ensure we handle agentId if present at the top level
            agent_id = message_data.get('agentId')
            if agent_id and not (isinstance(content, dict) and 'agentId' in content):
                if isinstance(content, dict):
                    content['agentId'] = agent_id
                else:
                    content = {'content': content, 'agentId': agent_id}

            print(f"Processed message: type={message_type}, content={content}")

            handlers = {
                'AGENT_MESSAGE': self._handle_agent_message,
                'FILE_UPLOAD': self._handle_file_upload,
                'FILE_UPLOAD_BATCH': self._handle_file_upload_batch
            }

            handler = handlers.get(message_type)
            if not handler:
                raise ValueError(f"Unknown message type: {message_type}")

            return await handler(content)

        except Exception as e:
            self.logger.error(f"Error handling message: {str(e)}")
            return {
                'type': 'ERROR',
                'content': {
                    'message': str(e),
                    'timestamp': datetime.now().isoformat()
                }
            }

    async def _handle_agent_message(self, content: dict) -> dict:
        try:
            print("STEP 1: Started processing agent message")
            # Handle string content
            if isinstance(content, str):
                try:
                    content = json.loads(content)
                    print("STEP 1.1: Converted string content to dict")
                except json.JSONDecodeError:
                    content = {"content": content}
                    print("STEP 1.2: Created simple content dict")

            agent_id = content.get('agentId')
            message_content = content.get('content')
            attachments = content.get('attachments', [])
            conversation_history = content.get(
                'conversationHistory', [])  # FIXED: proper spelling

            # ADDED: Automatically optimize conversation history (NO FRONTEND CHANGES NEEDED!)
            if conversation_history:
                original_length = len(conversation_history)
                conversation_history = self._optimize_conversation_history(
                    conversation_history)

                if len(conversation_history) < original_length:
                    self.logger.info(
                        f"[MessageHandler] Ã°Å¸â€™Â¡ Auto-optimized: {original_length} Ã¢â€ â€™ {len(conversation_history)} messages"
                    )

            print(
                f"STEP 2: Extracted agentId={agent_id}, content={message_content}, history={len(conversation_history)} messages")

            # Format the user message with clear sections
            user_message = f"User Question: {message_content}\n\n"

            # Process attached files with better formatting
            if attachments:
                print(f"Processing {len(attachments)} attached files")
                user_message += "## Files Directly Attached to This Message:\n\n"

                for idx, attachment in enumerate(attachments):
                    file_path = attachment.get('path')
                    if file_path:
                        # Convert web path to file system path
                        if file_path.startswith('/uploads/'):
                            # Remove leading slash to make it relative
                            # becomes 'uploads/filename.ext'
                            file_path = file_path[1:]

                        if os.path.exists(file_path):
                            try:
                                file_extension = os.path.splitext(file_path)[
                                    1].lower()
                                file_name = attachment.get(
                                    'name', 'unnamed_file')

                                from file_utilities import read_file_content
                                file_content = read_file_content(
                                    file_path, 5000)

                                # Format differently based on file type
                                user_message += f"### File {idx+1}: {file_name}\n"
                                if file_extension in ['.py', '.js', '.ts', '.jsx', '.tsx', '.html', '.css']:
                                    user_message += f"```{file_extension[1:]}\n{file_content}\n```\n\n"
                                elif file_extension in ['.json', '.xml']:
                                    user_message += f"```{file_extension[1:]}\n{file_content}\n```\n\n"
                                elif file_extension in ['.csv', '.tsv']:
                                    user_message += f"CSV data:\n```\n{file_content}\n```\n\n"
                                else:
                                    user_message += f"Content:\n{file_content}\n\n"
                            except Exception as e:
                                user_message += f"### Error reading file {attachment.get('name')}: {str(e)}\n\n"

            # Create a system prompt to guide Claude
            system_prompt = (
                "You are an AI assistant in OpexAssistant. Your purpose is to analyze files and answer questions. "
                "When looking at code or data files, be thorough and precise. "
                "If files are attached, focus on analyzing their content to provide detailed insights. "
                "Format your responses with clear markdown structure including paragraphs, headers, and code blocks as appropriate."
                + SINGLE_LLM_ENHANCED_PROMPT
            )

            # Update the API call section in _handle_agent_message method
            print("STEP 4: About to call Claude API")
            try:
                # Call the Claude API with the formatted context AND conversation history
                response = await self.model.generate(
                    prompt=user_message,
                    max_tokens=4096,
                    temperature=0.7,
                    system_prompt=system_prompt,
                    conversation_history=conversation_history  # FIXED: proper spelling
                )

                print(
                    f"STEP 4.2: API response received, length: {len(response)} characters")

            except Exception as api_error:
                print(f"STEP 4 ERROR: API generation error: {str(api_error)}")
                import traceback
                traceback.print_exc()
                response = f"Error generating response: {str(api_error)}. Please try again or check your API configuration."

            print("STEP 5: Creating response object")
            response_object = {
                'type': 'AGENT_RESPONSE',
                'agentId': agent_id,
                'content': response,
                'timestamp': datetime.now().isoformat()
            }

            print(f"STEP 6: Returning response object")
            return response_object

        except Exception as e:
            print(f"GENERAL ERROR in _handle_agent_message: {str(e)}")
            import traceback
            traceback.print_exc()

            return {
                'type': 'ERROR',
                'content': {
                    'agentId': content.get('agentId', 'unknown'),
                    'message': f"Error generating response: {str(e)}",
                    'timestamp': datetime.now().isoformat()
                }
            }

    async def _handle_file_upload(self, content: dict) -> dict:
        """Handle single file upload"""
        return await self.file_handler.handle_file_upload(content)

    async def _handle_file_upload_batch(self, content: dict) -> dict:
        """Handle multiple file uploads"""
        return await self.file_handler.handle_file_upload_batch(content)

    def _analyze_for_artifacts(self, response: str) -> dict:
        """
        Analyzes LLM response and extracts potential artifacts.
        Returns modified content with artifact markers and artifact metadata.
        """
        import re
        import time

        artifacts = []
        modified_content = response

        # Pattern 1: Detect code blocks for artifact conversion
        code_pattern = r'```(\w+)?\n(.*?)```'
        code_matches = re.finditer(code_pattern, response, re.DOTALL)

        for match in code_matches:
            language = match.group(1) or 'plaintext'
            code_content = match.group(2).strip()

            # Check if code exceeds threshold
            line_count = len(code_content.split('\n'))
            if line_count >= self.artifact_threshold_lines:
                # Generate artifact ID
                artifact_id = f"code_{int(time.time() * 1000)}"

                # Extract title from first comment or use generic title
                title_match = re.search(
                    r'^(?:#|//|/\*)\s*(.+?)(?:\*/)?$', code_content, re.MULTILINE)
                title = title_match.group(1).strip(
                ) if title_match else f"{language.capitalize()} Implementation"

                # Create artifact metadata
                artifact = {
                    "id": artifact_id,
                    "type": "code",
                    "language": language,
                    "title": title,
                    "content": code_content,
                    "lines": line_count
                }
                artifacts.append(artifact)

                # Replace in content with marker
                marker = f"[ARTIFACT:{artifact_id}:code:{title}]"
                modified_content = modified_content.replace(
                    match.group(0), marker, 1)

        # Pattern 2: Detect document-style content
        doc_pattern = r'(?:^|\n)(#{1,3}\s+.+?)(?=\n#{1,3}\s+|\Z)'
        doc_matches = list(re.finditer(
            doc_pattern, response, re.MULTILINE | re.DOTALL))

        for i, match in enumerate(doc_matches):
            section_content = match.group(0).strip()
            if len(section_content) >= self.artifact_threshold_chars:
                artifact_id = f"doc_{int(time.time() * 1000)}_{i}"

                # Extract title from first header
                title_match = re.search(
                    r'^#{1,3}\s+(.+?)$', section_content, re.MULTILINE)
                title = title_match.group(1).strip(
                ) if title_match else "Documentation"

                artifact = {
                    "id": artifact_id,
                    "type": "markdown",
                    "title": title,
                    "content": section_content,
                    "chars": len(section_content)
                }
                artifacts.append(artifact)

                marker = f"[ARTIFACT:{artifact_id}:markdown:{title}]"
                modified_content = modified_content.replace(
                    match.group(0), marker, 1)

        # Pattern 3: Detect presentation-style content
        slide_pattern = r'(?:Slide\s+\d+:|##\s+Slide\s+\d+).*?(?=(?:Slide\s+\d+:|##\s+Slide\s+\d+)|$)'
        slide_matches = list(re.finditer(slide_pattern, response, re.DOTALL))

        if len(slide_matches) >= 3:  # Only create presentation artifact if 3+ slides
            slides = []
            for idx, match in enumerate(slide_matches):
                slides.append({
                    "number": idx + 1,
                    "content": match.group(0).strip()
                })

            artifact_id = f"pres_{int(time.time() * 1000)}"
            title = "Presentation"

            # Try to extract presentation title
            title_match = re.search(r'^#\s+(.+?)$', response, re.MULTILINE)
            if title_match:
                title = title_match.group(1).strip()

            full_content = "\n\n".join([s["content"] for s in slides])
            artifact = {
                "id": artifact_id,
                "type": "presentation",
                "title": title,
                "content": full_content,
                "slides": slides
            }
            artifacts.append(artifact)

            # Replace all slides with single marker
            for match in slide_matches:
                modified_content = modified_content.replace(
                    match.group(0), "", 1)
            modified_content = modified_content.strip(
            ) + f"\n\n[ARTIFACT:{artifact_id}:presentation:{title}]"

        return {
            "content": modified_content,
            "artifacts": artifacts
        }


class Compiler:
    def __init__(self, host='0.0.0.0', port=None, display_config=None):
        self.display_config = display_config or {
            'width': 1024,
            'height': 768,
            'display_num': None
        }

        self.setup_logging()
        self._configure_environment()

        self.host = host
        # Configure HTTP port (Render uses PORT, local dev uses HTTP_PORT)
        http_port = os.environ.get('PORT') or os.environ.get('HTTP_PORT')
        if http_port is not None:
            self.http_port = int(http_port)
        elif port is not None:
            self.http_port = port
        else:
            self.http_port = 8770
            print(
                f"WARNING: No port specified, using fallback HTTP port {self.http_port}")

        self.model, self.tokenizer = self._load_model()
        self.message_handler = MessageHandler(
            self.model,
            self.tokenizer,
        )

        # ADDED: Configure conversation history optimization
        # You can adjust these values to control token usage:
        # - max_history_messages: How many recent messages to keep (default: 10)
        # - history_token_limit: Max tokens for history (default: 2000)
        self.message_handler.max_history_messages = int(
            os.getenv('MAX_HISTORY_MESSAGES', '10'))
        self.message_handler.history_token_limit = int(
            os.getenv('HISTORY_TOKEN_LIMIT', '2000'))

        self.logger.info(
            f"[Compiler] Ã°Å¸â€œâ€¹ History settings: max_messages={self.message_handler.max_history_messages}, "
            f"token_limit={self.message_handler.history_token_limit}"
        )

        # ---- Supabase config ----
        self.SB_URL = os.getenv("SUPABASE_URL")
        self.SB_KEY = os.getenv("SUPABASE_SERVICE_KEY")
        self.storage = OutputStorage(bucket=os.getenv(
            "SUPABASE_BUCKET_OUTPUT", "user-outputs"))
        # After: self.storage = OutputStorage(...)
        if getattr(self.storage, "client", None):
            self.logger.info(
                f"[Compiler] Ã¢Å“â€¦ Supabase connected. Bucket='{self.storage.bucket}', URL='{self.SB_URL}', "
                f"ForceLocal={self.storage.force_local}, PublicBucket={self.storage.public_bucket}, "
                f"SignTTL={self.storage.sign_ttl}s"
            )
        else:
            self.logger.warning(
                "[Compiler] Ã¢Å¡Â Ã¯Â¸Â Supabase NOT active (missing keys or client init failed). "
                "Falling back to local /files/outputs when saving."
            )
        if not (self.SB_URL and self.SB_KEY):
            self.logger.warning(
                "Supabase env vars missing; outputs will save locally.")
            self.supabase: Optional[Client] = None
        else:
            try:
                self.supabase: Client = create_client(self.SB_URL, self.SB_KEY)
                self.logger.info(
                    f"Connected to Supabase bucket: {self.storage.bucket}")
            except Exception as e:
                self.logger.error(f"Failed to connect to Supabase: {e}")
                self.supabase = None
        self.SB_BUCKET = "user-outputs"
        self.SB_SIGN_TTL = 604800  # 7 days (hard default; no env required)

        # ---- Close the Loop local mode: no Supabase means one local user ----
        # The local user's ID is also the bridge's secret: set BRIDGE_TOKEN in .env
        # to a long random string.
        self.local_mode = self.supabase is None
        self.local_user_id = os.getenv("BRIDGE_TOKEN", "")
        if self.local_mode and not self.local_user_id:
            self.logger.error("Local mode needs BRIDGE_TOKEN in .env (any long random string).")

    async def verify_clerk_user(self, request) -> Optional[str]:
        """
        Extract and return clerk_user_id from Authorization Bearer JWT.
        Returns clerk_user_id string if valid, None if missing or malformed.
        """
        if self.local_mode:
            return self.local_user_id
        try:
            auth = request.headers.get("Authorization", "")
            print("AUTH", auth)
            if not auth.startswith("Bearer "):
                return None
            token = auth.split(" ", 1)[1]
            payload = jwt.decode(token, options={"verify_signature": False})
            return payload.get("sub")
        except Exception as e:
            self.logger.error(f"JWT decode error: {e}")
            return None

    async def get_user_token_balance(self, clerk_user_id: str) -> dict:
        """
        Query Supabase to get user's token allocation and remaining balance.
        Returns: {"email": str, "token_allocation": int,
            "tokens_remaining": int}
        """
        if self.local_mode:
            return {"email": "local", "token_allocation": 10**12, "tokens_remaining": 10**12}
        try:
            if not self.supabase:
                self.logger.error("Supabase client not initialized")
                return {"error": "Database not available"}

            result = self.supabase.table('users').select(
                'email, token_allocation, tokens_remaining').eq('clerk_user_id', clerk_user_id).execute()

            if not result.data or len(result.data) == 0:
                self.logger.error(
                    f"No user found with clerk_user_id: {clerk_user_id}")
                return {"error": "User not found"}

            user_data = result.data[0]
            self.logger.info(
                f"User {user_data['email']} has {user_data['tokens_remaining']} tokens remaining")

            return {
                "email": user_data['email'],
                "token_allocation": user_data['token_allocation'],
                "tokens_remaining": user_data['tokens_remaining']
            }

        except Exception as e:
            self.logger.error(f"Error querying user token balance: {str(e)}")
            return {"error": str(e)}

    async def update_token_consumption(self, clerk_user_id: str, tokens_consumed: int) -> bool:
        """
        Update user's tokens_remaining after API call completes.
        Returns: True if successful, False otherwise
        """
        if self.local_mode:
            return True
        try:
            if not self.supabase:
                self.logger.error("Supabase client not initialized")
                return False

            balance = await self.get_user_token_balance(clerk_user_id)
            if "error" in balance:
                return False

            new_remaining = balance['tokens_remaining'] - tokens_consumed

            result = self.supabase.table('users').update({
                'tokens_remaining': new_remaining
            }).eq('clerk_user_id', clerk_user_id).execute()

            self.logger.info(
                f"Updated user {balance['email']}: consumed {tokens_consumed} tokens, {new_remaining} remaining")
            return True

        except Exception as e:
            self.logger.error(f"Error updating token consumption: {str(e)}")
            return False


    def _upload_local_and_log(self, local_path: Path, user_id: Optional[str], prefix: str = "artifacts") -> dict:
        """
        Upload an existing local file (e.g., something in /tmp/opex/outputs) to Supabase via OutputStorage.
        Returns the dict from OutputStorage (with signed_url/public_url or local fallback).
        """
        try:
            res = self.storage.save_file_path(
                file_path=str(local_path),
                user_id=user_id or "anonymous",
                prefix=prefix,
                # used only if FORCE_LOCAL_OUTPUTS=true
                local_dir=str(Path("/tmp/opex/outputs")),
            )
            url = res.get("signed_url") or res.get(
                "public_url") or res.get("download_url")
            if "signed_url" in res or "public_url" in res:
                self.logger.info(
                    f"[Compiler] Uploaded '{local_path.name}' to Supabase. URL ready.")
            else:
                self.logger.warning(
                    f"[Compiler] Using local fallback for '{local_path.name}' -> {url}")
            return res
        except Exception as e:
            self.logger.error(
                f"[Compiler] Upload failed for '{local_path}': {e}")
            return {"filename": local_path.name, "error": str(e)}

    def _configure_environment(self):
        """Configure environment variables needed by tools and API"""
        load_dotenv()
        self.logger.info("Loaded environment variables from .env file")
        # Set display configuration for tools
        os.environ['WIDTH'] = str(self.display_config['width'])
        os.environ['HEIGHT'] = str(self.display_config['height'])
        os.environ['KMP_DUPLICATE_LIB_OK'] = 'TRUE'

        # API key configuration with helpful message
        if not os.environ.get('MOONSHOT_API_KEY'):
            self.logger.warning("MOONSHOT_API_KEY not set in .env")
        else:
            # Mask the API key in logs
            key = os.environ.get('MOONSHOT_API_KEY')
            masked_key = f"{key[:4]}...{key[-4:]}" if len(key) > 8 else "****"
            self.logger.info(f"Using Moonshot API key: {masked_key}")

        # Create output directory
        output_dir = Path("/tmp/opex/outputs")
        output_dir.mkdir(parents=True, exist_ok=True)

    def setup_logging(self):
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler("compiler.log"),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)

    def setup_fastapi(self):
        app = FastAPI()
        
        # ── Message API (message.py) ──
        message_init(self.supabase)
        app.include_router(message_router)
        
        # ── Agent API (agent.py) ──
        agent_init(self.supabase, self)
        app.include_router(agent_router)


        # ── Email accounts for the local agents (mail_accounts.py) ──
        mail_accounts_init(self.supabase)
        app.include_router(mail_accounts_router)
        
        # Add CORS middleware
        app.add_middleware(
            CORSMiddleware,
            # For development; restrict this in production
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["Content-Disposition"],
        )

        # --- Web server file roots (force everything to /tmp/opex) ---
        BASE_DIR = Path("/tmp/opex").resolve()
        OUTPUTS_DIR = (BASE_DIR / "outputs").resolve()
        PREVIEW_DIR = (BASE_DIR / "preview").resolve()
        LOGS_DIR = (BASE_DIR / "logs").resolve()
        for p in (OUTPUTS_DIR, PREVIEW_DIR, LOGS_DIR):
            p.mkdir(parents=True, exist_ok=True)

        # Ensure uploads dir exists before mount
        Path("uploads").mkdir(parents=True, exist_ok=True)

        # --- Public static mounts for downloads ---
        app.mount("/files/outputs",
                  StaticFiles(directory=str(OUTPUTS_DIR)), name="files_outputs")
        app.mount("/files/preview",
                  StaticFiles(directory=str(PREVIEW_DIR)), name="files_preview")
        app.mount("/files/logs",    StaticFiles(directory=str(LOGS_DIR)),
                  name="files_logs")

        # Mount uploads directory for file access
        app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

        # ---- Auth helpers (decode user id) ----
        def _extract_user_id(request: Optional[Request]) -> Optional[str]:
            try:
                if self.local_mode:
                    return self.local_user_id
                if request is None:
                    return None
                # Prefer explicit header if you already pass it from frontend (dev fallback)
                if request.headers.get("x-user-id"):
                    return request.headers.get("x-user-id")
                auth = request.headers.get("Authorization", "")
                if auth.startswith("Bearer "):
                    token = auth.split(" ", 1)[1]
                    # Only need 'sub'; skip signature verify to avoid JWKS fetch
                    payload = jwt.decode(
                        token, options={"verify_signature": False})
                    return payload.get("sub")
            except Exception:
                return None

        @app.get("/api/download/{area}/{filename}")
        async def verified_download(area: str, filename: str, download: bool = False):
            # In prod (default), disable local file serving; force Supabase URLs
            if os.getenv("FORCE_LOCAL_OUTPUTS", "false").lower() != "true":
                raise HTTPException(
                    status_code=403, detail="Local download disabled; use Supabase URLs")

            # Dev fallback only (FORCE_LOCAL_OUTPUTS=true)
            ROOTS = {"outputs": OUTPUTS_DIR,
                     "preview": PREVIEW_DIR, "logs": LOGS_DIR}
            root = ROOTS.get(area)
            if root is None:
                raise HTTPException(status_code=404, detail="Invalid area")
            if "/" in filename or "\\" in filename:
                raise HTTPException(status_code=400, detail="Invalid filename")
            p = (root / filename).resolve()
            if not p.exists() or not p.is_file():
                raise HTTPException(status_code=404, detail="File not found")

            media_type, _ = mimetypes.guess_type(p.name)
            disposition = "attachment" if download else "inline"
            return FileResponse(
                str(p),
                media_type=media_type or "application/octet-stream",
                filename=p.name,
                headers={
                    "Content-Disposition": f'{disposition}; filename="{p.name}"',
                    "Cache-Control": "private, max-age=3600",
                },
            )

        # Define file upload endpoint
        @app.post("/api/upload")
        async def upload_file(file: UploadFile, entityId: str = Form(...), entityType: str = Form(...)):
            try:
                # Handle file upload normally
                result = await self.message_handler.file_handler.handle_fastapi_upload(file, entityId, entityType)

                # Also index files based on their type
                if result.get("success") and "file" in result:
                    file_path = result["file"]["path"]

                    # Only use Elasticsearch for PROJECT files
                    if entityType == "project":
                        # Replace RAG with Elasticsearch for project files
                        try:
                            from core.executors.project_search_executor import ProjectSearchExecutor
                            search_executor = ProjectSearchExecutor()

                            es_result = await search_executor.index_document(
                                file_path=file_path,
                                filename=file.filename,
                                file_type=os.path.splitext(file.filename)[1],
                                entity_id=entityId,
                                entity_type=entityType
                            )

                            if es_result:
                                result["elasticsearch_indexed"] = True
                                self.logger.info(
                                    f"Project file {file.filename} indexed in Elasticsearch")
                            else:
                                self.logger.warning(
                                    f"Failed to index project file in Elasticsearch")

                        except Exception as es_error:
                            self.logger.warning(
                                f"Elasticsearch indexing failed: {str(es_error)}")

                return result
            except Exception as e:
                return {"success": False, "error": str(e)}

        # Define file list endpoint
        @app.get("/api/files/{entity_type}/{entity_id}")
        async def list_files(entity_type: str, entity_id: str):
            try:
                files = await self.message_handler.file_handler.list_files(entity_id, entity_type)
                return {"success": True, "files": files}
            except Exception as e:
                return {"success": False, "error": str(e)}

        @app.post("/api/search")
        async def project_search(body: dict = Body(...)):
            query = body.get("query") or body.get("description") or ""
            entity_id = body.get("entityId") or body.get("projectId")
            entity_type = body.get("entityType", "project")
            if not entity_id:
                return JSONResponse(status_code=400, content={"error": "Missing entityId"})
            task = {"description": query, "entityId": entity_id,
                    "entityType": entity_type}
            result = await self.project_search_executor.execute_task(task)
            return JSONResponse(status_code=200 if result.get("status") != "error" else 500, content=result)

        @app.get("/api/user/api-key")
        async def get_user_api_key(request: Request):
            """Retrieve the user's Unkey API key from Supabase"""
            try:
                user_id = _extract_user_id(request)
                if not user_id:
                    return JSONResponse(status_code=401, content={"error": "Not authenticated"})

                if not self.supabase:
                    return JSONResponse(status_code=500, content={"error": "Database not configured"})

                # Query Supabase users table for the user's API key
                response = self.supabase.table("users").select(
                    "unkey_api_key").eq("clerk_user_id", user_id).execute()

                if not response.data or len(response.data) == 0:
                    return JSONResponse(status_code=404, content={"error": "User not found or no subscription"})

                api_key = response.data[0].get("unkey_api_key")
                if not api_key:
                    return JSONResponse(status_code=404, content={"error": "No API key found - Please subscribe"})

                return JSONResponse(status_code=200, content={"apiKey": api_key})
            except Exception as e:
                print(f"Error retrieving API key: {e}")
                return JSONResponse(status_code=500, content={"error": "Failed to retrieve API key"})

        # TUNER V3 BRIDGE ENDPOINTS
        @app.get("/api/bridge/download")
        async def download_bridge(request: Request):
            """Download bridge.py with user's API key embedded"""
            try:
                user_id = _extract_user_id(request)
                if not user_id:
                    return JSONResponse(status_code=401, content={"error": "Not authenticated"})

                if not self.local_mode:
                    if not self.supabase:
                        return JSONResponse(status_code=500, content={"error": "Database not configured"})

                    # Verify user has an active subscription before issuing bridge
                    response = self.supabase.table("users").select(
                        "subscription_plan, tokens_remaining").eq("clerk_user_id", user_id).execute()

                    if not response.data or len(response.data) == 0:
                        return JSONResponse(status_code=404, content={"error": "User not found"})

                    user_record = response.data[0]
                    if user_record.get("subscription_plan") == "free_trial" and user_record.get("tokens_remaining", 0) <= 0:
                        return JSONResponse(status_code=403, content={"error": "Please subscribe to download the bridge"})

                # Read bridge template
                bridge_template_path = Path(__file__).parent / "bridge.py"

                if not bridge_template_path.exists():
                    bridge_template_path = Path("bridge.py")

                if not bridge_template_path.exists():
                    return JSONResponse(
                        status_code=500,
                        content={"error": "Bridge template not found"}
                    )

                with open(bridge_template_path, "r", encoding="utf-8") as f:
                    bridge_code = f.read()

                # Embed clerk_user_id as the bridge identity token
                bridge_code = bridge_code.replace(
                    "{{BOUNDARY_API_KEY}}", user_id)

                # Return as downloadable file
                from fastapi.responses import Response
                return Response(
                    content=bridge_code,
                    media_type="text/x-python",
                    headers={
                        "Content-Disposition": "attachment; filename=bridge.py",
                        "Content-Type": "text/x-python; charset=utf-8"
                    }
                )

            except Exception as e:
                self.logger.error(f"Error generating bridge download: {e}")
                return JSONResponse(status_code=500, content={"error": str(e)})

        # Bridge command queue (in-memory for now, use Redis in production)
        bridge_result_queues = {}   # {command_id: result}

        @app.post("/api/bridge/verify")
        async def verify_bridge_token(request: Request):
            """Verify that a bridge identity token (clerk_user_id) is valid and has active subscription"""
            try:
                clerk_user_id = request.headers.get(
                    "Authorization", "").replace("Bearer ", "")
                if self.local_mode:
                    if clerk_user_id and clerk_user_id == self.local_user_id:
                        return JSONResponse(status_code=200, content={"valid": True})
                    return JSONResponse(status_code=401, content={"error": "Invalid bridge token"})

                if not clerk_user_id:
                    return JSONResponse(status_code=401, content={"error": "No identity token provided"})

                if not self.supabase:
                    return JSONResponse(status_code=500, content={"error": "Database not configured"})

                result = self.supabase.table("users").select(
                    "subscription_plan, tokens_remaining").eq("clerk_user_id", clerk_user_id).execute()

                if not result.data or len(result.data) == 0:
                    self.logger.warning(
                        f"Bridge verify: no user found for clerk_user_id {clerk_user_id[:12]}...")
                    return JSONResponse(status_code=401, content={"error": "User not found"})

                user = result.data[0]
                self.logger.info(
                    f"Bridge verify: user found, plan={user.get('subscription_plan')}, tokens={user.get('tokens_remaining')}")
                return JSONResponse(status_code=200, content={"valid": True})

            except Exception as e:
                self.logger.error(f"Bridge token verification error: {e}")
                return JSONResponse(status_code=500, content={"error": str(e)})

        @app.post("/api/bridge/execute")
        async def bridge_execute(request: Request):
            """
            Executors POST commands here.

            Request body:
            {
                "id": "command-uuid",
                "type": "bash",
                "cmd": "whoami",
                "timeout": 30
            }

            Response:
            {
                "status": "queued",
                "command_id": "command-uuid"
            }
            """
            try:
                api_key = request.headers.get(
                    "Authorization", "").replace("Bearer ", "")

                if not api_key:
                    return JSONResponse(status_code=401, content={"error": "No API key"})
                
                if self.local_mode and api_key != self.local_user_id:
                    return JSONResponse(status_code=401, content={"error": "Invalid bridge token"})

                # Get command data
                command_data = await request.json()
                command_id = command_data.get("id")

                if not command_id:
                    return JSONResponse(status_code=400, content={"error": "Missing command ID"})

                # Queue command for bridge client to pick up
                if api_key not in bridge_pending_commands:
                    bridge_pending_commands[api_key] = []

                bridge_pending_commands[api_key].append(command_data)

                self.logger.info(
                    f"📥 Command queued: {command_id[:8]} from {api_key[:10]}...")

                return JSONResponse(status_code=200, content={
                    "status": "queued",
                    "command_id": command_id
                })

            except Exception as e:
                self.logger.error(f"Bridge execute error: {e}")
                return JSONResponse(status_code=500, content={"error": str(e)})

        @app.get("/api/bridge/result/{command_id}")
        async def bridge_get_result(command_id: str, request: Request):
            """
            Executors GET results here (polling).

            Response if pending:
            {
                "status": "pending"
            }

            Response if complete:
            {
                "status": "complete",
                "result": {
                    "success": true,
                    "output": "adriel",
                    "error": null,
                    "status": 0
                }
            }
            """
            try:
                api_key = request.headers.get(
                    "Authorization", "").replace("Bearer ", "")

                if not api_key:
                    return JSONResponse(status_code=401, content={"error": "No API key"})
                
                if self.local_mode and api_key != self.local_user_id:
                    return JSONResponse(status_code=401, content={"error": "Invalid bridge token"})

                # Check if results are ready
                if command_id in bridge_command_results:
                    result = bridge_command_results[command_id]
                    # Don't delete yet - executor might poll multiple times

                    return JSONResponse(status_code=200, content={
                        "status": "complete",
                        "result": result
                    })

                # Still pending
                return JSONResponse(status_code=200, content={
                    "status": "pending"
                })

            except Exception as e:
                self.logger.error(f"Bridge result fetch error: {e}")
                return JSONResponse(status_code=500, content={"error": str(e)})

        @app.post("/api/bridge/poll")
        async def bridge_poll(request: Request):
            """Bridge client polls this endpoint for pending commands"""
            try:
                api_key = request.headers.get(
                    "Authorization", "").replace("Bearer ", "")

                if not api_key:
                    return JSONResponse(status_code=401, content={"error": "No API key"})
                
                if self.local_mode and api_key != self.local_user_id:
                    return JSONResponse(status_code=401, content={"error": "Invalid bridge token"})

                # Check for pending commands using MODULE-LEVEL storage
                if api_key in bridge_pending_commands and len(bridge_pending_commands[api_key]) > 0:
                    commands = bridge_pending_commands[api_key]
                    bridge_pending_commands[api_key] = []  # Clear queue

                    self.logger.info(
                        f"📤 Sending {len(commands)} commands to bridge client")

                    return JSONResponse(status_code=200, content={
                        "has_commands": True,
                        "commands": commands
                    })

                return JSONResponse(status_code=200, content={
                    "has_commands": False
                })

            except Exception as e:
                self.logger.error(f"Bridge poll error: {e}")
                return JSONResponse(status_code=500, content={"error": str(e)})

        @app.post("/api/bridge/results")
        async def bridge_results(request: Request):
            """Bridge client sends command results here"""
            try:
                api_key = request.headers.get(
                    "Authorization", "").replace("Bearer ", "")

                if not api_key:
                    return JSONResponse(status_code=401, content={"error": "No API key"})

                if self.local_mode and api_key != self.local_user_id:
                    return JSONResponse(status_code=401, content={"error": "Invalid bridge token"})

                # Get results from bridge
                data = await request.json()
                command_id = data.get("command_id")
                results = data.get("results")

                if not command_id or not results:
                    return JSONResponse(status_code=400, content={"error": "Missing data"})

                # Store results using MODULE-LEVEL storage
                bridge_command_results[command_id] = results

                self.logger.info(
                    f"📬 Results received for command: {command_id[:8]}")

                return JSONResponse(status_code=200, content={"status": "received"})

            except Exception as e:
                self.logger.error(f"Bridge results error: {e}")
                return JSONResponse(status_code=500, content={"error": str(e)})

        # ── Boundary V4: scheduled wake-ups ──
        # Windows Task Scheduler runs ~/Boundary/wake/boundary_wake.py at the time an
        # agent chose; that script calls this endpoint, which starts the named agent
        # with the message it left itself, exactly as if the user had typed it.
        self._wake_tasks = set()

        @app.post("/api/bridge/wake")
        async def bridge_wake(request: Request):
            try:
                clerk_user_id = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
                if not clerk_user_id:
                    return JSONResponse(status_code=401, content={"error": "No identity token"})

                if self.local_mode and clerk_user_id != self.local_user_id:
                    return JSONResponse(status_code=401, content={"error": "Invalid bridge token"})

                data = await request.json()
                agent_id = data.get("agent_id") or ""
                message = (data.get("message") or "").strip()
                wakeup_id = data.get("wakeup_id") or ""
                if not agent_id or not message:
                    return JSONResponse(status_code=400, content={"error": "agent_id and message are required"})

                balance = await self.get_user_token_balance(clerk_user_id)
                if "error" in balance:
                    return JSONResponse(status_code=401, content={"error": "User not found"})
                if balance["tokens_remaining"] <= 0:
                    return JSONResponse(status_code=402, content={"error": "Insufficient tokens"})

                header = f"[Boundary scheduled wake-up {wakeup_id}"
                if data.get("directive_id"):
                    header += f" | directive {data['directive_id']}"
                if data.get("kind"):
                    header += f" | {data['kind']}"
                header += f" | scheduled for {data.get('scheduled_for', '?')} local time"
                late = int(data.get("late_minutes") or 0)
                if late >= 10:
                    header += (f" | fired {late} min late: the computer may have been off or asleep, "
                               f"so treat anything unobserved since then as unverified")
                header += "]"
                wake_message = f"{header}\n{message}"

                task = asyncio.create_task(self._run_woken_agent(clerk_user_id, agent_id, wake_message))
                self._wake_tasks.add(task)
                task.add_done_callback(self._wake_tasks.discard)

                self.logger.info(f"⏰ Wake-up {wakeup_id} accepted for agent {agent_id[:8]}...")
                return JSONResponse(status_code=202, content={"status": "accepted", "wakeup_id": wakeup_id})

            except Exception as e:
                self.logger.error(f"Bridge wake error: {e}")
                return JSONResponse(status_code=500, content={"error": str(e)})

        @app.post("/api/chat/execute-local")
        async def execute_local_command(request: Request):
            """
            Called by chat interface to execute command on user's local machine
            Queues command for bridge to pick up
            """
            try:
                # Get user's API key
                user_id = _extract_user_id(request)
                if not user_id:
                    return JSONResponse(status_code=401, content={"error": "Not authenticated"})

                # clerk_user_id IS the bridge routing key now
                api_key = user_id

                # Parse command from request
                data = await request.json()
                command = {
                    "id": str(uuid.uuid4()),
                    "type": data.get("type", "bash"),
                    "cmd": data.get("command"),
                    "chat_id": data.get("chat_id")
                }

                # Add to user's command queue
                if api_key not in bridge_command_queues:
                    bridge_command_queues[api_key] = []

                bridge_command_queues[api_key].append(command)

                # Wait for results (with timeout)
                timeout_seconds = 60
                poll_interval = 0.5
                max_polls = int(timeout_seconds / poll_interval)

                for i in range(max_polls):
                    if command["id"] in bridge_result_queues:
                        results = bridge_result_queues[command["id"]]
                        del bridge_result_queues[command["id"]]  # Cleanup
                        return JSONResponse(status_code=200, content=results)

                    await asyncio.sleep(poll_interval)

                # Timeout
                return JSONResponse(
                    status_code=408,
                    content={"error": "Command timeout - is bridge running?"}
                )

            except Exception as e:
                self.logger.error(f"Execute local command error: {e}")
                return JSONResponse(status_code=500, content={"error": str(e)})

        # STREAMING ENDPOINT WITH CONVERSATION HISTORY SUPPORT
        @app.post("/api/agent/message/stream")
        async def agent_message_stream(request: Request):
            # Authenticate via Clerk JWT
            clerk_user_id = await self.verify_clerk_user(request)
            if not clerk_user_id:
                return JSONResponse(
                    status_code=401,
                    content={
                        "error": "Not authenticated",
                        "message": "Please log in to access AI features"
                    }
                )

            # Check user's token balance in Supabase
            token_balance = await self.get_user_token_balance(clerk_user_id)
            if "error" in token_balance:
                return JSONResponse(
                    status_code=500,
                    content={
                        "error": "Failed to retrieve token balance",
                        "message": "Please contact support if this persists"
                    }
                )

            if token_balance['tokens_remaining'] <= 0:
                return JSONResponse(
                    status_code=402,
                    content={
                        "error": "Insufficient tokens",
                        "message": (
                            "You have 0 tokens remaining. Please upgrade your plan "
                            "to continue using Tuner."
                        ),
                        "tokens_remaining": 0,
                        "token_allocation": token_balance['token_allocation']
                    }
                )

            self.logger.info(
                f"✅ Auth passed. User {clerk_user_id[:12]}... has {token_balance['tokens_remaining']} tokens remaining"
            )

            # Parse request body
            data = await request.json()
            agentId = data.get('agentId')
            content = data.get('content')
            attachments = data.get('attachments', [])
            projectId = data.get('projectId')
            # ADDED: conversation history
            conversation_history = data.get('conversationHistory', [])

            # Include attachments, api_key AND conversation_history in the data passed to streaming
            stream_data = {
                "agentId": agentId,
                "content": content,
                "attachments": attachments,
                "projectId": projectId,
                "clerk_user_id": clerk_user_id,
                "conversation_history": conversation_history,  # ADDED: pass conversation history
            }

            return StreamingResponse(
                self._stream_agent_response(stream_data, request),
                media_type="text/event-stream"
            )

        # API endpoint for agent messages (replacing WebSocket)

        @app.post("/api/agent/message")
        async def agent_message(request: Request):
            try:
                # Authenticate via Clerk JWT
                clerk_user_id = await self.verify_clerk_user(request)
                if not clerk_user_id:
                    return JSONResponse(
                        status_code=401,
                        content={
                            "error": "Not authenticated",
                            "message": "Please log in to access AI features"
                        }
                    )
                self.logger.info(
                    f"✅ Auth passed for user {clerk_user_id[:12]}...")

                # Parse request body
                data = await request.json()
                agent_id = data.get('agentId')
                content = data.get('content')
                if agent_id and content:
                    await save_message_to_db(clerk_user_id, agent_id, 'user', content)

                # Process with message handler
                result = await self.message_handler._handle_agent_message(data)

                if agent_id and "content" in result:
                    await save_message_to_db(clerk_user_id, agent_id, 'assistant', str(result['content']))

                return result
            except Exception as e:
                self.logger.error(f"Error handling agent message: {str(e)}")
                return JSONResponse(
                    status_code=500,
                    content={
                        "type": "ERROR",
                        "content": {
                            "message": str(e),
                            "timestamp": datetime.now().isoformat()
                        }
                    }
                )

        # Add to setup_fastapi method in compiler.py
        @app.post("/api/agent/multi-llm")
        async def agent_multi_llm(request: Request):
            try:
                # Authenticate via Clerk JWT
                clerk_user_id = await self.verify_clerk_user(request)
                if not clerk_user_id:
                    return JSONResponse(
                        status_code=401,
                        content={
                            "error": "Not authenticated",
                            "message": "Please log in to access AI features"
                        }
                    )
                self.logger.info(
                    f"✅ Auth passed. Identified user: {clerk_user_id[:12]}...")

                data = await request.json()
                content = data.get('content')
                user_id = clerk_user_id

                # Create orchestrator with API keys
                api_key = moonshot_api_key
                orchestrator = MultiLLMOrchestrator({
                    "planner": api_key,
                    "executor": api_key,
                    "summarizer": api_key
                },
                    clerk_user_id=clerk_user_id,
                    supabase_client=self.supabase,
                    logger=self.logger,
                    tools=None,
                    mcp_manager=None,
                    mcp_registry=None,
                    compiler_service=self  # NEW: Pass compiler reference
                )

                # Process the request through all agent models
                task_result = await orchestrator.start_task(content, user_id=user_id)

                # Format the response for the frontend
                response_thread = []

                # Add each agent's messages to the thread
                if task_result.get("summaries"):
                    initial_summary = next(
                        (s for s in task_result["summaries"] if s["type"] == "initial_summary"), None)
                    if initial_summary:
                        response_thread.append({
                            "role": "summarizer",
                            "content": initial_summary["content"]
                        })

                if task_result.get("plan"):
                    response_thread.append({
                        "role": "planner",
                        "content": task_result["plan"].get("plannerResponse", "Plan created successfully.")
                    })

                for execution in task_result.get("execution_results", []):
                    response_thread.append({
                        "role": "executor",
                        "content": execution.get("executionDetails", "Execution completed.")
                    })

                # Add progress summaries
                progress_summaries = [s for s in task_result.get("summaries", [])
                                      if s["type"] == "progress_summary"]
                for summary in progress_summaries:
                    response_thread.append({
                        "role": "summarizer",
                        "content": summary["content"]
                    })

                # Add final summary if available
                final_summary = next((s for s in task_result.get("summaries", [])
                                      if s["type"] == "final_summary"), None)
                if final_summary:
                    response_thread.append({
                        "role": "summarizer",
                        "content": final_summary["content"]
                    })

                return {
                    'type': 'AGENT_MULTI_LLM_RESPONSE',
                    'content': response_thread,
                    'timestamp': datetime.now().isoformat()
                }
            except Exception as e:
                self.logger.error(f"Error in multi-LLM processing: {str(e)}")
                import traceback
                traceback.print_exc()

                return JSONResponse(
                    status_code=500,
                    content={
                        "type": "ERROR",
                        "content": {
                            "message": str(e),
                            "timestamp": datetime.now().isoformat()
                        }
                    }
                )

        # MULTI-LLM STREAMING WITH CONVERSATION HISTORY
        @app.post("/api/agent/multi-llm/stream")
        async def agent_multi_llm_stream(request: Request):
            # Authenticate via Clerk JWT
            clerk_user_id = await self.verify_clerk_user(request)

            if not clerk_user_id:
                return JSONResponse(
                    status_code=401,
                    content={
                        "error": "Not authenticated",
                        "message": "Please log in to access AI features"
                    }
                )

            user_id = clerk_user_id
            self.logger.info(
                f"✅ Auth passed. Identified user: {clerk_user_id[:12]}...")

            # Check user's token balance in Supabase
            token_balance = await self.get_user_token_balance(clerk_user_id)
            if "error" in token_balance:
                return JSONResponse(
                    status_code=500,
                    content={
                        "error": "Failed to retrieve token balance",
                        "message": "Please contact support if this persists"
                    }
                )

            if token_balance['tokens_remaining'] <= 0:
                return JSONResponse(
                    status_code=402,
                    content={
                        "error": "Insufficient tokens",
                        "message": (
                            "You have 0 tokens remaining. Please upgrade your plan "
                            "to continue using Tuner."
                        ),
                        "tokens_remaining": 0,
                        "token_allocation": token_balance['token_allocation']
                    }
                )

            self.logger.info(
                f"✅ Token balance check passed. User has {token_balance['tokens_remaining']} tokens remaining"
            )

            data = await request.json()
            content = data.get('content')
            attachments = data.get('attachments', [])
            # ADDED: conversation history
            conversation_history = data.get('conversationHistory', [])
            agent_id = data.get('agentId')  # ADDED: agent ID for title event

            async def generate():
                try:
                    orchestrator = MultiLLMOrchestrator(
                        api_keys={
                            "planner": moonshot_api_key,
                            "executor": moonshot_api_key,
                            "summarizer": moonshot_api_key
                        },
                        clerk_user_id=clerk_user_id,
                        supabase_client=self.supabase,
                        logger=self.logger,
                        compiler_service=self
                    )

                    # Save the user's message, as the single-LLM route does
                    if agent_id and content:
                        await save_message_to_db(clerk_user_id, agent_id, 'user', content)

                    # Format content
                    full_content = content

                    if attachments:
                        full_content += "\n\n## Attached Files:\n"
                        for attachment in attachments:
                            try:
                                file_name = attachment.get('name', 'File')

                                # Handle base64 data attachments (from frontend)
                                if attachment.get('data'):
                                    try:
                                        import base64
                                        import tempfile
                                        from file_utilities import read_file_content

                                        # Extract base64 data (remove data:type;base64, prefix)
                                        data_url = attachment.get('data')
                                        if ',' in data_url:
                                            file_data = base64.b64decode(
                                                data_url.split(',')[1])
                                        else:
                                            file_data = base64.b64decode(
                                                data_url)

                                        # Get file extension from name
                                        file_extension = os.path.splitext(file_name)[
                                            1].lower()

                                        # Create temporary file with proper extension
                                        with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as temp_file:
                                            temp_file.write(file_data)
                                            temp_file_path = temp_file.name

                                        # Use file_utilities to read content properly
                                        file_content = read_file_content(
                                            temp_file_path, 5000)

                                        # Clean up temporary file
                                        os.unlink(temp_file_path)

                                    except Exception as decode_error:
                                        file_content = f"[Error processing file: {str(decode_error)}]"

                                # Handle path-based attachments (legacy)
                                elif attachment.get('path'):
                                    file_path = attachment.get('path')
                                    if file_path.startswith('/uploads/'):
                                        # Remove leading slash
                                        file_path = file_path[1:]

                                    if os.path.exists(file_path):
                                        from file_utilities import read_file_content
                                        file_content = read_file_content(
                                            file_path, 5000)
                                    else:
                                        file_content = f"[File not found: {file_path}]"
                                else:
                                    file_content = "[No file data available]"

                                full_content += f"\n### {file_name}:\n```\n{file_content}\n```\n"

                            except Exception as e:
                                full_content += (
                                    f"\n### Error processing {attachment.get('name', 'file')}: {str(e)}\n"
                                )

                    # Track token consumption (if you later add per-chunk usage)
                    total_tokens_consumed = 0

                    # Stream the results & respect Stop (disconnect) with conversation_history
                    async for agent_result in orchestrator.stream_task(
                        full_content,
                        conversation_history=conversation_history,  # ADDED: pass conversation history
                        user_id=user_id,  # ADDED: pass user ID
                        agent_id=agent_id  # ADDED: scope cross-agent search to exclude current agent
                    ):
                        # If frontend aborted (Stop), bail out
                        if await request.is_disconnected():
                            self.logger.info(
                                "Client disconnected; stopping multi-LLM stream.")
                            if hasattr(orchestrator, "cancel") and callable(getattr(orchestrator, "cancel")):
                                try:
                                    await orchestrator.cancel()
                                except Exception:
                                    pass
                            break

                        yield f"data: {json.dumps(agent_result)}\n\n"

                    # Save the final reply so the chat survives closing and reopening
                    final_text = getattr(orchestrator, "final_summary_text", "")
                    if agent_id and final_text:
                        await save_message_to_db(clerk_user_id, agent_id, 'assistant', final_text)
                    
                    # Final logging
                    if total_tokens_consumed > 0:
                        self.logger.info(
                            f"Ã¢Å“â€¦ Multi-LLM session complete. Total consumed: {total_tokens_consumed} tokens"
                        )
                    else:
                        # Fallback estimation if needed
                        estimated_tokens = len(full_content) // 4
                        if estimated_tokens > 0:
                            success = await self.update_token_consumption(clerk_user_id, estimated_tokens)
                            if success:
                                self.logger.info(
                                    f"Ã¢Å“â€¦ Multi-LLM estimated and consumed {estimated_tokens} tokens"
                                )

                    yield f"data: {json.dumps({'complete': True})}\n\n"
                except Exception as e:
                    self.logger.error(
                        f"Error in multi-llm streaming: {str(e)}")
                    yield f"data: {json.dumps({'error': str(e)})}\n\n"
                    yield f"data: {json.dumps({'complete': True})}\n\n"

            return StreamingResponse(generate(), media_type="text/event-stream")


        # Add this to the setup_fastapi method in compiler.py
        @app.post("/api/executor/task")
        async def execute_task(request: Request):
            """Endpoint for the executor agent to receive and process tasks"""
            try:
                # Parse request body
                data = await request.json()

                # Initialize executor handler if needed
                if not hasattr(self, 'executor_handler'):
                    from executor_handler import ExecutorHandler
                    self.executor_handler = ExecutorHandler(
                        model=self.model,
                        tools=None,
                        file_handler=self.message_handler.file_handler
                    )

                # Process the task
                result = await self.executor_handler.process_task(data)
                return result
            except Exception as e:
                self.logger.error(f"Error handling executor task: {str(e)}")
                import traceback
                traceback.print_exc()
                return JSONResponse(
                    status_code=500,
                    content={
                        "type": "ERROR",
                        "content": {
                            "message": str(e),
                            "timestamp": datetime.now().isoformat()
                        }
                    }
                )

        @app.post("/api/planner/task")
        async def plan_task(request: Request):
            """Endpoint for the planner agent to create task plans"""
            try:
                # Parse request body
                data = await request.json()

                # Get the user's request
                user_request = data.get("request", "")
                context = data.get("context", {})

                # Build system prompt for planner
                system_prompt = """You are the Planner agent in a multi-agent system. Your role is to:
    1. Analyze complex user requests
    2. Break them down into clear, sequential tasks
    3. Create structured plans that the Executor agent can follow
    4. Consider resource constraints and dependencies

    Provide a detailed plan with specific steps the Executor should take."""

                # Build the planner prompt
                planner_prompt = f"""USER REQUEST:
    {user_request}

    Your task is to analyze this request and create a detailed plan for the Executor agent to follow.
    Break down the task into clear steps, considering what tools might be needed at each stage.
    Explain your reasoning for each step and any potential challenges.

    Please provide a structured plan with numbered steps."""

                # Call the API
                plan = await self.model.generate(
                    prompt=planner_prompt,
                    system_prompt=system_prompt,
                    max_tokens=2048,
                    temperature=0.5
                )

                # Return the plan
                return {
                    "type": "PLANNER_RESPONSE",
                    "plan": plan,
                    "timestamp": datetime.now().isoformat()
                }
            except Exception as e:
                self.logger.error(f"Error creating plan: {str(e)}")
                return JSONResponse(
                    status_code=500,
                    content={
                        "type": "ERROR",
                        "content": {
                            "message": str(e),
                            "timestamp": datetime.now().isoformat()
                        }
                    }
                )

        @app.get("/api/download/powerpoint/{file_id}")
        async def download_powerpoint(file_id: str, request: Request):
            file_path = OUTPUTS_DIR / f"{file_id}.pptx"
            if not file_path.exists():
                return JSONResponse(status_code=404, content={"error": "File not found"})

            # Identify user (namespacing + auth if you want to enforce)
            user_id = _extract_user_id(request)
            prod_strict = os.getenv("FORCE_LOCAL_OUTPUTS",
                                    "false").lower() != "true"
            if prod_strict and not user_id:
                # If you prefer, you can allow anonymous downloads. This keeps it strict.
                raise HTTPException(
                    status_code=401, detail="Missing user identity")

            # Upload (or local fallback) and return a JSON payload with URL
            saved = self._upload_local_and_log(
                file_path, user_id=user_id, prefix="powerpoints")
            payload = {
                "success": True,
                "storageMode": "supabase" if ("signed_url" in saved or "public_url" in saved) else "local_fallback",
                "filename": saved.get("filename", file_path.name),
                **saved,
            }
            return JSONResponse(payload)

        @app.post("/api/artifacts/download/{artifact_id}")
        async def download_artifact(artifact_id: str, request: Request):
            try:
                data = await request.json()
                artifact = data.get("artifact")
                if not artifact:
                    return JSONResponse(status_code=404, content={"error": "Artifact not found"})

                ext_map = {"code": artifact.get(
                    "language", "txt"), "markdown": "md", "presentation": "pptx"}
                ext = ext_map.get(artifact["type"], "txt")
                base_name = f"{artifact['title'].replace(' ', '_')}.{ext}"

                if artifact["type"] == "presentation":
                    file_bytes = self._generate_pptx(artifact)
                else:
                    file_bytes = artifact["content"].encode("utf-8")

                # identify user so we can store under user-outputs/{user_id}/...
                user_id = _extract_user_id(request)

                # In prod, require identity (unless you're intentionally allowing local fallback)
                prod_strict = os.getenv(
                    "FORCE_LOCAL_OUTPUTS", "false").lower() != "true"
                if prod_strict and not user_id:
                    raise HTTPException(
                        status_code=401, detail="Missing user identity")

                saved = self.storage.save_bytes(
                    file_bytes,
                    ext=f".{ext}",
                    filename=base_name,
                    user_id=user_id or "anonymous",           # namespaced even in dev
                    # used only if FORCE_LOCAL_OUTPUTS=true
                    local_dir=str(OUTPUTS_DIR)
                )

                storage_mode = "supabase" if "signed_url" in saved else "local_fallback"
                payload = {"success": True, "storageMode": storage_mode,
                           "filename": saved["filename"], **saved}
                return JSONResponse(payload)

            except Exception as e:
                self.logger.error(f"Error downloading artifact: {e}")
                return JSONResponse(
                    status_code=500,
                    content={"error": str(e)}
                )

        # ============================================================
        # CLERK WEBHOOK - Handle user signups (creates FREE TRIAL users)
        # ============================================================
        @app.post("/api/webhooks/clerk")
        async def clerk_webhook(request: Request):
            """Handle Clerk webhook events for user creation"""
            try:
                webhook_secret = os.getenv('CLERK_WEBHOOK_SECRET')
                if not webhook_secret:
                    self.logger.error("CLERK_WEBHOOK_SECRET not configured")
                    return JSONResponse(status_code=500, content={"error": "Webhook not configured"})

                svix_id = request.headers.get("svix-id")
                svix_timestamp = request.headers.get("svix-timestamp")
                svix_signature = request.headers.get("svix-signature")

                if not all([svix_id, svix_timestamp, svix_signature]):
                    return JSONResponse(status_code=400, content={"error": "Missing svix headers"})

                body = await request.body()

                try:
                    wh = Webhook(webhook_secret)
                    payload = wh.verify(body, {
                        "svix-id": svix_id,
                        "svix-timestamp": svix_timestamp,
                        "svix-signature": svix_signature
                    })
                except Exception as e:
                    self.logger.error(f"Webhook verification failed: {e}")
                    return JSONResponse(status_code=400, content={"error": "Invalid signature"})

                if payload.get("type") == "user.created":
                    user_data = payload.get("data", {})
                    clerk_user_id = user_data.get("id")
                    email_addresses = user_data.get("email_addresses", [])
                    email = email_addresses[0].get(
                        "email_address") if email_addresses else None

                    if not clerk_user_id or not email:
                        self.logger.error(
                            f"Missing user data in webhook: {user_data}")
                        return JSONResponse(status_code=400, content={"error": "Invalid user data"})

                    supabase_url = os.getenv('SUPABASE_URL')
                    supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')

                    if not supabase_url or not supabase_key:
                        self.logger.error(
                            "Supabase credentials not configured")
                        return JSONResponse(status_code=500, content={"error": "Database not configured"})

                    async with httpx.AsyncClient() as client:
                        check_response = await client.get(
                            f"{supabase_url}/rest/v1/users?email=eq.{quote(email)}",
                            headers={
                                "apikey": supabase_key,
                                "Authorization": f"Bearer {supabase_key}",
                            }
                        )

                        existing_users = check_response.json() if check_response.status_code == 200 else []

                        if existing_users and len(existing_users) > 0:
                            # User exists (paid before signing up) - UPDATE with clerk_user_id
                            user = existing_users[0]
                            user_id = user['id']

                            update_response = await client.patch(
                                f"{supabase_url}/rest/v1/users?id=eq.{user_id}",
                                headers={
                                    "apikey": supabase_key,
                                    "Authorization": f"Bearer {supabase_key}",
                                    "Content-Type": "application/json",
                                    "Prefer": "return=minimal"
                                },
                                json={"clerk_user_id": clerk_user_id}
                            )

                            if update_response.status_code not in [200, 204]:
                                self.logger.error(
                                    f"Failed to update user: {update_response.text}")
                                return JSONResponse(status_code=500, content={"error": "Database update failed"})

                            self.logger.info(
                                f"Updated existing user {email} with clerk_user_id {clerk_user_id}")
                        else:
                            # User doesn't exist - CREATE FREE TRIAL user
                            # Identity is clerk_user_id; no third-party key management needed

                            create_response = await client.post(
                                f"{supabase_url}/rest/v1/users",
                                headers={
                                    "apikey": supabase_key,
                                    "Authorization": f"Bearer {supabase_key}",
                                    "Content-Type": "application/json",
                                    "Prefer": "return=minimal"
                                },
                                json={
                                    "clerk_user_id": clerk_user_id,
                                    "email": email,
                                    "subscription_plan": "free_trial",
                                    "token_allocation": 150000,
                                    "tokens_remaining": 150000,
                                    "unkey_api_key": None
                                }
                            )

                            if create_response.status_code not in [200, 201]:
                                self.logger.error(
                                    f"Failed to create user: {create_response.text}")
                                return JSONResponse(status_code=500, content={"error": "Database insert failed"})

                            self.logger.info(
                                f"Created FREE TRIAL user {email} with 150,000 tokens")

                    return JSONResponse(status_code=200, content={"success": True})

                return JSONResponse(status_code=200, content={"success": True})

            except Exception as e:
                self.logger.error(f"Clerk webhook error: {e}")
                import traceback
                traceback.print_exc()
                return JSONResponse(status_code=500, content={"error": str(e)})

        # ============================================================
        # STRIPE WEBHOOK - Handle payments (upgrades users to paid tiers)
        # ============================================================
        @app.post("/api/webhooks/stripe")
        async def stripe_webhook(request: Request):
            """Handle Stripe webhook events for payment processing"""
            try:
                stripe.api_key = os.getenv('STRIPE_SECRET_KEY')
                webhook_secret = os.getenv('STRIPE_WEBHOOK_SECRET')

                if not webhook_secret:
                    self.logger.error("STRIPE_WEBHOOK_SECRET not configured")
                    return JSONResponse(status_code=500, content={"error": "Webhook not configured"})

                payload = await request.body()
                sig_header = request.headers.get('stripe-signature')

                if not sig_header:
                    return JSONResponse(status_code=400, content={"error": "Missing stripe-signature header"})

                try:
                    event = stripe.Webhook.construct_event(
                        payload, sig_header, webhook_secret)
                except ValueError as e:
                    self.logger.error(f"Invalid Stripe payload: {e}")
                    return JSONResponse(status_code=400, content={"error": "Invalid payload"})
                except stripe.error.SignatureVerificationError as e:
                    self.logger.error(f"Invalid Stripe signature: {e}")
                    return JSONResponse(status_code=400, content={"error": "Invalid signature"})

                if event['type'] == 'checkout.session.completed':
                    session = event['data']['object']
                    customer_email = session.get('customer_email') or session.get(
                        'customer_details', {}).get('email')
                    # ✅ NEW: save for renewals/cancellations
                    stripe_customer_id = session.get('customer')

                    try:
                        line_items = stripe.checkout.Session.list_line_items(
                            session['id'], limit=1)
                        price_id = line_items.data[0].price.id if line_items.data else None
                    except Exception as e:
                        self.logger.error(f"Failed to get line items: {e}")
                        price_id = None

                    if not customer_email:
                        self.logger.error(
                            f"No customer email in Stripe session: {session}")
                        return JSONResponse(status_code=400, content={"error": "No customer email"})

                    # Price ID to subscription plan mapping
                    # ✅ Updated: 3 tiers (Starter/Professional/Business), V3 token allocations
                    price_mapping = {
                        'price_1T53NbPHC9KkR2hgUrWEP2gf': {'plan': 'starter',      'tokens': 750000},
                        'price_1T53ODPHC9KkR2hgu65XaR9F': {'plan': 'professional', 'tokens': 3000000},
                        'price_1T53OrPHC9KkR2hgJ8lY58xa': {'plan': 'business',     'tokens': 10000000},
                    }

                    subscription_info = price_mapping.get(
                        price_id, {'plan': 'starter', 'tokens': 500000})
                    subscription_plan = subscription_info['plan']
                    token_allocation = subscription_info['tokens']

                    self.logger.info(
                        f"Processing payment for {customer_email}: {subscription_plan} with {token_allocation} tokens")

                    # Identity handled via clerk_user_id; no Unkey key generation needed
                    unkey_api_key = None
                    self.logger.info(
                        f"Processing payment for {customer_email}: {subscription_plan} with {token_allocation} tokens")

                    supabase_url = os.getenv('SUPABASE_URL')
                    supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')

                    if not supabase_url or not supabase_key:
                        self.logger.error(
                            "Supabase credentials not configured")
                        return JSONResponse(status_code=500, content={"error": "Database not configured"})

                    async with httpx.AsyncClient() as client:
                        response = await client.get(
                            f"{supabase_url}/rest/v1/users?email=eq.{quote(customer_email)}",
                            headers={
                                "apikey": supabase_key,
                                "Authorization": f"Bearer {supabase_key}",
                            }
                        )

                        existing_users = response.json() if response.status_code == 200 else []

                        if existing_users and len(existing_users) > 0:
                            user = existing_users[0]
                            user_id = user['id']

                            update_response = await client.patch(
                                f"{supabase_url}/rest/v1/users?id=eq.{user_id}",
                                headers={
                                    "apikey": supabase_key,
                                    "Authorization": f"Bearer {supabase_key}",
                                    "Content-Type": "application/json",
                                    "Prefer": "return=minimal"
                                },
                                json={
                                    "subscription_plan": subscription_plan,
                                    "token_allocation": token_allocation,
                                    "tokens_remaining": token_allocation,
                                    "unkey_api_key": unkey_api_key,
                                    "stripe_customer_id": stripe_customer_id  # ✅ NEW
                                }
                            )

                            if update_response.status_code not in [200, 204]:
                                self.logger.error(
                                    f"Failed to update user: {update_response.text}")
                                return JSONResponse(status_code=500, content={"error": "Database update failed"})

                            self.logger.info(
                                f"Updated user {customer_email} to {subscription_plan} with {token_allocation} tokens")
                        else:
                            create_response = await client.post(
                                f"{supabase_url}/rest/v1/users",
                                headers={
                                    "apikey": supabase_key,
                                    "Authorization": f"Bearer {supabase_key}",
                                    "Content-Type": "application/json",
                                    "Prefer": "return=minimal"
                                },
                                json={
                                    "clerk_user_id": None,
                                    "email": customer_email,
                                    "subscription_plan": subscription_plan,
                                    "token_allocation": token_allocation,
                                    "tokens_remaining": token_allocation,
                                    "unkey_api_key": unkey_api_key,
                                    "stripe_customer_id": stripe_customer_id  # ✅ add this
                                }
                            )

                            if create_response.status_code not in [200, 201]:
                                self.logger.error(
                                    f"Failed to create user: {create_response.text}")
                                return JSONResponse(status_code=500, content={"error": "Database insert failed"})

                            self.logger.info(
                                f"Created pending user {customer_email} with {subscription_plan} plan")

                    return JSONResponse(status_code=200, content={"success": True})

                # ============================================================
                # MONTHLY RENEWAL - Reset tokens to full allocation
                # ============================================================
                elif event['type'] == 'invoice.payment_succeeded':
                    invoice = event['data']['object']

                    # Only act on subscription renewals, not the first payment
                    if invoice.get('billing_reason') != 'subscription_cycle':
                        return JSONResponse(status_code=200, content={"success": True})

                    stripe_customer_id = invoice.get('customer')
                    if not stripe_customer_id:
                        self.logger.error(
                            "invoice.payment_succeeded: no customer ID in event")
                        return JSONResponse(status_code=400, content={"error": "No customer ID"})

                    supabase_url = os.getenv('SUPABASE_URL')
                    supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')

                    async with httpx.AsyncClient() as client:
                        lookup = await client.get(
                            f"{supabase_url}/rest/v1/users?stripe_customer_id=eq.{stripe_customer_id}",
                            headers={"apikey": supabase_key,
                                     "Authorization": f"Bearer {supabase_key}"}
                        )
                        users = lookup.json() if lookup.status_code == 200 else []
                        if not users:
                            self.logger.error(
                                f"invoice.payment_succeeded: no user found for customer {stripe_customer_id}")
                            return JSONResponse(status_code=404, content={"error": "User not found"})

                        user = users[0]
                        reset = await client.patch(
                            f"{supabase_url}/rest/v1/users?id=eq.{user['id']}",
                            headers={
                                "apikey": supabase_key,
                                "Authorization": f"Bearer {supabase_key}",
                                "Content-Type": "application/json",
                                "Prefer": "return=minimal"
                            },
                            json={"tokens_remaining": user['token_allocation']}
                        )
                        if reset.status_code not in [200, 204]:
                            self.logger.error(
                                f"Failed to reset tokens for {user['email']}: {reset.text}")
                            return JSONResponse(status_code=500, content={"error": "Token reset failed"})

                        self.logger.info(
                            f"Monthly renewal: reset {user['email']} to {user['token_allocation']} tokens")
                    return JSONResponse(status_code=200, content={"success": True})

                # ============================================================
                # PLAN CHANGE - Upgrade or downgrade subscription
                # ============================================================
                elif event['type'] == 'customer.subscription.updated':
                    subscription = event['data']['object']
                    stripe_customer_id = subscription.get('customer')

                    items = subscription.get('items', {}).get('data', [])
                    new_price_id = items[0]['price']['id'] if items else None

                    if not stripe_customer_id or not new_price_id:
                        self.logger.error(
                            "subscription.updated: missing customer or price ID")
                        return JSONResponse(status_code=400, content={"error": "Missing data"})

                    plan_lookup = {
                        'price_1T53NbPHC9KkR2hgUrWEP2gf': {'plan': 'starter',      'tokens': 750000},
                        'price_1T53ODPHC9KkR2hgu65XaR9F': {'plan': 'professional', 'tokens': 3000000},
                        'price_1T53OrPHC9KkR2hgJ8lY58xa': {'plan': 'business',     'tokens': 10000000},
                    }
                    new_plan_info = plan_lookup.get(new_price_id)
                    if not new_plan_info:
                        self.logger.error(
                            f"subscription.updated: unrecognised price ID {new_price_id}")
                        return JSONResponse(status_code=200, content={"success": True})

                    new_plan = new_plan_info['plan']
                    new_allocation = new_plan_info['tokens']

                    supabase_url = os.getenv('SUPABASE_URL')
                    supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')

                    async with httpx.AsyncClient() as client:
                        lookup = await client.get(
                            f"{supabase_url}/rest/v1/users?stripe_customer_id=eq.{stripe_customer_id}",
                            headers={"apikey": supabase_key,
                                     "Authorization": f"Bearer {supabase_key}"}
                        )
                        users = lookup.json() if lookup.status_code == 200 else []
                        if not users:
                            self.logger.error(
                                f"subscription.updated: no user found for customer {stripe_customer_id}")
                            return JSONResponse(status_code=404, content={"error": "User not found"})

                        user = users[0]
                        current_remaining = user.get('tokens_remaining', 0)

                        # Carryover: upgrade gets full new allocation, downgrade keeps current capped at new
                        new_remaining = max(current_remaining, new_allocation) if new_allocation > user.get('token_allocation', 0) \
                            else min(current_remaining, new_allocation)

                        update = await client.patch(
                            f"{supabase_url}/rest/v1/users?id=eq.{user['id']}",
                            headers={
                                "apikey": supabase_key,
                                "Authorization": f"Bearer {supabase_key}",
                                "Content-Type": "application/json",
                                "Prefer": "return=minimal"
                            },
                            json={
                                "subscription_plan": new_plan,
                                "token_allocation": new_allocation,
                                "tokens_remaining": new_remaining
                            }
                        )
                        if update.status_code not in [200, 204]:
                            self.logger.error(
                                f"Failed to update plan for {user['email']}: {update.text}")
                            return JSONResponse(status_code=500, content={"error": "Plan update failed"})

                        self.logger.info(
                            f"Plan change: {user['email']} → {new_plan} "
                            f"({current_remaining} → {new_remaining} tokens remaining)"
                        )
                    return JSONResponse(status_code=200, content={"success": True})

                # ============================================================
                # CANCELLATION - Downgrade to free trial, zero out tokens
                # ============================================================
                elif event['type'] == 'customer.subscription.deleted':
                    subscription = event['data']['object']
                    stripe_customer_id = subscription.get('customer')

                    if not stripe_customer_id:
                        self.logger.error(
                            "subscription.deleted: no customer ID in event")
                        return JSONResponse(status_code=400, content={"error": "No customer ID"})

                    supabase_url = os.getenv('SUPABASE_URL')
                    supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')

                    async with httpx.AsyncClient() as client:
                        lookup = await client.get(
                            f"{supabase_url}/rest/v1/users?stripe_customer_id=eq.{stripe_customer_id}",
                            headers={"apikey": supabase_key,
                                     "Authorization": f"Bearer {supabase_key}"}
                        )
                        users = lookup.json() if lookup.status_code == 200 else []
                        if not users:
                            self.logger.error(
                                f"subscription.deleted: no user found for customer {stripe_customer_id}")
                            return JSONResponse(status_code=404, content={"error": "User not found"})

                        user = users[0]
                        downgrade = await client.patch(
                            f"{supabase_url}/rest/v1/users?id=eq.{user['id']}",
                            headers={
                                "apikey": supabase_key,
                                "Authorization": f"Bearer {supabase_key}",
                                "Content-Type": "application/json",
                                "Prefer": "return=minimal"
                            },
                            json={
                                "subscription_plan": "free_trial",
                                "token_allocation": 0,
                                "tokens_remaining": 0
                            }
                        )
                        if downgrade.status_code not in [200, 204]:
                            self.logger.error(
                                f"Failed to downgrade {user['email']}: {downgrade.text}")
                            return JSONResponse(status_code=500, content={"error": "Downgrade failed"})

                        self.logger.info(
                            f"Cancellation processed: {user['email']} downgraded to free_trial")
                    return JSONResponse(status_code=200, content={"success": True})

                # All other Stripe events - acknowledge and ignore
                return JSONResponse(status_code=200, content={"success": True})

            except Exception as e:
                self.logger.error(f"Stripe webhook error: {e}")
                import traceback
                traceback.print_exc()
                return JSONResponse(status_code=500, content={"error": str(e)})

        # ============================================================
        # STRIPE CUSTOMER PORTAL - Let users manage their subscription
        # ============================================================
        @app.post("/api/billing/portal")
        async def billing_portal(request: Request):
            """
            Generate a Stripe Customer Portal session URL.
            Frontend calls this, then redirects the user to the returned URL.
            """
            try:
                stripe.api_key = os.getenv('STRIPE_SECRET_KEY')

                user_id = _extract_user_id(request)
                if not user_id:
                    return JSONResponse(status_code=401, content={"error": "Not authenticated"})

                if not self.supabase:
                    return JSONResponse(status_code=500, content={"error": "Database not configured"})

                result = self.supabase.table("users").select("stripe_customer_id, email") \
                    .eq("clerk_user_id", user_id).execute()

                if not result.data:
                    return JSONResponse(status_code=404, content={"error": "User not found"})

                stripe_customer_id = result.data[0].get("stripe_customer_id")
                if not stripe_customer_id:
                    return JSONResponse(
                        status_code=404,
                        content={
                            "error": "No valid subscription found. Please subscribe first."}
                    )

                portal_session = stripe.billing_portal.Session.create(
                    customer=stripe_customer_id,
                    return_url="https://boundary.xuanwo.ai",
                )

                self.logger.info(
                    f"Portal session created for user {result.data[0].get('email')}")
                return JSONResponse(status_code=200, content={"url": portal_session.url})

            except stripe.error.StripeError as e:
                self.logger.error(f"Stripe portal error: {e}")
                return JSONResponse(status_code=500, content={"error": str(e)})
            except Exception as e:
                self.logger.error(f"Billing portal error: {e}")
                return JSONResponse(status_code=500, content={"error": str(e)})

        return app

    def _load_agent_history(self, clerk_user_id: str, agent_id: str, limit: int = 20) -> List[Dict[str, str]]:
        """The agent's recent saved messages, oldest first, for a woken run's context."""
        try:
            if not self.supabase:
                import message
                rows = message._local_load(agent_id)[-limit:]
                return [{"role": r["role"], "content": r["content"]} for r in rows
                        if r.get("role") in ("user", "assistant") and r.get("content")]
            res = (
                self.supabase.table("messages")
                .select("role, content, timestamp")
                .eq("user_id", clerk_user_id)
                .eq("agent_id", agent_id)
                .order("timestamp", desc=True)
                .limit(limit)
                .execute()
            )
            rows = list(reversed(res.data or []))
            return [{"role": r["role"], "content": r["content"]}
                    for r in rows if r.get("role") in ("user", "assistant") and r.get("content")]
        except Exception as e:
            self.logger.warning(f"[Wake] Could not load agent history: {e}")
            return []

    async def _run_woken_agent(self, clerk_user_id: str, agent_id: str, wake_message: str):
        """Run the multi-agent loop for a scheduled wake-up, with no browser attached,
        saving the wake message and the final reply to the agent's chat."""
        try:
            history = self._load_agent_history(clerk_user_id, agent_id)
            await save_message_to_db(clerk_user_id, agent_id, 'user', wake_message)

            orchestrator = MultiLLMOrchestrator(
                api_keys={
                    "planner": moonshot_api_key,
                    "executor": moonshot_api_key,
                    "summarizer": moonshot_api_key
                },
                clerk_user_id=clerk_user_id,
                supabase_client=self.supabase,
                logger=self.logger,
                compiler_service=self
            )
            orchestrator.stream_delay = 0  # nobody is watching the stream

            async for _event in orchestrator.stream_task(
                wake_message,
                conversation_history=history,
                user_id=clerk_user_id,
                agent_id=agent_id
            ):
                pass

            reply = (getattr(orchestrator, "final_summary_text", "")
                    or "(The woken agent finished without a final summary.)")
            await save_message_to_db(clerk_user_id, agent_id, 'assistant', reply)
            self.logger.info(f"⏰ Woken run finished for agent {agent_id[:8]}...")

        except Exception as e:
            self.logger.error(f"⏰ Woken run failed for agent {agent_id[:8]}...: {e}", exc_info=True)
            try:
                await save_message_to_db(clerk_user_id, agent_id, 'assistant',
                                        f"The scheduled wake-up ran but failed: {e}")
            except Exception:
                pass

    def _generate_pptx(self, artifact):
        """Generate a PowerPoint file from presentation artifact data"""
        try:
            from pptx import Presentation
            from pptx.util import Inches, Pt

            prs = Presentation()

            # Add title slide
            title_slide_layout = prs.slide_layouts[0]
            slide = prs.slides.add_slide(title_slide_layout)
            title = slide.shapes.title
            subtitle = slide.placeholders[1]

            title.text = artifact['title']
            subtitle.text = f"Generated on {datetime.now().strftime('%Y-%m-%d')}"

            # Add content slides
            for slide_data in artifact.get('slides', []):
                bullet_slide_layout = prs.slide_layouts[1]
                slide = prs.slides.add_slide(bullet_slide_layout)

                # Extract slide title and content
                slide_content = slide_data['content']
                lines = slide_content.split('\n')

                # Set slide title
                if lines and lines[0].startswith(('Slide', '##')):
                    slide.shapes.title.text = lines[0].replace(
                        '##', '').replace('Slide', 'Slide').strip()
                    content_lines = lines[1:]
                else:
                    slide.shapes.title.text = f"Slide {slide_data['number']}"
                    content_lines = lines

                # Add content to text frame
                tf = slide.placeholders[1].text_frame
                tf.clear()

                for line in content_lines:
                    if line.strip():
                        p = tf.add_paragraph()
                        p.text = line.strip()
                        p.level = 0 if not line.startswith((' ', '\t')) else 1

            # Save to bytes
            from io import BytesIO
            pptx_bytes = BytesIO()
            prs.save(pptx_bytes)
            pptx_bytes.seek(0)

            return pptx_bytes.read()
        except ImportError:
            # If python-pptx not installed, return a simple text file
            content = f"# {artifact['title']}\n\n"
            for slide in artifact.get('slides', []):
                content += f"{slide['content']}\n\n"
            return content.encode('utf-8')

    def _load_model(self):
        try:
            # Still using same class name for compatibility
            from api_client import ClaudeAPIClient

            # Get API key from environment or configuration
            api_key = os.environ.get("MOONSHOT_API_KEY")
            if not api_key:
                self.logger.warning(
                    "MOONSHOT_API_KEY not found in environment variables")

            # Initialize API client with explicit API key
            model = ClaudeAPIClient(api_key=api_key)

            # Use None for tokenizer as we don't need it with API
            tokenizer = None

            self.logger.info("Moonshot API client initialized successfully")
            return model, tokenizer

        except ImportError as e:
            self.logger.error(f"Failed to import required modules: {str(e)}")
            self.logger.error(
                "Please install required packages: pip install aiohttp")
            raise RuntimeError(
                f"Missing dependencies for Moonshot API: {str(e)}")
        except Exception as e:
            self.logger.error(
                f"Error initializing Moonshot API client: {str(e)}")
            raise RuntimeError(
                f"Error initializing Moonshot API client: {str(e)}")

    def _get_model_path(self) -> str:
        if getattr(sys, 'frozen', False):
            base_path = Path(sys._MEIPASS)
        else:
            base_path = Path(__file__).resolve().parent.parent
        return str(base_path / "llm")

    async def _stream_agent_response(self, data, request: Request):
        """
        Stream a single-agent response WITH CONVERSATION HISTORY,
        with proper cancellation when the client disconnects (Stop button).
        Backend automatically optimizes history - frontend doesn't need to change!
        """
        print(f"=== STREAM AGENT RESPONSE START ===")
        print(f"Data received: {data}")
        print(f"Project ID: {data.get('projectId')}")
        print(f"Content: {data.get('content')}")
        agent_id = data.get('agentId')
        content = data.get('content')
        attachments = data.get('attachments', [])
        conversation_history = data.get('conversation_history', [])
        clerk_user_id = data.get('clerk_user_id')

        # ADDED: Automatically optimize conversation history (NO FRONTEND CHANGES NEEDED!)
        if conversation_history:
            original_length = len(conversation_history)
            conversation_history = self.message_handler._optimize_conversation_history(
                conversation_history)

            if len(conversation_history) < original_length:
                self.logger.info(
                    f"[Compiler] Ã°Å¸â€™Â¡ Auto-optimized: {original_length} Ã¢â€ â€™ {len(conversation_history)} messages"
                )

        api_key = data.get('api_key')

        if clerk_user_id and agent_id and content:
            await save_message_to_db(clerk_user_id, agent_id, 'user', content)

        # Format the user message with attachments
        user_message = f"User Question: {content}\n\n"

        # Process attached files - handle both path-based and data-based attachments
        if attachments:
            user_message += "## Files Directly Attached to This Message:\n\n"

            for idx, attachment in enumerate(attachments):
                try:
                    file_name = attachment.get('name', 'unnamed_file')
                    file_extension = os.path.splitext(file_name)[1].lower()

                    # Handle base64 data attachments (from frontend)
                    if attachment.get('data'):
                        try:
                            import base64
                            import tempfile
                            from file_utilities import read_file_content

                            # Extract base64 data (remove data:type;base64, prefix)
                            data_url = attachment.get('data')
                            if ',' in data_url:
                                file_data = base64.b64decode(
                                    data_url.split(',')[1])
                            else:
                                file_data = base64.b64decode(data_url)

                            # Create temporary file with proper extension
                            with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as temp_file:
                                temp_file.write(file_data)
                                temp_file_path = temp_file.name

                            # Use file_utilities to read content properly
                            file_content = read_file_content(
                                temp_file_path, 5000)

                            # Clean up temporary file
                            os.unlink(temp_file_path)

                        except Exception as decode_error:
                            file_content = f"[Error processing file: {str(decode_error)}]"

                    # Handle path-based attachments (legacy)
                    elif attachment.get('path'):
                        file_path = attachment.get('path')
                        if file_path.startswith('/uploads/'):
                            file_path = file_path[1:]  # Remove leading slash

                        if os.path.exists(file_path):
                            from file_utilities import read_file_content
                            file_content = read_file_content(file_path, 5000)
                        else:
                            file_content = f"[File not found: {file_path}]"
                    else:
                        file_content = "[No file data available]"

                    # Format file content based on type
                    user_message += f"### File {idx+1}: {file_name}\n"
                    if file_extension in ['.py', '.js', '.ts', '.jsx', '.tsx', '.html', '.css']:
                        user_message += f"```{file_extension[1:]}\n{file_content}\n```\n\n"
                    elif file_extension in ['.json', '.xml']:
                        user_message += f"```{file_extension[1:]}\n{file_content}\n```\n\n"
                    elif file_extension in ['.csv', '.tsv']:
                        user_message += f"CSV data:\n```\n{file_content}\n```\n\n"
                    else:
                        user_message += f"Content:\n{file_content}\n\n"

                except Exception as e:
                    user_message += f"### Error processing file {attachment.get('name', 'unknown')}: {str(e)}\n\n"

        # Add user message to history
        system_prompt = (
            "You are an AI assistant in OpexAssistant. Your purpose is to analyze files and answer questions. "
            "When looking at code or data files, be thorough and precise. "
            "If files are attached, focus on analyzing their content to provide detailed insights. "
            "Format your responses with clear markdown structure including paragraphs, headers, and code blocks as appropriate."
            + SINGLE_LLM_ENHANCED_PROMPT
        )

        try:
            # Start the LLM generation as a background task with conversation history
            gen_task = asyncio.create_task(
                self.model.generate(
                    prompt=user_message,
                    max_tokens=1024,
                    temperature=0.7,
                    system_prompt=system_prompt,
                    conversation_history=conversation_history  # ADDED: pass conversation history
                )
            )

            # Wait for either the model to finish OR the client to disconnect
            response = None
            while True:
                if gen_task.done():
                    if gen_task.cancelled():
                        raise asyncio.CancelledError()
                    response = gen_task.result()
                    break

                # Check if client is gone (Stop button)
                if await request.is_disconnected():
                    self.logger.info(
                        f"Client disconnected / Stop pressed for agent {agent_id}, cancelling generation task."
                    )
                    gen_task.cancel()
                    raise asyncio.CancelledError()

                await asyncio.sleep(0.1)

            # Token tracking
            if isinstance(response, dict) and 'usage' in response:
                tokens_consumed = response.get(
                    'usage', {}).get('total_tokens', 0)
            elif isinstance(response, dict) and 'total_tokens' in response:
                tokens_consumed = response.get('total_tokens', 0)
            else:
                tokens_consumed = len(
                    str(response)) // 4 if isinstance(response, str) else 0

            if api_key and tokens_consumed > 0:
                success = await self.update_token_consumption(api_key, tokens_consumed)
                if success:
                    self.logger.info(
                        f"✓ Consumed {tokens_consumed} tokens, updated user balance")
                else:
                    self.logger.warning(
                        f"✗ Failed to update token consumption for {tokens_consumed} tokens"
                    )

            # Extract plain text from dict responses
            if isinstance(response, dict):
                response_text = response.get(
                    'content', response.get('text', str(response)))
            else:
                response_text = response

            # Analyze response for artifacts
            artifact_result = self.message_handler._analyze_for_artifacts(
                response_text)
            modified_response = artifact_result['content']
            artifacts = artifact_result.get('artifacts', [])

            # If we have artifacts, send metadata first
            if artifacts:
                yield f"data: {json.dumps({'type': 'artifacts', 'artifacts': artifacts, 'agentId': agent_id})}\n\n"

            # Stream the modified response with artifact markers
            chunk_size = 30
            for i in range(0, len(modified_response), chunk_size):
                # If user hits stop mid-stream, also stop quickly
                if await request.is_disconnected():
                    self.logger.info(
                        f"Client disconnected while streaming chunks for agent {agent_id}; stopping stream."
                    )
                    raise asyncio.CancelledError()

                chunk = modified_response[i:i+chunk_size]
                yield f"data: {json.dumps({'token': chunk, 'agentId': agent_id})}\n\n"
                await asyncio.sleep(0.03)

            yield f"data: {json.dumps({'complete': True, 'agentId': agent_id})}\n\n"

            if clerk_user_id and agent_id and modified_response:
                await save_message_to_db(clerk_user_id, agent_id, 'assistant', modified_response)

        except asyncio.CancelledError:
            # Frontend aborted the request (Stop button)
            self.logger.info(
                f"Streaming cancelled by client for agent {agent_id}.")
            try:
                yield f"data: {json.dumps({'cancelled': True, 'agentId': agent_id})}\n\n"
            except Exception:
                pass

        except Exception as e:
            self.logger.error(f"Streaming error: {str(e)}")
            import traceback
            traceback.print_exc()

            yield f"data: {json.dumps({'token': f'Error generating response: {str(e)}', 'agentId': agent_id})}\n\n"
            yield f"data: {json.dumps({'complete': True, 'agentId': agent_id})}\n\n"

        except asyncio.CancelledError:
            # Frontend aborted the request (Stop button)
            self.logger.info(
                f"Streaming cancelled by client for agent {agent_id}.")
            try:
                yield f"data: {json.dumps({'cancelled': True, 'agentId': agent_id})}\n\n"
            except Exception:
                pass

        except Exception as e:
            self.logger.error(f"Streaming error: {str(e)}")
            import traceback
            traceback.print_exc()

            yield f"data: {json.dumps({'token': f'Error generating response: {str(e)}', 'agentId': agent_id})}\n\n"
            yield f"data: {json.dumps({'complete': True, 'agentId': agent_id})}\n\n"

    async def start(self):
        """Start the FastAPI HTTP server only (no WebSockets)"""
        # Get HTTP port from environment
        env_port = os.environ.get('HTTP_PORT')
        if env_port:
            self.http_port = int(env_port)

        # Setup FastAPI
        app = self.setup_fastapi()

        self.logger.info(
            f"Starting HTTP server on {self.host}:{self.http_port}")

        # Create Uvicorn config and server instance
        config = uvicorn.Config(app, host=self.host, port=self.http_port)
        server = uvicorn.Server(config)

        # Run the HTTP server
        await server.serve()


async def main():
    host = os.environ.get('HOST', '0.0.0.0')
    compiler = Compiler(host=host)
    await compiler.start()

if __name__ == "__main__":
    asyncio.run(main())
