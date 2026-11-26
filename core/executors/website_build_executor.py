"""
Website Builder Executor Agent
Generates complete, functional websites (multiple files in a folder).
- Generates Python script that creates website files
- Runs the script in a dedicated site workspace
- Packs the folder to a ZIP
- Returns URLs with improved output handling
"""

from __future__ import annotations

import os
import json
import logging
import asyncio
import shutil
import zipfile
from typing import Dict, Any, List, Optional
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse

from .base_executor import BaseExecutor
from ..execution.script_manager import ScriptExecutionManager

# Optional Supabase storage helper
try:
    from ..storage import OutputStorage
    _HAS_OUTPUT_STORAGE = True
except Exception:
    OutputStorage = None
    _HAS_OUTPUT_STORAGE = False

logger = logging.getLogger(__name__)


class WebsiteBuildExecutor(BaseExecutor):
    """
    Executor for creating complete websites.
    Generates Python code that creates website files, then packages as ZIP.
    """

    def __init__(self, mcp_manager, mcp_registry, model_client):
        super().__init__(mcp_manager, mcp_registry)
        self.logger = logging.getLogger(__name__)
        self.executor_name = "WebsiteBuildExecutor"
        self.model = model_client
        self.script_manager = ScriptExecutionManager()
        
        # Backend base URL for absolute URLs
        self.backend_base = (os.getenv("NEXT_PUBLIC_API_URL") or "").rstrip("/")
        
        # Setup directories
        self.outputs_root = Path("/tmp/opex/outputs").resolve()
        self.sites_root = self.outputs_root / "sites"
        self.sites_root.mkdir(parents=True, exist_ok=True)
        
        # Initialize storage
        self.storage = OutputStorage() if _HAS_OUTPUT_STORAGE else None
        
        # Download param behavior
        self.force_download = (os.getenv("OUTPUT_FORCE_DOWNLOAD", "false").lower() == "true")
        
        self.logger.info("✅ Website Build Executor initialized")

    # ───────────────────────── URL Helpers ─────────────────────────

    def _abs(self, raw: str) -> str:
        """Return an absolute URL for a possibly relative path."""
        if not raw:
            return ""
        if raw.startswith("http://") or raw.startswith("https://"):
            return raw
        base = self.backend_base
        if not base:
            return raw
        return f"{base}{raw if raw.startswith('/') else '/' + raw}"

    def _strip_download_param(self, url: str) -> str:
        """Remove `download` ONLY when empty/boolean-like. Keep string filenames."""
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
        """Ensure `download=<filename>` is present (not boolean)."""
        if not url:
            return url
        p = urlparse(url)
        q = dict(parse_qsl(p.query, keep_blank_values=True))
        if "download" not in q or (q["download"] or "").strip().lower() in ("", "true", "1"):
            q["download"] = filename
        return urlunparse(p._replace(query=urlencode(q)))

    @staticmethod
    def _format_bytes(bytes_size: int) -> str:
        """Format bytes into human-readable string"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if bytes_size < 1024.0:
                return f"{bytes_size:.1f} {unit}"
            bytes_size /= 1024.0
        return f"{bytes_size:.1f} TB"

    # ───────────────────────── Core Execution ─────────────────────────

    async def execute_task(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute website creation task."""
        results: Dict[str, Any] = {
            "status": "started",
            "executorUsed": self.executor_name,
            "artifacts": [],
            "summary": "",
            "executorFullResponse": "",
        }

        try:
            # Extract task info
            task_id = str(task_data.get("id") or f"site_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
            description = task_data.get("description", "")
            requirements = task_data.get("requirements", []) or []
            context = task_data.get("context", {})
            user_id = task_data.get("userId", "anonymous")

            self.logger.info(f"🌐 Building website: {task_id}")

            # Create workspace
            site_dir = (self.sites_root / task_id).resolve()
            site_dir.mkdir(parents=True, exist_ok=True)
            self.logger.info(f"📁 Workspace: {site_dir}")

            # Step 1: Generate Python builder script
            self.logger.info("🤖 Generating website builder code...")
            code = await self._generate_builder_code(description, requirements, context)

            # Step 2: Save builder script
            script_name = f"website_builder_{task_id}.py"
            script_path = await self.script_manager.save_script(code=code, script_name=script_name)
            self.logger.info(f"💾 Saved builder script: {script_path}")

            # Step 3: Execute script in site directory
            self.logger.info(f"▶️ Executing builder script (cwd={site_dir})...")
            exec_result = await self.script_manager.execute_script(
                script_path,
                cwd=site_dir,
                user_id=user_id,
            )

            # Check execution result
            if exec_result.get("exit_code", 1) != 0:
                error_msg = exec_result.get("error") or exec_result.get("stderr", "Unknown error")
                self.logger.error(f"❌ Builder script failed: {error_msg}")
                results["status"] = "error"
                results["error"] = error_msg
                results["summary"] = "Website builder script execution failed"
                results["script_path"] = str(script_path)
                results["execution_output"] = exec_result.get("output", "")
                return results

            self.logger.info("✅ Builder script executed successfully")

            # Step 4: Collect generated files
            produced_files = [
                p.relative_to(site_dir).as_posix() 
                for p in site_dir.rglob("*") 
                if p.is_file()
            ]
            
            if not produced_files:
                raise Exception("No files were created by the builder script")

            self.logger.info(f"📄 Generated {len(produced_files)} files")

            # Step 5: Create ZIP archive
            self.logger.info("📦 Creating ZIP archive...")
            zip_filename = f"website_{task_id}.zip"
            zip_path = self.outputs_root / zip_filename
            self._create_zip_archive(site_dir, zip_path)
            
            zip_size = zip_path.stat().st_size
            self.logger.info(f"📦 ZIP created: {zip_path.name} ({self._format_bytes(zip_size)})")

            # Step 6: Upload ZIP to storage
            self.logger.info("☁️ Uploading ZIP to storage...")
            zip_url_info = await self._upload_file_to_storage(
                zip_path, user_id, f"websites/{task_id}", zip_filename
            )

            # Step 7: Optional - Upload index.html for preview
            preview_url_info = None
            index_path = site_dir / "index.html"
            if index_path.exists():
                self.logger.info("🔍 Uploading preview...")
                preview_url_info = await self._upload_file_to_storage(
                    index_path, user_id, f"websites/{task_id}/preview", "index.html"
                )

            # Step 8: Build normalized output files
            output_files = []
            
            # Add ZIP file
            zip_file_obj = {
                "filename": zip_filename,
                "name": zip_filename,
                "type": "website_archive",
                "download_url": zip_url_info["url"],
                "public_url": zip_url_info["url"],
                "size_bytes": zip_size,
                "size_formatted": self._format_bytes(zip_size),
                "total_files": len(produced_files),
                "files": produced_files[:50],  # First 50 files
            }
            output_files.append(zip_file_obj)

            # Add preview if available
            if preview_url_info:
                preview_file_obj = {
                    "filename": "index.html",
                    "name": "Website Preview",
                    "type": "website_preview",
                    "download_url": preview_url_info["url"],
                    "public_url": preview_url_info["url"],
                }
                output_files.append(preview_file_obj)

            results["outputFiles"] = output_files

            # Step 9: Build user-facing markdown
            md_lines = ["", "### Created Files"]
            
            # ZIP download link
            md_lines.append(
                f"- **{zip_filename}** — [Download ZIP]({zip_file_obj['download_url']})  "
                f"(Website Archive - {self._format_bytes(zip_size)})"
            )
            
            # Preview link if available
            if preview_url_info:
                md_lines.append(
                    f"- **Website Preview** — [Open in Browser]({preview_url_info['url']})  "
                    f"(Live Preview)"
                )

            # File listing
            md_lines.append("")
            md_lines.append("### Files in Website")
            for file_path in produced_files[:20]:  # Show first 20
                md_lines.append(f"- {file_path}")
            if len(produced_files) > 20:
                md_lines.append(f"- ... and {len(produced_files) - 20} more files")

            results["executorFullResponse"] = "\n".join(md_lines) + "\n"

            # Step 10: Create artifact metadata
            artifact = {
                "type": "website",
                "title": f"Generated Website - {task_id}",
                "download_url": zip_file_obj["download_url"],
                "preview_url": preview_url_info["url"] if preview_url_info else None,
                "total_files": len(produced_files),
                "files": produced_files[:50],
                "size_bytes": zip_size,
                "size_formatted": self._format_bytes(zip_size),
            }
            
            results["artifacts"] = [artifact]
            results["status"] = "completed"
            results["summary"] = (
                f"Successfully created website with {len(produced_files)} files "
                f"({self._format_bytes(zip_size)})"
            )
            results["script_path"] = str(script_path)
            results["execution_output"] = exec_result.get("output", "")

        except Exception as e:
            self.logger.exception("❌ Website build failed")
            results["status"] = "error"
            results["error"] = str(e)
            results["summary"] = f"Error creating website: {str(e)}"

        return results

    # ───────────────────────── Code Generation ─────────────────────────

    async def _generate_builder_code(
        self,
        description: str,
        requirements: List[str],
        context: Dict[str, Any]
    ) -> str:
        """Generate Python code that creates website files."""
        
        # Import prompt
        try:
            from comprehensive_formatting_prompts import WEBSITE_BUILDER_PROMPT
            self.logger.info("✅ Loaded WEBSITE_BUILDER_PROMPT")
        except ImportError as e:
            self.logger.warning(f"⚠️ Failed to import prompt: {e}")
            # Fallback prompt
            WEBSITE_BUILDER_PROMPT = """You are a Python code generator for creating websites.

Generate a Python script that:
1. Creates website files using Python file I/O (open(), write())
2. Assumes current working directory is the target website folder
3. Creates at minimum: index.html, styles.css, script.js
4. Writes complete, production-ready HTML/CSS/JS content
5. Uses relative links in HTML (e.g., <link href="styles.css">)
6. Does NOT use 'return' statements or sys.exit()
7. Keeps the script under 180 lines
8. Does NOT make external network calls

The script should be executable Python code that creates all necessary files."""

        # Build requirements text
        requirements_text = "\n".join(f"- {req}" for req in requirements) if requirements else "- Modern, responsive website"
        
        # User prompt
        user_prompt = f"""## Website Request
{description}

## Requirements
{requirements_text}

## Context
User's Original Request: {context.get('userRequest', 'Build a website')}

## Instructions for the Python builder script you will generate:
- Assume the current working directory (cwd) is the target website folder
- Create at minimum: index.html, styles.css, script.js (you can add more files/folders as needed)
- Use Python file I/O: open(filename, 'w', encoding='utf-8') and write complete content
- Keep the script ≤ 180 lines total
- No external network calls
- Do NOT use 'return' at the end; just write files and exit naturally
- Make relative links (e.g., <link href="styles.css">, <script src="script.js">)
- Write complete, production-ready code in each file

Generate the complete Python script now:"""

        # Call LLM
        self.logger.info("📤 Requesting code from LLM...")
        response = await self.model.generate(
            prompt=user_prompt,
            system_prompt=WEBSITE_BUILDER_PROMPT,
            temperature=0.6,
            max_tokens=4500,
        )

        # Extract code
        code = self._extract_code(response)
        
        if not code or len(code.strip()) < 50:
            raise Exception("LLM returned invalid or too-short code")
        
        self.logger.info(f"✅ Generated builder code ({len(code)} chars)")
        return code

    def _extract_code(self, response: str) -> str:
        """Extract Python code from LLM response."""
        
        if not response:
            raise ValueError("Empty response from LLM")
        
        # Strip markdown fences if present
        cleaned = response.strip()
        
        if "```python" in cleaned:
            start = cleaned.find("```python") + len("```python")
            end = cleaned.find("```", start)
            if end != -1:
                return cleaned[start:end].strip()
        
        if "```" in cleaned:
            start = cleaned.find("```") + 3
            end = cleaned.find("```", start)
            if end != -1:
                return cleaned[start:end].strip()
        
        # No markdown fences found, return as-is
        return cleaned

    # ───────────────────────── File Operations ─────────────────────────

    def _create_zip_archive(self, source_dir: Path, zip_path: Path) -> None:
        """Create ZIP archive of website folder."""
        
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for file_path in source_dir.rglob('*'):
                if file_path.is_file():
                    arcname = file_path.relative_to(source_dir)
                    zipf.write(file_path, arcname)
                    self.logger.debug(f"📦 Added to ZIP: {arcname}")

    async def _upload_file_to_storage(
        self, 
        file_path: Path, 
        user_id: str, 
        prefix: str,
        filename: str
    ) -> Dict[str, str]:
        """
        Upload file to Supabase storage and return URL info.
        Falls back to local URL if Supabase unavailable.
        
        Returns:
            {"url": str, "type": "supabase" | "local"}
        """
        
        # If no storage configured, use local URL
        if not self.storage:
            rel_path = file_path.relative_to(self.outputs_root)
            local_url = f"/files/outputs/{rel_path.as_posix()}"
            abs_url = self._abs(local_url)
            self.logger.info(f"📂 Local URL (no Supabase): {abs_url}")
            return {"url": abs_url, "type": "local"}

        # Try uploading to Supabase
        try:
            with open(file_path, 'rb') as fh:
                result = self.storage.save_bytes(
                    fh.read(),
                    ext=file_path.suffix,
                    filename=filename,
                    user_id=user_id,
                    prefix=prefix,
                    local_dir=str(self.outputs_root),
                )

            # Extract URL from result
            raw_url = (
                result.get("signed_url") or 
                result.get("public_url") or 
                result.get("download_url") or
                ""
            )
            
            if raw_url:
                # Make absolute
                abs_url = self._abs(raw_url)
                
                # Handle download param
                final_url = (
                    self._ensure_download_filename(abs_url, filename)
                    if (self.force_download or "download=" in abs_url)
                    else self._strip_download_param(abs_url)
                )
                
                self.logger.info(f"☁️ Supabase URL: {final_url[:60]}...")
                return {"url": final_url, "type": "supabase"}
            else:
                raise Exception("No URL in storage result")

        except Exception as e:
            self.logger.warning(f"⚠️ Supabase upload failed: {e}")
            self.logger.info("📂 Falling back to local URL")
            
            # Fallback to local
            rel_path = file_path.relative_to(self.outputs_root)
            local_url = f"/files/outputs/{rel_path.as_posix()}"
            abs_url = self._abs(local_url)
            return {"url": abs_url, "type": "local"}
