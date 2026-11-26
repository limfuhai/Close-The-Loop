# frontend_app_build_executor.py
"""
Frontend App Build Executor
--------------------------------------------------------------
Generates a React app with proper output system:
- Creates files in /tmp/opex/outputs/apps/{task_id}
- Packs to ZIP in /tmp/opex/outputs
- Uploads ZIP via OutputStorage.save_bytes (same as WebsiteBuildExecutor)
- Returns normalized outputFiles + artifacts with proper URLs
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

try:
    from ..storage import OutputStorage
    _HAS_OUTPUT_STORAGE = True
except Exception:
    OutputStorage = None
    _HAS_OUTPUT_STORAGE = False

logger = logging.getLogger(__name__)


class FrontendAppExecutor:
    """Generate a React frontend app and upload to storage with website-like output."""

    def __init__(self, mcp_manager, mcp_registry, model):
        self.mcp_manager = mcp_manager
        self.mcp_registry = mcp_registry
        self.model = model
        
        # Output directories setup (consistent with website executor)
        self.outputs_root = Path("/tmp/opex/outputs").resolve()
        self.apps_root = self.outputs_root / "apps"
        self.apps_root.mkdir(parents=True, exist_ok=True)
        
        # Initialize storage
        self.storage = OutputStorage() if _HAS_OUTPUT_STORAGE else None

        # Backend base URL for absolute URLs
        self.backend_base = (os.getenv("NEXT_PUBLIC_API_URL") or "").rstrip("/")

        # Download param behavior (same as WebsiteBuildExecutor)
        self.force_download = (os.getenv("OUTPUT_FORCE_DOWNLOAD", "false").lower() == "true")
        
        logger.info("✅ Initialized Frontend App Executor")

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
        """Format bytes into human-readable string."""
        for unit in ["B", "KB", "MB", "GB"]:
            if bytes_size < 1024.0:
                return f"{bytes_size:.1f} {unit}"
            bytes_size /= 1024.0
        return f"{bytes_size:.1f} TB"

    # ───────────────────────── Core Execution ─────────────────────────

    async def execute_task(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate a complete React app, zip it, and upload via OutputStorage.save_bytes.
        Returns dict similar to WebsiteBuildExecutor.
        """
        app_dir: Optional[Path] = None
        zip_path: Optional[Path] = None

        # Base result structure (similar to WebsiteBuildExecutor)
        results: Dict[str, Any] = {
            "status": "started",
            "executorUsed": "FrontendAppExecutor",
            "artifacts": [],
            "summary": "",
            "executorFullResponse": "",
        }
        
        try:
            # Extract task parameters
            description = (task_data.get("description") or "").strip()
            requirements = task_data.get("requirements", []) or []
            context = task_data.get("context", {}) or {}
            task_id = str(task_data.get("task_id") or task_data.get("id") or
                          f"frontend_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
            user_id = task_data.get("userId", "anonymous")
            
            # Get app name from context or generate from description
            app_name = context.get("appName") or self._generate_app_name(description)
            
            logger.info(f"🚀 Starting React app build: {app_name} (task_id={task_id})")
            logger.info(f"📝 Description: {description}")
            logger.info(f"📋 Requirements: {len(requirements)} items")
            
            # Step 1: Create unique app directory
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_name = self._sanitize_filename(app_name)
            app_dir = self.apps_root / f"{safe_name}_{timestamp}"
            app_dir.mkdir(parents=True, exist_ok=True)
            
            logger.info(f"📁 Created app directory: {app_dir}")
            
            # Step 2: Generate React app structure using LLM
            logger.info("🤖 Generating React app code...")
            app_structure = await self._generate_app_structure(
                description, requirements, context, task_data
            )
            
            # Step 3: Write all files to the app directory
            logger.info(f"📝 Writing {len(app_structure)} files...")
            files_created = await self._write_app_files(app_dir, app_structure)
            
            logger.info(f"✅ Created {len(files_created)} files")
            for file_path in files_created[:5]:  # Show first 5 files
                logger.info(f"  ✓ {file_path}")
            if len(files_created) > 5:
                logger.info(f"  ... and {len(files_created) - 5} more files")
            
            # Step 4: Create ZIP file (in /tmp/opex/outputs, same as Website)
            logger.info("📦 Creating ZIP archive...")
            zip_path = await self._create_zip(app_dir, safe_name, task_id)
            zip_size = zip_path.stat().st_size
            logger.info(f"✅ ZIP created: {zip_path.name} ({self._format_bytes(zip_size)})")
            
            # Step 5: Upload ZIP via storage helper (same pattern as WebsiteBuildExecutor)
            logger.info("☁️ Uploading app ZIP to storage...")
            zip_url_info = await self._upload_file_to_storage(
                zip_path,
                user_id=user_id,
                prefix=f"apps/{task_id}",
                filename=zip_path.name,
            )

            # No special preview file like index.html here (this is source code app)
            preview_url_info = None

            # Step 6: Build normalized outputFiles list (similar to website)
            output_files = []
            zip_file_obj = {
                "filename": zip_path.name,
                "name": zip_path.name,
                "type": "react_app_archive",
                "download_url": zip_url_info["url"],
                "public_url": zip_url_info["url"],
                "size_bytes": zip_size,
                "size_formatted": self._format_bytes(zip_size),
                "total_files": len(files_created),
                "files": files_created[:50],  # First 50 files
            }
            output_files.append(zip_file_obj)

            results["outputFiles"] = output_files

            # Step 7: Build user-facing markdown
            md_lines = []
            md_lines.append("✅ **React App Built Successfully!**")
            md_lines.append("")
            md_lines.append(f"📦 **App Name:** {app_name}")
            md_lines.append(f"📁 **Files Created:** {len(files_created)}")
            md_lines.append(f"💾 **ZIP Size:** {self._format_bytes(zip_size)}")
            md_lines.append("")
            md_lines.append(
                f"🔗 **Download:** [Click here to download your app]({zip_file_obj['download_url']})"
            )
            md_lines.append("")
            md_lines.append("**Next Steps:**")
            md_lines.append("1. Extract the ZIP file")
            md_lines.append("2. Run `npm install` to install dependencies")
            md_lines.append("3. Run `npm start` to start the development server")
            md_lines.append("4. Your app will open at http://localhost:3000")
            md_lines.append("")
            md_lines.append("### Files in App")
            for file_path in files_created[:20]:
                md_lines.append(f"- {file_path}")
            if len(files_created) > 20:
                md_lines.append(f"- ... and {len(files_created) - 20} more files")

            full_md = "\n".join(md_lines) + "\n"

            # Step 8: Artifact metadata (similar style to website)
            artifact = {
                "type": "react_app",
                "title": f"Generated React App - {app_name}",
                "download_url": zip_file_obj["download_url"],
                "preview_url": None,
                "total_files": len(files_created),
                "files": files_created[:50],
                "size_bytes": zip_size,
                "size_formatted": self._format_bytes(zip_size),
                "data": {
                    "app_name": app_name,
                    "zip_file": str(zip_path),
                },
            }

            results["artifacts"] = [artifact]
            results["status"] = "completed"
            results["summary"] = (
                f"Successfully created React app with {len(files_created)} files "
                f"({self._format_bytes(zip_size)})"
            )
            results["executorFullResponse"] = full_md
            # Keep some of your previous keys for compatibility with orchestrator/UI
            results["download_url"] = zip_file_obj["download_url"]
            results["files_created"] = files_created
            results["total_files"] = len(files_created)
            results["zip_path"] = str(zip_path)
            results["app_dir"] = str(app_dir)

            return results

        except Exception as e:
            logger.error(f"❌ Frontend App Build failed: {e}", exc_info=True)
            error_message = f"Failed to build React app: {str(e)}"
            
            results["status"] = "error"
            results["summary"] = error_message
            results["executorFullResponse"] = error_message
            results["error"] = str(e)
            results["app_dir"] = str(app_dir) if app_dir else None
            return results
        
        finally:
            # Cleanup: Remove temporary app directory (keep ZIP in outputs_root)
            if app_dir and app_dir.exists():
                try:
                    shutil.rmtree(app_dir)
                    logger.info(f"🧹 Cleaned up temporary directory: {app_dir}")
                except Exception as cleanup_error:
                    logger.warning(f"⚠️  Cleanup failed: {cleanup_error}")

    # ───────────────────────── LLM App Generation ─────────────────────────

    async def _generate_app_structure(
        self, 
        description: str, 
        requirements: List[str], 
        context: Dict,
        task_data: Dict[str, Any]
    ) -> Dict[str, str]:
        """
        Generate React app structure using LLM.
        Returns dict mapping file paths to their contents.
        """
        try:
            from comprehensive_formatting_prompts import FRONTEND_APP_BUILDER_PROMPT
            system_prompt = FRONTEND_APP_BUILDER_PROMPT
            logger.info("✅ Loaded FRONTEND_APP_BUILDER_PROMPT")
        except ImportError as e:
            logger.warning(f"⚠️ Failed to import FRONTEND_APP_BUILDER_PROMPT: {e}")
            system_prompt = """You are a React app code generator.
Create production-ready React 18 applications with modern best practices.
Generate ONLY a Python script that creates all necessary files."""

        requirements_text = "\n".join(f"- {req}" for req in requirements) if requirements else "- Modern, responsive React app"
        
        user_prompt = f"""Create a complete, production-ready React 18 application.

## App Description
{description}

## Requirements
{requirements_text}

## Additional Context
{json.dumps(context, indent=2) if context else "{}"}

Generate a Python script that:
1. Creates all necessary files and directories
2. Uses React 18 + React Router 6 + Axios
3. Includes proper package.json with all dependencies
4. Has a working development setup (can run with 'npm start')
5. Follows modern React best practices (hooks, functional components)
6. Includes proper error boundaries and loading states
7. Has clean, production-ready code

The script should use this pattern:
```python
from pathlib import Path

# Create directories
Path('public').mkdir(exist_ok=True)
Path('src').mkdir(exist_ok=True)
Path('src/components').mkdir(exist_ok=True)
Path('src/pages').mkdir(exist_ok=True)
Path('src/services').mkdir(exist_ok=True)

# Create files
open('public/index.html', 'w', encoding='utf-8').write('''...''')
open('src/index.js', 'w', encoding='utf-8').write('''...''')
open('src/App.js', 'w', encoding='utf-8').write('''...''')
open('package.json', 'w', encoding='utf-8').write('''...''')
# ... etc
```

Generate the complete Python script now:"""

        logger.info("📤 Sending request to LLM for React app generation...")
        response = await self.model.generate(
            prompt=user_prompt,
            system_prompt=system_prompt,
            temperature=0.7,
            max_tokens=20000,
        )
        
        logger.info("📥 Extracting Python script from LLM response...")
        script_code = self._extract_code(response)
        
        if not script_code:
            raise ValueError("LLM did not return valid Python code for app generation")
        
        # Execute script in a temporary directory to capture file structure
        logger.info("🔧 Executing script to generate file structure...")
        temp_dir = self.outputs_root / f"temp_app_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        
        try:
            import subprocess
            script_path = temp_dir / "builder_script.py"
            script_path.write_text(script_code, encoding="utf-8")
            
            result = subprocess.run(
                ["python3", str(script_path)],
                cwd=str(temp_dir),
                capture_output=True,
                text=True,
                timeout=60,
            )
            
            if result.returncode != 0:
                raise RuntimeError(f"Script execution failed: {result.stderr}")
            
            app_structure: Dict[str, str] = {}
            for file_path in temp_dir.rglob("*"):
                if file_path.is_file() and file_path.name != "builder_script.py":
                    relative_path = str(file_path.relative_to(temp_dir))
                    try:
                        content = file_path.read_text(encoding="utf-8")
                        app_structure[relative_path] = content
                    except Exception as read_error:
                        logger.warning(f"Could not read {relative_path}: {read_error}")
            
            logger.info(f"✅ Generated {len(app_structure)} files in app structure")
            return app_structure
            
        finally:
            if temp_dir.exists():
                shutil.rmtree(temp_dir)

    # ───────────────────────── File Operations ─────────────────────────

    async def _write_app_files(
        self, 
        app_dir: Path, 
        app_structure: Dict[str, str]
    ) -> List[str]:
        """Write all app files to the app directory. Returns list of created file paths."""
        files_created: List[str] = []
        
        for file_path, content in app_structure.items():
            full_path = app_dir / file_path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            
            try:
                full_path.write_text(content, encoding="utf-8")
                files_created.append(file_path)
            except Exception as e:
                logger.error(f"Failed to write {file_path}: {e}")
        
        return files_created

    async def _create_zip(self, app_dir: Path, app_name: str, task_id: str) -> Path:
        """
        Create a ZIP archive of the app directory in /tmp/opex/outputs.
        Returns path to the ZIP file.
        """
        zip_filename = f"react_app_{task_id}.zip"
        zip_path = self.outputs_root / zip_filename
        
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            for file_path in app_dir.rglob("*"):
                if file_path.is_file():
                    arcname = file_path.relative_to(app_dir)
                    zipf.write(file_path, arcname)
        
        return zip_path

    async def _upload_file_to_storage(
        self,
        file_path: Path,
        user_id: str,
        prefix: str,
        filename: str,
    ) -> Dict[str, str]:
        """
        Upload file to Supabase-style storage via OutputStorage.save_bytes,
        mirroring WebsiteBuildExecutor behavior.
        Returns: {"url": str, "type": "supabase" | "local"}
        """
        # If no storage configured, use local URL
        if not self.storage:
            rel_path = file_path.relative_to(self.outputs_root)
            local_url = f"/files/outputs/{rel_path.as_posix()}"
            abs_url = self._abs(local_url)
            logger.info(f"📂 Local URL (no Supabase): {abs_url}")
            return {"url": abs_url, "type": "local"}

        # Try uploading via save_bytes
        try:
            with open(file_path, "rb") as fh:
                result = self.storage.save_bytes(
                    fh.read(),
                    ext=file_path.suffix,
                    filename=filename,
                    user_id=user_id,
                    prefix=prefix,
                    local_dir=str(self.outputs_root),
                )

            raw_url = (
                result.get("signed_url")
                or result.get("public_url")
                or result.get("download_url")
                or ""
            )

            if raw_url:
                abs_url = self._abs(raw_url)
                final_url = (
                    self._ensure_download_filename(abs_url, filename)
                    if (self.force_download or "download=" in abs_url)
                    else self._strip_download_param(abs_url)
                )
                logger.info(f"☁️ Supabase URL: {final_url[:60]}...")
                return {"url": final_url, "type": "supabase"}
            else:
                raise Exception("No URL in storage result")

        except Exception as e:
            logger.warning(f"⚠️ Supabase upload failed: {e}")
            logger.info("📂 Falling back to local URL")
            rel_path = file_path.relative_to(self.outputs_root)
            local_url = f"/files/outputs/{rel_path.as_posix()}"
            abs_url = self._abs(local_url)
            return {"url": abs_url, "type": "local"}

    # ───────────────────────── Helpers ─────────────────────────

    def _extract_code(self, response: str) -> str:
        """Extract Python code from LLM response."""
        if not isinstance(response, str):
            return ""
        
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
        
        return cleaned

    def _generate_app_name(self, description: str) -> str:
        """Generate a safe app name from description."""
        if not description:
            return "react-app"
        words = description.split()[:3]
        name = "-".join(words).lower()
        return self._sanitize_filename(name)

    def _sanitize_filename(self, name: str) -> str:
        """Sanitize a string for use as filename."""
        import re
        safe_name = re.sub(r"[^\w\s-]", "", name)
        safe_name = re.sub(r"[\s_]+", "-", safe_name)
        safe_name = re.sub(r"-+", "-", safe_name)
        safe_name = safe_name.strip("-")
        return safe_name[:50] or "app"
