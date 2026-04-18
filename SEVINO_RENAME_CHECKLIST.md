# Saturn → Sevino Rename Checklist

All decisions locked in. Purely action items below.

**Decisions:**
- **GitHub:** delete empty `sevino-ai/sevino`, rename `sevino-ai/saturn` → `sevino`
- **Subfolders:** `saturn-api/` → `sevino-api/`, `saturn-app/` → `sevino-app/`
- **iOS bundle ID:** `ai.sevino.Saturn` → `ai.sevino.Sevino` (test targets: `.SevinoTests`, `.SevinoUITests`)
- **API domain:** `api.sevino.ai` (prod), `staging-api.sevino.ai` (staging)
- **Cutover style:** hard cutover (Railway free tier allows 2 custom domains, both slots are full)
- **Apple Dev / App Store Connect:** not registered yet — use new name when you register, no action now
- **iOS UI copy:** literal `Saturn` → `Sevino` swap
- **Sentry:** project is generically named `fastapi-backend` — no rename needed
- **Cutover window:** weekend of April 18–19, 2026

---

## 0. Pre-cutover prep (Fri April 17 evening)

- [ ] Announce freeze in Slack, confirm Thar + Shivam have pushed all outstanding work
- [ ] Export Railway env vars (prod + staging) to a local secrets store
- [ ] Take a Supabase backup (dashboard → Database → Backups)
- [ ] Archive current iOS build from Xcode Organizer (just in case)
- [ ] Confirm local `saturn-api/.env` is intact (not committed — ignore file check, just backup locally)

---

## 1. GitHub repo rename

- [x] Delete empty `sevino-ai/sevino` repo (Settings → Danger Zone)
- [x] Rename `sevino-ai/saturn` → `sevino-ai/sevino` (Settings → General → Repository name)
- [x] Verify branch protection rules survived the rename
- [x] Tell Thar + Shivam to run `git remote set-url origin git@github.com:sevino-ai/sevino.git` (old URLs redirect automatically but cleaner to update)

---

## 2. Repo folder rename (in a feature branch)

```bash
git checkout -b chore/rename-to-sevino
git mv saturn-api sevino-api
git mv saturn-app/Saturn saturn-app/Sevino-tmp  # temporary; full iOS rename in step 4
git mv saturn-app sevino-app
```

- [x] Rename `saturn-api/` → `sevino-api/`
- [x] Rename `saturn-app/` → `sevino-app/`
- [x] Update root `README.md`
- [x] Update root `CLAUDE.md`
- [x] Update `.github/copilot-instructions.md` (other three templates had no Saturn refs)

---

## 3. Backend code (`sevino-api/`)

- [x] `pyproject.toml`: name + description updated
- [x] `app/main.py`: root endpoint literal updated (FastAPI title is driven from `settings.APP_NAME` via `config.py`)
- [x] `app/config.py`: `APP_NAME`, `APP_DESCRIPTION` defaults updated
- [x] Middleware: `app/middleware/logging.py` structlog logger renamed `saturn.access` → `sevino.access`; `tests/integration/test_middleware.py` updated to match
- [x] `sevino-api/README.md`
- [x] `sevino-api/CLAUDE.md`
- [x] `sevino-api/docs/blueprint.md`, `docs/architecture.md`, `docs/testing.md`, `docs/onboarding-backend-plan.md`
- [x] `sevino-api/.env.example` (had no Saturn refs, nothing to change)
- [x] `sevino-api/supabase/config.toml` (`project_id = "saturn-api"` → `"sevino-api"`)
- [x] `sevino-api/Makefile` (leading comment)
- [x] `sevino-api/docs/database/db_schema.html` (title + ERD label)
- [x] `uv.lock` regenerated via `uv lock` (reflects new package name `sevino-api`)
- [x] Final sanity pass: `grep -ri "saturn" sevino-api/` returns zero matches
- Note: `app/worker.py` had 0 Saturn refs (the audit estimate of 3 was wrong)

---

## 4. iOS code (`sevino-app/`)

Largest chunk of work (~49 files).

### Xcode project + targets
- [x] Rename `.xcodeproj`: `Saturn.xcodeproj` → `Sevino.xcodeproj` (Xcode in-app rename)
- [x] Rename primary target: `Saturn` → `Sevino`
- [x] Rename test targets: `SaturnTests` → `SevinoTests`, `SaturnUITests` → `SevinoUITests`
- [x] Rename scheme file: `Saturn.xcscheme` → `Sevino.xcscheme`
- [x] Source folder rename on disk: outer `Sevino-tmp/` → `Sevino/`, inner `Saturn/` → `Sevino/`, `SaturnTests/` → `SevinoTests/`, `SaturnUITests/` → `SevinoUITests/`

### Build settings (project.pbxproj)
- [x] `PRODUCT_NAME` → `Sevino` (via target rename)
- [x] `PRODUCT_MODULE_NAME` → `Sevino`
- [x] `PRODUCT_BUNDLE_IDENTIFIER` main target → `ai.sevino.Sevino`
- [x] `PRODUCT_BUNDLE_IDENTIFIER` SevinoTests → `ai.sevino.SevinoTests`
- [x] `PRODUCT_BUNDLE_IDENTIFIER` SevinoUITests → `ai.sevino.SevinoUITests`
- [x] `PBXFileSystemSynchronizedRootGroup` paths updated to match renamed folders
- [x] `TEST_TARGET_NAME`, `productName`, `remoteInfo` all updated

### Source code
- [x] Swift file renames: `App/SaturnApp.swift` → `SevinoApp.swift`, `Utils/SaturnGlass.swift` → `SevinoGlass.swift`, `SevinoUITests/SaturnUITests.swift` → `SevinoUITests.swift`, `SaturnUITestsLaunchTests.swift` → `SevinoUITestsLaunchTests.swift`
- [x] Type renames: `struct SaturnApp` → `SevinoApp`, `enum SaturnGlass` → `SevinoGlass`, `struct SaturnGlassContainer` → `SevinoGlassContainer`, UI test classes
- [x] Color tokens in `Utils/Color+Theme.swift`: 11 `saturn*` tokens → `sevino*`; all ~28 caller files updated
- [x] `@testable import Saturn` → `@testable import Sevino` across 10 test files
- [x] UI copy in `HomeView.swift`, `WelcomeView.swift`, and elsewhere (literal swap)
- [x] `Localizable.xcstrings` string values swapped
- [x] `APIError.swift` doc comment updated
- [x] `sevino-app/README.md`
- [x] `sevino-app/Sevino/CLAUDE.md` (kept intentional lowercase `saturn` monorepo reference — repo root still named `saturn/`)
- [x] `sevino-app/guide.md`
- [x] xcconfig header comments

### Verify
- [x] Clean build folder + full rebuild — succeeds
- [x] `grep -ri "saturn" sevino-app/` — only expected leftovers remain: xcconfig `API_BASE_URL` domains (deferred to step 7), Xcode userdata files (auto-regenerate), and the intentional `saturn` monorepo path reference

### Commit + open PR
- [ ] Commit the iOS rename
- [ ] Open PR but **do not merge yet** — wait for Railway + DNS prep below

---

## 5. Railway cutover (prod + staging)

Constraint: non-premium Railway allows 2 custom domains at a time. Must remove old before adding new.

### Prod
- [ ] Rename Railway project `saturn` → `sevino`
- [ ] Rename `web` service if Saturn-named → `api`
- [ ] Rename `worker` service if Saturn-named → `worker`
- [ ] Rename Redis service if Saturn-named
- [ ] Verify service is still connected to the renamed GitHub repo (usually auto-follows)
- [ ] Update monorepo root path: `saturn-api/` → `sevino-api/` (both web and worker services)
- [ ] Update watch paths to `sevino-api/**`

### Staging
- [ ] Same renames on staging project

### Env vars (prod + staging, both services)
- [ ] Update any env var with `saturn-api.sevino.ai` → `api.sevino.ai` (prod) / `staging-api.sevino.ai` (staging)
- [ ] Check specifically: `BASE_URL`, `PUBLIC_API_URL`, any Supabase redirect override

### Slack/Discord
- [ ] Update Railway → Slack notification routings if any channel names have Saturn

---

## 6. DNS + Railway domain swap (coordinate with step 5)

Hard cutover due to Railway 2-domain cap.

### Prod
- [ ] In DNS, add `api.sevino.ai` CNAME pointing at Railway
- [ ] In Railway prod service: remove `saturn-api.sevino.ai` domain
- [ ] In Railway prod service: add `api.sevino.ai`, wait for SSL provisioning
- [ ] Test `https://api.sevino.ai/health` returns 200
- [ ] Remove `saturn-api.sevino.ai` DNS record

### Staging
- [ ] In DNS, add `staging-api.sevino.ai` CNAME
- [ ] In Railway staging service: remove old staging domain, add `staging-api.sevino.ai`
- [ ] Test `https://staging-api.sevino.ai/health` returns 200
- [ ] Remove old staging DNS record

---

## 7. iOS config cutover (post-merge)

- [ ] Update `Config.staging.xcconfig`: `API_BASE_URL` → `https://staging-api.sevino.ai`
- [ ] Update `Config.release.xcconfig`: `API_BASE_URL` → `https://api.sevino.ai`
- [ ] `Config.debug.xcconfig` stays as `http://127.0.0.1:8000` (local)
- [ ] Build, archive, ship to TestFlight

---

## 8. Supabase

- [ ] Project display name → `Sevino` (keep project ref / URL — don't migrate)
- [ ] Auth → URL Configuration: update Site URL + any Redirect URLs pointing at old domain
- [ ] Auth → Email Templates: replace "Saturn" copy
- [ ] Auth → Providers: update OAuth redirect URIs
- [ ] Database webhooks: update URLs pointing at old Railway domain
- [ ] Project description / metadata in dashboard
- [ ] Spot-check: storage buckets (unlikely), edge functions (unlikely)

---

## 9. Third-party webhook + dashboard updates

### Plaid dashboard
- [ ] Application name → Sevino
- [ ] Webhook URL → `https://api.sevino.ai/webhooks/plaid`
- [ ] Link allowed redirect URIs
- [ ] OAuth redirect URIs
- [ ] Application logo / branding

### Alpaca Broker dashboard
- [ ] Application name → Sevino
- [ ] Webhook endpoints (account status SSE, ACH events) → `https://api.sevino.ai/...`
- [ ] Allowlisted IPs/domains
- [ ] OAuth callback URLs (if used)
- [ ] API key labels (hygiene — optional)

---

## 10. Linear

- [ ] Rename initiative "Saturn MVP Launch" → "MVP Launch"
- [ ] Rename any projects with "Saturn" in the name
- [ ] Update Linear → GitHub integration to new repo (else PR/branch linking breaks)
- [ ] Search docs/labels/views for Saturn references

---

## 11. Slack

- [ ] Rename channels (`#saturn-dev`, `#saturn-alerts`, etc.) — Slack preserves history
- [ ] Update GitHub / Railway / Linear Slack app channel routings
- [ ] Pinned messages / canvases with old GitHub links

---

## 12. Docs + agent infra final pass

- [ ] Root `README.md`
- [ ] Root `CLAUDE.md`
- [ ] `sevino-api/README.md`, `sevino-api/docs/blueprint.md`, `docs/architecture.md`, `docs/testing.md`
- [ ] `sevino-app/README.md`, `sevino-app/Sevino/CLAUDE.md`
- [ ] `.claude/agents/*`, `.claude/skills/*` — spot-check (audit found no "saturn" references but verify after folder rename)
- [ ] Notion / internal wiki pages (external to repo)

---

## 13. Does NOT apply to this repo (skip)

Confirmed absent during audit — ignore these entirely:

- **PostHog** — not a dependency.
- **Stripe** — not integrated.
- **Vercel / marketing site** — no config in repo.
- **Cloudflare Workers / R2** — not in repo; only DNS at registrar.
- **Status page** — no integration.
- **Email provider templates** (Resend/Postmark/SendGrid) — not wired up.
- **Crash reporting beyond Sentry** — none.
- **GitHub Actions workflows** — directory has no workflows.
- **CODEOWNERS, Dependabot** — not present.
- **iOS entitlements** (App Groups, Keychain sharing, Associated Domains, URL schemes, Sign in with Apple) — none wired up.
- **Python package directory rename** — package is `app/`, not `saturn_api/`.
- **`SATURN_*` env vars** — none exist.
- **CORS origin hardcoding** — no saturn domain in allowlist.
- **Apple Developer / App Store Connect** — not registered yet; use "Sevino" at registration time.
- **Sentry project rename** — project is generically named `fastapi-backend`.
- **.env security cleanup** — false alarm; `.env` is properly gitignored, only `.env.example` is tracked.

---

## Execution order (weekend of April 18–19, 2026)

1. **Friday evening:** Step 0 (pre-cutover prep, freeze announcement)
2. **Saturday AM:** Steps 1–4 in a feature branch (GitHub rename, folder rename, backend code, iOS code)
3. **Saturday AM:** Open PR, don't merge
4. **Saturday midday:** Steps 5–6 (Railway service + env var updates, DNS swap). Do staging first as a dry run, then prod.
5. **Saturday midday:** Merge PR once `api.sevino.ai` is verified working
6. **Saturday PM:** Step 7 (iOS config → TestFlight build)
7. **Saturday PM:** Step 8 (Supabase)
8. **Saturday PM:** Step 9 (Plaid + Alpaca webhook URLs)
9. **Sunday:** Steps 10–11 (Linear, Slack — non-breaking, do as cleanup)
10. **Sunday:** Step 12 (docs final pass)
