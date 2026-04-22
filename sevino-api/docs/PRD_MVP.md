# SEVINO — Product Requirements Document

**AI-Native Investing Platform — Stage 1A: Chat-First AI Brokerage**

Version 2.0 | March 2026 | Confidential
Team: 3 Technical Co-Founders (Full-Time) | Status: Draft

---

## 1. Introduction & Overview

Sevino is a chat-first AI brokerage built for the 100+ million Americans who know they should be investing but don't feel confident enough to start. Rather than bolting AI onto a traditional brokerage dashboard, Sevino replaces the dashboard entirely. The AI is the interface. There is no portfolio view to navigate, no stock screener to learn, no chart to interpret. There is a conversation.

When a user opens Sevino, they see a chat. The AI knows their income, their goals, their risk tolerance, and their portfolio. It greets them, surfaces what's relevant, and helps them make decisions through natural dialogue. When they're ready to act, they say "Buy $500 of VTI" and the AI presents a trade confirmation card inline. They long-press. Done.

This PRD defines the scope for **Stage 1A**: the chat-first AI brokerage shipping as a **closed beta on iOS via TestFlight**.

### 1.1 Why Now

- Brokerage-as-a-service infrastructure (Alpaca) allows startups to offer real trading without becoming a broker-dealer.
- LLMs with tool-calling can retrieve real-time financial data, parse SEC filings, and reason about portfolios — eliminating the hallucination risk that previously made AI unsafe for finance.
- Incumbent brokerages cannot rebuild their products around chat without abandoning billions of dollars in existing dashboard infrastructure.
- No existing AI finance app combines conversational research, personalized analysis, and trade execution in a single interface.
- 73% of Gen Z aspiring investors say they don't know how to start investing. 44% of non-investors feel overwhelmed by the process. The problem is not access — it's confidence.

### 1.2 Who We Build For — "Ready Riley"

Riley is 26, makes $82K, has $12K in savings, and has downloaded Robinhood twice and closed it both times. She is not financially illiterate — she understands compound interest, knows the word "ETF," and has a 401(k) through work. But she is a vibe investor with no analytical framework. Her biggest fear is making a mistake with real money and not knowing it.

**Riley Litmus Test — every feature must pass:**

- Would this make Riley more confident?
- Would Riley understand this without Googling?
- Does this respect Riley's intelligence?
- Does this bring Riley closer to action?
- Would Riley tell a friend about this?

### 1.3 Competitive Landscape

| Competitor | What They Do | Sevino Differentiation |
|---|---|---|
| Robinhood | Self-directed brokerage, dashboard-first | Chat IS the interface. AI researches, explains, and executes in one thread |
| Wealthfront / Betterment | Robo-advisors with preset portfolios | Conversational AI, flexible strategies, user stays in control |
| Astor | SEC-registered AI advisor, voice chat | Sevino executes trades. Astor cannot. |
| Schwab / Fidelity | Full-service, legacy interfaces | AI-first experience; no dashboard to learn |
| Public.com | Social investing, AI stock summaries | No personalization or execution from AI |
| AInvest / Magnifi | AI search and analysis tools | Dashboard-first; Sevino's AI is the product |

---

## 2. Goals & Objectives

### 2.1 MVP Goal

Validate that a chat-first AI brokerage — with no traditional dashboard — drives higher engagement, faster first trades, and better retention than traditional brokerage interfaces, within a controlled closed beta on iOS.

### 2.2 SMART Objectives

| Category | Metric | Target |
|---|---|---|
| Acquisition | Waitlist signups | 1,000+ pre-launch |
| Acquisition | Beta users (TestFlight) | 200–500 active |
| Activation | Onboarding completion | 80%+ |
| Activation | First AI interaction in first session | 95%+ |
| Activation | Alpaca account opening in first session | 40%+ |
| Engagement | AI messages/user/day | 5+ average |
| Engagement | Weekly retention (Week 4) | 40%+ |
| Engagement | DAU/MAU ratio | >25% |
| Conversion | Alpaca funding rate (within 7 days) | 70%+ |
| Conversion | First trade (within 14 days of funding) | 50%+ |
| Financial | Aggregate AUM | $500K–$1M |
| Financial | Average deposit size | $1,000–$5,000 |
| Quality | AI response accuracy | <2% user-reported errors |
| Quality | Trade execution errors | <0.1% |
| Quality | Beta NPS | 50+ |

---

## 3. App Architecture & Navigation

Sevino's interface is radically simple. There are **three surfaces** and **no bottom navigation bar**.

### 3.1 Main Screen: The Chat

The main screen is a full-screen chat interface with three elements:

**Persistent Status Bar** — A thin, always-visible bar at the top showing: (1) portfolio value with daily change indicator (green up / red down arrow), (2) AI Radar icon, (3) Holdings icon. Force-pressing the portfolio value opens a modal with a performance chart. Tapping the Radar icon navigates to the Radar page. Tapping the Holdings icon opens holdings items.

**Chat Area** — The main conversational interface. Displays AI messages (text + MCP UI cards), user messages, and interactive elements (trade confirmations, stock info cards, charts, portfolio visuals). Each session is a new conversation thread. The AI sends a static greeting when a new chat opens.

**Input Area** — Timed contextual shortcut bubbles above the text input field. Shortcuts change based on time of day, market conditions, and user context. Below the shortcuts is the standard text input with send button.

### 3.2 Swipe Left: Chat History

Swiping left from the main screen reveals the chat history panel — a scrollable list of previous conversation threads (like ChatGPT's sidebar). Each thread shows a title (AI-generated summary or first message), date, and preview. Tapping a thread opens it in the main chat area. At the bottom of the history panel is a **Settings button** that navigates to the settings screen.

### 3.3 AI Radar

Force clicking the radar button from the main screen reveals the full AI Radar — a scrollable list of stocks and ETFs the AI has identified as relevant to the user based on their profile, goals, and market conditions. Each item shows: ticker, company name, a one-line AI-generated context blurb, and current price with daily change.

Tapping any Radar item opens the main chat and surfaces an MCP UI card with detailed stock information. The user can then continue the conversation about that stock, ask follow-up questions, or execute a trade.

Items remain on the Radar for 7 days unless the user favorites them (favorites persist until manually removed) or the AI determines they're no longer relevant. The AI refreshes the Radar daily.

---

## 4. Functional Requirements

### 4.1 Chat-Based Onboarding

> Riley's first experience feels like a conversation, not a form.

**FR-1.1** Upon first login, the system shall present an onboarding experience styled as a chat conversation. The UI uses the same chat interface as the main app (message bubbles, interactive elements) but the flow is **scripted — not AI-generated** — for speed, consistency, and regulatory compliance.

**FR-1.2** The onboarding chat shall collect:
- Date of birth
- Annual income
- Net worth
- Risk tolerance (ask: what would you do if your portfolio dropped 20% — sell, hold, buy more)
- Investment goals (retirement, house down payment, general wealth building, education, other)
- Time horizon (1–3 years, 3–7 years, 7+ years)
- Experience level (beginner / intermediate / advanced)

**FR-1.3** Each field shall include a brief, plain-language explanation delivered as a chat message. Example: "Risk tolerance is basically how you'd feel if your investments dropped 20%. Would you panic-sell, hold tight, or buy more?"

**FR-1.4** Interactive elements (buttons, sliders, selection cards) shall be used for responses rather than free-text input where possible.

**FR-1.5** Upon completing the questionnaire, the system shall prompt the user to open an Alpaca brokerage account with the ability to: "Set up my account now".

**FR-1.6** Alpaca account creation (KYC/AML flow) shall occur in the **Settings screen under Accounts**, not within the onboarding chat.

**FR-1.7** All onboarding data shall be stored as the user's **Profile Card** and injected into the AI agent's context for every conversation.

**FR-1.8** Upon completing onboarding and the optional account setup prompt, the AI shall take over with full context: "Nice to meet you, Riley. Based on what you told me, here's what I'd suggest we talk about first."

### 4.2 Profile Card

> The AI's memory of Riley.

**FR-2.1** The system shall maintain a Profile Card for each user containing all data collected during onboarding: date of birth (age), income, net worth, risk tolerance, investment goals, time horizon, and experience level.

**FR-2.2** The Profile Card shall be injected into the AI agent's context for every conversation, ensuring every response is personalized to the user's financial situation and goals.

**FR-2.3** The user shall be able to view and edit their Profile Card from Settings > Personal Information at any time.

**FR-2.4** When the user updates their Profile Card, the changes shall be reflected in all subsequent AI conversations immediately.

**FR-2.5** The AI shall adapt its language complexity based on the experience level in the Profile Card: simpler explanations for beginners, more sophisticated analysis for advanced users.

### 4.3 Alpaca Brokerage Integration

> A real brokerage account, inside the app.

**FR-3.1** The system shall integrate with **Alpaca's Broker API** to allow users to open a brokerage account within the Sevino app.

**FR-3.2** Account creation shall include KYC/AML verification handled entirely by Alpaca. All KYC data shall be collected within the Sevino settings UI and submitted to Alpaca's Broker API. The user shall **not** be redirected to an Alpaca-hosted page.

**FR-3.3** The system shall support ACH fund deposits and withdrawals within the app via Alpaca's Transfers API. Bank account linking shall use **Plaid Link** to capture account information and generate a processor token passed to Alpaca's ACH API.

**FR-3.4** Deposit flow:
1. User links bank account via Plaid Link (one-time)
2. User enters deposit amount in Settings
3. User confirms
4. System initiates ACH transfer via Alpaca
5. UI communicates expected settlement time (1–3 business days)

**FR-3.5** Withdrawal flow follows the same pattern with direction set to outgoing.

**FR-3.6** The system shall support **fractional share purchases** through Alpaca.

**FR-3.7** Asset classes supported: **US equities and ETFs only**. No crypto, no options.

**FR-3.8** SIPC protection information ($500,000 per customer, $250,000 cash sub-limit) shall be displayed during account creation and accessible in Settings.

**FR-3.9** Account details (cash balance, buying power, holdings, order history) shall be accessible through Settings > Accounts and via the status bar force-press modal.

**FR-3.10** Uninvested USD cash in the user's Alpaca account shall automatically earn interest via Alpaca's **High-Yield Cash program (FDIC Bank Sweep)**. Enrollment shall occur automatically upon account creation.

**FR-3.11** Sevino shall configure a **0.10% APR partner take rate**. The remaining interest shall be passed through to the user. At the current underlying rate, this results in approximately **3.20% APY** for the user.

**FR-3.12** The user's current APY and accrued interest shall be visible in the plus icon in the chat section, and surfaced by the AI when the user asks about their cash or account balance.

**FR-3.13** The AI shall reference the interest rate when relevant in conversation: "Your $2,400 in uninvested cash is earning 3.20% APY — that's about 8x the national average!"

**FR-3.14** Cash balances enrolled in the FDIC Bank Sweep are potentially eligible for FDIC pass-through insurance up to $2,500,000 per customer. This shall be communicated during account creation and in Settings > Accounts.

**FR-3.15** The interest rate is variable and tied to the federal funds rate. The app shall display the current rate with a disclaimer that it is subject to change.

### 4.4 AI Agent — Core Behavior

> The AI is the product.

**FR-4.1** The AI agent shall be the **primary interface** of the application. There is no separate dashboard or portfolio view — all information is delivered through the chat via text responses and MCP UI components.

**FR-4.2** The AI agent shall receive the user's **Profile Card** (risk tolerance, goals, time horizon, experience level, income, net worth, age) as context for every conversation.

**FR-4.3** The AI agent shall receive the user's current **Alpaca holdings, balances, and account status** as context for portfolio-related queries.

**FR-4.4** The AI agent shall use **Claude (Anthropic)** as the LLM provider with tool/function calling to interact with external APIs.

**FR-4.5** The AI agent shall adapt language complexity based on the user's experience level: simpler explanations for beginners, more sophisticated analysis for advanced users.

**FR-4.6** Each conversation shall be a separate thread. Opening the app starts a new conversation. Users can access and resume previous conversations via the chat history panel (swipe left).

**FR-4.7** The AI shall send a **static greeting message** when a new conversation opens. The greeting shall include the user's name and a brief portfolio status (if they have an Alpaca account): "Good morning, Riley. Your portfolio is at $4,230, up 1.2% today. What's on your mind?"

**FR-4.8** When the AI lacks sufficient data to answer a question, it shall **state this clearly rather than hallucinating**. All financial data shall be retrieved via tool calls, never generated from training data.

**FR-4.9** The user should be able to turn off the AI's access to the internet for security reasons. This is turned on by default.

### 4.5 AI Agent — MCP UI Components

> Information rendered visually, inline, in the conversation.

MCP UI is the primary mechanism for displaying structured information in the chat. Rather than typing long text responses, the AI renders interactive visual components inline.

**FR-5.1** The AI shall render MCP UI cards for the following content types:

- **Stock Info Card:** Ticker, company name, current price, daily change, mini sparkline chart, key metrics (market cap, P/E, 52-week range, dividend yield). Rendered when the user asks about a specific stock or taps an AI Radar item.
- **Trade Confirmation Card:** Ticker, company name, order type, action, quantity or dollar amount, estimated cost, account. Long-press to execute. Show success or error on execution.
- **Portfolio Summary Card:** Total portfolio value, daily change, allocation breakdown, top holdings. Rendered when the user asks about their portfolio or force-presses the status bar.
- **Performance Chart Card:** Interactive line chart with selectable time ranges (1D, 1W, 1M, 3M, 6M, 1Y, All). Rendered when discussing portfolio or stock performance.
- **AI Radar Card:** Stock info card variant with AI-generated context blurb explaining relevance. Rendered when the user taps a Radar item.
- **Earnings Summary Card:** Revenue vs estimate, EPS vs estimate, guidance, key highlights. Rendered when discussing earnings.

**FR-5.2** MCP UI cards shall be interactive where appropriate: tappable elements to drill deeper, expandable sections for additional detail, and action buttons (e.g., "Buy this" on a Stock Info Card, "Tell me more" on a Radar Card).

**FR-5.3** The AI shall **prefer MCP UI cards over plain text** for any structured data. Prices, metrics, charts, comparisons, and trade confirmations shall always be rendered as cards, never as formatted text.

### 4.6 AI Agent — Research & Analysis

> Ask anything about any stock, anytime.

**FR-6.1** The agent shall answer general financial education questions without requiring an Alpaca account.

**FR-6.2** The agent shall retrieve and present real-time and historical market data for any US equity or ETF, rendered as MCP UI Stock Info Cards.

**FR-6.3** The agent shall perform factual stock analysis including financials, valuation metrics, revenue growth, and analyst sentiment.

**FR-6.4** The agent shall perform factual comparative analysis between securities when requested, rendered as MCP UI Comparison Cards.

**FR-6.5** The agent shall fetch and parse SEC filings (10-Ks, 10-Qs) from the **EDGAR API** and summarize relevant sections.

**FR-6.6** The agent shall fetch and summarize earnings call transcripts.

**FR-6.7** The agent shall perform portfolio descriptive analytics: sector allocation, geographic exposure, asset class breakdown, concentration analysis, and performance — rendered as MCP UI Portfolio Summary and Performance Chart Cards.

**FR-6.8** The agent shall provide general market commentary using real-time market data.

**FR-6.9** All research and analysis outputs shall include a disclaimer that information is for informational/educational purposes only.

### 4.7 AI Radar

> Stocks worth knowing about, surfaced by the AI.

**FR-7.1** The system shall maintain a personalized AI Radar for each user — a curated list of stocks and ETFs the AI has identified as potentially relevant based on the user's Profile Card (goals, risk tolerance, experience level, time horizon).

**FR-7.2** The AI shall populate and refresh the Radar daily based on the user's profile and current market conditions.

**FR-7.3** Each Radar item shall include: ticker, company name, current price, daily change, and a one-line AI-generated context blurb explaining relevance (e.g., "Broad market ETF aligned with your long-term wealth-building goal").

**FR-7.4** The Radar shall be accessible via the Radar icon in the status bar.

**FR-7.5** Tapping a Radar item shall open the main chat and surface an MCP UI Radar Card with detailed stock information. The user can then continue the conversation, ask follow-ups, or initiate a trade.

**FR-7.6** Items shall remain on the Radar for **7 days**. If the user does not interact with an item within 7 days, it is removed and replaced.

**FR-7.7** The user shall be able to "favorite" Radar items. Favorited items persist until manually unfavorited. Favorited items are also accessible via the Watchlist icon in the status bar.

**FR-7.8** When the user opens a new chat, the AI may reference new Radar additions in its greeting or surface 1–2 new items as cards: "I added VTI to your Radar this morning — it's a broad market ETF that aligns with your goals. Want to learn more?"

**FR-7.9** The AI Radar shall **NOT include directive language**. Items are surfaced as "potentially relevant" or "worth knowing about," never as recommendations to buy. Framing shall be educational and informational only.

**FR-7.10** The Radar algorithm shall consider: alignment with user's stated goals, risk tolerance match, portfolio diversification opportunities, market conditions, and sector relevance. It shall **NOT** consider payment, promotion, or any revenue-driven signal.

### 4.8 Natural Language Trading

> "Buy $200 of TSLA" → done.

**FR-8.1** Trade execution shall only be available for users with a **funded Alpaca account**.

**FR-8.2** When a user requests a trade via natural language, the agent shall parse the intent and present an **MCP UI Trade Confirmation Card**.

**FR-8.3** The Trade Confirmation Card shall display: ticker symbol, company name, order type (market/limit), action (buy/sell), quantity or dollar amount, estimated cost, and account.

**FR-8.4** The user shall **long-press** the Trade Confirmation Card to execute. No trade shall execute without this explicit confirmation.

**FR-8.5** There shall be **no dollar threshold** that bypasses confirmation. Every trade requires long-press regardless of size.

**FR-8.6** No additional PIN or biometric verification shall be required beyond the long-press.

**FR-8.7** Supported order types: **market and limit**.

**FR-8.8** Fractional shares shall be supported for all eligible securities.

**FR-8.9** If ambiguous, the AI shall ask for clarification: "Did you mean Apple Inc (AAPL) or Apple Hospitality REIT (APLE)?"

**FR-8.10** If a trade creates risky concentration (>50% in one stock), the agent shall flag the risk with a clear explanation but still execute if the user confirms. Sevino respects user autonomy.

**FR-8.11** The agent shall **never refuse to execute a legal, user-directed trade** on the basis of risk alone.

**FR-8.12** After execution, the agent shall display an MCP UI Trade Execution Card with fill details and portfolio impact.

**FR-8.13** If an order fails, the agent shall display an MCP UI Error Card explaining why and suggesting next steps.

**FR-8.14** When a user without an Alpaca account requests a trade, the agent shall explain that an account is needed and offer to guide them to Settings for setup.

**FR-8.15** When markets are closed, orders shall queue with clear warnings about potential price differences at market open.

### 4.9 Persistent Status Bar

> Key numbers, always visible.

**FR-9.1** A thin, persistent bar shall be displayed at the top of the chat screen at all times, below the system status bar.

**FR-9.2** The status bar shall display three items: (1) portfolio value with daily change indicator (green up / red down arrow), (2) AI Radar icon, (3) Holdings icon.

**FR-9.3** For users without an Alpaca account or with a $0 balance, the portfolio value area shall display "Set up your account" or a relevant CTA.

**FR-9.4** Force-pressing the portfolio value shall open a modal displaying: total portfolio value, daily change ($ and %), a performance chart with selectable time ranges, holdings breakdown, cash balance, and buying power. The modal shall include a "Chat about this" button that closes the modal and pre-loads a relevant prompt.

**FR-9.5** Tapping the AI Radar icon shall navigate to the Radar modal.

**FR-9.6** Tapping the Holdings icon shall open a modal showing all holdings with current account values.

**FR-9.7** The status bar shall update in real-time during market hours.

**FR-9.8** The status bar shall be visually minimal — thin, unobtrusive, and not competing with the chat for attention.

### 4.10 Timed Contextual Shortcuts

> The right question at the right time.

**FR-10.1** The system shall display contextual shortcut bubbles above the chat text input in every new conversation.

**FR-10.2** Shortcuts shall change based on time of day, market conditions, and user context:

- **Morning (pre-market, 6–9:30am ET):** "How's my portfolio?" / "Any news today?" / "Invest $100"
- **Market hours (normal):** "What's moving today?" / "Check my Radar" / "Show my portfolio"
- **Market hours (after >2% drop):** "What happened?" / "Am I okay?" / "Should I do anything?"
- **Post-earnings (for held/Radar stocks):** "How did [TICKER] do?" / "What does this mean for me?"
- **Evening (post-market):** "How did I do today?" / "Teach me something" / "Plan my next investment"
- **After inactivity (>7 days):** "What did I miss?" / "Catch me up" / "How's my portfolio?"
- **New user:** "Help me get started" / "What is investing?" / "How does this app work?"

**FR-10.3** Shortcuts shall be personalized where possible: if a stock the user holds just reported earnings, that ticker shall appear in suggestions.

**FR-10.4** Tapping a shortcut shall send it as a message in the chat, triggering the AI to respond as if the user typed it.

**FR-10.5** Shortcuts shall disappear once the user sends their first message (typed or tapped) and shall not reappear until a new conversation is started.

**FR-10.6** A maximum of **3–4 shortcut bubbles** shall be displayed at once to avoid visual clutter.

### 4.11 Regulatory Gating Framework

> What the AI can and cannot do — and why.

**FR-11.1** The AI agent's capabilities shall be controlled via **feature flags** that map to regulatory status.

**Ungated (no RIA required):**
- User-directed trade execution
- General financial education
- Factual research and data retrieval
- Comparative factual analysis
- SEC filing parsing and earnings summarization
- Portfolio descriptive analytics
- General market commentary

**Gray Area (ungated with educational framing):**
- General asset class guidance personalized to user profile ("Many financial professionals suggest...")
- Situational financial questions answered with general frameworks
- Portfolio drift detection as factual observation
- AI Radar surfacing specific stocks as "potentially relevant to your profile" — framed as informational discovery, not recommendations

**Gated (requires RIA, disabled via feature flag):**
- Recommending specific securities tied to user's personal situation
- Constructing personalized portfolios with specific tickers
- Proactive buy/sell recommendations
- Tax-loss harvesting recommendations
- Rebalancing recommendations
- Autonomous trading modes

**FR-11.2** When a user requests a gated capability, the agent shall explain the limitation naturally and redirect toward ungated capabilities.

**FR-11.3** The gating mechanism shall be implemented as configurable feature flags so capabilities can be enabled without code changes upon RIA registration.

### 4.12 Disclaimers & Legal

**FR-12.1** The app shall display a risk disclosure during onboarding before the Alpaca account creation prompt.

**FR-12.2** The app shall clearly state that Sevino is not a registered investment adviser and all AI content is for informational/educational purposes only.

**FR-12.3** The app shall display that brokerage services are provided by Alpaca Securities LLC, a FINRA member and SIPC-protected entity.

**FR-12.4** Terms of Service and Privacy Policy shall be presented and accepted during registration.

**FR-12.5** The AI agent shall include appropriate disclaimers when providing research, analysis, or educational commentary.

**FR-12.6** AI Radar items shall include a persistent disclaimer that surfaced stocks are not recommendations and are presented for informational purposes only.

---

## 5. Settings Screen

The settings screen is accessible via the Settings button at the bottom of the chat history panel (swipe left). It is organized into five sections.

### 5.1 Accounts

- **Alpaca Account:** Create account (if not yet created), view account status, account number, account type
- **Funding:** Link bank account (via Plaid Link), deposit funds, withdraw funds, view pending transfers
- **Holdings:** View current holdings with quantity, value, and gain/loss for each position
- **Order History:** View all past orders with status (filled, pending, canceled), fill price, date/time
- **Cash Balance & Buying Power:** View available cash and buying power

### 5.2 Login & Security

- **Email:** View and update email address
- **Password:** Change password
- **Sign-In Methods:** Manage connected sign-in methods (Apple, Google, email/password)
- **Active Sessions:** View and manage active sessions
- **Delete Account:** Permanently delete account and all data

### 5.3 Personal Information

- **Profile Card:** View and edit all onboarding data (age, income, net worth, risk tolerance, goals, time horizon, experience level)
- **Notification Preferences:** Configure push notification settings
- **Data & Privacy:** View stored data, export data, privacy policy link

### 5.4 Appearance

- **Theme:** Light mode / Dark mode / System default
- **Text Size:** Standard / Large (accessibility)

### 5.5 Legal & Support

- Terms of Service
- Privacy Policy
- Disclosures: Alpaca Securities, SIPC, FINRA
- Help & Support: Contact information, FAQ
- About Sevino: Version number, credits

---

## 6. Non-Functional Requirements

### 6.1 Performance

| ID | Requirement |
|---|---|
| NFR-1.1 | App launch to interactive chat within 3 seconds on iPhone 12 or above |
| NFR-1.2 | AI agent responses shall begin streaming within 3 seconds. Simple queries complete within 5 seconds |
| NFR-1.3 | MCP UI cards shall render within 1 second of data availability |
| NFR-1.4 | Heavy data retrieval (SEC filings, earnings transcripts) may take up to 15 seconds with a loading indicator |
| NFR-1.5 | Trade confirmation cards shall render within 1 second |
| NFR-1.6 | Trade execution (long-press to order submission) shall complete within 2 seconds |
| NFR-1.7 | Market data shall be no more than 1 minute delayed during market hours |
| NFR-1.8 | Status bar shall update within 5 seconds of market data changes |

### 6.2 Security

| ID | Requirement |
|---|---|
| NFR-2.1 | All data in transit encrypted using TLS 1.2 or higher |
| NFR-2.2 | Sensitive user data at rest encrypted using AES-256 or equivalent |
| NFR-2.3 | Auth tokens stored securely using iOS Keychain |
| NFR-2.4 | KYC-sensitive data (SSN, government ID) transmitted directly to Alpaca and not stored on Sevino servers |
| NFR-2.5 | API keys stored server-side only, never exposed to the client |
| NFR-2.6 | Backend rate limiting on all API endpoints |
| NFR-2.7 | User sessions expire after configurable inactivity period (default: 30 days) |
| NFR-2.8 | All trade execution requests and outcomes logged for audit |
| NFR-2.9 | Supabase Row-Level Security (RLS) enabled to ensure users access only their own data |
| NFR-2.10 | User conversation data sent to LLM shall not include raw SSN, full bank account numbers, or unnecessary PII |

### 6.3 Reliability & Availability

| ID | Requirement |
|---|---|
| NFR-3.1 | Target 99.5% uptime during market hours (9:30 AM – 4:00 PM ET, Mon–Fri) |
| NFR-3.2 | If AI agent is unavailable, the status bar and settings remain functional with a clear message |
| NFR-3.3 | If Alpaca API is unavailable, display clear message and surface last-known portfolio data |
| NFR-3.4 | Error tracking via Sentry |

### 6.4 Usability

| ID | Requirement |
|---|---|
| NFR-4.1 | Mobile-first iOS design following Apple Human Interface Guidelines |
| NFR-4.2 | Chat-based onboarding completable in under 3 minutes |
| NFR-4.3 | Alpaca account creation (including KYC) completable in under 7 minutes |
| NFR-4.4 | Plain, jargon-free language for beginner-level users. Financial terms explained inline |
| NFR-4.5 | MCP UI cards shall display company name (not just ticker) and use plain language for all labels |
| NFR-4.6 | Error states always include plain-language explanation and suggested next step |
| NFR-4.7 | Support both light and dark mode |

### 6.5 Accessibility

| ID | Requirement |
|---|---|
| NFR-5.1 | VoiceOver support for all primary user flows including chat, MCP UI cards, and status bar |
| NFR-5.2 | Minimum touch target sizes of 44x44 points |
| NFR-5.3 | WCAG 2.1 AA contrast ratios (4.5:1 body text, 3:1 large text) |
| NFR-5.4 | Dynamic Type support for system font scaling |

### 6.6 Compliance & Data Privacy

| ID | Requirement |
|---|---|
| NFR-6.1 | Comply with applicable US financial data regulations and Alpaca's Broker API terms |
| NFR-6.2 | Privacy Policy detailing data collection, usage, and sharing |
| NFR-6.3 | Comply with Apple App Store Review Guidelines including data privacy labels and account deletion |
| NFR-6.4 | Trade execution logs retained for minimum 3 years |
| NFR-6.5 | AI Radar algorithm and surfacing logic documented for regulatory review if needed |

---

## 7. Key Risks

| Risk | Severity | Mitigation |
|---|---|---|
| AI Radar construed as investment advice | High | Educational framing only; no directive language; disclaimers; legal review |
| AI hallucination in financial context | High | Tool-calling architecture; real data retrieval; disclaimers; user feedback |
| No dashboard disorienting users | Medium | Status bar; force-press modals; shortcuts reduce blank-page anxiety |
| Alpaca dependency (single provider) | Medium | Contractual protections; monitor alternatives; diversify post-beta |
| User trust barrier (AI + real money) | Medium | Chat first, account later; transparent confirmations; educational framing |
| AI cost per user exceeding target | Medium | Model optimization; caching; tiered usage limits at scale |
| Chat-first reducing discoverability | Medium | Timed shortcuts; AI Radar; proactive greeting; status bar entry points |
| Competitor launches chat-first brokerage | Medium | Speed to market; Riley-focused design; data moat grows daily |

---

## 8. Technical Architecture Summary (for implementation reference)

### 8.1 Stack

- **Mobile:** iOS (Swift/SwiftUI), TestFlight distribution
- **Backend:** Supabase (Postgres + Auth + RLS + Edge Functions)
- **AI:** Claude (Anthropic) with tool/function calling
- **Brokerage:** Alpaca Broker API (fully disclosed, firm-level API keys)
- **Bank Linking:** Plaid Link → processor token → Alpaca ACH
- **Market Data:** Alpaca Market Data API (REST on-demand, WebSocket deferred)
- **Real-time Events:** Alpaca Broker API SSE streams for account status, transfer status, and trade events (order fills/cancels/rejects)
- **Caching:** Redis (30–60s TTL for rate limit protection)
- **Error Tracking:** Sentry
- **Analytics:** PostHog or equivalent

### 8.2 Key Architectural Decisions

- **No direct mobile-to-Alpaca calls.** All brokerage API calls route through the backend using firm-level API keys.
- **Market data fetched on-demand via REST.** Single background job refreshes portfolio value for status bar. Market Data WebSocket deferred to future.
- **AI Radar stores only ticker references** and batch-fetches prices via Alpaca's snapshot endpoint.
- **Instant Funding via Journaling** moved to backlog.
- **US-only launch.** Canadian expansion (CIRO, FINTRAC/AML, FX) deferred.

### 8.3 Data Flow

```
iOS App → Supabase Edge Functions → Alpaca Broker API
                                  → Alpaca Market Data API
                                  → Claude (Anthropic) API
                                  → EDGAR API
                                  → Plaid Link (client-side SDK → processor token)
```

---

*Sevino Inc. | March 2026 | Confidential*
