"""
Coding Executor - Generates fixed versions of buggy code files (WEB-STYLE OUTPUTS)
- Writes to /tmp/opex/outputs (same as ScriptExecutionManager)
- Returns relative URLs under /files/outputs
- If OutputStorage is configured, also uploads to Supabase and returns absolute signed URLs
- Mirrors Docs/Sheets executors' output shape and markdown
"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from datetime import datetime
from typing import Dict, Any, List, Optional
from pathlib import Path
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse

from .base_executor import BaseExecutor
from ..execution.code_editor import (
    gather_context,
    extract_code_from_response,   # keep using only the extractor
)
from ..execution.script_manager import ScriptExecutionManager

# Optional Supabase storage helper (core/storage.py)
try:
    from ..storage import OutputStorage  # adjust path if your OutputStorage is elsewhere
    _HAS_OUTPUT_STORAGE = True
except Exception:
    OutputStorage = None  # type: ignore
    _HAS_OUTPUT_STORAGE = False


class CodeEditorExecutor(BaseExecutor):
    """Executor for analyzing and fixing code files (consistent with Docs/Sheets outputs)."""

    def __init__(self, mcp_manager, mcp_registry, model_client):
        super().__init__(mcp_manager, mcp_registry)
        self.logger = logging.getLogger(__name__)
        self.executor_name = "CodingExecutor"
        self.model = model_client

        # Prefer NEXT_PUBLIC_API_URL, fallback to BACKEND_URL
        self.backend_base = (
            os.getenv("NEXT_PUBLIC_API_URL")
            or os.getenv("BACKEND_URL")
            or ""
        ).rstrip("/")

        # SAME directories as ScriptExecutionManager
        self.script_manager = ScriptExecutionManager()
        self.outputs_dir = Path(self.script_manager.outputs_dir)  # -> /tmp/opex/outputs
        self.outputs_dir.mkdir(parents=True, exist_ok=True)

        # Optional toggle: force ?download=<filename> (like SheetsExecutor)
        self.force_download = (os.getenv("OUTPUT_FORCE_DOWNLOAD", "false").lower() == "true")

    # ───────────────────────── URL Helpers (parity with SheetsExecutor) ─────────────────────────

    def _abs(self, raw: str) -> str:
        """Return an absolute URL for a possibly-relative path."""
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
        Avoids Supabase error: querystring/download must be string
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
        """
        if not url:
            return url
        p = urlparse(url)
        q = dict(parse_qsl(p.query, keep_blank_values=True))
        if "download" not in q or (q["download"] or "").strip().lower() in ("", "true", "1"):
            q["download"] = filename
        return urlunparse(p._replace(query=urlencode(q)))

    @staticmethod
    def _guess_type_from_name(name: str) -> str:
        n = (name or "").lower()
        if n.endswith(".py"):
            return "file"
        if n.endswith(".xlsx"):
            return "spreadsheet"
        if n.endswith(".pptx"):
            return "presentation"
        if n.endswith(".docx"):
            return "document"
        if n.endswith(".pdf"):
            return "pdf"
        if any(n.endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".gif", ".webp")):
            return "image"
        return "file"

    # ───────────────────────── Core ─────────────────────────

    async def execute_task(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        results: Dict[str, Any] = {
            "status": "started",
            "executorUsed": self.executor_name,
            "artifacts": [],
            "summary": "",
            "executorFullResponse": "",
        }

        try:
            from comprehensive_formatting_prompts import CODEEDITOR_EXECUTOR_PROMPT

            description = task_data.get("description", "") or ""
            requirements: List[str] = task_data.get("requirements", []) or []
            context: Dict[str, Any] = task_data.get("context", {}) or {}

            self.logger.info(f"[{self.executor_name}] Task description: {description}")
            self.logger.info(f"[{self.executor_name}] Requirements: {requirements}")
            self.logger.info(f"[{self.executor_name}] Context keys: {list(context.keys())}")

            # ---- Determine code context (inline or referenced files) ----
            context_data = ""
            target_file: Optional[str] = None

            if any(tok in description for tok in ("def ", "class ", "import ", "```")):
                context_data = f"## PROVIDED CODE:\n{description}"
                target_file = "code.py"
            else:
                py_files: List[str] = []
                py_files.extend(re.findall(r"[\w/\\]+\.py\b", description))
                for req in requirements:
                    py_files.extend(re.findall(r"[\w/\\]+\.py\b", req or ""))

                user_request = context.get("userRequest", "")
                py_files.extend(re.findall(r"[\w/\\]+\.py\b", user_request or ""))

                if py_files:
                    py_files = list(set(py_files))
                    self.logger.info(f"[{self.executor_name}] Found file references: {py_files}")
                    target_file = Path(py_files[0]).name
                    try:
                        context_data = gather_context(py_files)
                        if not context_data:
                            context_data = "## FILES TO CREATE:\n" + "\n".join(py_files)
                    except Exception as e:
                        self.logger.warning(f"[{self.executor_name}] Could not read files: {e}")
                        context_data = "## FILES MENTIONED (not found):\n" + "\n".join(py_files)

            if not context_data:
                context_data = "## NEW CODE GENERATION REQUEST"
                target_file = "generated_code.py"

            prompt = f"""## TASK:
{description}

## REQUIREMENTS:
{chr(10).join('- ' + req for req in requirements)}

## CONTEXT:
User's Original Request: {context.get('userRequest', 'Process the code')}

## CODE CONTEXT:
{context_data}

## INSTRUCTIONS:
Based on the task and requirements, generate the complete Python code.
If fixing existing code, output the complete FIXED version.
If new code generation, create the complete implementation.
Output ONLY the Python code, no explanations.
The code should be complete, well-structured, and ready to run.
"""

            # ---- Generate code ----
            self.logger.info(f"[{self.executor_name}] Generating code...")
            llm_response = await self.model.generate(
                system_prompt=CODEEDITOR_EXECUTOR_PROMPT,
                prompt=prompt,
                temperature=0.3,
            )
            results["executorFullResponse"] = llm_response

            # ---- Extract code ----
            fixed_code = extract_code_from_response(llm_response)
            if not fixed_code or not fixed_code.strip():
                raise ValueError("No Python code extracted from model response.")

            # ---- Save file into /tmp/opex/outputs (always) ----
            if not target_file:
                target_file = "output_code.py"
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename_only = f"{Path(target_file).stem}_{ts}.py"

            output_path = self.outputs_dir / filename_only
            # IMPORTANT: write here directly; do NOT call save_fixed_code (it writes elsewhere)
            output_path.write_text(fixed_code, encoding="utf-8")
            exists_flag = output_path.exists()
            self.logger.info(f"[{self.executor_name}] Saved: {output_path} exists={exists_flag}")

            # ---- Optional upload to Supabase storage ----
            rel_url = f"/files/outputs/{filename_only}"  # local static mount (always)
            upload_meta: Dict[str, Any] = {}
            absolute_primary: Optional[str] = None  # primary absolute (maybe signed)

            if _HAS_OUTPUT_STORAGE and exists_flag:
                try:
                    storage = OutputStorage()  # picks bucket/ttl from env
                    upload_meta = storage.save_file_path(
                        file_path=str(output_path),
                        user_id=task_data.get("userId", "anonymous"),
                        prefix="artifacts",  # same namespace used by other executors
                    )
                    # save_file_path is expected to return e.g. {"filename","path","download_url",...}
                    primary = (upload_meta.get("download_url")
                               or upload_meta.get("url")
                               or upload_meta.get("public_url")
                               or upload_meta.get("path")
                               or "")
                    if primary:
                        absolute_primary = self._abs(primary)
                        self.logger.info("✅ Uploaded to Supabase: %s", absolute_primary)
                except Exception as e:
                    self.logger.info("ℹ️ Supabase upload skipped/failed, using local static file. Reason: %s", e)

            # ---- Build final primary → normalized download URL (Sheets-style) ----
            primary_url = absolute_primary or self._abs(rel_url) or rel_url
            # If force_download or already has ?download, ensure a filename; else strip boolean/empty
            final_download = (
                self._ensure_download_filename(primary_url, filename_only)
                if (self.force_download or "download=" in primary_url)
                else self._strip_download_param(primary_url)
            )

            storage_kind = "supabase" if absolute_primary else "local"
            signed = bool(absolute_primary)

            normalized_entry = {
                "filename": filename_only,
                "type": self._guess_type_from_name(filename_only),
                "mimetype": "text/x-python",
                # Keep both absolute and relative references
                "url": (absolute_primary or rel_url),
                "public_url": (absolute_primary or None),
                "relative_url": rel_url,
                "storage": storage_kind,
                "signed": signed,
                "size": len(fixed_code.encode("utf-8")),
                "download_url": final_download,
                **({"path": upload_meta.get("path")} if upload_meta else {}),
            }
            results["outputFiles"] = [normalized_entry]
            results["previews"] = []  # parity key

            # ---- Append user-facing markdown (Sheets-style "Open") ----
            md_lines = [
                "",
                "### Created Files",
                f"- **{filename_only}** — [Open]({final_download})  (Python)",
            ]
            results["executorFullResponse"] += "\n" + "\n".join(md_lines) + "\n"

            # ---- Artifact summary ----
            artifact = {
                "id": f"{self.executor_name}-{uuid.uuid4()}",
                "type": "code",
                "title": f"Generated: {filename_only}",
                "data": {
                    "lines_of_code": len(fixed_code.splitlines()),
                },
                "metadata": {
                    "timestamp": datetime.now().isoformat(),
                    "executor": self.executor_name,
                    "storage": storage_kind,
                    "signed": signed,
                },
                "display_url": primary_url,
                "download_url": final_download,
                "relative_url": rel_url,
            }
            results["artifacts"] = [artifact]

            results["status"] = "completed"
            results["summary"] = f"Created code file '{filename_only}'"

        except Exception as e:
            self.logger.error(f"{self.executor_name} error: {str(e)}")
            results["status"] = "error"
            results["error"] = str(e)
            results["summary"] = f"Error during code generation: {str(e)}"

        return results

