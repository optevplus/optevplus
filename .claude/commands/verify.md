---
description: Run lint, types and tests; report only what failed
---
Run these from `SystemCode`, in order, and stop at the first failure:

```bash
uv run ruff check .
uv run mypy optev
uv run pytest
```

Report only failures and the fix for each. If everything passes, say so in one line —
do not summarise what passed.
