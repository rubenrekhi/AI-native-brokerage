---
name: pr
description: Create a pull request with properly formatted title, body, and Linear ticket reference, creating the ticket if no relevant one exists
argument-hint: <target-branch> [SEV-X]
---

Delegate this workflow to the 'pr-wizard' agent using `mode: bypassPermissions` so it can run git and gh commands autonomously without prompting. Pass the following as the prompt:

---

## PR Workflow

Before starting, read both template files from the `.github/` folder. Use `git rev-parse --show-toplevel` to find the repo root if the files aren't in the current directory:
- `.github/PULL_REQUEST_TEMPLATE.md` — PR body template to follow
- `.github/COMMIT_MESSAGE_TEMPLATE.md` — commit format used in this repo (for summarizing changes)

## Task

Arguments: $ARGUMENTS

- First argument = target branch (required)
- Second argument = Linear ticket e.g. SEV-42 (optional)

Steps:

1. Get current branch name
2. Diff current branch vs target branch
3. Resolve the Linear ticket — reuse an existing one or create a new one:
   - If the second argument provided a ticket, verify it with the Linear MCP (`get_issue`) and use it.
   - Else extract SEV-\d+ from the branch name → verify with `get_issue` and use it.
   - Else search existing tickets (`list_issues`, `team: "Sevino"`, `query` = gist of the change) and reuse one if it clearly covers this change.
   - Else create a new ticket (`save_issue`, `team: "Sevino"`, imperative title, description of what/why + a note it was auto-created by the PR workflow) and use its identifier + url.
   - Only if the Linear MCP is unreachable: omit the ticket and note it in the summary.
4. Draft PR title (imperative, under 70 chars)
5. Fill PR body using the template above (put the resolved/created ticket on the `Resolves:` line)
6. Run: `gh pr create --base <target-branch> --title "..." --body "..."`
7. Return the PR URL and the Linear ticket, noting whether it was reused or newly created
