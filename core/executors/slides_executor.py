"""
Google Slides Executor - Local Generation Version
Creates PowerPoint presentations using python-pptx
- Executes LLM-generated Python to build slides
- Saves artifacts via ScriptExecutionManager
- Normalizes URLs (keeps ?download=<filename> only when valid/desired)
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


class SlidesExecutor(BaseExecutor):
    """Executor for creating presentations using python-pptx."""

    def __init__(self, mcp_manager, mcp_registry, model_client):
        super().__init__(mcp_manager, mcp_registry)
        self.logger = logging.getLogger(__name__)
        self.executor_name = "SlidesExecutor"
        self.model = model_client
        # Use backend base so relative paths become absolute for the frontend
        self.backend_base = (os.getenv("NEXT_PUBLIC_API_URL") or "").rstrip("/")
        self.script_manager = ScriptExecutionManager()

        # Optional toggle: force ?download=<filename>
        # Default is False (strip boolean/empty download params)
        self.force_download = (os.getenv("OUTPUT_FORCE_DOWNLOAD", "false").lower() == "true")

    # ───────────────────────── Helpers ─────────────────────────

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
        """
        Remove `download` ONLY when empty/boolean-like. Keep string filenames.
        Avoids errors like: querystring/download must be string
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
        Ensure `download=<filename>` is present (not boolean). Preserve other params (e.g., Supabase tokens).
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
        name_lower = (name or "").lower()
        if name_lower.endswith(".pptx"):
            return "presentation"
        if name_lower.endswith(".xlsx"):
            return "spreadsheet"
        if name_lower.endswith(".docx"):
            return "document"
        if name_lower.endswith(".pdf"):
            return "pdf"
        if any(name_lower.endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".gif", ".webp")):
            return "image"
        return "file"

    # ───────────────────────── Core ─────────────────────────

    async def execute_task(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute presentation creation task."""
        results: Dict[str, Any] = {
            "status": "started",
            "executorUsed": self.executor_name,
            "artifacts": [],
            "summary": "",
            "executorFullResponse": "",
        }

        try:
            # Import the prompt from comprehensive_formatting_prompts
            from comprehensive_formatting_prompts import (
                SLIDES_EXECUTOR_PROMPT,
                EXECUTOR_RESPONSE_FORMAT,
            )

            # Combine prompts
            full_prompt = SLIDES_EXECUTOR_PROMPT + "\n\n" + EXECUTOR_RESPONSE_FORMAT

            # Add task context
            prompt = f"""{full_prompt}

## TASK DETAILS:
{json.dumps(task_data, indent=2)}

Now generate the Python code to create this presentation with professional dark themes and all requested content.
"""

            # Generate code using LLM
            self.logger.info("Generating presentation creation code...")

            llm_response = await self.model.generate(
                system_prompt=(
                    "You are an expert Python programmer specializing in PowerPoint "
                    "creation using python-pptx. Always create professional presentations with dark themes."
                ),
                prompt=prompt,
                temperature=0.7,
            )
            results["executorFullResponse"] = llm_response

            # Extract Python code from response
            code = self._extract_python_code(llm_response)
            if not code:
                raise Exception("No Python code found in LLM response")

            # Execute the code
            self.logger.info("Executing presentation creation code...")
            execution_result = await self.script_manager.execute_code_directly(
                code, user_id=task_data.get("userId", "anonymous")
            )

            if execution_result.get("exit_code", 1) != 0:
                raise Exception(f"Code execution failed: {execution_result.get('error')}")

            # Collect created files and preview artifacts
            output_files: List[Dict[str, Any]] = execution_result.get("output_files", []) or []
            previews: List[Dict[str, Any]] = execution_result.get("artifacts", []) or []

            # Normalize every file to guarantee a valid absolute URL and sane download param behavior
            normalized_files: List[Dict[str, Any]] = []
            for f in output_files:
                filename = f.get("filename") or f.get("name") or "presentation.pptx"

                # Prefer the server-provided download_url (Supabase signed / local), then fallbacks
                raw_primary = (
                    f.get("download_url")
                    or f.get("url")
                    or f.get("public_url")
                    or f.get("relative_url")
                    or ""
                )
                abs_primary = self._abs(raw_primary)

                # If force_download or the URL already includes ?download, ensure it's a filename
                # Otherwise strip boolean/empty download to avoid SDK errors
                final_url = (
                    self._ensure_download_filename(abs_primary, filename)
                    if (self.force_download or "download=" in abs_primary)
                    else self._strip_download_param(abs_primary)
                )

                # Store back for downstream consumers (frontend reads `download_url`)
                f["download_url"] = final_url
                f.setdefault("public_url", abs_primary)
                f.setdefault("type", f.get("type") or self._guess_type_from_name(filename))
                normalized_files.append(f)

            results["outputFiles"] = normalized_files
            results["previews"] = previews

            self.logger.info(
                "SlidesExecutor produced %d file(s), %d preview(s).",
                len(normalized_files),
                len(previews),
            )
            for f in normalized_files:
                self.logger.info("Artifact URL: %s", f.get("download_url"))

            # Build user-facing markdown (aligned with SheetsExecutor wording)
            if normalized_files:
                md_lines = ["", "### Created Files"]
                for f in normalized_files:
                    filename = f.get("filename", "file")
                    file_type = f.get("type", "")
                    public_url = f.get("download_url") or ""

                    label = (
                        "Spreadsheet" if file_type == "spreadsheet" else
                        "Presentation" if file_type == "presentation" else
                        "Document"     if file_type == "document"     else
                        "Image"        if file_type == "image"        else
                        "PDF"          if file_type == "pdf"          else
                        "File"
                    )

                    if public_url:
                        md_lines.append(f"- **{filename}** — [Open]({public_url})  ({label})")
                    else:
                        md_lines.append(f"- **{filename}**  ({label})")

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

            # Optional: parse artifact metadata from stdout
            artifact = self._parse_artifact_from_output(execution_result.get("output", "") or "")
            if artifact:
                results["artifacts"] = [artifact]
                results["status"] = "completed"
                results["summary"] = (
                    f"Created presentation '{artifact.get('title', 'Untitled')}' "
                    f"with {len(artifact.get('slides', []))} slides"
                )
            else:
                results["status"] = "completed"
                results["summary"] = "Created presentation"

        except Exception as e:
            self.logger.error(f"Slides executor error: {str(e)}")
            results["status"] = "error"
            results["error"] = str(e)
            results["summary"] = f"Error creating presentation: {str(e)}"

        return results

    # ───────────────────────── Parsing helpers ─────────────────────────

    def _extract_python_code(self, response: str) -> str:
        """Extract Python code from LLM response."""
        # Prefer fenced code blocks
        code_blocks = re.findall(r"```python\s+(.*?)\s+```", response, re.DOTALL | re.IGNORECASE)
        if code_blocks:
            return "\n\n".join(code_blocks).strip()

        # Fallback: from first import/from line onward
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
        """Parse ARTIFACT_JSON from execution output."""
        try:
            match = re.search(r"ARTIFACT_JSON:\s*({.*?})\s*(?:\n|$)", output, re.DOTALL)
            if not match:
                return None
            artifact_str = match.group(1)

            # Normalizations for safe JSON parsing
            artifact_str = artifact_str.replace("\\n", "\\\\n")
            if "'" in artifact_str and '"' not in artifact_str:
                artifact_str = artifact_str.replace("'", '"')

            # If braces seem imbalanced, attempt full-object capture
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
