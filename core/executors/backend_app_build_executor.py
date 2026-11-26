"""
Flask App Build Executor (FIXED + Minimal Fallback)
--------------------------------------------------------------
- Fixed: Parser doesn't break on backticks inside JSON
- Minimal: Super simple general fallback (no domain-specific patterns)
- LLM-First: Trust the AI, 16K tokens
"""

from __future__ import annotations

import os
import json
import logging
import shutil
import zipfile
import re
from typing import Dict, Any, List, Optional, Tuple
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

# LLM Prompt - Trust the AI to be creative
BACKEND_APP_BUILDER_PROMPT = """You are a senior Flask engineer who creates clean, beginner-friendly backends.

🎯 YOUR MISSION:
Understand EXACTLY what the user wants and create a Flask backend that does it perfectly.

📝 USER'S REQUEST:
{DESCRIPTION}

📋 ADDITIONAL REQUIREMENTS:
{REQUIREMENTS}

🧠 BE SMART & FLEXIBLE:
- Understand the DOMAIN and create appropriate fields
- Add smart features that make sense
- Make it production-ready with comments

⚠️ CRITICAL OUTPUT FORMAT:
Your response must be ONLY a JSON object. Nothing else!

DO NOT include:
- ❌ Explanations before the JSON
- ❌ Explanations after the JSON  
- ❌ Markdown code fences like ```json
- ❌ Any text outside the JSON object

DO include:
- ✅ Start immediately with {{
- ✅ End with }}
- ✅ Escape quotes as \\" inside strings
- ✅ Use \\n for newlines in code

YOUR RESPONSE MUST START WITH: {{"files":

📦 RETURN THIS JSON STRUCTURE:
{{
  "files": {{
    "app.py": "<full Flask app with comments>",
    "requirements.txt": "flask>=2.0,<4.0\\nflask-cors>=3.0,<5.0\\nwerkzeug>=2.0,<4.0",
    ".gitignore": "__pycache__/\\n.env\\n.venv/\\n*.db\\n*.sqlite\\n",
    "README.md": "<comprehensive guide with curl examples>"
  }}
}}

🏗️ APP.PY REQUIREMENTS:
- Import: flask, request, jsonify, flask_cors, sqlite3, os
- Setup: app = Flask(__name__); CORS(app)
- Database: SQLite with row_factory = sqlite3.Row, PRAGMA foreign_keys=ON
- Infer main resource from description
- Create table at startup with app.app_context()
- Add HELPFUL COMMENTS explaining each section
- CRUD endpoints: GET /resource, GET /resource/:id, POST /resource, PUT /resource/:id, DELETE /resource/:id
- Root endpoint: GET / returns {{"message": "API running"}}
- Run on port 8000: app.run(host="0.0.0.0", port=8000)

🎯 REMEMBER:
- Output ONLY valid JSON (start with {{ end with }})
- No markdown, no explanations
- Be creative and understand the domain
"""

SYSTEM_PROMPT = """You are an expert Flask developer. Create perfect APIs that match the user's domain.

CRITICAL: Your response must be ONLY valid JSON. Start with { and end with }.
Do not add any text before or after the JSON object."""


class BackendAppExecutor:
    """Flask backend generator - LLM first, minimal fallback."""

    def __init__(self, mcp_manager, mcp_registry, model):
        self.mcp_manager = mcp_manager
        self.mcp_registry = mcp_registry
        self.model = model

        self.outputs_root = Path("/tmp/opex/outputs").resolve()
        self.apps_root = self.outputs_root / "apps"
        self.apps_root.mkdir(parents=True, exist_ok=True)

        self.storage = OutputStorage() if _HAS_OUTPUT_STORAGE else None
        self.backend_base = (os.getenv("NEXT_PUBLIC_API_URL") or "").rstrip("/")
        self.force_download = (os.getenv("OUTPUT_FORCE_DOWNLOAD", "false").lower() == "true")

        logger.info("✅ Flask Executor (LLM-First, Minimal Fallback)")

    def _abs(self, raw: str) -> str:
        if not raw or raw.startswith("http"):
            return raw
        return f"{self.backend_base or ''}{raw if raw.startswith('/') else '/' + raw}"

    def _strip_download_param(self, url: str) -> str:
        if not url:
            return url
        p = urlparse(url)
        q = dict(parse_qsl(p.query))
        q.pop("download", None)
        return urlunparse(p._replace(query=urlencode(q)))

    def _ensure_download_filename(self, url: str, filename: str) -> str:
        if not url:
            return url
        p = urlparse(url)
        q = dict(parse_qsl(p.query))
        q["download"] = filename
        return urlunparse(p._replace(query=urlencode(q)))

    @staticmethod
    def _format_bytes(size: int) -> str:
        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"

    async def execute_task(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """Main execution."""
        app_dir: Optional[Path] = None

        results = {
            "status": "started",
            "executorUsed": "BackendAppExecutor",
            "artifacts": [],
            "summary": "",
            "executorFullResponse": "",
        }

        try:
            description = (task_data.get("description") or "").strip()
            requirements = task_data.get("requirements", []) or []
            context = task_data.get("context", {}) or {}
            task_id = str(task_data.get("task_id") or task_data.get("id") or f"backend_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
            user_id = task_data.get("userId", "anonymous")

            if not description:
                raise ValueError("Description required")

            app_name = context.get("appName") or self._generate_app_name(description)
            
            logger.info(f"🚀 Building: {app_name}")
            logger.info(f"📝 Request: {description}")

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_name = self._sanitize_filename(app_name)
            app_dir = self.apps_root / f"{safe_name}_{timestamp}"
            app_dir.mkdir(parents=True, exist_ok=True)

            # Generate via LLM
            logger.info("🤖 Asking LLM to design backend...")
            app_structure = await self._generate_via_llm(description, requirements)

            if "README.md" not in app_structure:
                app_structure["README.md"] = self._quick_readme(app_name, description)

            logger.info(f"📝 Writing {len(app_structure)} files...")
            files_created = await self._write_files(app_dir, app_structure)

            if not files_created:
                raise Exception("No files created")

            logger.info("📦 Creating ZIP...")
            zip_path = await self._create_zip(app_dir, safe_name, task_id)
            zip_size = zip_path.stat().st_size

            logger.info("☁️ Uploading...")
            zip_url = await self._upload(zip_path, user_id, task_id, zip_path.name)

            zip_obj = {
                "filename": zip_path.name,
                "download_url": zip_url["url"],
                "size_bytes": zip_size,
                "size_formatted": self._format_bytes(zip_size),
                "total_files": len(files_created),
                "files": files_created,
            }

            results.update({
                "status": "completed",
                "summary": f"✅ Created {app_name} ({len(files_created)} files, {self._format_bytes(zip_size)})",
                "download_url": zip_obj["download_url"],
                "outputFiles": [zip_obj],
                "artifacts": [{
                    "type": "flask_backend",
                    "title": f"Flask - {app_name}",
                    "download_url": zip_obj["download_url"],
                    "files": files_created,
                }],
                "executorFullResponse": f"# ✅ {app_name} Ready!\n\n[Download]({zip_obj['download_url']})\n\n```bash\npip install -r requirements.txt\npython app.py\n```",
            })

            logger.info(f"✅ Done: {app_name}")
            return results

        except Exception as e:
            logger.error(f"❌ Failed: {e}", exc_info=True)
            results.update({
                "status": "error",
                "summary": f"Failed: {e}",
                "error": str(e),
            })
            return results
        finally:
            if app_dir and app_dir.exists():
                shutil.rmtree(app_dir, ignore_errors=True)

    # ═══════════════════════════════════════════════════════════════════
    # LLM GENERATION - Let AI be creative!
    # ═══════════════════════════════════════════════════════════════════

    async def _generate_via_llm(self, description: str, requirements: List[str]) -> Dict[str, str]:
        """Let LLM design the backend."""
        
        req_text = "\n".join(f"- {r}" for r in requirements) if requirements else ""
        if req_text:
            req_text = f"\nADDITIONAL REQUIREMENTS:\n{req_text}"
        
        prompt = BACKEND_APP_BUILDER_PROMPT.format(
            DESCRIPTION=description,
            REQUIREMENTS=req_text
        )

        try:
            logger.info("⏳ LLM thinking...")
            
            response = await self.model.generate(
                prompt=prompt,
                system_prompt=SYSTEM_PROMPT,
                temperature=0.8,  # Creative!
                max_tokens=16000,
            )
            
            logger.info(f"📥 Response: {len(response)} chars")
            
            # FIXED parser!
            files = self._parse_json_fixed(response)
            
            if not files or "app.py" not in files:
                logger.warning("⚠️ LLM output invalid, using minimal fallback")
                return self._minimal_fallback(description)
            
            logger.info(f"✅ LLM created: {list(files.keys())}")
            return files
            
        except Exception as e:
            logger.error(f"❌ LLM failed: {e}")
            return self._minimal_fallback(description)

    def _parse_json_fixed(self, response: str) -> Dict[str, str]:
        """
        FIXED JSON parser - doesn't break on backticks inside JSON!
        
        The bug: Old parser found ``` inside README content and extracted wrong part.
        The fix: If response starts with {, don't look for markdown fences!
        """
        if not response:
            return {}
        
        trimmed = response.strip()
        
        # If it starts with {, it's already JSON - don't mess with it!
        if trimmed.startswith("{"):
            logger.info("✅ Response starts with { - parsing directly")
            # Just find the JSON boundaries
            json_start = 0
            json_end = trimmed.rfind("}") + 1
            
            if json_end == 0:
                logger.error("No closing }")
                return {}
            
            json_str = trimmed[json_start:json_end]
        else:
            # Only if it doesn't start with {, look for markdown fences
            logger.info("Looking for markdown fences...")
            if "```json" in trimmed:
                start = trimmed.find("```json") + 7
                end = trimmed.find("```", start)
                if end != -1:
                    json_str = trimmed[start:end].strip()
                else:
                    return {}
            elif "```" in trimmed:
                start = trimmed.find("```") + 3
                end = trimmed.find("```", start)
                if end != -1:
                    json_str = trimmed[start:end].strip()
                else:
                    return {}
            else:
                # No fences, try to find JSON
                json_start = trimmed.find("{")
                json_end = trimmed.rfind("}") + 1
                if json_start == -1 or json_end == 0:
                    return {}
                json_str = trimmed[json_start:json_end]
        
        # Parse the JSON
        try:
            data = json.loads(json_str)
            
            if not isinstance(data, dict):
                logger.error(f"Not a dict: {type(data)}")
                return {}
            
            files = data.get("files", {})
            
            if not isinstance(files, dict):
                logger.error(f"Files not a dict: {type(files)}")
                return {}
            
            logger.info(f"✅ Parsed {len(files)} files")
            return files
            
        except json.JSONDecodeError as e:
            logger.error(f"JSON error at pos {e.pos}: {e.msg}")
            # Show context
            if e.pos:
                start = max(0, e.pos - 100)
                end = min(len(json_str), e.pos + 100)
                logger.error(f"Context: ...{json_str[start:end]}...")
            return {}

    # ═══════════════════════════════════════════════════════════════════
    # MINIMAL FALLBACK - Ultra simple, no domain patterns
    # ═══════════════════════════════════════════════════════════════════

    def _minimal_fallback(self, description: str) -> Dict[str, str]:
        """
        Ultra-minimal fallback - just basic CRUD.
        No domain-specific patterns, no minerals, no nothing.
        Just a simple API that works.
        """
        logger.info("⚙️ Minimal fallback: creating basic CRUD API")
        
        # Extract a simple resource name
        resource = self._guess_resource_name(description)
        
        logger.info(f"📦 Resource: {resource}")
        
        # Absolute bare minimum Flask app - no fancy features!
        app_py = f'''"""Minimal Flask API"""
from flask import Flask, request, jsonify, g
from flask_cors import CORS
import sqlite3
import os

DB = os.getenv("DATABASE_PATH", "app.db")
app = Flask(__name__)
CORS(app)

def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close(e): 
    g.pop("db", None)

def init():
    db().execute("CREATE TABLE IF NOT EXISTS {resource} (id INTEGER PRIMARY KEY, name TEXT, data TEXT)")
    db().commit()

with app.app_context():
    init()

@app.get("/")
def root():
    return {{"message": "API running", "resource": "{resource}"}}

@app.get("/{resource}")
def list_all():
    rows = db().execute("SELECT * FROM {resource}").fetchall()
    return jsonify([dict(r) for r in rows])

@app.get("/{resource}/<int:id>")
def get_one(id):
    r = db().execute("SELECT * FROM {resource} WHERE id=?", (id,)).fetchone()
    return jsonify(dict(r)) if r else ("Not found", 404)

@app.post("/{resource}")
def create():
    d = request.get_json() or {{}}
    c = db()
    c.execute("INSERT INTO {resource} (name, data) VALUES (?, ?)", (d.get("name"), d.get("data")))
    c.commit()
    return jsonify({{"id": c.execute("SELECT last_insert_rowid()").fetchone()[0]}}), 201

@app.put("/{resource}/<int:id>")
def update(id):
    d = request.get_json() or {{}}
    c = db()
    c.execute("UPDATE {resource} SET name=?, data=? WHERE id=?", (d.get("name"), d.get("data"), id))
    c.commit()
    return jsonify({{"updated": c.rowcount > 0}})

@app.delete("/{resource}/<int:id>")
def delete(id):
    c = db()
    c.execute("DELETE FROM {resource} WHERE id=?", (id,))
    c.commit()
    return ("", 204)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
'''

        readme = f"""# {resource.title()} API

{description}

## Quick Start
```bash
pip install -r requirements.txt
python app.py
```

## API Endpoints

### Create
```bash
curl -X POST http://localhost:8000/{resource} \\
  -H "Content-Type: application/json" \\
  -d '{{"name":"test","data":"value"}}'
```

### List All
```bash
curl http://localhost:8000/{resource}
```

### Get One
```bash
curl http://localhost:8000/{resource}/1
```

### Update
```bash
curl -X PUT http://localhost:8000/{resource}/1 \\
  -H "Content-Type: application/json" \\
  -d '{{"name":"updated","data":"new value"}}'
```

### Delete
```bash
curl -X DELETE http://localhost:8000/{resource}/1
```

## Customize

Edit `app.py` to add more fields to the database table.

## Deploy

```bash
pip install gunicorn
gunicorn -b 0.0.0.0:8000 app:app
```
"""

        return {
            "app.py": app_py,
            "requirements.txt": "flask>=2.0,<4.0\nflask-cors>=3.0,<5.0\n",
            ".gitignore": "*.db\n__pycache__/\n.venv/\n",
            "README.md": readme,
        }

    def _guess_resource_name(self, description: str) -> str:
        """
        Simple resource name guess - no complex patterns.
        Just extract a reasonable noun from the description.
        """
        d = description.lower()
        
        # Very basic keyword matching (no domain-specific stuff!)
        simple_keywords = [
            "item", "product", "task", "post", "note", "record",
            "entry", "resource", "data", "object"
        ]
        
        # Check if any keyword is in description
        for keyword in simple_keywords:
            if keyword in d:
                return keyword + "s"
        
        # Try to extract first noun-like word
        words = [w for w in d.split() if len(w) > 3 and w.isalpha()]
        if words:
            word = words[0]
            # Make it plural
            if not word.endswith('s'):
                word += 's'
            return word
        
        # Ultimate fallback
        return "items"

    def _quick_readme(self, app_name: str, description: str) -> str:
        """Quick README if LLM didn't provide one."""
        return f"""# {app_name}

{description}

## Quick Start
```bash
pip install -r requirements.txt
python app.py
```

Visit: http://localhost:8000

Check the API documentation at the root endpoint.
"""

    # ═══════════════════════════════════════════════════════════════════
    # FILE OPERATIONS
    # ═══════════════════════════════════════════════════════════════════

    async def _write_files(self, app_dir: Path, files: Dict[str, str]) -> List[str]:
        created = []
        for path, content in files.items():
            full_path = app_dir / path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                full_path.write_text(content, encoding="utf-8")
                created.append(path)
            except Exception as e:
                logger.error(f"Failed {path}: {e}")
        return created

    async def _create_zip(self, app_dir: Path, name: str, task_id: str) -> Path:
        zip_path = self.outputs_root / f"flask_backend_{task_id}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            for f in app_dir.rglob("*"):
                if f.is_file():
                    z.write(f, f.relative_to(app_dir))
        return zip_path

    async def _upload(self, file_path: Path, user_id: str, task_id: str, filename: str) -> Dict[str, str]:
        if not self.storage:
            rel = file_path.relative_to(self.outputs_root)
            return {"url": self._abs(f"/files/outputs/{rel.as_posix()}"), "type": "local"}
        
        try:
            with open(file_path, "rb") as f:
                result = self.storage.save_bytes(
                    f.read(),
                    ext=file_path.suffix,
                    filename=filename,
                    user_id=user_id,
                    prefix=f"apps/{task_id}",
                    local_dir=str(self.outputs_root),
                )
            url = result.get("signed_url") or result.get("public_url") or ""
            return {"url": self._abs(url) if url else "", "type": "supabase"}
        except Exception:
            rel = file_path.relative_to(self.outputs_root)
            return {"url": self._abs(f"/files/outputs/{rel.as_posix()}"), "type": "local"}

    def _generate_app_name(self, description: str) -> str:
        if not description:
            return "flask-api"
        words = description
        return "-".join(words).lower()

    def _sanitize_filename(self, name: str) -> str:
        safe = re.sub(r"[^\w\s-]", "", name)
        safe = re.sub(r"[\s_]+", "-", safe)
        return (safe.strip("-") or "api")[:40]
