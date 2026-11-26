"""
Data Executor - Generates JSONL training data from gathered documents
Converts ProjectSearchExecutor results into Axolotl-compatible JSONL format
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


class DataExecutor(BaseExecutor):
    """Executor for generating JSONL training data from documents."""

    def __init__(self, mcp_manager, mcp_registry, model_client):
        super().__init__(mcp_manager, mcp_registry)
        self.logger = logging.getLogger(__name__)
        self.executor_name = "DataExecutor"
        self.model = model_client
        self.script_manager = ScriptExecutionManager()
        self.backend_base = (os.getenv("NEXT_PUBLIC_API_URL") or "").rstrip("/")
        self.force_download = (os.getenv("OUTPUT_FORCE_DOWNLOAD", "false").lower() == "true")

    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ URL Helper Methods â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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
        if name_lower.endswith(".jsonl"):
            return "training_data"
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

    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ Main Execution â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    async def execute_task(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute training data generation task."""
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
                DATA_EXECUTOR_PROMPT,
                EXECUTOR_RESPONSE_FORMAT,
            )

            # Combine prompts
            full_prompt = DATA_EXECUTOR_PROMPT + "\n\n" + EXECUTOR_RESPONSE_FORMAT

            # Extract context from task_data
            context = task_data.get("context", {})
            
            # FIX: Extract gathered content from previous executor results
            gathered_content = self._extract_gathered_content(context)
            
            # Extract other context
            company_name = context.get("companyName", "Customer")
            document_topics = context.get("documentTopics", [])

            # Log what we received
            self.logger.info(f"DataExecutor received {len(gathered_content)} characters of content")

            # Add task context
            prompt = f"""{full_prompt}

## TASK DETAILS:

**Company Name:** {company_name}

**Gathered Document Content:**
{gathered_content}

**Document Topics Covered:**
{', '.join(document_topics) if document_topics else 'Various topics'}

**Your Task:**
Generate Python code that creates training_data.jsonl with 100-500 diverse QA examples based on the gathered content above.

Remember:
- Extract answers directly from the content provided
- Never invent information not present in the documents
- Cover all topics comprehensively
- Vary question phrasing for diversity
- Use proper JSONL format (newline-delimited JSON)

Generate the complete Python code now!
"""

            # Generate code using LLM
            self.logger.info("Generating training data generation code...")

            llm_response = await self.model.generate(
                system_prompt=(
                    "You are an expert Python programmer specializing in LLM training data generation. "
                    "Create high-quality, diverse training datasets in JSONL format."
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
            self.logger.info("Executing training data generation code...")
            execution_result = await self.script_manager.execute_code_directly(
                code, user_id=task_data.get("userId", "anonymous")
            )

            if execution_result.get("exit_code", 1) != 0:
                raise Exception(f"Code execution failed: {execution_result.get('error')}")

            # Collect created files
            output_files: List[Dict[str, Any]] = execution_result.get("output_files", []) or []
            
            # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â• NEW: Normalize URLs â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
            normalized_files: List[Dict[str, Any]] = []
            for f in output_files:
                filename = f.get("filename") or f.get("name") or "training_data.jsonl"
                raw_primary = (
                    f.get("download_url")
                    or f.get("url")
                    or f.get("public_url")
                    or f.get("relative_url")
                    or ""
                )
                abs_primary = self._abs(raw_primary)

                # Handle download parameter
                if self.force_download or ("download=" in abs_primary):
                    final_url = self._ensure_download_filename(abs_primary, filename)
                else:
                    final_url = self._strip_download_param(abs_primary)

                # Store normalized URLs
                f["download_url"] = final_url
                f.setdefault("public_url", abs_primary)
                f.setdefault("type", f.get("type") or self._guess_type_from_name(filename))
                normalized_files.append(f)

            results["outputFiles"] = normalized_files
            # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

            self.logger.info(
                "DataExecutor produced %d file(s).",
                len(normalized_files),
            )

            # Find the JSONL file (clusters format from DataExecutor)
            jsonl_file = None
            for f in normalized_files:
                filename = f.get("filename", "")
                if filename.endswith(".jsonl"):
                    jsonl_file = f
                    break

            if not jsonl_file:
                raise Exception("No JSONL file generated")

            # Expand clusters to full training data format
            try:
                from ..execution.training_data_manager import TrainingDataManager
                
                manager = TrainingDataManager(logger=self.logger)
                company_name = context.get("companyName", "Customer")
                
                # Expand clusters to full JSONL format
                full_jsonl_path, num_examples = manager.expand_clusters_to_jsonl(
                    cluster_file_path=jsonl_file.get("local_path"),
                    company_name=company_name
                )
                
                # Update file reference to point to expanded training_data.jsonl
                jsonl_file["local_path"] = full_jsonl_path
                jsonl_file["filename"] = "training_data.jsonl"
                
                self.logger.info(f"✅ Expanded to {num_examples} training examples")
                
            except Exception as e:
                self.logger.error(f"Failed to expand training data: {str(e)}")
                raise

            # Now trigger Modal operations via tuner_execution
            try:
                from ..execution.tuner_execution import TunerExecutionManager
                
                tuner_manager = TunerExecutionManager(logger=self.logger)
                
                # Process training data (uploads to R2, triggers Modal, stores URL)
                tuner_result = await tuner_manager.process_training_data(
                    jsonl_path=jsonl_file.get("local_path"),
                    task_data=task_data
                )
                
                # Add tuner info to results
                results["customerId"] = tuner_result.get("customer_id")
                results["servingUrl"] = tuner_result.get("serving_url")
                results["tunerStatus"] = tuner_result.get("status")
                results["num_examples"] = tuner_result.get("num_examples")
                
                self.logger.info(f"âœ… Tuner operations completed for customer: {tuner_result.get('customer_id')}")
                
            except Exception as e:
                # Modal operations failed (expected in testing)
                self.logger.warning(f"âš ï¸ Modal operations failed: {str(e)}")
                results["tunerError"] = str(e)
                # Don't fail the whole task - training data was still created

            # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â• NEW: Build markdown with links â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
            md_lines = ["", "### Training Data Generated âœ…"]
            
            
            # Get training example count from tuner result
            example_count = results.get("num_examples", 0)
            
            md_lines.append(f"**Training Examples**: {example_count}")
            md_lines.append("")
            
            # Add downloadable link
            if normalized_files:
                md_lines.append("### Created Files")
                for f in normalized_files:
                    filename = f.get("filename", "file")
                    file_type = f.get("type", "")
                    public_url = f.get("download_url") or ""
                    
                    label = (
                        "Training Data" if file_type == "training_data" else
                        "Document" if file_type == "document" else
                        "File"
                    )
                    
                    if public_url:
                        md_lines.append(f"- **{filename}** â€“ [Download]({public_url})  ({label})")
                    else:
                        md_lines.append(f"- **{filename}**  ({label})")
                md_lines.append("")
            # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
            
            if results.get("tunerError"):
                md_lines.append("âš ï¸ **Warning**: Modal operations failed")
                md_lines.append(f"**Error**: {results['tunerError']}")
                md_lines.append("**Training data is ready** but finetuning was not triggered")
            else:
                md_lines.append(f"**Customer ID**: {results.get('customerId')}")
                md_lines.append(f"**Serving URL**: {results.get('servingUrl')}")
                md_lines.append("âœ… **Finetuning initiated** (will take 2-3 hours)")

            results["executorFullResponse"] += "\n" + "\n".join(md_lines) + "\n"

            results["status"] = "completed"
            results["summary"] = "Generated JSONL training data"
            results["jsonlFile"] = jsonl_file

        except Exception as e:
            self.logger.error(f"Data executor error: {str(e)}")
            results["status"] = "error"
            results["error"] = str(e)
            results["summary"] = f"Error generating training data: {str(e)}"

        return results

    def _extract_gathered_content(self, context: Dict[str, Any]) -> str:
        """
        Extract gathered document content from previous executor results.
        
        This is the FIX for the information relay pipeline connection.
        """
        gathered_content = ""
        
        # First, try to get from previousResults (the correct pipeline way)
        previous_results = context.get("previousResults", [])
        
        for result in previous_results:
            executor_used = result.get("executorUsed", "")
            
            # Look for ProjectSearchExecutor results
            if executor_used == "ProjectSearchExecutor":
                # Extract content from execution details
                execution_details = result.get("executionDetails", "")
                if execution_details:
                    gathered_content += execution_details + "\n\n"
                
                # Also check executorFullResponse
                full_response = result.get("executorFullResponse", "")
                if full_response and full_response not in gathered_content:
                    gathered_content += full_response + "\n\n"
        
        # Fallback: Check if content was passed directly (backward compatibility)
        if not gathered_content:
            gathered_content = context.get("gatheredContent", "")
        
        # Final fallback: Try to extract from initialSummary if it contains document content
        if not gathered_content:
            initial_summary = context.get("initialSummary", "")
            # Only use if it's substantial (more than just a summary)
            if len(initial_summary) > 2000:
                gathered_content = initial_summary
        
        return gathered_content.strip()

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