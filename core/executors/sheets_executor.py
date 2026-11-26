"""
Google Sheets Executor - Local Generation Version
Creates Excel files using openpyxl, pandas, and matplotlib.
- Executes LLM-generated Python to build spreadsheets
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


class SheetsExecutor(BaseExecutor):
    """Executor for creating spreadsheets with data and charts using openpyxl."""

    def __init__(self, mcp_manager, mcp_registry, model_client):
        super().__init__(mcp_manager, mcp_registry)
        self.logger = logging.getLogger(__name__)
        self.executor_name = "SheetsExecutor"
        self.model = model_client
        # Use backend base so relative paths become absolute for the frontend
        self.backend_base = (os.getenv("NEXT_PUBLIC_API_URL") or "").rstrip("/")
        self.script_manager = ScriptExecutionManager()

        # Optional toggle: force ?download=<filename> if you explicitly want it.
        # Default is False.
        self.force_download = (
            os.getenv("OUTPUT_FORCE_DOWNLOAD", "false").lower() == "true"
        )

    # ───────────────────────── Helpers ─────────────────────────

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
        new_query = urlencode(q)
        return urlunparse(p._replace(query=new_query))

    @staticmethod
    def _guess_type_from_name(name: str) -> str:
        name_lower = (name or "").lower()
        if name_lower.endswith(".xlsx"):
            return "spreadsheet"
        if name_lower.endswith(".pptx"):
            return "presentation"
        if name_lower.endswith(".docx"):
            return "document"
        if name_lower.endswith(".pdf"):
            return "pdf"
        if any(name_lower.endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".gif", ".webp")):
            return "image"
        return "file"

    # ───────────────────────── Core ─────────────────────────

    async def execute_task(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute spreadsheet creation task."""
        results: Dict[str, Any] = {
            "status": "started",
            "executorUsed": self.executor_name,
            "artifacts": [],
            "summary": "",
            "executorFullResponse": "",
        }

        try:
            from comprehensive_formatting_prompts import (
                SHEETS_EXECUTOR_PROMPT,
                EXECUTOR_RESPONSE_FORMAT,
            )

            full_prompt = SHEETS_EXECUTOR_PROMPT + "\n\n" + EXECUTOR_RESPONSE_FORMAT

            prompt = f"""{full_prompt}

## TASK DETAILS:
{json.dumps(task_data, indent=2)}

Now generate the Python code to create this spreadsheet with all requested data, formatting, and charts.
"""

            self.logger.info("Generating spreadsheet creation code...")

            llm_response = await self.model.generate(
                system_prompt=(
                    "You are an expert Python programmer specializing in Excel file creation "
                    "using openpyxl, pandas, and matplotlib."
                ),
                prompt=prompt,
                temperature=0.7,
            )
            results["executorFullResponse"] = llm_response

            code = self._extract_python_code(llm_response)
            if not code:
                raise Exception("No Python code found in LLM response")

            self.logger.info("Executing spreadsheet creation code...")

            # Execute script and collect outputs (same pattern as SlidesExecutor)
            execution_result = await self.script_manager.execute_code_directly(
                code,
                user_id=task_data.get("userId", "anonymous"),
            )

            if execution_result.get("exit_code", 1) != 0:
                raise Exception(f"Code execution failed: {execution_result.get('error')}")

            # Collect created files and preview artifacts
            output_files: List[Dict[str, Any]] = execution_result.get("output_files", []) or []
            previews: List[Dict[str, Any]] = execution_result.get("artifacts", []) or []

            self.logger.info(
                "SheetsExecutor raw execution_result: output_files=%d, previews=%d",
                len(output_files),
                len(previews),
            )

            # Normalize every file to guarantee a valid absolute URL
            normalized_files: List[Dict[str, Any]] = []
            for f in output_files:
                filename = f.get("filename") or f.get("name") or "spreadsheet.xlsx"

                # Prefer server-provided download_url, then url/public_url/relative_url
                raw_primary = (
                    f.get("download_url")
                    or f.get("url")
                    or f.get("public_url")
                    or f.get("relative_url")
                    or ""
                )
                abs_primary = self._abs(raw_primary)

                # Ensure proper download parameter, same logic as SlidesExecutor
                final_url = (
                    self._ensure_download_filename(abs_primary, filename)
                    if (self.force_download or "download=" in abs_primary)
                    else self._strip_download_param(abs_primary)
                )

                f["download_url"] = final_url
                f.setdefault("public_url", abs_primary)
                f.setdefault("type", f.get("type") or self._guess_type_from_name(filename))

                normalized_files.append(f)

                # Helpful logging for debugging frontend issues
                self.logger.info(
                    "SheetsExecutor file normalized: name=%s, type=%s, download_url=%s, public_url=%s",
                    filename,
                    f.get("type"),
                    f.get("download_url"),
                    f.get("public_url"),
                )

            results["outputFiles"] = normalized_files
            results["previews"] = previews

            self.logger.info(
                "SheetsExecutor produced %d file(s), %d preview(s).",
                len(normalized_files),
                len(previews),
            )

            # Build user-facing markdown (same style as SlidesExecutor)
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

            # Parse ARTIFACT_JSON from stdout (same logic)
            artifact = self._parse_artifact_from_output(execution_result.get("output", "") or "")
            if artifact:
                results["artifacts"] = [artifact]
                results["status"] = "completed"
                results["summary"] = (
                    f"Created spreadsheet '{artifact.get('title', 'Untitled')}' "
                    f"with {len(artifact.get('sections', []))} sections"
                )
            else:
                results["status"] = "completed"
                results["summary"] = "Created spreadsheet"

        except Exception as e:
            self.logger.error(f"Sheets executor error: {str(e)}")
            results["status"] = "error"
            results["error"] = str(e)
            results["summary"] = f"Error creating spreadsheet: {str(e)}"

        return results

    # ───────────────────────── Parsing helpers ─────────────────────────

    def _extract_python_code(self, response: str) -> str:
        """Extract Python code from LLM response."""
        code_blocks = re.findall(r"```python\s+(.*?)\s+```", response, re.DOTALL | re.IGNORECASE)
        if code_blocks:
            return "\n\n".join(code_blocks).strip()

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

            artifact_str = artifact_str.replace("\\n", "\\\\n")
            if "'" in artifact_str and '"' not in artifact_str:
                artifact_str = artifact_str.replace("'", '"')

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
