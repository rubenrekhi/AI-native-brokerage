# Saturn

Saturn is an AI-native brokerage app for US consumers, built by [Sevino](https://sevino.ai). Users trade stocks in natural language, get AI-driven trade and portfolio analysis, and manage their investments — all through a mobile-first experience.

## How It Works

The iOS app is the user-facing interface. It communicates with a FastAPI backend over HTTPS using REST APIs. Every request is authenticated with a JWT issued by Supabase Auth.

```
┌──────────────┐        HTTPS + JWT        ┌──────────────┐
│              │  ────────────────────────▶ │              │
│  Saturn App  │                            │  Saturn API  │
│  (Swift/     │  ◀──────────────────────── │  (FastAPI)   │
│   SwiftUI)   │        JSON responses      │              │
└──────────────┘                            └──────┬───────┘
                                                   │
                              ┌─────────────┬──────┴───────┬─────────────┐
                              │             │              │             │
                        ┌─────▼─────┐ ┌─────▼─────┐ ┌─────▼─────┐ ┌────▼────┐
                        │ Supabase  │ │  Alpaca   │ │   Plaid   │ │  Redis  │
                        │ Postgres  │ │ Broker API│ │    API    │ │  + ARQ  │
                        └───────────┘ └───────────┘ └───────────┘ └─────────┘
```

- **Supabase Postgres** — user profiles, AI conversation history, app data. Accessed via SQLAlchemy + asyncpg.
- **Alpaca Broker API** — brokerage accounts, KYC, trading, portfolio data, custody of funds. Source of truth for all financial data.
- **Plaid** — bank account linking for deposits/withdrawals via ACH.
- **Redis + ARQ** — background job queue for AI agent processing, trade analysis, and scheduled tasks.

## Monorepo Structure

```
saturn/
├── .claude/          # Claude Code configuration
├── .github/          # CI workflows (backend + frontend, triggered independently)
├── README.md         # ← you are here
├── saturn-api/       # FastAPI backend (Python)
│   └── README.md     # Backend setup & dev guide
└── saturn-app/       # iOS app (Swift/SwiftUI)
    └── README.md     # Frontend setup & dev guide
```

The backend deploys to Railway. The iOS app builds in Xcode and ships via TestFlight / App Store. They are independent deployment pipelines connected only by the API contract.

## Team

| Name | Role |
|------|------|
| Ruben Rekhi | CTO |
| Tharsihan Ariyanayagam | CPO |
| Shivam Suri | CEO |