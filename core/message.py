import re
import uuid
import logging
from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/messages", tags=["messages"])


def _extract_user_id(request: Request):
    """Extract user_id from JWT token or header."""
    try:
        if supabase is None:
            return "local"
        if request.headers.get("x-user-id"):
            return request.headers.get("x-user-id")
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            import jwt
            token = auth.split(" ", 1)[1]
            payload = jwt.decode(token, options={"verify_signature": False})
            return payload.get("sub")
    except Exception:
        return None


# ── Dependency: Supabase client injected from compiler ──────────────
supabase = None


def init(supabase_client):
    """Called once from compiler.py to inject the Supabase client."""
    global supabase
    supabase = supabase_client

# ── Local mode (no Supabase): messages live in ~/Boundary/chats/messages.jsonl ──
import json
from pathlib import Path
LOCAL_MESSAGES = Path.home() / "Boundary" / "chats" / "messages.jsonl"


def _local_save(row):
    LOCAL_MESSAGES.parent.mkdir(parents=True, exist_ok=True)
    row = {**row, "timestamp": datetime.now().isoformat()}
    with open(LOCAL_MESSAGES, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def _local_load(agent_id=None):
    """Saved messages, oldest first."""
    if not LOCAL_MESSAGES.exists():
        return []
    rows = []
    with open(LOCAL_MESSAGES, encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if agent_id is None or r.get("agent_id") == agent_id:
                rows.append(r)
    return rows

# ── POST /api/messages ──────────────────────────────────────────────
@router.post("")
async def create_message(request: Request):
    """
    Create a new message.

    Body JSON:
      - agent_id  (str, required)
      - role      (str, required: "user" | "assistant")
      - title     (str, optional)
      - keywords  (list[str], optional)
      - content   (str, required)
    """
    user_id = _extract_user_id(request)
    if not user_id:
        return JSONResponse(status_code=401, content={"error": "Not authenticated"})

    if not supabase:
        return JSONResponse(status_code=500, content={"error": "Database not configured"})

    try:
        data = await request.json()

        agent_id = data.get("agent_id")
        role = data.get("role")
        content = data.get("content")

        # Validate required fields
        if not all([agent_id, role, content]):
            return JSONResponse(
                status_code=400,
                content={"error": "agent_id, role, and content are required"},
            )

        if role not in ("user", "assistant"):
            return JSONResponse(
                status_code=400,
                content={"error": "role must be 'user' or 'assistant'"},
            )

        row = {
            "id": str(uuid.uuid4()),
            "agent_id": agent_id,
            "user_id": user_id,
            "role": role,
            "content": content,
        }

        result = supabase.table("messages").insert(row).execute()

        return JSONResponse(
            status_code=201,
            content={
                "success": True,
                "message": result.data[0] if result.data else row,
            },
        )

    except Exception as e:
        logger.error(f"Error creating message: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


# ── GET /api/messages ───────────────────────────────────────────────
@router.get("")
async def get_messages(request: Request):
    """
    Search messages for the authenticated user.

    Query params:
      - agent_id  (optional): filter by agent
      - title     (optional): partial match (case-insensitive)
      - keyword   (optional): exact match inside keywords array
      - limit     (optional): default 50
      - offset    (optional): default 0
    """
    user_id = _extract_user_id(request)
    if not user_id:
        return JSONResponse(status_code=401, content={"error": "Not authenticated"})

    if not supabase:
        rows = list(reversed(_local_load(request.query_params.get("agent_id"))))
        return JSONResponse(status_code=200, content={"success": True, "messages": rows, "count": len(rows)})

    try:
        params = request.query_params
        agent_id = params.get("agent_id")
        limit = int(params.get("limit", 50))
        offset = int(params.get("offset", 0))

        # Always scoped to authenticated user
        query = supabase.table("messages").select("*").eq("user_id", user_id)

        if agent_id:
            query = query.eq("agent_id", agent_id)



        query = query.order("timestamp", desc=True).range(offset, offset + limit - 1)
        result = query.execute()

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "messages": result.data,
                "count": len(result.data),
            },
        )

    except Exception as e:
        logger.error(f"Error fetching messages: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

async def save_message_to_db(user_id: str, agent_id: str, role: str, content: str):
    """Internal helper to save a message directly from the backend."""
    try:
        # Remove the tone label the frontend puts before user messages (e.g. "Neutral: ...").
        # Only for user messages, and only when the text before the first colon is a short
        # label of letters, so assistant replies and wake-up messages are saved whole.
        if role == "user":
            label, sep, rest = content.partition(":")
            if sep and len(label.strip()) <= 30 and re.fullmatch(r"[A-Za-z][A-Za-z \-]*", label.strip()):
                content = rest.strip()


        row = {
            "id": str(uuid.uuid4()),
            "agent_id": agent_id,
            "user_id": user_id,
            "role": role,
            "content": content,
        }
        if not supabase:
            return _local_save(row)
        result = supabase.table("messages").insert(row).execute()
        return result.data[0] if result.data else row
    except Exception as e:
        logger.error(f"Error saving message internal: {e}")
        return None

async def get_messages_for_agent(agent_id: str, limit: int = 10):
    """Internal helper to retrieve the most recent messages for an agent."""
    if not supabase:
        return [{"role": r["role"], "content": r["content"]} for r in _local_load(agent_id)][-limit:]
    try:
        # Fetch latest messages descending, limit X
        query = supabase.table("messages").select("role, content").eq("agent_id", agent_id)
        query = query.order("timestamp", desc=True).limit(limit)
        result = query.execute()
        
        # Reverse to get chronological order
        messages = result.data or []
        messages.reverse()
        return messages
    except Exception as e:
        logger.error(f"Error fetching messages for agent '{agent_id}': {e}")
        return []
