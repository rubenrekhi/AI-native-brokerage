# Sevino

Sevino is an AI-native brokerage app for US consumers, built by [Sevino](https://sevino.ai). Users trade stocks in natural language, get AI-driven trade and portfolio analysis, and manage their investments — all through a mobile-first experience.

## How It Works

The iOS app is the user-facing interface. It communicates with a FastAPI backend over HTTPS using REST APIs and SSE streams. User requests are authenticated with a JWT issued by Supabase Auth; hosted environments also require the static `X-API-Key` gate.

```
┌──────────────┐     HTTPS + JWT/API key    ┌──────────────┐
│              │  ────────────────────────▶ │              │
│  Sevino App  │                            │  Sevino API  │
│  (Swift/     │  ◀──────────────────────── │  (FastAPI)   │
│   SwiftUI)   │        JSON responses      │              │
└──────────────┘                            └──────┬───────┘
                                                   │
                                  Backend dependencies/providers
                                                   │
             ┌───────────┐ ┌───────────┐ ┌───────────┐ ┌─────────┐
             │ Supabase  │ │  Alpaca   │ │   Plaid   │ │ Redis   │
             │ Postgres  │ │ Broker API│ │    API    │ │ + ARQ   │
             └───────────┘ └───────────┘ └───────────┘ └─────────┘
             ┌───────────┐ ┌───────────┐ ┌───────────┐
             │ Anthropic │ │    FMP    │ │ Langfuse  │
             │  Claude   │ │Market Data│ │  Tracing  │
             └───────────┘ └───────────┘ └───────────┘
```

- **Supabase Postgres** — user profiles, AI conversation history, app data. Accessed via SQLAlchemy + asyncpg.
- **Alpaca Broker API** — brokerage accounts, KYC, trading, portfolio data, custody of funds. Source of truth for all financial data.
- **Plaid** — bank account linking for deposits/withdrawals via ACH.
- **Redis + ARQ** — background job queue for AI agent processing, trade analysis, scheduled tasks, SSE listeners, funding reconciliation, radar refreshes, and digest generation.
- **Anthropic Claude** — AI agent runtime for natural-language brokerage workflows.
- **Langfuse** — optional tracing and cost observability for AI turns.
- **Financial Modeling Prep (FMP)** — market data, fundamentals, news, earnings, radar/digest enrichment, and optional chart-bar source during the FMP bars rollout.

## Development Setup

- Backend setup, provider keys, migrations, tests, and worker commands live in [sevino-api/README.md](sevino-api/README.md).
- iOS setup, Xcode configuration, local API wiring, and app test notes live in [sevino-app/README.md](sevino-app/README.md).
- Backend environment variables are copied from [sevino-api/.env.example](sevino-api/.env.example).

## Monorepo Structure

```
sevino/
├── .claude/          # Claude Code configuration
├── .github/          # GitHub Actions workflows (backend CI currently)
├── README.md         # ← you are here
├── sevino-api/       # FastAPI backend (Python)
│   └── README.md     # Backend setup & dev guide
└── sevino-app/       # iOS app (Swift/SwiftUI)
    └── README.md     # Frontend setup & dev guide
```

The backend deploys to Railway. The iOS app builds in Xcode and ships via TestFlight / App Store. They are independent deployment pipelines connected only by the API contract.

## Team

| Name | Role |
|------|------|
| Ruben Rekhi | CTO |
| Tharsihan Ariyanayagam | CPO |
| Shivam Suri | CEO |
