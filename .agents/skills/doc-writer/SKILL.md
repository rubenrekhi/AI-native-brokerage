---
name: doc-writer
description: Review all code and docs, then update any documentation that has drifted from the current architecture, directory structure, integrations, or configuration.
---

Delegate this workflow to the 'doc-writer' agent using `mode: bypassPermissions` so it can read all files and make edits autonomously without prompting. Pass the following as the prompt:

---

Audit all project documentation against the current state of the codebase.

Follow the audit workflow defined in your agent instructions. Work through every doc file, check it against the actual code, and update any sections that have drifted.

When you're done, return a brief summary of what changed and what was already accurate.
