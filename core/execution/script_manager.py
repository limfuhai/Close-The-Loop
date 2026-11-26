# react/core/execution/script_manager.py
"""
Script execution manager that handles Python script generation, storage, and execution.
- Saves generated scripts to /tmp/opex/scripts
- Executes them with cwd=/tmp/opex/outputs (default) or a caller-provided cwd
- Detects artifacts (docx/xlsx/pptx/png/pdf/other)
- Creates preview PDFs (pure-Python; Windows COM if available)
- Uploads artifacts (+ previews) to Supabase Storage when configured
- Returns download URLs (signed Supabase URLs or local /files/... fallback)
"""

import os
import json
import asyncio
import subprocess
import logging
from datetime import datetime
from typing import Dict, Any, Optional, List, Union
from pathlib import Path
import platform
import uuid

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from PIL import Image  # noqa: F401  (used by ReportLab's ImageReader path)

# OPTIONAL win32 for Windows-only conversion; safe on Linux
try:
    import win32com.client as win32  # type: ignore
except Exception:
    win32 = None

# Wire in unified storage helper (your file lives at core/storage.py)
try:
    from core.storage import OutputStorage
except Exception:
    OutputStorage = None  # type: ignore


class ScriptExecutionManager:
    """
    Manages the lifecycle of generated Python scripts.

    Responsibilities:
    1) Create /tmp/opex directory structure
    2) Save generated scripts
    3) Execute scripts in isolated subprocess (cwd=/tmp/opex/outputs)
    4) Detect and return resulting files with stable download URLs
    5) Create preview PDFs for office/image artifacts
    6) Upload everything to Supabase (if configured), else serve locally
    """

    def __init__(self, compiler_service=None):
        self.logger = logging.getLogger(self.__class__.__name__)

        self.base_dir = "/tmp/opex"
        self.scripts_dir = os.path.join(self.base_dir, "scripts")
        self.outputs_dir = os.path.join(self.base_dir, "outputs")   # served at /files/outputs
        self.logs_dir = os.path.join(self.base_dir, "logs")         # served at /files/logs
        self.preview_dir = os.path.join(self.base_dir, "preview")   # served at /files/preview

        for d in (self.base_dir, self.scripts_dir, self.outputs_dir, self.logs_dir, self.preview_dir):
            os.makedirs(d, exist_ok=True)

        self.logger.info(f"Script execution environment initialized at: {self.base_dir}")

        self.execution_history: List[Dict[str, Any]] = []
        self.python_executable = self._find_python_executable()

        # Instantiate unified storage (Supabase preferred, local fallback)
        self.storage = OutputStorage() if OutputStorage else None

        # NEW: Bridge support
        self.compiler_service = compiler_service
        self.bridge_command_timeout = 300  # 5 minutes default
        self.bridge_poll_interval = 0.5    # Poll every 500ms

    # ──────────────────────────────────────────────────────────────────────────
    # Utilities
    # ──────────────────────────────────────────────────────────────────────────

    def _find_python_executable(self) -> str:
        candidates = ["python3", "python", "python3.12", "python3.11", "python3.10", "python3.9", "py"]
        for exe in candidates:
            try:
                res = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=5)
                if res.returncode == 0:
                    self.logger.info(f"Using Python executable: {exe}")
                    return exe
            except (subprocess.SubprocessError, FileNotFoundError):
                continue
        self.logger.warning("Could not verify Python executable, defaulting to 'python'")
        return "python"

    def _url(self, area: str, filename: str) -> str:
        """Relative URL for local fallback (frontend should prefix with NEXT_PUBLIC_API_URL)."""
        return f"/files/{area}/{filename}"

    # ──────────────────────────────────────────────────────────────────────────
    # Script save & exec
    # ──────────────────────────────────────────────────────────────────────────

    async def save_script(self, code: str, script_name: Optional[str] = None) -> str:
        if not script_name:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
            script_name = f"generated_script_{ts}.py"
        if not script_name.endswith(".py"):
            script_name += ".py"
        path = os.path.join(self.scripts_dir, script_name)
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(code)
            self.logger.info(f"Script saved: {path}")
            return path
        except Exception as e:
            msg = f"Failed to save script: {e}"
            self.logger.error(msg)
            raise RuntimeError(msg)

    async def execute_script(
        self,
        script_path: str,
        timeout: int = 300,
        *,
        user_id: str = "anonymous",
        cwd: Optional[Union[str, Path]] = None,
    ) -> Dict[str, Any]:
        """Execute a saved script; detect & upload outputs; return normalized result."""
        self.logger.info(f"Executing script: {script_path}")
        start_ts = datetime.now().timestamp()
        working_dir = str(cwd) if cwd else self.outputs_dir
        os.makedirs(working_dir, exist_ok=True)  # add this line right after working_dir is set
        
        try:
            env = os.environ.copy()
            # project_root: react/core/execution/... → react/
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            env["PYTHONPATH"] = f"{project_root}{os.pathsep}{self.scripts_dir}"

            proc = await asyncio.create_subprocess_exec(
                self.python_executable,
                script_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=working_dir,   # all script-created files land here
                env=env
            )

            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
                exit_code = proc.returncode
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return {
                    "exit_code": 1,
                    "status": "error",
                    "error": f"Script execution timed out after {timeout} seconds",
                    "output": "",
                    "script_path": script_path,
                    "output_files": []
                }

            out = stdout.decode("utf-8", errors="replace")
            err = stderr.decode("utf-8", errors="replace")

            self.execution_history.append({
                "script_path": script_path,
                "timestamp": datetime.now().isoformat(),
                "exit_code": exit_code,
                "stdout_length": len(out),
                "stderr_length": len(err)
            })

            await self._save_execution_log(script_path, exit_code, out, err, working_dir=working_dir)

            # Detect files created after start_ts
            detected_files = self._detect_output_files(start_ts, base_dir=working_dir)

            # Upload artifacts to Supabase (or keep local) and return unified download URLs
            linked_files = await self._export_and_link(detected_files, user_id=user_id, area="outputs")

            result: Dict[str, Any]
            if exit_code == 0:
                result = {
                    "exit_code": 0,
                    "status": "completed",
                    "output": out,
                    "error": err if err else None,
                    "script_path": script_path,
                    "output_files": linked_files
                }
            else:
                result = {
                    "exit_code": exit_code,
                    "status": "error",
                    "error": err if err else f"Script failed with exit code {exit_code}",
                    "output": out,
                    "script_path": script_path,
                    "output_files": linked_files
                }

            # Build previews for office/image artifacts and upload them too
            artifacts: List[Dict[str, Any]] = []
            for f in result["output_files"]:
                if f.get("type") in {"presentation", "spreadsheet", "document", "image"}:
                    pdf = self._convert_to_pdf(f["local_path"])
                    if pdf:
                        preview_info = await self._export_single_file(pdf, user_id=user_id, area="preview")
                        if preview_info:
                            artifacts.append({
                                "type": "document_preview",
                                "original": f["download_url"],                    # signed/local
                                "preview": preview_info.get("signed_url") or preview_info.get("download_url"),
                                "filename": f["filename"],
                                "document_type": f["type"],
                                "preview_url": preview_info.get("signed_url") or preview_info.get("download_url")
                            })
            result["artifacts"] = artifacts

            return result

        except Exception as e:
            msg = f"Script execution failed: {e}"
            self.logger.error(msg)
            return {
                "exit_code": 1,
                "status": "error",
                "error": msg,
                "output": "",
                "script_path": script_path,
                "output_files": [],
                "artifacts": []
            }

    async def execute_code_directly(
        self,
        code: str,
        script_name: Optional[str] = None,
        timeout: int = 300,
        *,
        user_id: str = "anonymous",
        api_key: Optional[str] = None,      # NEW: For bridge authentication
        prefer_local: bool = False,          # NEW: Hint to use bridge if available
        save_to_desktop: bool = False        # NEW: Force bridge + Desktop path
    ) -> Dict[str, Any]:
        """
        Execute code via best available method:
        - If bridge available + (prefer_local OR save_to_desktop) → Execute via bridge
        - Otherwise → Execute on server (existing behavior)
        
        Args:
            code: Python code to execute
            script_name: Optional script filename
            timeout: Execution timeout in seconds
            user_id: User identifier (for server execution)
            api_key: User's Unkey API key (for bridge execution)
            prefer_local: Hint to prefer bridge if available
            save_to_desktop: Force bridge execution with Desktop path
            
        Returns:
            Same format as before:
            {
                "exit_code": 0,
                "status": "completed",
                "output": "stdout",
                "error": "stderr or None",
                "execution_mode": "server" | "bridge",  # NEW: Track where it ran
                "output_files": [...],
                "artifacts": [...]
            }
        """
        
        # Check if bridge execution requested and available
        if (prefer_local or save_to_desktop) and api_key:
            bridge_available = await self._check_bridge_available(api_key)
            
            if bridge_available:
                self.logger.info("Executing via bridge (local machine)")
                return await self._execute_via_bridge(
                    code=code,
                    api_key=api_key,
                    timeout=timeout,
                    save_to_desktop=save_to_desktop
                )
            else:
                self.logger.warning("Bridge requested but not available, falling back to server")
        
        # Default: Server execution (UNCHANGED - existing code path)
        self.logger.info("Executing via server")
        try:
            path = await self.save_script(code, script_name)
            result = await self.execute_script(path, timeout, user_id=user_id)
            result["execution_mode"] = "server"  # NEW: Track execution mode
            return result
        except Exception as e:
            return {
                "exit_code": 1,
                "status": "error",
                "error": str(e),
                "output": "",
                "script_path": None,
                "output_files": [],
                "artifacts": [],
                "execution_mode": "server"
            }

    # ──────────────────────────────────────────────────────────────────────────
    # Artifact detection
    # ──────────────────────────────────────────────────────────────────────────

    def _detect_output_files(self, since_timestamp: float, base_dir: Optional[str] = None) -> List[Dict[str, Any]]:
        root = base_dir or self.outputs_dir
        files: List[Dict[str, Any]] = []
        try:
            for dirpath, _, filenames in os.walk(root):
                for name in filenames:
                    p = os.path.join(dirpath, name)
                    st = os.stat(p)
                    if st.st_mtime < since_timestamp:
                        continue
    
                    ext = os.path.splitext(name)[1].lower()
                    ftype = (
                        "presentation" if ext == ".pptx" else
                        "spreadsheet"  if ext == ".xlsx" else
                        "document"     if ext == ".docx" else
                        "image"        if ext in {".png", ".jpg", ".jpeg", ".gif"} else
                        "pdf"          if ext == ".pdf" else
                        "other"
                    )
    
                    # URL: keep it under /files/outputs/<relative>
                    rel_path = os.path.relpath(p, self.outputs_dir)
                    info = {
                        "filename": rel_path,                 # preserve subfolders (e.g., sites/abc/index.html)
                        "local_path": p,
                        "size": st.st_size,
                        "created": datetime.fromtimestamp(st.st_mtime).isoformat(),
                        "type": ftype,
                        "url": self._url("outputs", rel_path.replace("\\", "/")),
                    }
                    files.append(info)
                    self.logger.info(f"Detected output file: {rel_path}")
        except Exception as e:
            self.logger.error(f"Error detecting output files: {e}")
        return files
    # ──────────────────────────────────────────────────────────────────────────
    # Pure-Python preview helpers + Windows COM
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _docx_to_preview_pdf(docx_path: str, pdf_path: str) -> bool:
        try:
            from docx import Document
            doc = Document(docx_path)
            c = canvas.Canvas(pdf_path, pagesize=letter)
            width, height = letter
            x, y = 1 * inch, height - 1 * inch
            line_h = 14

            c.setFont("Helvetica-Bold", 14)
            c.drawString(x, y, "DOCX preview (text-only)")
            y -= 20
            c.setFont("Helvetica", 11)

            lines = 0
            for para in doc.paragraphs:
                text = (para.text or "").strip()
                if not text:
                    continue
                for chunk in [text[i:i + 100] for i in range(0, len(text), 100)]:
                    if y < 1 * inch:
                        c.showPage(); y = height - 1 * inch; c.setFont("Helvetica", 11)
                    c.drawString(x, y, chunk)
                    y -= line_h
                    lines += 1
                    if lines > 800:
                        break
                if lines > 800:
                    break

            c.showPage(); c.save()
            return True
        except Exception:
            return False

    @staticmethod
    def _pptx_to_preview_pdf(pptx_path: str, pdf_path: str) -> bool:
        try:
            from pptx import Presentation
            prs = Presentation(pptx_path)
            c = canvas.Canvas(pdf_path, pagesize=letter)
            width, height = letter
            x, y = 1 * inch, height - 1 * inch
            line_h = 14

            c.setFont("Helvetica-Bold", 14)
            c.drawString(x, y, "PPTX preview (slide texts)")
            y -= 24
            c.setFont("Helvetica", 11)

            for idx, slide in enumerate(prs.slides, start=1):
                if y < 1 * inch:
                    c.showPage(); y = height - 1 * inch; c.setFont("Helvetica", 11)
                c.setFont("Helvetica-Bold", 12)
                c.drawString(x, y, f"Slide {idx}")
                y -= 18
                c.setFont("Helvetica", 11)

                texts = []
                for sh in slide.shapes:
                    if hasattr(sh, "text") and sh.text:
                        t = sh.text.strip()
                        if t:
                            texts.append(t)
                joined = "\n".join(texts)

                if joined:
                    for para in joined.splitlines():
                        for chunk in [para[i:i + 100] for i in range(0, len(para), 100)]:
                            if y < 1 * inch:
                                c.showPage(); y = height - 1 * inch; c.setFont("Helvetica", 11)
                            c.drawString(x, y, chunk)
                            y -= line_h
                y -= 8

            c.showPage(); c.save()
            return True
        except Exception:
            return False

    @staticmethod
    def _xlsx_to_preview_pdf(xlsx_path: str, pdf_path: str, max_rows: int = 30, max_cols: int = 8) -> bool:
        try:
            from openpyxl import load_workbook
            wb = load_workbook(xlsx_path, read_only=True, data_only=True)
            ws = wb.active

            c = canvas.Canvas(pdf_path, pagesize=letter)
            width, height = letter
            x0, y = 0.75 * inch, height - 0.75 * inch
            line_h = 14
            col_w = (width - 1.5 * inch) / max_cols

            c.setFont("Helvetica-Bold", 14)
            c.drawString(x0, y, f"XLSX preview (sheet: {ws.title})")
            y -= 22
            c.setFont("Helvetica", 10)
            c.setLineWidth(0.5)

            rows = ws.iter_rows(min_row=1, max_row=max_rows, max_col=max_cols, values_only=True)
            for r in rows:
                if y < 1 * inch:
                    c.showPage(); y = height - 0.75 * inch; c.setFont("Helvetica", 10); c.setLineWidth(0.5)
                x = x0
                for val in r:
                    txt = "" if val is None else str(val)
                    txt = (txt[:18] + "…") if len(txt) > 20 else txt
                    c.drawString(x + 2, y, txt)
                    c.line(x, y + 12, x, y - 2)  # vertical
                    x += col_w
                c.line(x, y + 12, x, y - 2)      # right border
                c.line(x0, y + 12, x, y + 12)    # row top
                y -= line_h

            c.line(x0, y + 12, x0 + col_w * max_cols, y + 12)  # bottom
            c.showPage(); c.save()
            wb.close()
            return True
        except Exception:
            return False

    def _convert_to_pdf(self, file_path: str) -> Optional[str]:
        """
        Convert/preview to PDF:
        - Windows + win32com: real Office->PDF
        - Otherwise: pure-Python previews
        - PNG: embed image in a PDF page
        """
        try:
            ext = os.path.splitext(file_path)[1].lower()
            base = os.path.splitext(os.path.basename(file_path))[0]
            os.makedirs(self.preview_dir, exist_ok=True)
            pdf_path = os.path.join(self.preview_dir, f"{base}.pdf")

            # Windows COM conversion (when available)
            if platform.system() == "Windows" and win32 is not None and ext in {".xlsx", ".docx", ".pptx"}:
                try:
                    abs_in = os.path.abspath(file_path)
                    abs_out = os.path.abspath(pdf_path)
                    if ext == ".xlsx":
                        excel = win32.Dispatch("Excel.Application"); excel.Visible = False
                        wb = excel.Workbooks.Open(abs_in)
                        wb.ExportAsFixedFormat(0, abs_out)
                        wb.Close(False); excel.Quit()
                    elif ext == ".docx":
                        word = win32.Dispatch("Word.Application"); word.Visible = False
                        doc = word.Documents.Open(abs_in)
                        doc.SaveAs2(abs_out, FileFormat=17)
                        doc.Close(); word.Quit()
                    elif ext == ".pptx":
                        ppt = win32.Dispatch("PowerPoint.Application")
                        pres = ppt.Presentations.Open(abs_in, WithWindow=False)
                        pres.SaveAs(abs_out, 32)
                        pres.Close(); ppt.Quit()
                    self.logger.info(f"Converted {ext} to PDF via COM: {pdf_path}")
                    return pdf_path
                except Exception as e:
                    self.logger.error(f"COM conversion failed ({ext}): {e}")
                    # fall through to previews

            # Pure-Python previews
            if ext == ".docx":
                return pdf_path if self._docx_to_preview_pdf(file_path, pdf_path) else None
            if ext == ".pptx":
                return pdf_path if self._pptx_to_preview_pdf(file_path, pdf_path) else None
            if ext == ".xlsx":
                return pdf_path if self._xlsx_to_preview_pdf(file_path, pdf_path) else None
            if ext == ".png":
                try:
                    c = canvas.Canvas(pdf_path, pagesize=letter)
                    img = ImageReader(file_path)
                    iw, ih = img.getSize()
                    pw, ph = letter
                    scale = min(pw / iw, ph / ih, 1.0)
                    x = (pw - iw * scale) / 2
                    y = (ph - ih * scale) / 2
                    c.drawImage(file_path, x, y, width=iw * scale, height=ih * scale)
                    c.save()
                    self.logger.info(f"PNG to PDF preview created: {pdf_path}")
                    return pdf_path
                except Exception as e:
                    self.logger.error(f"PNG->PDF failed: {e}")
                    return None

            self.logger.warning(f"No PDF conversion/preview available for {ext}")
            return None

        except Exception as e:
            self.logger.error(f"PDF conversion error: {e}")
            return None

    # ──────────────────────────────────────────────────────────────────────────
    # Logs, cleanup, stats
    # ──────────────────────────────────────────────────────────────────────────

    async def _save_execution_log(self, script_path: str, exit_code: int, stdout: str, stderr: str, *, working_dir: Optional[str] = None):
        try:
            name = os.path.basename(script_path)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            log_name = f"{name}_{ts}.log"
            log_path = os.path.join(self.logs_dir, log_name)
            with open(log_path, "w", encoding="utf-8") as f:
                f.write(f"Script: {name}\n")
                f.write(f"Executed at: {datetime.now().isoformat()}\n")
                f.write(f"Exit Code: {exit_code}\n")
                f.write(f"Working Directory: {working_dir or self.outputs_dir}\n")
                f.write("\n" + "=" * 50 + " STDOUT " + "=" * 50 + "\n")
                f.write(stdout)
                f.write("\n" + "=" * 50 + " STDERR " + "=" * 50 + "\n")
                f.write(stderr)
        except Exception as e:
            self.logger.error(f"Failed to save execution log: {e}")

    async def cleanup_old_files(self, older_than_hours: int = 24) -> Dict[str, int]:
        removed = {"scripts": 0, "logs": 0, "outputs": 0, "preview": 0}
        cutoff = datetime.now().timestamp() - (older_than_hours * 3600)
        for directory, key in [
            (self.scripts_dir, "scripts"),
            (self.logs_dir, "logs"),
            (self.outputs_dir, "outputs"),
            (self.preview_dir, "preview"),
        ]:
            if not os.path.exists(directory):
                continue
            try:
                for name in os.listdir(directory):
                    p = os.path.join(directory, name)
                    if os.path.isfile(p) and os.stat(p).st_mtime < cutoff:
                        try:
                            os.remove(p)
                            removed[key] += 1
                        except Exception as e:
                            self.logger.warning(f"Failed to remove {p}: {e}")
            except Exception as e:
                self.logger.error(f"Cleanup failed for {directory}: {e}")
        if sum(removed.values()) > 0:
            self.logger.info(f"Cleanup complete: {removed}")
        return removed

    def get_execution_statistics(self) -> Dict[str, Any]:
        if not self.execution_history:
            return {
                "total_executions": 0,
                "successful_executions": 0,
                "failed_executions": 0,
                "success_rate": 0.0,
                "last_execution": None,
                "base_directory": self.base_dir,
                "python_executable": self.python_executable
            }
        total = len(self.execution_history)
        successful = sum(1 for e in self.execution_history if e.get("exit_code") == 0)
        failed = total - successful
        return {
            "total_executions": total,
            "successful_executions": successful,
            "failed_executions": failed,
            "success_rate": (successful / total * 100) if total > 0 else 0.0,
            "last_execution": self.execution_history[-1]["timestamp"],
            "base_directory": self.base_dir,
            "python_executable": self.python_executable
        }

    # ──────────────────────────────────────────────────────────────────────────
    # Export helpers (Supabase/local)
    # ──────────────────────────────────────────────────────────────────────────

    async def _export_and_link(self, files: List[Dict[str, Any]], *, user_id: str, area: str) -> List[Dict[str, Any]]:
        """
        Upload each detected file to Supabase (if configured); otherwise keep local.
        Returns file dicts with unified `download_url`.
        """
        linked: List[Dict[str, Any]] = []
        for f in files:
            uploaded = await self._export_single_file(f["local_path"], user_id=user_id, area=area)
            f_out = dict(f)
            if uploaded:
                f_out["download_url"] = uploaded.get("signed_url") or uploaded.get("download_url")
                f_out["path"] = uploaded.get("path")  # Supabase object path when available
            else:
                # fallback to local
                f_out["download_url"] = f["url"]
            linked.append(f_out)
        return linked

    async def _export_single_file(self, local_path: str, *, user_id: str, area: str) -> Optional[Dict[str, Any]]:
        """
        Upload a single local file path to Supabase (if available), else return local URL info.
        """
        try:
            name = os.path.basename(local_path)
            _, ext = os.path.splitext(name)
            with open(local_path, "rb") as fh:
                data = fh.read()

            if self.storage:
                info = self.storage.save_bytes(
                    data,
                    ext=ext or "",
                    filename=name,
                    user_id=user_id,
                    local_dir=os.path.join(self.base_dir, area)  # local fallback dir (/tmp/opex/outputs or /preview)
                )
                return info
            else:
                return {"download_url": self._url(area, name), "filename": name}
        except Exception as e:
            self.logger.error(f"Failed to export {local_path}: {e}")
            return None

    async def _check_bridge_available(self, api_key: str) -> bool:
        """
        Check if bridge is connected for this user.
        
        Returns:
            True if bridge is actively polling and ready
        """
        
        if not self.compiler_service:
            return False
        
        try:
            # Check if this API key has active bridge connection
            # Bridge is "available" if it's actively polling /api/bridge/poll
            
            # TODO: Implement actual check via compiler
            # For now, assume available if compiler_service exists
            # Real implementation should check:
            # - Is bridge_command_queues[api_key] being polled?
            # - When was last poll? (< 10 seconds ago = active)
            
            return True  # Placeholder
            
        except Exception as e:
            self.logger.error(f"Bridge availability check failed: {e}")
            return False

    def _modify_code_for_desktop(self, code: str) -> str:
        """
        Modify code to save files to Desktop instead of current directory.
        
        Prepends Desktop path detection and cwd change to code.
        """
        
        desktop_setup = '''
    import os
    from pathlib import Path

    # Auto-detect Desktop path
    if os.name == 'nt':  # Windows
        DESKTOP_PATH = Path.home() / "Desktop"
    else:  # macOS/Linux
        DESKTOP_PATH = Path.home() / "Desktop"

    # Create Desktop if it doesn't exist (unlikely but safe)
    DESKTOP_PATH.mkdir(exist_ok=True)

    # Change working directory to Desktop
    os.chdir(DESKTOP_PATH)

    print(f"Working directory set to: {DESKTOP_PATH}")

    '''
        
        return desktop_setup + "\n" + code

    def _parse_desktop_files(self, stdout: str) -> List[Dict[str, Any]]:
        """
        Parse stdout to detect files created on Desktop.
        
        Looks for patterns like:
        - "Created: filename.docx"
        - "Saved to: /path/to/Desktop/file.pdf"
        
        Returns:
            List of file info dicts (no download URLs - files are local)
        """
        
        files = []
        
        # Simple pattern matching (can be enhanced)
        for line in stdout.split("\n"):
            if "Created:" in line or "Saved to:" in line or "Written:" in line:
                # Extract filename
                parts = line.split(":")
                if len(parts) >= 2:
                    filename = parts[-1].strip()
                    
                    files.append({
                        "filename": filename,
                        "local_path": f"~/Desktop/{filename}",
                        "type": self._guess_type_from_name(filename),
                        "status": "local",  # Indicates file is on user's machine
                        "download_url": None  # No URL - file is local
                    })
        
        return files


    def _guess_type_from_name(self, name: str) -> str:
        """Guess file type from filename (existing method - no changes)."""
        name_lower = (name or "").lower()
        if name_lower.endswith(".docx"):
            return "document"
        if name_lower.endswith(".pptx"):
            return "presentation"
        if name_lower.endswith(".xlsx"):
            return "spreadsheet"
        if name_lower.endswith(".pdf"):
            return "pdf"
        return "file"