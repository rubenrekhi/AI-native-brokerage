---
name: review
description: Review code changes against frontend and backend best practices before pushing
argument-hint: [pr-url-or-number]
---

Review code changes and flag violations of project coding standards. Routes to the correct auditor agent based on which files were changed.

## Step 1: Get the changed files

If a PR URL or number is provided in `$ARGUMENTS`:
- Run `gh pr diff <url-or-number> --name-only` to get changed file paths
- Run `gh pr view <url-or-number> --json title,body` for context

If no arguments (default — review current branch):
- Determine the base branch: `git merge-base origin/main HEAD`
- Run `git diff origin/main...HEAD --name-only` to get changed file paths
- If no branch diff, fall back to `git diff --staged --name-only`

## Step 2: Classify changes

Categorize every changed file:
- **Frontend**: any file under `sevino-app/` or with a `.swift` extension
- **Backend**: any file under `sevino-api/` or with a `.py` extension
- **Other**: docs, CI, config — skip these (no auditor needed)

## Step 3: Route to auditor agents

Based on the classification:

- **Frontend files only** — delegate to the `fe-auditor` agent. Pass the diff source (branch or PR reference) as the prompt.
- **Backend files only** — delegate to the `be-auditor` agent. Pass the diff source as the prompt.
- **Both frontend and backend files** — delegate to both agents sequentially. Run `fe-auditor` first, then `be-auditor` (if it exists). Combine both reports in the final output.
- **No frontend or backend files** — tell the user: "No reviewable source files changed (only docs/config/CI)." and stop.

## Step 4: Return the combined report

After the auditor agent(s) finish, return their full reports to the user. Do not summarize or truncate — pass through the complete output.
