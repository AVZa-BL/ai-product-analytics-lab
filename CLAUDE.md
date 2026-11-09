# Working rules

- Every task: before adding or keeping a test, a helper, a config option, a CI job or a document,
  ask whether anything would break, or be missed, without it. If not, leave it out or delete it.
- Keep as little as possible. A test earns its place by guarding behaviour (a boundary, a
  reference value, a security property, an output format), not by repeating another test or by
  matching prose. Prefer one parametrized test to several copies.
- Plans and specs are scaffolding: delete a plan once its work has merged; git keeps it.
- Show evidence for a cut (coverage unchanged, or a mutation that is still caught) and say
  what remains unverified.

## Mark finished chats as done

- When a task is fully and successfully completed (requested work done and verified, nothing
  failing or blocked), rename the chat as the last step. New title = `✅ [done] <original title>`,
  the original title unchanged.
- If a session-title tool is available (e.g. `mcp__claude-code-remote__set_session_title`), read
  the current title first (`get_session`), then call it.
- If no such tool exists (local CLI), say so in one line and tell the user to run
  `/rename ✅ [done] <original title>`.
- Never stack prefixes: if the title already starts with `✅ [done]`, leave it.
- Do not rename when the task failed, is partial, or is waiting on the user's answer.
- For a follow-up task in an already-renamed chat, keep the existing prefix.
