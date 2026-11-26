import logging
import time
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent", tags=["agent"])

# ── Dependencies injected from compiler ──────────────
supabase = None
compiler = None

def init(supabase_client, compiler_instance):
    """Called once from compiler.py to inject the Supabase client and compiler instance."""
    global supabase, compiler
    supabase = supabase_client
    compiler = compiler_instance


async def _generate_agent_title(initial_prompt: str, clerk_user_id: str) -> str:
    """Generate a short agent title using the model chain in api_client.py."""
    try:
        prompt = f"Based on this agent's initial task, generate a short description of the agent (1 sentences, 8-10 word). Return sentences that describe the agent, nothing else.\n\nInitial Task: {initial_prompt}\n\nAgent Name:"

        from api_client import ClaudeAPIClient
        client = ClaudeAPIClient()
        result = await client.generate(prompt=prompt, max_tokens=1024, temperature=0.7)

        title = result["text"].strip()

        # Track token consumption
        if compiler:
            tokens_consumed = result.get("usage", {}).get("total_tokens", 10)
            await compiler.update_token_consumption(clerk_user_id, tokens_consumed)

        logger.info(f"Generated agent title: {title}")
        return title

    except Exception as e:
        logger.error(f"Error generating agent title: {str(e)}")
        return "New Agent"


@router.post("")
@router.post("/")
async def create_new_agent(request: Request):
    """
    Synchronous endpoint to generate agent name based on the initial prompt,
    and save the agent to the database.
    """
    try:
        clerk_user_id = await compiler.verify_clerk_user(request) if compiler else None
        if not clerk_user_id:
            return JSONResponse(
                status_code=401,
                content={
                    "error": "Not authenticated",
                    "message": "Please log in to access AI features"
                }
            )

        # Parse request body
        data = await request.json()
        
        # Use provided ID from FE or generate a new one
        agent_id = data.get('id', str(int(time.time() * 1000)))
        
        initial_prompt = data.get('initialPrompt', '').strip()
        project_id = data.get('projectId')
        prefer_multi_agent = data.get('preferMultiAgent', True)

        if not initial_prompt:
            return JSONResponse(
                status_code=400,
                content={"error": "initialPrompt is required"}
            )

        # Generate agent name using existing helper method
        name = await _generate_agent_title(initial_prompt, clerk_user_id)

        if supabase:
            agent_record = {
                "id": agent_id,
                "user_id": clerk_user_id,
                "name": name,
                "initial_prompt": initial_prompt,
                "project_id": project_id,
                "status": "active",
                "prefer_multi_agent": prefer_multi_agent
            }
            try:
                supabase.table('agents').insert(agent_record).execute()
                logger.info(f"Agent {agent_id} saved to database")
            except Exception as db_e:
                logger.error(f"Failed to save agent to database: {str(db_e)}")
                # Proceed anyway to allow local functionality

        return JSONResponse(content={
            "id": agent_id,
            "name": name,
            "initialPrompt": initial_prompt,
            "project": project_id,
            "status": "active",
            "preferMultiAgent": prefer_multi_agent
        })

    except Exception as e:
        logger.error(f"Error creating agent: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )


@router.get("")
@router.get("/")
async def get_agents(request: Request):
    """
    Retrieve agents for the authenticated user from the database.
    """
    try:
        user_id = await compiler.verify_clerk_user(request) if compiler else None
        if not user_id:
            return JSONResponse(status_code=401, content={"error": "Not authenticated"})

        if not supabase:
            return JSONResponse(status_code=500, content={"error": "Database not configured"})

        result = supabase.table("agents").select("*").eq("user_id", user_id).execute()
        
        # Process database records to match the frontend expected structure
        agents = []
        for row in result.data:
            agents.append({
                "id": row.get("id"),
                "name": row.get("name"),
                "initialPrompt": row.get("initial_prompt"),
                "project": row.get("project_id"),
                "status": row.get("status", "active"),
                "dateCreated": row.get("date_created"),
                "lastModified": row.get("last_modified"),
                "preferMultiAgent": row.get("prefer_multi_agent")
            })

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "agents": agents
            }
        )

    except Exception as e:
        logger.error(f"Error fetching agents: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})
