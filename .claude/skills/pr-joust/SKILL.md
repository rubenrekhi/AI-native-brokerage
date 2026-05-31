---
name: pr-joust
description: Have Claude and Codex independently review a PR, rebut each other's findings, then have Claude Opus referee and produce a final recommendation.
argument-hint: [pr-url-or-number] [--local] [--post] [--keep]
---

Run a two-LLM code review joust. Claude and Codex each review the same diff independently, then read each other's findings and produce verdicts (agree/disagree/refine), and finally a Claude Opus referee synthesizes both reviews into a ranked recommendation.

Delegate this workflow to the `pr-joust-orchestrator` agent using `mode: bypassPermissions` so it can run git, gh, and codex commands autonomously without prompting.

## Argument parsing

Parse `$ARGUMENTS` and pass them through to the orchestrator verbatim. The orchestrator handles:

- `<pr-url-or-number>` — review a specific PR. Accepts a number (`889`), full URL, or `<owner>/<repo>#<n>`.
- `--local` — review uncommitted + branch-vs-`origin/main` changes in the working tree.
- (no args) — review current branch vs `origin/main`.
- `--post` — after the report is produced, post it as a top-level PR comment via `gh pr comment`. PR mode only.
- `--keep` — preserve `/tmp/joust-<id>/` scratch directory for inspection.

## Output

Return the orchestrator's final report verbatim. Do not summarize or truncate.
