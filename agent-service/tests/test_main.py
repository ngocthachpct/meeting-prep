"""Tests for the FastAPI wrapper (main.py).

Requires mocking google.adk because the ADK package is not installed
in all test environments.
"""

import json
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

# ---------------------------------------------------------------------------
# Mock google.adk before main is imported
# ---------------------------------------------------------------------------
mock_adk = MagicMock()
mock_adk.runners.Runner = MagicMock
mock_adk.sessions.InMemorySessionService = MagicMock
mock_adk.agents.LlmAgent = MagicMock
mock_adk.agents.SequentialAgent = MagicMock
mock_adk.tools.mcp_tool.mcp_toolset.McpToolset = MagicMock
mock_adk.tools.mcp_tool.mcp_session_manager.StreamableHTTPConnectionParams = MagicMock
sys.modules["google.adk"] = mock_adk
sys.modules["google.adk.runners"] = mock_adk.runners
sys.modules["google.adk.sessions"] = mock_adk.sessions
sys.modules["google.adk.agents"] = mock_adk.agents
sys.modules["google.adk.tools.mcp_tool.mcp_toolset"] = mock_adk.tools.mcp_tool.mcp_toolset
sys.modules[
    "google.adk.tools.mcp_tool.mcp_session_manager"
] = mock_adk.tools.mcp_tool.mcp_session_manager
sys.modules["google.genai"] = MagicMock()
sys.modules["google.genai.types"] = MagicMock()

sys.modules["meeting_agent"] = MagicMock()
sys.modules["meeting_agent.agent"] = MagicMock()
sys.modules["meeting_agent.agent"].root_agent = MagicMock()

from main import app, session_service


# Make session_service.create_session actually async
session_service.create_session = AsyncMock()
session_service.create_session.return_value = None


@pytest.fixture
def client():
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.asyncio
async def test_healthz(client):
    resp = await client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.asyncio
@patch("main.runner.run_async")
async def test_prep_endpoint(mock_run_async, client):
    fake_event = MagicMock()
    fake_event.is_final_response.return_value = True
    fake_event.content.parts = [MagicMock(text=json.dumps({"mode": "prep", "markdown_brief": "# brief"}))]
    mock_run_async.return_value.__aiter__.return_value = [fake_event]

    resp = await client.post(
        "/meetings/prep",
        json={"user_id": "u1", "meeting_id": "evt_001"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "prep"


@pytest.mark.asyncio
@patch("main.runner.run_async")
async def test_followup_endpoint(mock_run_async, client):
    fake_event = MagicMock()
    fake_event.is_final_response.return_value = True
    fake_event.content.parts = [
        MagicMock(
            text=json.dumps(
                {
                    "mode": "followup",
                    "summary": "Discussed sprint",
                    "action_items": [{"owner": "Alice", "task": "Finish API", "deadline": "Friday"}],
                }
            )
        )
    ]
    mock_run_async.return_value.__aiter__.return_value = [fake_event]

    resp = await client.post(
        "/meetings/followup",
        json={"user_id": "u1", "transcript": "Alice will finish the API by Friday"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "followup"
    assert len(data["action_items"]) == 1


@pytest.mark.asyncio
@patch("main.runner.run_async")
async def test_prep_empty_response(mock_run_async, client):
    fake_event = MagicMock()
    fake_event.is_final_response.return_value = True
    fake_event.content.parts = [MagicMock(text=json.dumps({"error": "empty response"}))]
    mock_run_async.return_value.__aiter__.return_value = [fake_event]

    resp = await client.post(
        "/meetings/prep",
        json={"user_id": "u1", "meeting_id": "evt_nonexistent"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"error": "empty response"}


@pytest.mark.asyncio
@patch("main.runner.run_async")
async def test_non_json_response(mock_run_async, client):
    fake_event = MagicMock()
    fake_event.is_final_response.return_value = True
    fake_event.content.parts = [MagicMock(text="plain text output")]
    mock_run_async.return_value.__aiter__.return_value = [fake_event]

    resp = await client.post(
        "/meetings/prep",
        json={"user_id": "u1", "meeting_id": "evt_001"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"raw": "plain text output"}


@pytest.mark.asyncio
async def test_prep_missing_fields(client):
    resp = await client.post("/meetings/prep", json={})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_followup_missing_fields(client):
    resp = await client.post("/meetings/followup", json={})
    assert resp.status_code == 422
