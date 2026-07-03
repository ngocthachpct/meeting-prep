"""
Meeting Prep & Follow-up Agent
------------------------------
Multi-agent pipeline built with Google ADK.

Pipeline (SequentialAgent):
  1. context_gatherer_agent  -> gathers raw context (calendar/gmail/drive OR pasted transcript)
  2. analysis_agent          -> summarizes context / extracts action items
  3. output_agent            -> produces the final deliverable (brief or draft email + action list)

State contract between agents (session.state):
  input               : the raw JSON string the caller sent (mode, meeting_id/transcript, ...)
  meeting_context      : output of context_gatherer_agent (JSON string)
  analysis_result      : output of analysis_agent (JSON string)
  final_output          : output of output_agent (JSON string) - this is what the API returns

`mode` is either "prep" (before the meeting) or "followup" (after the meeting).
Each agent reads {mode} out of its upstream state and branches its own behavior via
its instruction - ADK does not need separate agents per mode here because the
LLM itself conditions on the mode field, which keeps the pipeline small and easy to reason about.
"""

import os

from mcp import StdioServerParameters
from google.adk.agents import LlmAgent, SequentialAgent
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams

MODEL = os.getenv("AGENT_MODEL", "gemini-2.5-flash")

# ---------------------------------------------------------------------------
# Tools: Google Workspace via MCP (Gmail, Calendar, Drive)
# ADK spawns gws-mcp-server as a subprocess over stdio.
# Install: npm install -g gws-mcp-server
# ---------------------------------------------------------------------------
workspace_toolset = McpToolset(
    connection_params=StdioConnectionParams(
        server_params=StdioServerParameters(
            command="npx",
            args=[
                "gws-mcp-server",
                "--services",
                os.getenv("GWS_MCP_SERVICES", "gmail,calendar,drive"),
            ],
        ),
    ),
)

# ---------------------------------------------------------------------------
# 1. Context Gatherer Agent
# ---------------------------------------------------------------------------
context_gatherer_agent = LlmAgent(
    name="ContextGathererAgent",
    model=MODEL,
    description="Collects raw context for a meeting, either from Google Workspace or from a pasted transcript.",
    instruction="""
You are the Context Gatherer for a meeting assistant.

You receive a JSON payload as input with this shape:
  {"mode": "prep" | "followup", "meeting_id": "<calendar event id, prep mode only>",
   "transcript": "<raw notes/transcript text, followup mode only>"}

If mode == "prep":
  - Use the calendar tool to fetch the event (title, time, attendees) for meeting_id.
  - Use the gmail tool to search for the most recent email threads involving those attendees
    (limit to the last 5 relevant messages, do not fetch full inbox).
  - Use the drive tool to search for documents whose title or content mentions the meeting
    title or attendees.
  - If a tool call fails or returns nothing, note that gap explicitly rather than inventing data.

If mode == "followup":
  - Do not call any tools. Treat the provided transcript/notes text as the sole source of truth.

Output ONLY a JSON object (no prose, no markdown fences) with this shape:
{
  "mode": "prep" | "followup",
  "attendees": ["name or email", ...],
  "background": "concise synthesis of what you found or were given, in your own words",
  "source_text": "the raw transcript text if mode == followup, else empty string"
}
""",
    tools=[workspace_toolset],
    output_key="meeting_context",
)

# ---------------------------------------------------------------------------
# 2. Analysis Agent
# ---------------------------------------------------------------------------
analysis_agent = LlmAgent(
    name="AnalysisAgent",
    model=MODEL,
    description="Turns raw meeting context into a structured brief (prep) or action items (followup).",
    instruction="""
You are the Analysis Agent. You receive the previous agent's output as {meeting_context},
a JSON string. Parse it.

If meeting_context.mode == "prep":
  Produce a meeting brief: for each attendee, a 1-2 sentence note on relevant background;
  a short list of open issues or unresolved threads; 3-5 suggested talking points.

If meeting_context.mode == "followup":
  Read meeting_context.source_text and extract:
  - a short summary of what was discussed and decided (3-5 sentences)
  - a list of action items, each with: owner (best guess from the text), task, deadline
    (if mentioned, else "not specified")

Output ONLY a JSON object (no prose, no markdown fences):
{
  "mode": "prep" | "followup",
  "summary": "...",
  "talking_points": ["...", ...],      // prep mode: fill this, followup mode: []
  "action_items": [                     // followup mode: fill this, prep mode: []
    {"owner": "...", "task": "...", "deadline": "..."}
  ]
}
""",
    output_key="analysis_result",
)

# ---------------------------------------------------------------------------
# 3. Output Agent
# ---------------------------------------------------------------------------
output_agent = LlmAgent(
    name="OutputAgent",
    model=MODEL,
    description="Produces the final deliverable: a dashboard-ready brief, or a draft follow-up email.",
    instruction="""
You are the Output Agent. You receive {analysis_result} as a JSON string. Parse it.

If analysis_result.mode == "prep":
  Do NOT send anything. Just format analysis_result into a clean markdown brief
  (headings: Attendees, Background, Open issues, Suggested talking points).

If analysis_result.mode == "followup":
  Use the gmail tool to CREATE A DRAFT (never send) addressed to the attendees, subject
  "Meeting follow-up: action items", body listing the summary and each action item.
  This is a draft only - a human must review and send it.

Output ONLY a JSON object (no prose, no markdown fences):
{
  "mode": "prep" | "followup",
  "markdown_brief": "... (prep mode only, else empty string)",
  "draft_created": true | false,        // followup mode only, else false
  "action_items": [ ... same shape as analysis_result.action_items, followup mode only ]
}
""",
    tools=[workspace_toolset],
    output_key="final_output",
)

# ---------------------------------------------------------------------------
# Root pipeline
# ---------------------------------------------------------------------------
root_agent = SequentialAgent(
    name="MeetingPrepFollowupPipeline",
    description="End-to-end meeting prep and follow-up assistant.",
    sub_agents=[context_gatherer_agent, analysis_agent, output_agent],
)
