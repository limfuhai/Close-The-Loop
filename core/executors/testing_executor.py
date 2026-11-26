"""
Testing Executor - Playwright-based automated testing (WEB-STYLE OUTPUTS)
- Generates tests via LLM, executes with Playwright
- Writes artifacts under /tmp/opex/outputs (via ScriptExecutionManager)
- If OutputStorage is configured, uploads to Supabase and returns signed URLs
- Normalizes output shape like Docs/Sheets/Coding executors
"""

from __future__ import annotations

import re
import json
import logging
import os
import uuid
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse

from .base_executor import BaseExecutor
from ..execution.script_manager import ScriptExecutionManager
from ..execution.test_runner import PlaywrightTestRunner

# Optional Supabase storage helper (core/storage.py)
try:
    from ..storage import OutputStorage  # adjust import if your tree differs
    _HAS_OUTPUT_STORAGE = True
except Exception:
    OutputStorage = None  # type: ignore
    _HAS_OUTPUT_STORAGE = False


class TestingExecutor(BaseExecutor):
    """
    Executor that generates and runs Playwright tests from natural-language requirements,
    with Supabase upload + signed download URLs (parity with Coding/Docs/Sheets executors).
    """

    def __init__(self, mcp_manager, mcp_registry, model_client):
        # Keep consistent with your other executors
        super().__init__(mcp_manager, mcp_registry)
        self.logger = logging.getLogger(self.__class__.__name__)
        self.executor_name = "TestingExecutor"
        self.model = model_client

        # Prefer NEXT_PUBLIC_API_URL, fallback to BACKEND_URL, else empty
        self.backend_base = (
            os.getenv("NEXT_PUBLIC_API_URL")
            or os.getenv("BACKEND_URL")
            or ""
        ).rstrip("/")

        # Output directories aligned with ScriptExecutionManager
        self.script_manager = ScriptExecutionManager()
        # manager exposes e.g., /tmp/opex/outputs
        self.outputs_dir: Path = Path(self.script_manager.outputs_dir)
        self.outputs_dir.mkdir(parents=True, exist_ok=True)

        # Playwright runner (your implementation)
        self.test_runner = PlaywrightTestRunner()

        # Optional toggle to always force a download filename
        self.force_download = (os.getenv("OUTPUT_FORCE_DOWNLOAD", "false").lower() == "true")

    # ───────────────────────── URL Helpers (parity with Coding/Sheets) ─────────────────────────

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
        """Ensure `download=<filename>` is present (and not boolean). Preserve other params."""
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
        if n.endswith(".json"):
            return "json"
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
        """
        Execute: prompt LLM → generate Playwright code → run → collect/upload artifacts
        Returns normalized 'outputFiles', signed 'download_url' when Supabase is configured,
        plus user-facing markdown ("### Created Files" with [Open] links).
        """
        results: Dict[str, Any] = {
            "status": "started",
            "executorUsed": self.executor_name,
            "artifacts": [],
            "summary": "",
            "executorFullResponse": "",
            "outputFiles": [],
            "previews": [],
        }

        try:
            from comprehensive_formatting_prompts import TESTING_EXECUTOR_SYSTEM_PROMPT

            description: str = task_data.get("description", "") or ""
            requirements: List[str] = task_data.get("requirements", []) or []
            context: Dict[str, Any] = task_data.get("context", {}) or {}
            user_id: str = task_data.get("userId", "anonymous")

            # ── Build LLM prompt
            prompt = self._build_test_generation_prompt(description, requirements, context)

            # ── Generate Playwright test code
            self.logger.info("[%s] Generating Playwright test code...", self.executor_name)
            llm_response = await self.model.generate(
                prompt=prompt,
                system_prompt=TESTING_EXECUTOR_SYSTEM_PROMPT,
                max_tokens=4000,
                temperature=0.3,
            )
            results["executorFullResponse"] = llm_response

            # ── Extract code + metadata
            test_code = self._extract_test_code(llm_response)
            if not test_code:
                raise ValueError("No test code found in LLM response")

            test_metadata = self._extract_test_metadata(llm_response)
            test_name = test_metadata.get("name", "automated_test")

            # Append generation summary
            gen_summary = f"""
Test Generation Summary:
- Test Name: {test_name}
- Target URL: {test_metadata.get('url', 'Not specified')}
- Test Scenarios: {test_metadata.get('scenarios', 'Not specified')}
- Framework: Python Playwright

Executing tests...
"""
            results["executorFullResponse"] = gen_summary + "\n" + results["executorFullResponse"]

            # ── Execute tests
            self.logger.info("[%s] Executing test: %s", self.executor_name, test_name)
            execution_result = self.test_runner.run_test_from_code(
                test_code=test_code,
                test_name=test_name,
                timeout=60,
            )
            test_results = execution_result.get("test_results", {}) or {}

            # ── Summarize execution
            exec_summary = f"""
Test Execution Results:
- Status: {test_results.get('status', 'unknown')}
- Total Tests: {test_results.get('total_tests', 0)}
- Passed: {test_results.get('passed', 0)}
- Failed: {test_results.get('failed', 0)}
"""
            if test_results.get("errors"):
                exec_summary += f"- Errors: {len(test_results.get('errors', []))}\n"
                for err in (test_results.get("errors", []) or [])[:3]:
                    exec_summary += f"  • {str(err)[:100]}...\n"

            shot_list = test_results.get("screenshots", []) or []
            if shot_list:
                exec_summary += f"- Screenshots captured: {len(shot_list)}\n"

            # File locations provided by the runner
            test_file = execution_result.get("test_file")
            json_file = execution_result.get("json_file")
            exec_summary += f"""
Files Generated:
- Test Script: {test_file or 'N/A'}
- Results JSON: {json_file or 'N/A'}
- Location: /tmp/opex/outputs
"""

            results["executorFullResponse"] += exec_summary

            # ── Normalize + upload artifacts
            created_files: List[Dict[str, Any]] = []
            md_lines = ["", "### Created Files"]

            def _to_abs_path(p: Optional[str]) -> Optional[Path]:
                if not p:
                    return None
                pth = Path(p)
                return pth if pth.is_absolute() else (self.outputs_dir / pth.name)

            # Bundle candidate files: script, json, screenshots
            candidates: List[Tuple[str, Optional[Path]]] = []
            if test_file:
                candidates.append((Path(test_file).name, _to_abs_path(test_file)))
            if json_file:
                candidates.append((Path(json_file).name, _to_abs_path(json_file)))
            for s in shot_list:
                try:
                    nm = Path(s).name
                except Exception:
                    nm = f"screenshot_{uuid.uuid4().hex}.png"
                candidates.append((nm, _to_abs_path(s)))

            # For each file: ensure exists → local rel URL → optional Supabase upload → final download URL
            for fname, apath in candidates:
                if not apath:
                    continue
                try:
                    if not apath.exists():
                        # Some runners may return relative paths that do not match outputs_dir;
                        # if so, just skip silently.
                        self.logger.warning("[%s] File not found, skipping: %s", self.executor_name, apath)
                        continue

                    rel_url = f"/files/outputs/{apath.name}"
                    absolute_primary: Optional[str] = None
                    upload_meta: Dict[str, Any] = {}

                    if _HAS_OUTPUT_STORAGE:
                        try:
                            storage = OutputStorage()
                            upload_meta = storage.save_file_path(
                                file_path=str(apath),
                                user_id=user_id,
                                prefix="artifacts",  # keep same namespace as other executors
                            )
                            primary = (
                                upload_meta.get("download_url")
                                or upload_meta.get("url")
                                or upload_meta.get("public_url")
                                or upload_meta.get("path")
                                or ""
                            )
                            if primary:
                                absolute_primary = self._abs(primary)
                                self.logger.info("Uploaded to Supabase: %s", absolute_primary)
                        except Exception as upx:
                            self.logger.info("Supabase upload failed/skipped for %s: %s", apath.name, upx)

                    primary_url = absolute_primary or self._abs(rel_url) or rel_url
                    # Normalize download param
                    final_download = (
                        self._ensure_download_filename(primary_url, fname)
                        if (self.force_download or "download=" in primary_url)
                        else self._strip_download_param(primary_url)
                    )
                    storage_kind = "supabase" if absolute_primary else "local"
                    signed = bool(absolute_primary)

                    entry = {
                        "filename": fname,
                        "type": self._guess_type_from_name(fname),
                        "mimetype": _guess_mime_like(fname),
                        "url": (absolute_primary or rel_url),
                        "public_url": (absolute_primary or None),
                        "relative_url": rel_url,
                        "storage": storage_kind,
                        "signed": signed,
                        "size": apath.stat().st_size if apath.exists() else None,
                        "download_url": final_download,
                    }
                    # include raw path from storage meta if any
                    if upload_meta.get("path"):
                        entry["path"] = upload_meta["path"]

                    created_files.append(entry)
                    md_lines.append(f"- **{fname}** — [Open]({final_download})")

                except Exception as one_file_err:
                    self.logger.warning("[%s] Skipped file %s due to error: %s", self.executor_name, fname, one_file_err)

            # Attach outputs + artifacts
            results["outputFiles"] = created_files
            results["artifacts"] = [{
                "id": f"{self.executor_name}-{uuid.uuid4()}",
                "type": "test_results",
                "title": f"Playwright Test: {test_name}",
                "test_file": test_file,
                "results_file": json_file,
                "status": test_results.get("status"),
                "summary": {
                    "total": test_results.get("total_tests", 0),
                    "passed": test_results.get("passed", 0),
                    "failed": test_results.get("failed", 0),
                },
                "metadata": {
                    "timestamp": datetime.now().isoformat(),
                    "executor": self.executor_name,
                    "storage": "supabase" if any(f.get("storage") == "supabase" for f in created_files) else "local",
                    "signed": any(f.get("signed") for f in created_files),
                },
            }]

            # Append the "Created Files" markdown to the full response
            results["executorFullResponse"] += "\n" + "\n".join(md_lines) + "\n"

            # Final status/summary
            results["status"] = "completed"
            results["summary"] = (
                f"Executed {test_results.get('total_tests', 0)} tests: "
                f"{test_results.get('passed', 0)} passed, {test_results.get('failed', 0)} failed"
            )

        except Exception as e:
            self.logger.error("Testing executor error: %s", e)
            results["status"] = "error"
            results["error"] = str(e)
            results["summary"] = f"Test execution failed: {str(e)}"
            results["executorFullResponse"] += f"\n\nError: {str(e)}"

        return results

    # ───────────────────────── LLM helpers ─────────────────────────

    def _build_test_generation_prompt(self, description: str, requirements: List[str], context: Dict[str, Any]) -> str:
        prompt = f"""Generate Python Playwright test code for the following requirements:

Task Description: {description}

Specific Requirements:
"""
        for req in requirements:
            prompt += f"- {req}\n"

        if context.get("userRequest"):
            prompt += f"\nOriginal User Request: {context['userRequest']}\n"

        prompt += """
IMPORTANT: Generate complete, runnable Python code using the Playwright sync API.
The code should include:
1. All necessary imports
2. Test functions that can be executed directly
3. Proper error handling
4. Screenshot capture on failures
5. Clear test result output

Output the code in a format that clearly indicates test status (PASS/FAIL) for each test case.
"""
        return prompt

    def _extract_test_code(self, response: str) -> str:
        # ```python ... ``` preferred
        code_blocks = re.findall(r'```python\s*(.*?)\s*```', response, re.DOTALL)
        if code_blocks:
            return '\n\n'.join(code_blocks).strip()

        # TEST_CODE: ... sentinel
        match = re.search(r'TEST_CODE:\s*\n(.*?)(?=\n[A-Z_]+:|$)', response, re.DOTALL)
        if match:
            return match.group(1).strip()

        # Fallback: lines after playwright imports
        lines = response.splitlines()
        buf, in_code = [], False
        for ln in lines:
            if ('from playwright' in ln) or ('import playwright' in ln):
                in_code = True
            if in_code:
                if ln.startswith('---') or ln.startswith('==='):
                    break
                buf.append(ln)
        return "\n".join(buf).strip()

    def _extract_test_metadata(self, response: str) -> Dict[str, str]:
        metadata = {"name": "automated_test", "url": "unknown", "scenarios": "unknown"}

        nm = re.search(r'TEST_NAME:\s*(.+)', response)
        if nm:
            metadata["name"] = nm.group(1).strip().replace(' ', '_').lower()

        urlm = re.search(r'(?:TARGET_URL|URL):\s*(.+)', response)
        if urlm:
            metadata["url"] = urlm.group(1).strip()

        sc = re.search(r'(?:SCENARIOS|TEST_SCENARIOS):\s*(.+)', response)
        if sc:
            metadata["scenarios"] = sc.group(1).strip()

        return metadata


# ───────────────────────── Mime helper (simple guesser) ─────────────────────────
def _guess_mime_like(name: str) -> str:
    n = (name or "").lower()
    if n.endswith(".json"):
        return "application/json"
    if n.endswith(".py"):
        return "text/x-python"
    if n.endswith(".png"):
        return "image/png"
    if n.endswith(".jpg") or n.endswith(".jpeg"):
        return "image/jpeg"
    if n.endswith(".gif"):
        return "image/gif"
    if n.endswith(".webp"):
        return "image/webp"
    return "application/octet-stream"
