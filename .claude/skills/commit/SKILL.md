---
name: commit
description: Analyze all unstaged changes, group them logically, and commit each group separately following the project commit conventions
---

Delegate this workflow to the 'pr-wizard' agent using `mode: bypassPermissions` so it can run git commands autonomously without prompting. Pass the following as the prompt:

---

## Commit Workflow

Commit message format to follow:
!`cat .github/COMMIT_MESSAGE_TEMPLATE.md`

## Task

1. Run `git status` and `git diff` to inspect all unstaged and untracked changes
2. Group changes into logical commits
3. Stage and commit each group sequentially using specific file paths (never `git add -A` or `git add .`)
4. Return a brief summary of what was committed
