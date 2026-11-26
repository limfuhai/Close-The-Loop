# TODO
import os
import json
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

from elasticsearch import Elasticsearch
from ..executors.base_executor import BaseExecutor


class ProjectSearchExecutor(BaseExecutor):
    """
    Executor for searching project documents using Elasticsearch.
    Objective: always return something useful for the user.
    Strategy:
      - Tier 1: multi_match over filename/content/path (forgiving, ranked)
      - Tier 2: wildcard over filename/path (handles underscores/partials)
      - Tier 3: recent docs fallback (avoid empty results)
    """

    def __init__(self, mcp_manager=None, mcp_registry=None, model_client=None):
        super().__init__(mcp_manager, mcp_registry)
        self.model_client = model_client
        self.logger = logging.getLogger(self.__class__.__name__)

        self.es_client = self._initialize_elasticsearch()
        self.index_name = "opex_project_docs"

        # Create index only if it doesn't exist yet (safe no-op if it does)
        self._ensure_index_exists()

    # ──────────────────────────────────────────────────────────────────────────
    # Connection & Index
    # ──────────────────────────────────────────────────────────────────────────
    def _initialize_elasticsearch(self) -> Optional[Elasticsearch]:
        """Initialize Elasticsearch connection."""
        try:
            endpoint = os.getenv("ELASTIC_ENDPOINT")
            api_key = os.getenv("ELASTIC_API_KEY")

            if endpoint and api_key:
                return Elasticsearch(hosts=[endpoint], api_key=api_key, verify_certs=True)

            # Fallback to local
            return Elasticsearch(["http://localhost:9200"])
        except Exception as e:
            self.logger.error(f"Failed to connect to Elasticsearch: {e}")
            return None

    def _ensure_index_exists(self):
        """
        Create index with analyzers so filename is searchable (text) and exact (.keyword) is preserved.
        If index already exists, do nothing.
        """
        if not self.es_client:
            return
        try:
            if self.es_client.indices.exists(index=self.index_name):
                return
        except Exception as e:
            self.logger.warning(f"Index existence check failed: {e}")
            return

        mapping = {
            "settings": {
                "analysis": {
                    "analyzer": {
                        # Standard is fine for mixed EN/ID text. Keep it simple.
                        "verbose_analyzer": {"type": "standard"}
                    }
                }
            },
            "mappings": {
                "properties": {
                    "content": {
                        "type": "text",
                        "analyzer": "verbose_analyzer",
                        "term_vector": "with_positions_offsets",
                        "fields": {"keyword": {"type": "keyword", "ignore_above": 256}},
                    },
                    "filename": {
                        "type": "text",
                        "fields": {"keyword": {"type": "keyword", "ignore_above": 256}},
                    },
                    "file_type": {
                        "type": "text",
                        "fields": {"keyword": {"type": "keyword", "ignore_above": 256}},
                    },
                    "upload_date": {"type": "date"},
                    "metadata": {
                        "properties": {
                            "path": {
                                "type": "text",
                                "fields": {"keyword": {"type": "keyword", "ignore_above": 256}},
                            },
                            "size": {"type": "long"},
                        }
                    },
                }
            },
        }

        try:
            self.es_client.indices.create(index=self.index_name, body=mapping)
            self.logger.info(f"Created Elasticsearch index: {self.index_name}")
        except Exception as e:
            self.logger.error(f"Failed to create index: {e}")

    # ──────────────────────────────────────────────────────────────────────────
    # Public entrypoint
    # ──────────────────────────────────────────────────────────────────────────
    async def execute_task(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute project document search using Elasticsearch with tiered fallbacks."""
        self.logger.info("Executing Project Search task")

        results = {
            "status": "started",
            "executorUsed": "ProjectSearchExecutor",
            "artifacts": [],
            "summary": "",
            "timestamp": datetime.now().isoformat(),
        }

        if not self.es_client:
            results["status"] = "error"
            results["error"] = "Elasticsearch not available"
            results["summary"] = "Cannot search: Elasticsearch connection failed"
            return results

        try:
            # Build user query text
            if self.model_client:
                llm_response = await self._generate_search_query(task_data)
                search_query = self._extract_query_from_response(llm_response)
            else:
                search_query = task_data.get("description", "") or task_data.get("query", "")

            # Perform tiered search
            search_results = await self._search_documents(search_query)

            # Format results for artifact
            formatted_results = self._format_search_results(search_results, search_query)

            artifact = self.create_artifact(
                "project_search_results",
                "Project Knowledge Search Results",
                formatted_results,
                {
                    "type": "project_search",
                    "query": search_query,
                    "result_count": len(search_results),
                },
            )

            results["artifacts"] = [artifact]
            results["status"] = "completed"
            results["summary"] = f"Found {len(search_results)} result(s) for: {search_query[:100]}"

        except Exception as e:
            self.logger.error(f"Project search error: {str(e)}")
            results["status"] = "error"
            results["error"] = str(e)
            results["summary"] = f"Search failed: {str(e)}"

        return results

    # ──────────────────────────────────────────────────────────────────────────
    # LLM Query Builder (optional)
    # ──────────────────────────────────────────────────────────────────────────
    async def _generate_search_query(self, task_data: Dict[str, Any]) -> str:
        """Use LLM to generate a concise search hint (optional)."""
        from comprehensive_formatting_prompts import PROJECT_SEARCH_EXECUTOR_PROMPT

        prompt = f"""
{PROJECT_SEARCH_EXECUTOR_PROMPT}

Task Description: {task_data.get('description', '')}
Context: {task_data.get('context', '')}

Instruction:
- Extract the essential search terms (keywords/phrases & filename hints) from the Task Description.
- Output one short line starting with 'SEARCH QUERY:' followed by the terms only.
"""
        response = await self.model_client.generate(
            prompt=prompt, temperature=0.2, max_tokens=200
        )
        return response

    def _extract_query_from_response(self, llm_response: str) -> str:
        """Extract the search query from LLM response."""
        if not isinstance(llm_response, str):
            try:
                llm_response = str(llm_response)
            except Exception:
                return ""
        if "SEARCH QUERY:" in llm_response:
            parts = llm_response.split("SEARCH QUERY:", 1)
            if len(parts) > 1:
                return parts[1].strip().splitlines()[0]
        # Fallback: first line
        return llm_response.strip().splitlines()[0][:256]

    # ──────────────────────────────────────────────────────────────────────────
    # Search (Tiered)
    # ──────────────────────────────────────────────────────────────────────────
    def _wildcard_tokens(self, q: str) -> str:
        """Turn 'supply chain data' -> 'supply*chain*data' for wildcard queries."""
        tokens = [t for t in (q or "").replace("_", " ").split() if t]
        return "*".join(tokens) if tokens else ""

    def _hits_to_results(self, hits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for h in hits:
            src = h.get("_source", {}) or {}
            meta = src.get("metadata", {}) or {}
            out.append(
                {
                    "score": float(h.get("_score", 0.0) or 0.0),
                    "filename": src.get("filename", "Unknown"),
                    "file_type": src.get("file_type", "Unknown"),
                    "excerpts": (h.get("highlight", {}) or {}).get("content", []),
                    "upload_date": src.get("upload_date"),
                    "path": meta.get("path"),
                }
            )
        return out

    async def _search_documents(self, query: str, max_results: int = 10) -> List[Dict[str, Any]]:
        """
        3-tier search:
          1) multi_match across filename/content/path (forgiving)
          2) wildcard on filename/path (handles underscores, partials)
          3) recent docs (avoid empty responses)
        """
        fields = ["filename^5", "content^3", "file_type", "metadata.path"]

        # ── Tier 1: core multi_match (preferred)
        core_body = {
            "size": max_results,
            "_source": ["filename", "file_type", "upload_date", "metadata.path"],
            "query": {
                "multi_match": {
                    "query": query,
                    "type": "best_fields",
                    "fields": fields,
                    "operator": "or",
                    "fuzziness": "AUTO",
                    "minimum_should_match": "2<75%",
                }
            },
            "highlight": {
                "fields": {
                    "content": {
                        "fragment_size": 200,
                        "number_of_fragments": 3,
                        "pre_tags": ["<mark>"],
                        "post_tags": ["</mark>"],
                    }
                }
            },
        }

        try:
            resp = self.es_client.search(index=self.index_name, body=core_body)
            hits = resp.get("hits", {}).get("hits", []) or []
            results = self._hits_to_results(hits)
            if results:
                return results
        except Exception as e:
            self.logger.warning(f"Tier 1 (multi_match) failed: {e}")

        # ── Tier 2: wildcard on filename/path (robust to underscores/partials)
        try:
            star = self._wildcard_tokens(query)  # "supply*chain*data"
            wildcard_should = []
            if star:
                wildcard_should = [
                    {"wildcard": {"filename.keyword": f"*{star}*"}},
                    {"wildcard": {"metadata.path.keyword": f"*{star}*"}},
                ]
            wildcard_body = {
                "size": max_results,
                "_source": ["filename", "file_type", "upload_date", "metadata.path"],
                "query": {"bool": {"should": wildcard_should}} if wildcard_should else {"match_none": {}},
            }
            resp2 = self.es_client.search(index=self.index_name, body=wildcard_body)
            hits2 = resp2.get("hits", {}).get("hits", []) or []
            results2 = self._hits_to_results(hits2)
            if results2:
                return results2
        except Exception as e:
            self.logger.warning(f"Tier 2 (wildcard) failed: {e}")

        # ── Tier 3: recent docs fallback (never empty)
        try:
            recent_body = {
                "size": min(max_results, 5),
                "_source": ["filename", "file_type", "upload_date", "metadata.path"],
                "query": {"match_all": {}},
                "sort": [{"upload_date": {"order": "desc"}}],
            }
            resp3 = self.es_client.search(index=self.index_name, body=recent_body)
            hits3 = resp3.get("hits", {}).get("hits", []) or []
            return self._hits_to_results(hits3)
        except Exception as e:
            self.logger.error(f"Tier 3 (recent fallback) failed: {e}")
            return []

    # ──────────────────────────────────────────────────────────────────────────
    # Formatting
    # ──────────────────────────────────────────────────────────────────────────
    def _format_search_results(self, results: List[Dict[str, Any]], query: str) -> str:
        """Format search results as markdown for artifact display."""
        lines: List[str] = []
        lines.append("# Project Knowledge Search Results\n")
        lines.append(f"**Query:** {query}\n")
        lines.append(f"**Total Results:** {len(results)}\n")
        lines.append("---\n")

        if not results:
            lines.append("No documents found. Showing recent uploads may help next time.\n")
        else:
            for i, r in enumerate(results, 1):
                lines.append(f"## Result {i}: {r.get('filename','Unknown')}\n")
                lines.append(f"**Type:** {r.get('file_type','Unknown')}  ")
                lines.append(f"**Relevance Score:** {round(float(r.get('score', 0.0)), 2)}\n")
                if r.get("upload_date"):
                    lines.append(f"**Uploaded:** {r['upload_date']}\n")
                if r.get("path"):
                    lines.append(f"**Path:** {r['path']}\n")

                lines.append("\n**Relevant Excerpts:**\n")
                excerpts = r.get("excerpts") or []
                if excerpts:
                    for ex in excerpts:
                        formatted = ex.replace("<mark>", "**").replace("</mark>", "**")
                        lines.append(f"> {formatted}\n\n")
                else:
                    lines.append("> *No excerpts available*\n\n")
                lines.append("---\n")

        return "\n".join(lines)

    # ──────────────────────────────────────────────────────────────────────────
    # Indexing (used by your upload pipeline)
    # ──────────────────────────────────────────────────────────────────────────
    async def index_document(self, file_path: str, filename: str, file_type: str):
        """Index a document for searching (called when files are uploaded)."""
        if not self.es_client:
            self.logger.error("Cannot index: Elasticsearch not available")
            return False

        try:
            if not os.path.isabs(file_path):
                file_path = os.path.abspath(file_path)

            if not os.path.exists(file_path):
                self.logger.error(f"File not found: {file_path}")
                return False

            content = await self._parse_document(file_path, file_type)

            doc = {
                "content": content,
                "filename": filename,
                "file_type": file_type,
                "upload_date": datetime.now().isoformat(),
                "metadata": {"path": file_path, "size": os.path.getsize(file_path)},
            }

            self.es_client.index(index=self.index_name, body=doc, refresh=True)
            self.logger.info(f"Indexed document: {filename}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to index {filename}: {e}")
            return False

    async def _parse_document(self, file_path: str, file_type: str) -> str:
        """Parse document content based on file type."""
        try:
            if file_type in [".txt", ".md", ".csv", ".log"]:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    return f.read()

            if file_type == ".pdf":
                import PyPDF2

                text = ""
                with open(file_path, "rb") as f:
                    pdf_reader = PyPDF2.PdfReader(f)
                    for page_num, page in enumerate(pdf_reader.pages, 1):
                        text += f"Page {page_num}:\n"
                        text += (page.extract_text() or "") + "\n\n"
                return text

            if file_type in [".xlsx", ".xls"]:
                import openpyxl

                wb = openpyxl.load_workbook(file_path, data_only=True, read_only=True)
                text = ""
                for sheet in wb.worksheets:
                    text += f"===== Sheet: {sheet.title} =====\n"
                    for row in sheet.iter_rows(values_only=True):
                        row_text = "\t".join(str(c) if c is not None else "" for c in row)
                        if row_text.strip():
                            text += row_text + "\n"
                    text += "\n"
                return text

            if file_type in [".docx", ".doc"]:
                from docx import Document

                doc = Document(file_path)
                text = ""
                for p in doc.paragraphs:
                    if p.text.strip():
                        text += p.text + "\n"
                for table in doc.tables:
                    for row in table.rows:
                        row_text = "\t".join(cell.text for cell in row.cells)
                        if row_text.strip():
                            text += row_text + "\n"
                return text

            if file_type in [".pptx", ".ppt"]:
                from pptx import Presentation

                prs = Presentation(file_path)
                text = ""
                for slide_num, slide in enumerate(prs.slides, 1):
                    text += f"===== Slide {slide_num} =====\n"
                    for shape in slide.shapes:
                        if hasattr(shape, "text") and shape.text:
                            text += shape.text + "\n"
                    text += "\n"
                return text

            if file_type == ".json":
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return json.dumps(data, indent=2, ensure_ascii=False)

            if file_type in [".html", ".htm"]:
                from bs4 import BeautifulSoup

                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    soup = BeautifulSoup(f.read(), "html.parser")
                    return soup.get_text()

            # Fallback: try as plain text
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()

        except Exception as e:
            return f"Could not parse file: {str(e)}"

