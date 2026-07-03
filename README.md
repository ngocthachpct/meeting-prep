# Meeting Prep & Follow-up Agent

A multi-agent system that helps prepare before meetings and summarize action items afterward,
using Google ADK for the agent tier and Node/Next.js for the application tier.
See `DEMO_SCRIPT.md` for the product demo script.

## Architecture

```
web (Next.js + Tailwind + shadcn/ui)  --HTTP-->  gateway (NestJS)  --HTTP-->  agent-service (ADK + FastAPI)
                                                                                    |
                                                                             McpToolset (Gmail/Calendar/Drive)
```

- **web/** — Dashboard (Next.js 14 App Router, Tailwind CSS 3, shadcn/ui):
  input meeting ID (prep) or paste transcript (followup), displays results as cards with an action items table.
- **gateway/** — NestJS: validates API key (Bearer token), calls agent-service,
  persists action items to a file-based tracker (swap for Postgres/Firestore in production).
  API: `POST /meetings/prep`, `POST /meetings/followup`, `GET /meetings/tracker`.
- **agent-service/** — FastAPI with an ADK pipeline of 3 sequential agents (`SequentialAgent`):
  API: `POST /meetings/prep`, `POST /meetings/followup`, `GET /healthz`.
  Pipeline:
  1.  `ContextGathererAgent` — reads Calendar/Gmail/Drive via MCP (prep mode) or receives transcript directly (followup mode)
  2.  `AnalysisAgent` — summarizes into a meeting brief (prep) or extracts action items (followup)
  3.  `OutputAgent` — formats brief for dashboard (prep) or creates a draft email via Gmail MCP tool (followup, does not send)

System prompts for each agent live in `agent-service/meeting_agent/agent.py`.

### File structure — web/

```
web/
├── app/
│   ├── globals.css          # Tailwind directives + shadcn CSS variables
│   ├── layout.tsx           # Root layout (Inter font)
│   └── page.tsx             # Main dashboard (shadcn components)
├── components/
│   └── ui/
│       ├── alert.tsx        # shadcn Alert (error display)
│       ├── badge.tsx        # shadcn Badge (mode/status)
│       ├── button.tsx       # shadcn Button
│       ├── card.tsx         # shadcn Card (section container)
│       ├── input.tsx        # shadcn Input (meeting ID)
│       ├── separator.tsx    # shadcn Separator
│       └── textarea.tsx     # shadcn Textarea (transcript)
├── lib/
│   └── utils.ts             # cn() helper (clsx + tailwind-merge)
├── tailwind.config.ts       # Tailwind config + shadcn theme
├── postcss.config.js        # PostCSS (Tailwind + Autoprefixer)
├── tsconfig.json            # TypeScript config
└── package.json
```

## Prerequisites

### Google Workspace CLI (gws)

Use `gws-mcp-server` to expose Gmail, Calendar, Drive tools to the AI agent.

```bash
# Install gws CLI (once)
npm install -g @googleworkspace/cli

# First-time auth — opens browser to sign in with Google
gws auth setup
```

### GWS MCP server

ADK automatically spawns `gws-mcp-server` over stdio — no separate terminal needed.

```bash
npm install -g gws-mcp-server
```

Verify auth is working:

```bash
gws drive files list --params '{\"pageSize\": 3}'
```

## Running locally

### 1. Agent service (Python)

```powershell
cd agent-service
python -m venv .venv
(deactivate -> exit)
# Activate venv (choose one based on your OS):
# PowerShell:  .\.venv\Scripts\Activate.ps1
# CMD:         .venv\Scripts\activate.bat
# bash:        source .venv/bin/activate

pip install -r requirements.txt
copy .env.example .env   # fill in GOOGLE_API_KEY, AGENT_MODEL, GWS_MCP_SERVICES

# debug individual agents in ADK's browser UI
adk web

# or run the real API for the gateway to call
uvicorn main:app --reload --port 8000
```

> **Note:** The MCP server (`gws-mcp-server`) is automatically spawned by ADK over stdio when the agent runs — no need to run it separately.

### 2. Gateway (NestJS)

```bash
cd gateway
npm install
npx nest new . --skip-install   # if nest-cli.json is missing, run once to generate boilerplate (or create nest-cli.json manually — see below)
cp .env.example .env            # fill in AGENT_SERVICE_URL, API_KEY, TRACKER_FILE_PATH
npm run start:dev
```

If `nest-cli.json` doesn't exist, create it with:

```json
{
  "$schema": "https://json.schemastore.org/nest-cli",
  "collection": "@nestjs/schematics",
  "sourceRoot": "src"
}
```

Run tests:

```bash
cd gateway
npm test
```

### 3. Web (Next.js + Tailwind + shadcn/ui)

```bash
cd web
npm install
npm run dev
```

By default the web dashboard uses `http://localhost:3001` for the gateway and `demo-api-key-123` as the API key.
Override via env:

```bash
echo "NEXT_PUBLIC_GATEWAY_URL=http://localhost:3001" > .env.local
echo "NEXT_PUBLIC_API_KEY=demo-api-key-123" >> .env.local
```

## Deploy (production path — Day 5 of the course)

- `agent-service`: `adk deploy cloud_run --project=$PROJECT_ID --region=us-west1 --service_name=meeting-agent`
  or deploy to Vertex AI Agent Engine for built-in observability/scaling.
- `gateway`: deploy the NestJS container to Cloud Run, set `AGENT_SERVICE_URL` + `API_KEY`.
- `web`: deploy Next.js to Vercel or Cloud Run, set `NEXT_PUBLIC_GATEWAY_URL` + `NEXT_PUBLIC_API_KEY`.

## Tech stack

| Layer      | Technology                                                                |
| ---------- | ------------------------------------------------------------------------- |
| Frontend   | React 18, Next.js 14 (App Router), Tailwind CSS 3, shadcn/ui              |
| Backend    | NestJS 10 (gateway), FastAPI + Google ADK (agent-service)                 |
| AI         | Google Gemini 2.5 Flash, 3-agent `SequentialAgent` pipeline               |
| Tools/APIs | Gmail, Calendar, Drive (via MCP / Streamable HTTP)                        |
| Auth       | API key (Bearer token) — gateway                                          |
| State      | File-based JSON tracker (gateway), InMemorySessionService (agent-service) |

## Capstone rubric mapping

| Criterion                | How the project addresses it                                                                                                                |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------- |
| Problem framing          | Solves a real pain point: time spent preparing for meetings + forgetting action items afterward                                             |
| Multi-agent architecture | 3 specialized agents orchestrated by `SequentialAgent`, passing state via `output_key`                                                      |
| Tool/API integration     | `McpToolset` connects to real Gmail/Calendar/Drive — no mock data                                                                           |
| Quality & guardrails     | Output agent only creates **draft** emails, never sends — human always reviews first; gateway validates action items (non-empty owner/task) |
| Production readiness     | Agent runtime decoupled from gateway/frontend, deployable to Cloud Run / Vertex AI Agent Engine                                             |
| State/memory             | Action item tracker persisted via JSON file (gateway), survives restarts                                                                    |
| Security                 | API key authentication (Bearer token) on all gateway endpoints                                                                              |
| UI/UX                    | Responsive dashboard with shadcn/ui, loading state, error alerts, action items table                                                        |

## Roadmap

- [x] Replace in-memory tracker with file-based JSON (gateway)
- [x] Add evaluation set (10 test cases) + runner script (`agent-service/evaluation/`)
- [x] Add guardrail: reject agent output if action item has empty owner or task
- [x] Add auth: API key (Bearer token) for gateway
- [x] Improve UI with shadcn/ui components
- [x] Add unit tests for gateway (8 tests) + agent-service (7 tests)
- [x] Standardize local run instructions for Windows/PowerShell
- [x] Migrate MCP transport from Streamable HTTP to stdio (ADK spawns `gws-mcp-server` automatically)
