"""
Bridge Query - Simple HTTP Client for Local Machine Commands
===========================================================

Sends commands to server, waits for bridge client to execute, returns results.
Works exactly like WebSearchExecutor: make request, poll for results, return.

Author: Adriel
Date: February 17, 2026
"""

import logging
import asyncio
import uuid
from typing import Dict, Any
from datetime import datetime
import aiohttp


class BridgeQuery:
    """
    Simple HTTP client for bridge commands.
    
    Usage:
    ```python
    query = BridgeQuery(
        api_key=task_data.get("apiKey"),
        server_url="https://boundary.onrender.com"
    )
    
    # Execute bash command
    result = await query.execute_bash("whoami")
    print(result["output"])  # "adriel"
    
    # Search files
    files = await query.search_files("*.pdf", "~/Documents")
    
    # List directory
    listing = await query.list_directory("~/Desktop")
    
    # Read file
    content = await query.read_file("~/report.pdf")
    ```
    """
    
    def __init__(self, api_key: str, server_url: str = "http://localhost:8770"):
        """
        Initialize bridge query client.
        
        Args:
            api_key: User's Unkey API key for authentication
            server_url: Server base URL (default: production)
        """
        self.logger = logging.getLogger(__name__)
        self.api_key = api_key
        self.server_url = server_url.rstrip('/')
        self.poll_interval = 0.5  # Poll every 0.5 seconds
        self.max_poll_time = 40   # Max 40 seconds wait
        
        self.logger.info(f"🌉 BridgeQuery initialized for {server_url}")
    
    # ═══════════════════════════════════════════════════════════════════
    # Public API - The Four Primitives
    # ═══════════════════════════════════════════════════════════════════
    
    async def execute_bash(
        self,
        command: str,
        timeout: int = 30
    ) -> Dict[str, Any]:
        """
        Execute bash command on local machine.
        
        Args:
            command: Bash command string (e.g., "whoami", "ls ~/Desktop")
            timeout: Command timeout in seconds
            
        Returns:
            {
                "success": True,
                "output": "command stdout",
                "error": "command stderr or None",
                "exit_code": 0
            }
        """
        command_id = str(uuid.uuid4())

        # Log only a short preview: commands can carry encoded credentials
        # and email content, and base64 is readable by anyone with the logs.
        self.logger.info(f"🔧 Executing bash ({len(command)} chars): {self._preview(command)}")

        # Send command to server
        await self._post_command({
            "id": command_id,
            "type": "bash",
            "cmd": command,
            "timeout": timeout
        })

        # Wait for results
        result = await self._poll_for_results(command_id, timeout + 10)

        return {
            "success": result.get("success", False),
            "output": result.get("output", ""),
            "error": result.get("error"),
            "exit_code": result.get("status", 1)
        }

    async def execute_python(
        self,
        code: str,
        timeout: int = 30,
        label: str = "python"
    ) -> Dict[str, Any]:
        """
        Run Python code on the local machine with the bridge's own Python
        (bridge command type "python": no shell, no command-length limit
        from cmd.exe, no quoting problems).

        The code itself is never logged, only the label, because it may
        contain an account's authorization code.
        """
        command_id = str(uuid.uuid4())
        self.logger.info(f"🐍 Executing python [{label}] ({len(code)} chars)")

        await self._post_command({
            "id": command_id,
            "type": "python",
            "cmd": code,
            "timeout": timeout
        })

        result = await self._poll_for_results(command_id, timeout + 10)

        return {
            "success": result.get("success", False),
            "output": result.get("output", ""),
            "error": result.get("error"),
            "exit_code": result.get("status", 1)
        }

    @staticmethod
    def _preview(command: str) -> str:
        """First words of a command, with long encoded blobs cut out."""
        head = command.split("-EncodedCommand")[0] if "-EncodedCommand" in command else command
        head = head.strip()
        return (head[:80] + "...") if len(head) > 80 else head

    async def list_directory(
        self,
        directory_path: str = "~/Desktop",
        show_hidden: bool = False,
        timeout: int = 10
    ) -> Dict[str, Any]:
        """
        List directory contents on local machine using PowerShell.
        """
        command_id = str(uuid.uuid4())
        
        # Build PowerShell command
        # Note: PowerShell -Force flag shows hidden files
        force_flag = "-Force" if show_hidden else ""
        command = f'powershell -Command "Get-ChildItem -Path \\"{directory_path}\\" {force_flag} | ForEach-Object {{ if ($_.PSIsContainer) {{ \\"DIR: $($_.Name)\\" }} else {{ \\"FILE: $($_.Name)\\" }} }}"'
        self.logger.info(f"📂 Listing directory: {directory_path}")
        
        await self._post_command({
            "id": command_id,
            "type": "bash",  # Bridge executes all commands as bash (which runs PowerShell)
            "cmd": command,
            "timeout": timeout
        })
        
        result = await self._poll_for_results(command_id, timeout + 5)
        
        # Parse PowerShell output
        if result.get("success"):
            output = result.get("output", "")
            files = []
            directories = []
            
            for line in output.split('\n'):
                line = line.strip()
                if line.startswith("DIR: "):
                    directories.append(line[5:])  # Remove "DIR: " prefix
                elif line.startswith("FILE: "):
                    files.append(line[6:])  # Remove "FILE: " prefix
            
            return {
                "success": True,
                "directory_path": directory_path,
                "files": files,
                "directories": directories,
                "total_items": len(files) + len(directories)
            }
        
        return {
            "success": False,
            "error": result.get("error", "Directory listing failed")
        }
    
    async def search_files(
        self,
        pattern: str,
        search_path: str = "~",
        max_results: int = 50,
        timeout: int = 30
    ) -> list:
        """
        Search for files matching pattern on local machine using PowerShell.
        
        Args:
            pattern: File pattern (e.g., "*.pdf", "*.docx,*.py")
            search_path: Where to search
            max_results: Maximum number of results
            timeout: Search timeout
            
        Returns:
            List of file paths: ["C:\\Users\\name\\file1.pdf", ...]
        """
        command_id = str(uuid.uuid4())
        
        # Convert bash brace patterns to PowerShell comma-separated
        # *.{docx,py} → *.docx,*.py
        ps_pattern = pattern.replace('{', '').replace('}', '')
        
        # Build PowerShell command with QUOTED path and -Include (not -Filter)
        # Use escaped quotes \" for paths with spaces
        command = f'powershell -Command "Get-ChildItem -Path \\"{search_path}\\" -Include {ps_pattern} -Recurse -File -ErrorAction SilentlyContinue | Select-Object -First {max_results} | ForEach-Object {{ $_.FullName }}"'
        
        self.logger.info(f"🔍 Searching for: {pattern} in {search_path}")
        
        await self._post_command({
            "id": command_id,
            "type": "bash",
            "cmd": command,
            "timeout": timeout
        })
        
        result = await self._poll_for_results(command_id, timeout + 5)
        
        if result.get("success"):
            output = result.get("output", "")
            files = [line.strip() for line in output.split('\n') if line.strip()]
            self.logger.info(f"✅ Found {len(files)} files")
            return files
        
        self.logger.warning(f"⚠️ Search failed: {result.get('error')}")
        return []
    
    async def read_file(
        self,
        file_path: str,
        max_chars: int = 50000,
        timeout: int = 60
    ) -> Dict[str, Any]:
        """
        Read TEXT file contents from local machine using PowerShell.
        Only supports plain text files - no binary formats.
        
        Args:
            file_path: Path to file
            max_chars: Maximum characters to read
            timeout: Read timeout
            
        Returns:
            {
                "success": True/False,
                "content": "file contents..." (if success),
                "error": "error message" (if failure)
            }
        """
        import os
        
        # Define supported text file extensions
        TEXT_EXTENSIONS = [
            '.txt', '.md', '.log',                    # Plain text
            '.py', '.js', '.ts', '.jsx', '.tsx',      # JavaScript/Python
            '.java', '.c', '.cpp', '.h', '.cs',       # Compiled languages
            '.go', '.rs', '.rb', '.php', '.swift',    # Other languages
            '.json', '.yaml', '.yml', '.xml',         # Config files
            '.csv', '.tsv',                           # Data files
            '.sql', '.sh', '.bat', '.ps1',            # Scripts
            '.html', '.css', '.scss', '.sass',        # Web
            '.cfg', '.conf', '.ini', '.env'           # Config variants
        ]
        
        # Check file extension
        _, file_ext = os.path.splitext(file_path)
        file_ext = file_ext.lower()
        
        if file_ext not in TEXT_EXTENSIONS:
            self.logger.warning(f"⚠️ Unsupported file type: {file_ext}")
            return {
                "success": False,
                "error": f"FileReader only supports text files. Cannot read binary file type '{file_ext}'. Supported: .txt, .md, .py, .js, .json, .csv, .log, etc."
            }
        
        command_id = str(uuid.uuid4())
        
        # Use PowerShell Get-Content with QUOTED path and line limit
        lines = max_chars // 80
        command = f'powershell -Command "Get-Content -Path \\"{file_path}\\" -TotalCount {lines} -ErrorAction SilentlyContinue"'
        
        self.logger.info(f"📖 Reading file: {file_path}")
        
        await self._post_command({
            "id": command_id,
            "type": "bash",
            "cmd": command,
            "timeout": timeout
        })
        
        result = await self._poll_for_results(command_id, timeout + 5)
        
        if result.get("success"):
            content = result.get("output", "")
            return {
                "success": True,
                "content": content[:max_chars],
                "size": len(content),
                "encoding": "utf-8"
            }
        
        return {
            "success": False,
            "error": result.get("error", "File read failed")
        }
    
    # ═══════════════════════════════════════════════════════════════════
    # Internal: HTTP Communication (Like WebSearchExecutor)
    # ═══════════════════════════════════════════════════════════════════
    
    async def _post_command(self, command_data: Dict[str, Any]) -> None:
        """
        POST command to server.
        
        Like WebSearchExecutor posting to Brave API.
        """
        url = f"{self.server_url}/api/bridge/execute"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=command_data, headers=headers) as response:
                    if response.status == 200:
                        self.logger.info(f"📤 Command queued: {command_data['id'][:8]}")
                    else:
                        error = await response.text()
                        self.logger.error(f"❌ Failed to queue command: {error}")
                        raise Exception(f"Server error: {response.status}")
        except Exception as e:
            self.logger.error(f"❌ POST failed: {str(e)}")
            raise
    
    async def _poll_for_results(
        self,
        command_id: str,
        max_wait: int
    ) -> Dict[str, Any]:
        """
        Poll server for command results.
        
        Exactly like WebSearchExecutor awaiting Brave API response.
        Returns when results ready or timeout.
        """
        url = f"{self.server_url}/api/bridge/result/{command_id}"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        
        elapsed = 0
        
        self.logger.info(f"⏳ Waiting for results (max {max_wait}s)...")
        
        while elapsed < max_wait:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, headers=headers) as response:
                        if response.status == 200:
                            data = await response.json()
                            
                            if data.get("status") == "complete":
                                self.logger.info(f"✅ Results received after {elapsed}s")
                                return data.get("result", {})
                            
                            # Still pending
                            await asyncio.sleep(self.poll_interval)
                            elapsed += self.poll_interval
                        else:
                            self.logger.warning(f"⚠️ Poll error: {response.status}")
                            await asyncio.sleep(self.poll_interval)
                            elapsed += self.poll_interval
            except Exception as e:
                self.logger.warning(f"⚠️ Poll exception: {str(e)}")
                await asyncio.sleep(self.poll_interval)
                elapsed += self.poll_interval
        
        # Timeout
        self.logger.error(f"❌ Timeout after {max_wait}s")
        return {
            "success": False,
            "error": f"Command timed out after {max_wait} seconds"
        }