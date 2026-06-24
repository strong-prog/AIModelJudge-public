# AIModelJudge — The AI Code Judge

**AIModelJudge** is a platform that helps developers make better decisions with AI. It runs multiple models simultaneously, compares their answers side-by-side, and delivers a single verified result. Think of it as a "council of experts" for your code.

Ask a question once — get three AI perspectives, watch them reason in real time, and receive a synthesized final answer backed by multiple models.

**Stack:** Python FastAPI + React 18 / TypeScript / Vite + D3.js + SQLite + aiogram (Telegram)

---

## Architecture

```
React SPA (:5173 dev, :9651 prod)     FastAPI Backend (:9651)
┌──────────────────────────────┐      ┌──────────────────────────────┐
│ Center Panel  │ Side Panels  │      │ routes.py       98 endpoints│
│ • SSE streaming              │      │ auth.py         JWT + API key│
│ • Tool cards                 │      │ tiers.py        feature flags│
│ • Thinking blocks            │◄─────│ primary_models  SSE streaming│
│ • Phase indicator            │ SSE  │ hooks.py        8 hook types │
├──────────────────────────────┤      │ rules.py        Rules engine │
│ Navigator: Sessions, Skills, │      │ prompt_guard    injection def│
│ Projects, Kanban, Cron       │      │ secrets_vault   Fernet vault │
│ Modals: Settings, Analytics, │      │ telegram_bot    aiogram      │
│ Login, Account               │      │ model_cache     LRU + TTL    │
└──────────────────────────────┘      └──────────────────────────────┘
```

### Judge Pipeline

1. **Analyze** — Determines which models to query and what context they need
2. **Compare** — Queries models in parallel (center + up to 2 side panels)
3. **Synthesize** — Tool calls execute and results are collected
4. **Deliver** — Final response streamed to the user via SSE

---

## Features

### Core
- **Multi-model SSE streaming** — concurrent model responses with Server-Sent Events
- **3-panel UI** — central judge with optional side expert panels
- **Thinking blocks** — reasoning separated from final responses (DeepSeek/R1-style)
- **Phase indicator** — visual progress through the 4-phase pipeline
- **Tool execution** — code search, file read/write, bash, web search, diff

### Security
- **Prompt injection defense** — pattern-based detection and sanitization
- **Rules engine** — configurable rules with hook-based custom actions
- **Encrypted secrets vault** — Fernet encryption at rest, vault-first with env fallback
- **JWT authentication** — API key + JWT with scope-based access (full/readonly/admin)
- **Audit logging** — JSONL audit trail with HMAC-SHA256 tamper detection
- **Rate limiting** — TokenBucket algorithm, 120 req/min per user
- **Execution sandbox** — subprocess isolation with resource limits

### Extras
- **Telegram bot** — `/judge` command for code review via Telegram
- **Kanban board** — task tracking with auto-generated action items
- **Skill system** — save and reuse successful prompt patterns
- **Cron scheduler** — recurring prompts with toggle and history
- **Memory graph** — D3.js force-directed visualization of session context
- **Dark/light themes** — CSS custom properties with comfort mode (reduced contrast)

---

## Quick Start

```bash
# Backend
pip install -r requirements.txt
PYTHONPATH=$PWD:$PWD/web:$PWD/services/shared python web/main.py

# Frontend dev server
cd web-react && npm install && npm run dev

# Production build (backend serves /app from dist)
cd web-react && npm run build
```

Requires Python 3.11+ and Node.js 18+.

Copy `.env.example` to `.env` and set `AMJ_JWT_SECRET` before running.

---

## Project Structure

```
web/                         # FastAPI backend
├── main.py                  # App factory, middleware, migrations
├── routes.py                # 98 API routes
├── primary_models.py        # Multi-model SSE streaming
├── auth.py                  # Authentication and user context
├── tiers.py                 # Feature flags and limits
├── hooks.py                 # Hook engine (8 hook types)
├── rules.py                 # Configurable rules engine
├── prompt_guard.py          # Prompt injection defense
├── secrets_vault.py         # Encrypted secrets management
├── model_cache.py           # LRU cache with adaptive TTL
├── data_layer.py            # SQLite data access layer
├── telegram_bot.py          # Telegram bot (aiogram v3)
├── cost_guard.py            # Usage tracking and limits
├── benchmarks.py            # Performance metrics (p50/p95)
├── sandbox.py               # Execution isolation
└── metrics.py               # Prometheus counters

web-react/src/               # React TypeScript frontend
├── App.tsx                  # Root component with providers
├── context/                 # AuthContext, AppContext (global state)
├── hooks/useSSE.ts          # SSE streaming hook
├── lib/api.ts               # API client (fetch wrapper)
├── components/
│   ├── chat/                # MessageInput, ChatMessage, ThinkingBlock
│   ├── layout/              # AppLayout, PanelStream, PhaseIndicator
│   ├── modals/              # Settings, Login, Account
│   └── views/               # Sessions, Kanban, Skills, Analytics, Memory
└── index.css                # Theme system (CSS custom properties)

services/shared/             # Backend-shared modules
├── hermes_proxy_v2.py       # SSE relay loop
├── tool_executor.py         # Tool dispatch and sandboxing
└── model_router.py          # Multi-model routing logic
```

---

## API Overview

| Group | Endpoints |
|-------|-----------|
| Chat | `POST /chat` (SSE), `POST /approve`, `POST /cancel` |
| Auth | `POST /auth/register`, `POST /auth/login`, `GET /auth/me` |
| Models | `GET /model/list`, `GET /model/current`, `POST /model/switch` |
| Sessions | `GET /sessions/recent`, `GET /sessions/{id}` |
| Skills | `GET /skills/list`, `POST /skills/create`, `POST /skills/rate` |
| Kanban | `GET /kanban/tasks`, `POST /kanban/tasks`, `PATCH /kanban/tasks/{id}` |
| Cron | `GET /cron/list`, `POST /cron/create`, `POST /cron/toggle` |
| Profiles | `GET /profile/list`, `GET /profile/current`, `POST /profile/switch` |
| Tools | `POST /diff`, `POST /upload` |
| Analytics | `GET /analytics/tokens`, `GET /benchmarks/stats` |

Interactive docs at `/docs` (Swagger UI) when the server is running.

---

## Security Scanning

Pre-commit hooks run automated secret detection on every commit:

```bash
pre-commit run --all-files        # all hooks (detect-secrets + trufflehog)

trufflehog filesystem . --no-update    # ad-hoc scan
detect-secrets scan --all-files        # ad-hoc scan
```

Configuration in `.pre-commit-config.yaml`, audited baseline in `.secrets.baseline`.

---

## Testing

```bash
bash tests/regression_test.sh
PYTHONPATH=$PWD:$PWD/web:$PWD/services/shared python tests/load_test.py
PYTHONPATH=$PWD:$PWD/web:$PWD/services/shared python tests/test_profiles.py
python tests/test_isolation.py
```

---

## Who is this for?

- **Developers** — get instant, multi-model code reviews without switching tabs
- **Teams** — reduce decision fatigue by comparing multiple AI perspectives
- **Tech leads** — enforce coding standards with custom rules and hooks
- **Startups** — evaluate which AI model works best for your use case

## License

MIT — see [LICENSE](./LICENSE)
