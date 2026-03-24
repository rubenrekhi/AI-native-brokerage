---
name: commit
description: Analyze all unstaged changes, group them logically, and commit each group separately following the project commit conventions
---

Delegate this workflow to the 'pr-wizard' agent using `mode: bypassPermissions` so it can run git commands autonomously without prompting. Pass the following as the prompt:

---

## Commit Workflow

Before starting, read the commit message format from `.github/COMMIT_MESSAGE_TEMPLATE.md`. Use `git rev-parse --show-toplevel` to find the repo root if the file isn't in the current directory.

## Task

1. Read `.github/COMMIT_MESSAGE_TEMPLATE.md` (relative to git root) to get the commit message format
2. Run `git status` and `git diff` to inspect all unstaged and untracked changes
3. Group changes into logical commits
4. Stage and commit each group sequentially using specific file paths (never `git add -A` or `git add .`)
5. Return a brief summary of what was committed
