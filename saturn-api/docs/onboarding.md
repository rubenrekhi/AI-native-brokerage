# Sevino — Onboarding & KYC Flow (Claude Code Reference)

> **Purpose:** Single source of truth for implementing the onboarding and KYC screens in the Sevino iOS app.
> Engineering reference only — not a product spec.

---

## Prerequisites (Before This Flow Starts)

The user has already completed **Sevino account creation** before entering this flow. The following data is already available:

| Field | Source | Notes |
|---|---|---|
| `email_address` | Account registration | Maps to Alpaca `contact.email_address` |
| `phone_number` | Account registration (verified via OTP) | Maps to Alpaca `contact.phone_number` |

The onboarding flow is entered immediately after account creation in a single continuous session.

---

## Architecture

- **UI pattern:** Scrolling vertical chat-card UI. Each screen is an AI-style chat message with a response area below. Tapping "Continue" scrolls to the next screen.
- **Content is scripted, not AI-generated.**
- **Two phases, one session, seamless warm handoff:**
  - **Phase 1 — Onboarding (Screens 1–18):** Profile + AI context collection. ~60% of progress bar.
  - **Phase 2 — KYC (Screens 19–28):** Alpaca account creation. ~40% of progress bar.
- **Progress bar:** Thin bar at top spanning the full flow (both phases).
- **Total:** 28 screens, ~7 minutes.

---

## Phase 1: Onboarding (Screens 1–18)

---

### Screen 1 — Welcome

- **Type:** Full-screen splash with background imagery
- **Input:** None
- **AI message:**

```
Hi, I'm Sevino.

I'm your AI investing partner. No dashboards to learn. No charts to decode.
Just a conversation about your money — and an AI that actually does something about it.

Let's get to know each other.
```

- **CTA:** "Let's go →"
- **Data stored:** None
- **Alpaca mapping:** None
- **Design notes:** Sevino logo at top. Atmospheric background. Warm, confident, simple tone.

---

### Screen 2 — First Name

- **Type:** Chat message + single text input
- **Input:** Text field (placeholder: "Your first name")
- **AI message:**

```
First things first — what should I call you?
```

- **CTA:** "Continue →"
- **Data stored:** `profile_card.preferred_name`
- **Alpaca mapping:** Pre-fills `identity.given_name` in KYC (Screen 19)
- **Validation:** Required, non-empty

---

### Screen 3 — Attribution

- **Type:** Chat message + grid selection (2-column, single-select)
- **AI message:**

```
Nice to meet you, {name}. Before we dive in — how did you find Sevino?

This helps us reach more people like you.
```

- **Options:** `TikTok` · `Instagram` · `X / Twitter` · `Friend` · `Google` · `Reddit` · `AI tool` · `LinkedIn` · `Article` · `Other`
- **CTA:** "Continue →"
- **Data stored:** `analytics.attribution_source`
- **Alpaca mapping:** None (internal analytics only)

---

### Screen 4 — Financial Worry

- **Type:** Chat message + selection cards (multi-select, max 3)
- **AI message:**

```
{name}, what's on your mind when it comes to money?

Pick the ones that hit home. (Up to 3)
```

- **Options:**
  1. `Not sure I'm saving enough`
  2. `Watching my money sit there doing nothing`
  3. `Feeling like I'm falling behind`
  4. `Overwhelmed by all the options`
  5. `I want to do more but don't know how`
  6. `I know what I'm doing — I just want better tools`
- **CTA:** "Continue →"
- **Data stored:** `profile_card.financial_worries[]`
- **Alpaca mapping:** None directly — used for AI context and reflection screen routing
- **Logic:** Option 6 routes to Variant D on Screen 5. All others route based on priority order below.

---

### Screen 5 — Reflection (Personalized by Worry)

- **Type:** Full-screen motivational with stat
- **Input:** None
- **Variant selection:** Based on user's first selected worry from Screen 4. If multiple worries selected, prioritize in the order listed below (check Variant A triggers first, then B, then C, then D).

#### Variant A
**Triggers:** "Not sure I'm saving enough" OR "Feeling like I'm falling behind"

```
You're not behind, {name}. You're early.

Most people your age haven't started investing at all. The fact that you're here
means you're already ahead of the curve.
```

**Stat:** `73% of young Americans say they want to invest but don't know where to start. You're about to solve that.`
**Source:** Investopedia, 2023

#### Variant B
**Triggers:** "Watching my money sit there doing nothing"

```
You're right to feel that way.

Cash in a savings account feels safe. But it's quietly losing ground.
Your instinct to put your money to work? That's a good one.
```

**Stat:** `$10,000 left in a savings account loses roughly $200–$400 in purchasing power every year to inflation. Invested, it could be growing.`
**Source:** Bureau of Labor Statistics CPI data

#### Variant C
**Triggers:** "Overwhelmed by all the options" OR "I want to do more but don't know how"

```
Totally fair, {name}.

There are over 4,000 stocks on the market, thousands of ETFs, and a million opinions
online. It's a lot. That's exactly why you won't be doing this alone.
```

**Stat:** `44% of non-investors say they feel overwhelmed by the process. The problem isn't you — it's that nobody made this simple enough.`
**Source:** Gallup/FINRA Foundation, 2022

#### Variant D
**Triggers:** "I know what I'm doing — I just want better tools"

```
Respect.

You don't need the basics explained. You need an AI that can pull real data,
analyze your portfolio, and help you move faster. That's what this is.
```

**Stat:** `88% of actively managed funds underperformed the S&P 500 over 15 years. Having the right analytical edge matters.`
**Source:** S&P Global SPIVA, 2024

- **CTA:** "Continue →"
- **Data stored:** None (display only)

---

### Screen 6 — Financial Goals

- **Type:** Chat message + selection cards (multi-select, max 3)
- **AI message:**

```
What are you hoping to build toward?

Pick what matters most. (Up to 3)
```

- **Options:**
  1. `Grow my wealth over time`
  2. `Save for a big goal (house, wedding, etc.)`
  3. `Get on track for retirement`
  4. `Build a safety net beyond savings`
  5. `Learn to invest with real money`
  6. `Make my cash work harder`
- **CTA:** "Continue →"
- **Data stored:** `profile_card.investment_goals[]`
- **Alpaca mapping:** Derived → `identity.investment_objective`
  - Options 1, 2, 3 → `growth`
  - Options 4, 6 → `capital_preservation`
  - Option 5 → `other`

---

### Screen 7 — Reflection (Personalized by Goals)

- **Type:** Full-screen motivational with stat
- **Input:** None
- **Variant selection:** Based on user's first selected goal from Screen 6, prioritized in order below.

#### Variant A
**Triggers:** "Grow my wealth over time" OR "Get on track for retirement" OR "Save for a big goal"

```
Good. You're thinking long-term.

That's the single most important thing in investing. Not picking the right stock —
having the patience to let time do the heavy lifting.
```

**Stat:** `$500/month invested consistently over 20 years at historical market returns could grow to over $300,000. Time is the cheat code.`
**Source:** Historical S&P 500 average annual return, ~10%. Simulated results are hypothetical.

#### Variant B
**Triggers:** "Build a safety net beyond savings" OR "Make my cash work harder"

```
Smart move, {name}.

Your money should be working as hard as you do. Right now, most of it probably isn't.
We'll fix that.
```

**Stat:** `3.20% APY — That's what uninvested cash earns in Sevino's FDIC-insured high-yield cash program vs 0.01% at most checking accounts.`

#### Variant C
**Triggers:** "Learn to invest with real money"

```
That's the best way to learn.

Reading about investing and actually doing it are completely different. You don't
need to know everything to start — you just need to start, and learn as you go.
```

**Stat:** `$1 — That's the minimum to buy your first investment on Sevino. Start small. Learn fast.`

- **CTA:** "Continue →"
- **Data stored:** None (display only)

---

### Screen 8 — Date of Birth

- **Type:** Chat message + date input (MM / DD / YYYY segmented fields)
- **AI message:**

```
When were you born?

This helps me personalize your investment timeline.
```

- **CTA:** "Continue →"
- **Data stored:** `profile_card.date_of_birth` + computed `profile_card.age`
- **Alpaca mapping:** `identity.date_of_birth` (ISO 8601: `YYYY-MM-DD`)
- **Validation:** Must be 18+. If under 18 → show: `"You need to be at least 18 to use Sevino."` and block progression.

---

### Screen 9 — Annual Income

- **Type:** Chat message + range selection cards (single-select)
- **AI message:**

```
What's your annual income, before taxes?

I use this to tailor guidance to your situation. No judgment — every number is a
great starting point.
```

- **Options:**
  - `Under $25K`
  - `$25K – $50K`
  - `$50K – $100K`
  - `$100K – $200K`
  - `$200K – $500K`
  - `$500K+`
- **CTA:** "Continue →"
- **Data stored:** `profile_card.annual_income_range`
- **Alpaca mapping:** `identity.annual_income_min` / `identity.annual_income_max` (bracket values)

---

### Screen 10 — Total Net Worth

- **Type:** Chat message + range selection cards (single-select)
- **AI message:**

```
What's your total net worth?

The big picture — add up everything you own (savings, investments, retirement
accounts, property) and subtract any debts.
```

- **Options:**
  - `Under $10K`
  - `$10K – $50K`
  - `$50K – $100K`
  - `$100K – $250K`
  - `$250K – $500K`
  - `$500K – $1M`
  - `$1M+`
- **CTA:** "Continue →"
- **Data stored:** `profile_card.total_net_worth_range`
- **Alpaca mapping:** `identity.total_net_worth_min` / `identity.total_net_worth_max`

---

### Screen 11 — Liquid Net Worth

- **Type:** Chat message + range selection cards (single-select)
- **AI message:**

```
And how much cash do you have that you could use right now?

Think bank accounts, savings accounts, money market — anything you could move or
invest this week. Don't count your home, car, or retirement accounts.
```

- **Options:**
  - `Under $10K`
  - `$10K – $25K`
  - `$25K – $50K`
  - `$50K – $100K`
  - `$100K – $250K`
  - `$250K+`
- **CTA:** "Continue →"
- **Data stored:** `profile_card.liquid_net_worth_range`
- **Alpaca mapping:** `identity.liquid_net_worth_min` / `identity.liquid_net_worth_max`

---

### Screen 12 — Income Stability

- **Type:** Chat message + selection cards with descriptions (single-select)
- **AI message:**

```
How steady is your income right now?
```

- **Options:**
  1. `Unpredictable` — It changes a lot month to month
  2. `Mostly stable` — But things could change
  3. `Solid` — Steady job and reliable paycheck
  4. `Very secure` — Multiple income sources or strong safety net
- **CTA:** "Continue →"
- **Data stored:** `profile_card.income_stability`
- **Alpaca mapping:** None directly — used for AI context (affects risk calibration)

---

### Screen 13 — Time Horizon

- **Type:** Chat message + selection cards (single-select)
- **AI message:**

```
How soon will you need most of the money you invest?

No wrong answer — this helps me calibrate how much risk makes sense.
```

- **Options:**
  - `Less than 2 years`
  - `2 – 5 years`
  - `5 – 10 years`
  - `10 – 20 years`
  - `20+ years`
- **CTA:** "Continue →"
- **Data stored:** `profile_card.time_horizon`
- **Alpaca mapping:** `identity.investment_time_horizon` + `identity.liquidity_needs` (derived)
  - Less than 2 years → `very_important`
  - 2–5 years → `somewhat_important`
  - 5–10 years → `not_important`
  - 10+ years → `not_important`

---

### Screen 14 — Risk Tolerance: Scenario

- **Type:** Chat message + selection cards with descriptions (single-select)
- **AI message:**

```
Imagine you invested $10,000 and the market dropped 25% — your balance shows $7,500.
What would you do?

Be honest — there's no right answer.
```

- **Options:**
  1. `Sell everything immediately` — Prevent further losses
  2. `Sell some` — Lock in remaining capital
  3. `Hold and do nothing` — Wait for recovery
  4. `Buy more while prices are low` — Take advantage of the dip
  5. `Not sure` — I honestly don't know what I'd do
- **CTA:** "Continue →"
- **Data stored:** `profile_card.risk_scenario_response`
- **Alpaca mapping:** Combined with Screen 15 → see risk mapping table below

---

### Screen 15 — Risk Tolerance: Max Drop

- **Type:** Chat message + selection cards (single-select)
- **AI message:**

```
How much of a drop could you handle without losing sleep?
```

- **Options:**
  - `0 – 5% decline`
  - `5 – 15% decline`
  - `15 – 25% decline`
  - `25 – 40% decline`
  - `40%+ decline`
- **CTA:** "Continue →"
- **Data stored:** `profile_card.max_loss_tolerance`
- **Alpaca mapping:** Combined with Screen 14 → `identity.risk_tolerance`

#### Combined Risk Mapping Logic (Screens 14 + 15)

| Scenario Response (Screen 14) | Max Drop (Screen 15) | → `identity.risk_tolerance` |
|---|---|---|
| Sell everything / Sell some | 0–5% or 5–15% | `conservative` |
| Sell everything / Sell some | 15–25% or higher | `moderate` |
| Hold / Not sure | 0–15% | `conservative` |
| Hold / Not sure | 15–40%+ | `moderate` |
| Buy more | 0–25% | `moderate` |
| Buy more | 25–40%+ | `aggressive` |

---

### Screen 16 — Investment Experience

- **Type:** Chat message + selection cards (single-select)
- **AI message:**

```
Which sounds most like you?
```

- **Options:**
  1. `I've never really invested`
  2. `I've invested a little, but not actively`
  3. `I invest regularly in stocks or funds`
  4. `I actively manage my portfolio and follow markets`
  5. `I've tried advanced strategies like options or crypto`
- **CTA:** "Continue →"
- **Data stored:** `profile_card.experience_level`
  - Options 1–2 → `beginner`
  - Option 3 → `intermediate`
  - Options 4–5 → `advanced`
- **Alpaca mapping:**
  - `identity.investment_experience_with_stocks`:
    - Option 1 → `none`
    - Option 2 → `limited`
    - Option 3 → `good`
    - Options 4–5 → `extensive`
  - `identity.investment_experience_with_options` → always `none`

---

### Screen 17 — Bridge: Compounding Chart (Personalized)

- **Type:** Full-screen with interactive bar chart
- **Input:** None (uses DOB from Screen 8)
- **Header:** `"You have {years_to_65} years of compounding ahead — Age 65 · {retirement_year}"`

#### Chart: Three Scenarios

All scenarios assume $500/month contribution, compounded monthly. Uses user's actual age from Screen 8. Target age = 65.

| Scenario | Rate | Color | Label |
|---|---|---|---|
| Cash in savings | 0.5% APY | Gray (smallest bar) | `Savings account` |
| Start in 5 years | ~10% historical, delayed 5 years | Gold (medium bar) | `Wait 5 years` |
| Start today | ~10% historical, full runway | Blue/primary (tallest bar) | `Start today` |

#### Example values (age 26, 39 years to 65)

- Savings account (0.5%, 39 yrs): ~$258,000
- Wait 5 years (10%, 34 yrs): ~$1,350,000
- Start today (10%, 39 yrs): ~$2,200,000

#### Computation

```
FV = P × [((1 + r/12)^(12×n) - 1) / (r/12)]

Where:
  P = 500 (monthly contribution)
  r = annual rate (0.005 for savings, 0.10 for investing)
  n = years to 65 (full runway or minus 5)
```

#### Key conversion line:

```
Those 5 years? They're worth ${gap_amount}. The best time to start was years ago.
The second best time is right now.
```

`{gap_amount}` = difference between "Start today" and "Wait 5 years" values.

#### Disclaimer (small text below chart):

```
Simulated results are hypothetical and for illustrative purposes only. They do not
reflect actual performance and are not a guarantee of future results. All investments
involve risk, including loss of principal. Historical S&P 500 returns (~10% annually)
include reinvested dividends and do not account for inflation, taxes, or fees.
$500/month assumed contribution.
```

- **CTA:** "Set up my account →"
- **Data stored:** None (display only)
- **Design notes:** This is the emotional peak and transition point into Phase 2. The gap between "start today" and "wait 5 years" makes procrastination tangible.

---

### Screen 18 — Risk Disclosure

- **Type:** Full-screen text with acknowledgment
- **AI message:**

```
One important thing before we set up your account.

Investing involves risk, including the possible loss of money. Past performance
doesn't guarantee future results. Sevino is not a registered investment adviser —
the AI provides information and education, not personalized investment advice.

Brokerage services are provided by Alpaca Securities LLC, member FINRA/SIPC. Your
investments are protected by SIPC up to $500,000 (including $250,000 cash).
```

- **CTA:** "I understand, let's continue →"
- **Data stored:** `onboarding.risk_disclosure_acknowledged = true` + `timestamp`
- **Alpaca mapping:** None
- **Compliance note:** Satisfies FR-12.1 (risk disclosure during onboarding before account creation prompt).

---

## Phase 2: KYC / Alpaca Account Creation (Screens 19–28)

Same scrolling chat-card UI. AI tone shifts to practical/efficient. Seamless transition from Phase 1.

---

### Screen 19 — KYC Introduction

- **Type:** Chat message, no input
- **AI message:**

```
Great, {name}. Now let's open your brokerage account. This takes about 3 minutes.

I'll need some legal information — your name, address, and a few details. This is
all required by federal law to verify your identity.

Your SSN is sent directly to Alpaca Securities and is never stored on Sevino's servers.
```

- **CTA:** "Let's do it →"
- **Data stored:** None

---

### Screen 20 — Legal Name

- **Type:** Chat message + text inputs (3 fields)
- **Fields:**
  - First name (pre-filled from Screen 2)
  - Middle name (optional)
  - Last name (required)
- **AI message:**

```
What's your legal name?

This needs to match your government ID exactly.
```

- **CTA:** "Continue →"
- **Data stored:** `kyc.legal_first_name`, `kyc.legal_middle_name`, `kyc.legal_last_name`
- **Alpaca mapping:** `identity.given_name` + `identity.middle_name` + `identity.family_name`
- **Validation:** First and last name required.

---

### Screen 21 — Social Security Number

- **Type:** Chat message + masked input
- **Input:** SSN field, format `XXX-XX-XXXX`, masked/obscured
- **AI message:**

```
What's your Social Security Number?

Encrypted and sent directly to Alpaca Securities for identity verification.
Sevino never stores your SSN.
```

- **CTA:** "Continue →"
- **Data stored:** Transmitted directly to Alpaca — **NOT stored in Sevino DB** (per NFR-2.4)
- **Alpaca mapping:** `identity.tax_id` + `identity.tax_id_type = USA_SSN`
- **Validation:** 9 digits, formatted XXX-XX-XXXX

---

### Screen 22 — Address

- **Type:** Chat message + form fields
- **Fields:**
  - Street address (required)
  - Apt/Unit (optional)
  - City (required)
  - State (dropdown, required)
  - ZIP code (required)
- **AI message:**

```
What's your home address?
```

- **CTA:** "Continue →"
- **Data stored:** `kyc.address`
- **Alpaca mapping:** `contact.street_address[]` + `contact.unit` + `contact.city` + `contact.state` + `contact.postal_code`

---

### Screen 23 — Citizenship

- **Type:** Chat message + selection (single-select)
- **AI message:**

```
Are you a US citizen or permanent resident?
```

- **Options:**
  1. `Yes, US citizen`
  2. `Yes, US permanent resident`
  3. `No (non-US)`
- **CTA:** "Continue →"
- **Data stored:** `kyc.citizenship_status`
- **Alpaca mapping:** `identity.country_of_citizenship` + `identity.country_of_birth` + `identity.country_of_tax_residence` = `USA`
- **Conditional:** If "No (non-US)" selected → show additional fields for visa type and country of citizenship.

---

### Screen 24 — Employment Information

- **Type:** Chat message + form fields
- **AI message:**

```
Tell me about your work.

Required by regulation — just a few quick fields.
```

- **Fields:**
  - Employment status (dropdown): `Employed` / `Self-employed` / `Unemployed` / `Student` / `Retired`
  - **If Employed or Self-employed:** Employer name, Job title, Industry (optional)
- **CTA:** "Continue →"
- **Data stored:** `kyc.employment_status` + `kyc.employer` + `kyc.job_title` → also stored as `profile_card.employment_info` for AI context
- **Alpaca mapping:** `identity.employment_status`: `EMPLOYED` / `UNEMPLOYED` / `STUDENT` / `RETIRED`

---

### Screen 25 — Funding Source

- **Type:** Chat message + multi-select cards
- **AI message:**

```
Where does the money you'll invest come from?

Select all that apply.
```

- **Options:**
  - `Employment income`
  - `Savings`
  - `Existing investments`
  - `Business income`
  - `Family`
  - `Inheritance`
- **CTA:** "Continue →"
- **Data stored:** `kyc.funding_sources[]`
- **Alpaca mapping:** `identity.funding_source[]`: `employment_income` / `savings` / `investments` / `business_income` / `family` / `inheritance`

---

### Screen 26 — Regulatory Disclosures (FINRA)

- **Type:** Chat message + toggle switches (batch, all default to OFF/No)
- **AI message:**

```
A few regulatory questions — most people breeze through these.
```

- **Toggles:**
  1. Are you or a family member a senior officer, director, or 10%+ shareholder of a publicly traded company?
  2. Are you or a family member employed by or affiliated with a stock exchange, FINRA, or a broker-dealer?
  3. Are you or an immediate family member a current or former senior political figure?

Each toggle has a `"Why do we ask this?"` expandable.

- **CTA:** "Continue →"
- **Data stored:** `kyc.disclosures`
- **Alpaca mapping:**
  - Toggle 1 → `disclosures.is_control_person`
  - Toggle 2 → `disclosures.is_affiliated_exchange_or_finra`
  - Toggle 3 → `disclosures.is_politically_exposed` + `disclosures.immediate_family_exposed`
- **Conditional:** If any toggle is YES → expand to collect required detail fields.

---

### Screen 27 — Agreements

- **Type:** Full-screen with scrollable agreement text and checkboxes
- **AI message:**

```
Last step — review and sign your account agreements.
```

- **Checkboxes (all required):**
  1. Customer Agreement
  2. Margin Agreement
  3. FDIC Bank Sweep Program Terms & Conditions (required for high-yield cash)
- **CTA:** "Open my account →" (disabled until all checked)
- **Data stored:** `kyc.agreements[]` with `timestamps` and `ip_address`
- **Alpaca mapping:** `agreements[]`: `customer_agreement` + `margin_agreement` with `signed_at` and `ip_address`
- **Note:** Customer agreement must be revision `22.2024.08+` for FDIC Sweep eligibility.

---

### Screen 28 — Submission & Confirmation

- **Type:** Full-screen with loading animation → success state
- **AI message (loading state):**

```
Setting up your account...
```

- **AI message (success state):**

```
You're all set, {name}. Your brokerage account is being verified. This usually takes
a few minutes — we'll let you know the moment it's ready.

In the meantime, let's start talking about your money.
```

- **CTA:** "Start my first conversation →"
- **Backend triggers:**
  1. `POST /v1/accounts` to Alpaca with full payload
  2. SSE listener for account status updates
  3. Auto-FDIC enrollment on `ACTIVE` status
- **Post-submission states:**
  - `ACTIVE` → User proceeds to main chat. AI sends first greeting (per FR-4.7).
  - `ACTION_REQUIRED` → Show in Settings with explanation.
  - `REJECTED` → Show clear explanation with next steps.

---

## Alpaca Payload Construction Reference

Complete mapping of every field in the `POST /v1/accounts` request body.

### Contact Object

| Alpaca Field | Source | Screen |
|---|---|---|
| `email_address` | Sevino account registration | Pre-onboarding |
| `phone_number` | Sevino account registration | Pre-onboarding |
| `street_address[]` | KYC | Screen 22 |
| `city` | KYC | Screen 22 |
| `state` | KYC | Screen 22 |
| `postal_code` | KYC | Screen 22 |

### Identity Object

| Alpaca Field | Source | Screen |
|---|---|---|
| `given_name` / `family_name` / `middle_name` | KYC (first name pre-filled from onboarding) | Screen 20 |
| `date_of_birth` | Onboarding | Screen 8 |
| `tax_id` / `tax_id_type` | KYC | Screen 21 |
| `country_of_citizenship` | KYC | Screen 23 |
| `funding_source[]` | KYC | Screen 25 |
| `annual_income_min` / `annual_income_max` | Onboarding | Screen 9 |
| `total_net_worth_min` / `total_net_worth_max` | Onboarding | Screen 10 |
| `liquid_net_worth_min` / `liquid_net_worth_max` | Onboarding | Screen 11 |
| `liquidity_needs` | Derived from time horizon | Screen 13 |
| `investment_experience_with_stocks` | Onboarding | Screen 16 |
| `investment_experience_with_options` | Hardcoded | Always `none` |
| `risk_tolerance` | Derived from risk questions | Screens 14 + 15 |
| `investment_objective` | Derived from goals | Screen 6 |
| `investment_time_horizon` | Onboarding | Screen 13 |

### Disclosures Object

| Alpaca Field | Source | Screen |
|---|---|---|
| `is_control_person` | KYC | Screen 26 |
| `is_affiliated_exchange_or_finra` | KYC | Screen 26 |
| `is_politically_exposed` | KYC | Screen 26 |
| `immediate_family_exposed` | KYC | Screen 26 |

### Agreements Array

| Alpaca Field | Source | Screen |
|---|---|---|
| `customer_agreement` (with `signed_at`, `ip_address`) | KYC | Screen 27 |
| `margin_agreement` (with `signed_at`, `ip_address`) | KYC | Screen 27 |

---

## Profile Card — Complete Field List

Injected into the AI's context for every conversation post-onboarding (per FR-2.2).

| Field | Screen | Used For |
|---|---|---|
| `preferred_name` | 2 | AI greeting, personalization |
| `date_of_birth` / `age` | 8 | Time horizon context, age-appropriate guidance |
| `financial_worries[]` | 4 | Emotional context for AI tone/framing |
| `investment_goals[]` | 6 | Goal-oriented guidance, Radar algorithm |
| `annual_income_range` | 9 | Contribution suggestions, affordability |
| `total_net_worth_range` | 10 | Wealth context, risk calibration |
| `liquid_net_worth_range` | 11 | Available capital context |
| `income_stability` | 12 | Risk calibration, emergency fund advice |
| `time_horizon` | 13 | Investment strategy, risk framing |
| `risk_scenario_response` | 14 | Granular risk profile for AI |
| `max_loss_tolerance` | 15 | Granular risk profile for AI |
| `experience_level` | 16 | Language complexity (FR-4.5) |
| `employment_info` | 24 | Income context, sector awareness |
| `funding_sources[]` | 25 | Understanding capital sources |
