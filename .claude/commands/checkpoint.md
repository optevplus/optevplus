---
description: Append session state to the active spec so the next session starts warm
---
Append a dated `## Checkpoint` section to the spec for the work in progress, covering:

- What now works, and where the code is
- What is half-built, and what specifically remains
- Decisions taken this session and why
- What the next session should do first

Keep it under 20 lines. This exists so the next session does not have to re-derive
context by reading the whole package.
