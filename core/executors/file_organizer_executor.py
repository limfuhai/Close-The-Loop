"""
File Organizer Executor - Organize files in a folder by type.
Uses a hardcoded PowerShell script via bridge.
Pure Move-Item / New-Item operations only — no file reading, no content access.
Safe for bridge: no stdout that passes through cp1252 decoder.
"""

from __future__ import annotations

import logging
import base64
from typing import Dict, Any

from .base_executor import BaseExecutor
from ..execution.bridge_query import BridgeQuery


class FileOrganizerExecutor(BaseExecutor):
    """Executor for organizing local files by extension into subfolders."""

    def __init__(self, mcp_manager, mcp_registry, model_client):
        super().__init__(mcp_manager, mcp_registry)
        self.logger = logging.getLogger(__name__)
        self.executor_name = "FileOrganizerExecutor"
        self.model = model_client

    async def execute_task(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """Organize files in the target folder by file extension."""

        results: Dict[str, Any] = {
            "status": "started",
            "executorUsed": self.executor_name,
            "filesOrganized": [],
            "summary": "",
        }

        try:
            api_key = task_data.get("apiKey")
            if not api_key:
                raise Exception("No API key provided - bridge access requires authentication")

            # Determine target folder from user request keywords
            context = task_data.get("context", {})
            user_request = context.get("userRequest", "").lower()

            if "desktop" in user_request or "\u684c\u9762" in user_request:
                target_folder = r"$env:USERPROFILE\Desktop"
            elif "documents" in user_request or "\u6587\u6863" in user_request:
                target_folder = r"$env:USERPROFILE\Documents"
            else:
                # Default: Downloads
                target_folder = r"$env:USERPROFILE\Downloads"

            self.logger.info(f"\U0001f4c1 Organizing: {target_folder}")

            powershell_command = self._build_organize_command(target_folder)
            query = BridgeQuery(api_key=api_key)

            self.logger.info("\U0001f309 Running file organization via bridge...")
            result = await query.execute_bash(
                command=powershell_command,
                timeout=120
            )

            if result["success"]:
                output = result.get("output", "").strip()
                if "organized successfully" not in output.lower():
                    raise Exception(f"Unexpected output: {output}")

                results["filesOrganized"] = [{"output": output}]
                results["status"] = "completed"
                results["summary"] = f"\u2705 {output}"
                self.logger.info(f"\u2705 Organization complete: {output}")

            else:
                error_msg = result.get("error", "Unknown error")
                raise Exception(f"Organization failed: {error_msg}")

        except Exception as e:
            self.logger.error(f"\u274c FileOrganizerExecutor failed: {str(e)}")
            results["status"] = "error"
            results["error"] = str(e)
            results["summary"] = f"\u274c Failed: {str(e)}"

        return results

    def _encode_powershell_script(self, script: str) -> str:
        """Encode PowerShell script to Base64 UTF-16LE for -EncodedCommand."""
        script_bytes = script.encode("utf-16le")
        encoded = base64.b64encode(script_bytes).decode("ascii")
        return f"powershell.exe -EncodedCommand {encoded}"

    def _build_organize_command(self, target_folder: str) -> str:
        """
        Build a hardcoded PowerShell script that organizes files by extension.
        Batches moves by category for speed.
        Leftover files go to a catch-all folder.
        Only uses New-Item and Move-Item. No Get-Content. Bridge-safe.
        Chinese folder names survive intact via UTF-16LE Base64 encoding.
        """

        script = (
            '$baseDir = "' + target_folder + '"\n'
            "$moved = 0\n"
            "\n"
            "$categories = [ordered]@{\n"
            '    "Python\u6587\u4ef6"     = @("*.py", "*.pyw", "*.ipynb")\n'
            '    "Word\u6587\u6863"       = @("*.docx", "*.doc")\n'
            '    "PDF\u6587\u4ef6"        = @("*.pdf")\n'
            '    "Excel\u6587\u4ef6"      = @("*.xlsx", "*.xls", "*.csv")\n'
            '    "\u56fe\u7247\u6587\u4ef6"       = @("*.png", "*.jpg", "*.jpeg", "*.gif", "*.webp", "*.bmp", "*.ico", "*.svg")\n'
            '    "\u89c6\u9891\u6587\u4ef6"       = @("*.mp4", "*.mkv", "*.avi", "*.mov", "*.wmv")\n'
            '    "\u97f3\u9891\u6587\u4ef6"       = @("*.mp3", "*.wav", "*.flac", "*.aac", "*.m4a")\n'
            '    "\u538b\u7f29\u6587\u4ef6"       = @("*.zip", "*.rar", "*.7z", "*.tar", "*.gz")\n'
            '    "HTML\u6587\u4ef6"       = @("*.html", "*.htm", "*.css")\n'
            '    "JSON\u6587\u4ef6"       = @("*.json")\n'
            '    "JSONL\u6587\u4ef6"      = @("*.jsonl")\n'
            '    "\u6587\u672c\u6587\u4ef6"       = @("*.txt", "*.md", "*.log", "*.rst")\n'
            '    "PowerPoint\u6587\u4ef6" = @("*.pptx", "*.ppt")\n'
            '    "\u811a\u672c\u6587\u4ef6"       = @("*.sh", "*.bat", "*.ps1", "*.cmd")\n'
            '    "\u5b89\u88c5\u5305"         = @("*.exe", "*.msi")\n'
            "}\n"
            "\n"
            "foreach ($folderName in $categories.Keys) {\n"
            "    $patterns = $categories[$folderName]\n"
            "    $destPath = Join-Path $baseDir $folderName\n"
            "    foreach ($pattern in $patterns) {\n"
            "        $files = Get-ChildItem -Path $baseDir -Filter $pattern -File -ErrorAction SilentlyContinue\n"
            "        if ($files) {\n"
            "            New-Item -Path $destPath -ItemType Directory -Force | Out-Null\n"
            "            foreach ($file in $files) {\n"
            "                Move-Item -Path $file.FullName -Destination $destPath -Force -ErrorAction SilentlyContinue\n"
            "                $moved++\n"
            "            }\n"
            "        }\n"
            "    }\n"
            "}\n"
            "\n"
            "# Move remaining unclassified files\n"
            '$otherPath = Join-Path $baseDir "\u5176\u4ed6\u6587\u4ef6"\n'
            "$remaining = Get-ChildItem -Path $baseDir -File -ErrorAction SilentlyContinue\n"
            "if ($remaining) {\n"
            "    New-Item -Path $otherPath -ItemType Directory -Force | Out-Null\n"
            "    foreach ($file in $remaining) {\n"
            "        Move-Item -Path $file.FullName -Destination $otherPath -Force -ErrorAction SilentlyContinue\n"
            "        $moved++\n"
            "    }\n"
            "}\n"
            "\n"
            'Write-Output "Files organized successfully. Moved $moved files."'
        )

        return self._encode_powershell_script(script)