"""
Google Docs Executor - Local Generation Version
Creates Word documents using python-docx.
- Executes LLM-generated Python to build documents
- Saves artifacts via ScriptExecutionManager
- Normalizes URLs (keeps ?download=<filename> when present)
"""

from __future__ import annotations

import json
import re
import logging
import os
from typing import Dict, Any, List, Optional
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse

from .base_executor import BaseExecutor
from ..execution.script_manager import ScriptExecutionManager


class DocsExecutor(BaseExecutor):
    """Executor for creating documents using python-docx."""

    def __init__(self, mcp_manager, mcp_registry, model_client, compiler_service=None):
        super().__init__(mcp_manager, mcp_registry)
        self.logger = logging.getLogger(__name__)
        self.executor_name = "DocsExecutor"
        self.model = model_client
        self.compiler_service = compiler_service
        
        # Base URL for turning relative paths into absolute links for the web UI
        self.backend_base = (os.getenv("NEXT_PUBLIC_API_URL") or "").rstrip("/")
        self.script_manager = ScriptExecutionManager(compiler_service=compiler_service)

        # Optional toggle: force ?download=<filename> if you explicitly want it.
        # Default is False.
        self.force_download = (os.getenv("OUTPUT_FORCE_DOWNLOAD", "false").lower() == "true")

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ Helpers ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _abs(self, raw: str) -> str:
        """Return an absolute URL for a possibly-relative path, using NEXT_PUBLIC_API_URL as base."""
        if not raw:
            return ""
        if raw.startswith("http://") or raw.startswith("https://"):
            return raw
        base = self.backend_base
        if not base:
            # If no base configured, just return the raw (could still work in dev)
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

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ Core ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def execute_task(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute document creation task."""
        results: Dict[str, Any] = {
            "status": "started",
            "executorUsed": self.executor_name,
            "artifacts": [],
            "summary": "",
            "executorFullResponse": "",
        }

        try:
            # Extract context
            context = task_data.get("context", {})
            user_request = context.get("userRequest", "").lower()
            api_key = task_data.get("apiKey")
            
            # Detect if user wants Desktop output
            save_to_desktop = any(trigger in user_request for trigger in [
                "save to desktop", "put on desktop", "save locally",
                "save to my desktop", "save on my computer"
            ])
            
            # Import the prompt from comprehensive_formatting_prompts
            from comprehensive_formatting_prompts import (
                DOCS_EXECUTOR_PROMPT,
                EXECUTOR_RESPONSE_FORMAT,
            )

            # Combine prompts
            full_prompt = DOCS_EXECUTOR_PROMPT + "\n\n" + EXECUTOR_RESPONSE_FORMAT

            # Add task context
            prompt = f"""{full_prompt}

## TASK DETAILS:
{json.dumps(task_data, indent=2)}

Now generate the Python code to create this document with professional formatting and all requested content.
"""

            # Generate code using LLM
            self.logger.info("Generating document creation code...")

            llm_response = await self.model.generate(
                system_prompt=(
                    "You are an expert Python programmer specializing in Word document creation using python-docx. "
                    "Create well-formatted, professional documents."
                ),
                prompt=prompt,
                temperature=0.7,
            )
            results["executorFullResponse"] = llm_response

            # Extract Python code from response
            code = self._extract_python_code(llm_response)
            if not code:
                raise Exception("No Python code found in LLM response")

            # Execute the code (sandboxed by ScriptExecutionManager)
            self.logger.info(f"Executing document creation code (save_to_desktop={save_to_desktop})...")
            
            execution_result = await self.script_manager.execute_code_directly(
                code=code,
                user_id=task_data.get("userId", "anonymous"),
                api_key=api_key,
                save_to_desktop=save_to_desktop
            )

            if execution_result.get("exit_code", 1) != 0:
                raise Exception(f"Code execution failed: {execution_result.get('error')}")

            # Collect created files and preview artifacts
            output_files: List[Dict[str, Any]] = execution_result.get("output_files", []) or []
            previews: List[Dict[str, Any]] = execution_result.get("artifacts", []) or []
            execution_mode = execution_result.get("execution_mode", "server")
            
            results["outputFiles"] = output_files
            results["previews"] = previews

            self.logger.info(
                f"DocsExecutor produced {len(output_files)} file(s), {len(previews)} preview(s) via {execution_mode}."
            )
            for f in output_files:
                # Prefer logging the finalized download link if present
                self.logger.info("Artifact URL: %s", f.get("download_url") or f.get("url") or f.get("public_url"))

            # Normalize output files to guarantee a valid download URL handling
            normalized_files: List[Dict[str, Any]] = []
            for f in output_files:
                filename = f.get("filename") or f.get("name") or "document.docx"
                
                # Handle local files (bridge execution)
                if f.get("status") == "local":
                    normalized_files.append({
                        "filename": filename,
                        "local_path": f.get("local_path", f"~/Desktop/{filename}"),
                        "type": self._guess_type_from_name(filename),
                        "status": "local",
                        "download_url": None
                    })
                    continue
                
                # Handle server files (normal execution)
                raw_primary = (
                    f.get("download_url")
                    or f.get("url")
                    or f.get("public_url")
                    or f.get("relative_url")
                    or ""
                )
                abs_primary = self._abs(raw_primary)

                # If ?download already present OR force_download is set, ensure it is a filename
                # otherwise strip boolean/empty download params to avoid SDK errors.
                if self.force_download or ("download=" in abs_primary):
                    final_url = self._ensure_download_filename(abs_primary, filename)
                else:
                    final_url = self._strip_download_param(abs_primary)

                # Store back for downstream consumers (frontend will use this directly)
                f["download_url"] = final_url
                f.setdefault("public_url", abs_primary)  # keep an absolute reference
                f.setdefault("type", f.get("type") or self._guess_type_from_name(filename))
                normalized_files.append(f)

            results["outputFiles"] = normalized_files

            # Build user-facing markdown with proper links (no '?download=true' booleans)
            if normalized_files:
                md_lines = ["", "### Created Files"]
                for f in normalized_files:
                    filename = f.get("filename", "file")
                    file_type = f.get("type", "")
                    
                    if f.get("status") == "local":
                        # Local file - show location
                        location = f.get("local_path", "Desktop")
                        md_lines.append(f"- ✓ **{filename}** (saved to {location})")
                    else:
                        # Server file - show download link
                        public_url = f.get("download_url") or ""
                        label = (
                            "Document"     if file_type == "document"     else
                            "Presentation" if file_type == "presentation" else
                            "Spreadsheet"  if file_type == "spreadsheet"  else
                            "Image"        if file_type == "image"        else
                            "PDF"          if file_type == "pdf"          else
                            "File"
                        )

                        if public_url:
                            md_lines.append(f"- **{filename}** — [Open]({public_url})  ({label})")
                        else:
                            md_lines.append(f"- **{filename}**  ({label})")

                # Previews (unchanged; already uses preview_url)
                if previews:
                    md_lines.append("")
                    md_lines.append("### Previews")
                    for pv in previews:
                        if pv.get("type") == "document_preview":
                            raw_preview = pv.get("preview_url") or pv.get("preview") or ""
                            pv_url = self._abs(raw_preview)
                            pv_name = pv.get("filename") or pv.get("original") or "preview.pdf"
                            if pv_url:
                                md_lines.append(f"- **{pv_name}** — [View PDF Preview]({pv_url})")

                results["executorFullResponse"] += "\n" + "\n".join(md_lines) + "\n"

            # Parse artifact from script stdout (optional)
            artifact = self._parse_artifact_from_output(execution_result.get("output", "") or "")
            if artifact:
                results["artifacts"] = [artifact]
                results["status"] = "completed"
                results["summary"] = f"Created document '{artifact.get('title', 'Untitled')}' with {len(artifact.get('sections', []))} sections"
            else:
                results["status"] = "completed"
                results["summary"] = "Created document"

        except Exception as e:
            self.logger.error(f"Docs executor error: {str(e)}")
            results["status"] = "error"
            results["error"] = str(e)
            results["summary"] = f"Error creating document: {str(e)}"

        return results

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ Parsing helpers ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _extract_python_code(self, response: str) -> str:
        """Extract Python code from LLM response."""
        # Look for fenced code blocks
        code_blocks = re.findall(r"```python\s+(.*?)\s+```", response, re.DOTALL | re.IGNORECASE)
        if code_blocks:
            return "\n\n".join(code_blocks).strip()

        # Fallback: try from first import/from line onward
        lines = response.splitlines()
        started = False
        buf: List[str] = []
        for line in lines:
            if line.strip().startswith(("import ", "from ")):
                started = True
            if started:
                buf.append(line)
        return "\n".join(buf).strip() if buf else ""

    def _parse_artifact_from_output(self, output: str) -> Optional[Dict[str, Any]]:
        """Parse ARTIFACT_JSON:{...} emitted by the generated script, if present."""
        try:
            match = re.search(r"ARTIFACT_JSON:\s*({.*?})\s*(?:\n|$)", output, re.DOTALL)
            if not match:
                return None

            artifact_str = match.group(1)

            # Quick normalizations
            artifact_str = artifact_str.replace("\\n", "\\\\n")
            # Allow single quotes — convert to double quotes naively
            # (safe enough for our controlled outputs)
            if "'" in artifact_str and '"' not in artifact_str:
                artifact_str = artifact_str.replace("'", '"')

            # If braces seem imbalanced, try to capture a full JSON object
            if artifact_str.count("{") != artifact_str.count("}"):
                json_start = output.find("ARTIFACT_JSON:") + len("ARTIFACT_JSON:")
                json_text = output[json_start:].strip()
                brace = 0
                end_pos = 0
                for i, ch in enumerate(json_text):
                    if ch == "{":
                        brace += 1
                    elif ch == "}":
                        brace -= 1
                        if brace == 0:
                            end_pos = i + 1
                            break
                if end_pos > 0:
                    artifact_str = json_text[:end_pos]

            return json.loads(artifact_str)
        except Exception as e:
            self.logger.error(f"Failed to parse artifact: {e}")
            return None