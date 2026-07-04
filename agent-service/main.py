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

import base64
import json
import logging
import os
import re
import subprocess
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
DRAFT_SUBJECT = "Meeting follow-up: action items"


def _run_gws(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["gws", *args],
        capture_output=True,
        text=True,
        timeout=30,
        shell=(os.name == "nt"),
        check=False,
    )


def _resolve_draft_to() -> str:
    """Email used as the Gmail draft recipient when the transcript has no emails."""
    configured = os.getenv("DEFAULT_DRAFT_TO", "").strip()
    if configured:
        return configured
    try:
        result = _run_gws(
            "gmail", "users", "getProfile", "--params", json.dumps({"userId": "me"})
        )
        if result.returncode == 0 and result.stdout.strip():
            profile = json.loads(result.stdout)
            email = str(profile.get("emailAddress", "")).strip()
            if email:
                return email
    except Exception as exc:
        logger.warning("Could not resolve Gmail profile for draft_to: %s", exc)
    return ""


def _format_followup_body(result: dict) -> str:
    lines = ["Meeting follow-up", ""]
    summary = str(result.get("summary") or "").strip()
    if summary:
        lines.extend(["Summary:", summary, ""])
    action_items = result.get("action_items") or []
    if action_items:
        lines.append("Action items:")
        for item in action_items:
            owner = str(item.get("owner") or "unassigned").strip()
            task = str(item.get("task") or "").strip()
            deadline = str(item.get("deadline") or "not specified").strip()
            lines.append(f"- {owner}: {task} (deadline: {deadline})")
    return "\n".join(lines).strip() + "\n"


def _create_gmail_draft(to: str, subject: str, body: str) -> bool:
    """Create a Gmail draft via gws (never sends). Returns True on success."""
    if not to or "@" not in to:
        return False
    # Minimal RFC 2822 message, base64url-encoded for Gmail drafts.create.
    message = (
        f"To: {to}\r\n"
        f"Subject: {subject}\r\n"
        "MIME-Version: 1.0\r\n"
        'Content-Type: text/plain; charset="UTF-8"\r\n'
        "Content-Transfer-Encoding: 8bit\r\n"
        f"\r\n{body}"
    )
    raw = base64.urlsafe_b64encode(message.encode("utf-8")).decode("ascii").rstrip("=")
    try:
        result = _run_gws(
            "gmail",
            "users",
            "drafts",
            "create",
            "--params",
            json.dumps({"userId": "me"}),
            "--json",
            json.dumps({"message": {"raw": raw}}),
        )
        if result.returncode == 0:
            return True
        logger.error(
            "Gmail draft creation failed: %s",
            (result.stderr or result.stdout or "")[:500],
        )
    except Exception as exc:
        logger.error("Gmail draft creation error: %s", exc)
    return False


def _ensure_followup_draft(result: dict, draft_to: str) -> dict:
    """If the agent did not create a draft, create one deterministically via gws."""
    if result.get("mode") != "followup" or result.get("draft_created"):
        return result
    if not draft_to:
        logger.warning("Skipping draft fallback: no draft recipient available")
        result["draft_created"] = False
        return result
    body = _format_followup_body(result)
    created = _create_gmail_draft(draft_to, DRAFT_SUBJECT, body)
    result["draft_created"] = created
    if created:
        logger.info("Created follow-up Gmail draft to %s", draft_to)
    return result

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
        draft_to = _resolve_draft_to()
        if not draft_to:
            logger.warning(
                "DEFAULT_DRAFT_TO is unset and Gmail profile lookup failed; "
                "draft creation may be skipped"
            )
        result = await _run_pipeline(
            req.user_id,
            {
                "mode": "followup",
                "transcript": req.transcript,
                "draft_to": draft_to,
            },
        )
        # Agent may skip gmail_drafts_create; guarantee a draft when possible.
        return _ensure_followup_draft(result, draft_to)
    except Exception as e:
        msg = str(e)
        logger.error(f"Followup failed: {msg[:500]}")
        raise HTTPException(status_code=502, detail=f"Agent error: {msg[:300]}")


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}
