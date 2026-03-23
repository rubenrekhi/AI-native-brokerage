# Commit Message Format

```
<type>(<scope>): <short imperative summary>
```

| Segment     | Purpose                                      | Rules                                                      |
| ----------- | -------------------------------------------- | ---------------------------------------------------------- |
| **type**    | Categorises the change                       | lowercase; choose from the list below                      |
| **scope**   | Pin-points where the change lives (optional) | 1-3 words, snakecase, such as `auth`, `js_bridge`, `Oauth` |
| **summary** | Explains what the commit does                | start with a verb, keep under 72 chars, no period          |

## Allowed `type` keywords

- **feat** – a new user-facing feature
- **fix** – a bug fix
- **docs** – documentation only
- **refactor** – code change that neither fixes a bug nor adds a feature
- **test** – adding or updating tests
- **chore** – tooling, build, or maintenance tasks (CI, dependency bumps, formatting)

## Writing guidelines

- Use the present-tense imperative: _add_, _update_, _remove_.
- Limit the first line to 72 characters; wrap additional detail in a body after a blank line.
- Reference work items or tickets in the body, not in the summary.
- Avoid generic scopes like _misc_; if nothing fits, omit the scope.

## Examples

```
feat(auth): add Google sign-in
fix(api): handle empty receipt list when importing
docs(readme): clarify local setup steps
refactor(ui): simplify receipt item component
chore(ci): bump Node version to 18
test(db): add integration tests for receipt import
```

## Optional body and footer

```
feat(email): import receipts from Gmail

Import plain-text and HTML emails within a user-selected date range,
parse attached PDFs, and queue each message for Document Intelligence
processing.

Refs: SEV-42
```
