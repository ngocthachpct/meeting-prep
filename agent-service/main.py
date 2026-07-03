"""
Thin FastAPI wrapper around the ADK agent pipeline so the NestJS gateway
can call it over plain HTTP/JSON.

Run locally:
  uvicorn main:app --reload --port 8000

For local interactive debugging of the agent itself (not this wrapper), use:
  adk web
which gives you a browser UI to inspect each sub-agent's input/output.

Deploy:
  adk deploy cloud_run --project=$PROJECT_ID --region=us-west1 --service_name=meeting-agent
  (or push this whole folder to Vertex AI Agent Engine, see README)
"""

import json
import logging
import os
import re
import uuid

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from meeting_agent.agent import root_agent

load_dotenv()
os.environ.setdefault("GOOGLE_API_KEY", os.getenv("GOOGLE_API_KEY", ""))

logging.basicConfig(level=logging.WARN)
logger = logging.getLogger("agent-service")

APP_NAME = "meeting-prep-followup"

app = FastAPI(title="Meeting Prep & Follow-up Agent")
session_service = InMemorySessionService()
runner = Runner(agent=root_agent, app_name=APP_NAME, session_service=session_service)


class PrepRequest(BaseModel):
    user_id: str
    meeting_id: str


class FollowupRequest(BaseModel):
    user_id: str
    transcript: str


def _strip_markdown_fence(text: str) -> str:
    return re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()


async def _run_pipeline(user_id: str, payload: dict) -> dict:
    session_id = str(uuid.uuid4())
    await session_service.create_session(
        app_name=APP_NAME, user_id=user_id, session_id=session_id
    )

    message = types.Content(role="user", parts=[types.Part(text=json.dumps(payload))])

    final_output = None
    async for event in runner.run_async(
        user_id=user_id, session_id=session_id, new_message=message
    ):
        if event.is_final_response() and event.content and event.content.parts:
            final_output = event.content.parts[0].text

    if not final_output:
        return {"error": "empty response"}

    cleaned = _strip_markdown_fence(final_output)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return {"raw": final_output}


@app.post("/meetings/prep")
async def prep(req: PrepRequest):
    try:
        return await _run_pipeline(req.user_id, {"mode": "prep", "meeting_id": req.meeting_id})
    except Exception as e:
        msg = str(e)
        logger.error(f"Prep failed: {msg[:500]}")
        raise HTTPException(status_code=502, detail=f"Agent error: {msg[:300]}")


@app.post("/meetings/followup")
async def followup(req: FollowupRequest):
    try:
        return await _run_pipeline(req.user_id, {"mode": "followup", "transcript": req.transcript})
    except Exception as e:
        msg = str(e)
        logger.error(f"Followup failed: {msg[:500]}")
        raise HTTPException(status_code=502, detail=f"Agent error: {msg[:300]}")


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}
