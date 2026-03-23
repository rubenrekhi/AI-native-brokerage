---
name: pr
description: Create a pull request with properly formatted title, body, and Linear ticket reference
argument-hint: <target-branch> [SEV-X]
---

Delegate this workflow to the 'pr-wizard' agent using `mode: bypassPermissions` so it can run git and gh commands autonomously without prompting. Pass the following as the prompt:

---

## PR Workflow

PR body template to follow:
!`cat .github/PULL_REQUEST_TEMPLATE.md`

Commit message format used in this repo (for summarizing changes):
!`cat .github/COMMIT_MESSAGE_TEMPLATE.md`

## Task

Arguments: $ARGUMENTS

- First argument = target branch (required)
- Second argument = Linear ticket e.g. SEV-42 (optional)

Steps:

1. Get current branch name
2. Diff current branch vs target branch
3. Resolve Linear ticket: extract SEV-\d+ from branch name → verify via Linear MCP → else ask user
4. Draft PR title (imperative, under 70 chars)
5. Fill PR body using the template above
6. Run: `gh pr create --base <target-branch> --title "..." --body "..."`
7. Return the PR URL
