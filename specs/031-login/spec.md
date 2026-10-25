# 031 · demo sign-in

**Owner:** Sushant  ·  **Status:** ready for review  ·  **Branch:** `sushant/login`

## Design section
> §4.6 App (`app/`): Streamlit multipage app. `app/data.py` is the only module that reads data
> … **No business logic in the app.**

The design defines no sign-in. This spec adds one paragraph to §4.6 (change log 1.20): every
page sits behind a sign-in for one fixed demo account, `Admin`; there is no sign-up or reset.

## Problem
The deployed app is open to anyone with the link. The demo needs a sign-in page with a single
account, and no way to create another.

## Contracts touched
None. No table, no contract model.

## Approach
- `optev/app/auth.py`: `USERNAME = "Admin"`; `demo_password()` reads `OPTEV_DEMO_PASSWORD`
  (`.env` locally, app secrets on Community Cloud); `check(username, password, expected)`
  compares in constant time and fails closed when no password is set; `require_login()`
  renders the form, `st.stop()`s until signed in, then shows Log Out in the sidebar.
- `main.py` calls `require_login()` before `st.navigation(...).run()`, so every page and deep
  link is gated in one place. Sign-in lives in `st.session_state` (per browser session).
- The password is never committed.

## Verification
`uv run pytest tests/test_app_auth.py`: the one account is accepted, wrong user, wrong case
or wrong password refused, and no password configured refuses everyone. Manually:
`uv run streamlit run optev/app/main.py` shows only the sign-in form until signed in.

## Open questions
- Deployment: `OPTEV_DEMO_PASSWORD` must be added to the Community Cloud app's secrets, or
  nobody can sign in there.

## Checkpoint · 25 Oct 2026
- Works: sign-in gate in `main.py` before navigation; wrong password refused; `/demand` and
  `/allocation` deep links show only the form; Log Out returns to the form and hides the nav
  (one hidden page while signed out). Checked in the browser on the sample.
- After sign-in the visitor lands on Overview, not the deep-linked page.
- Verify: ruff and mypy clean; `tests/test_app_auth.py` and `tests/test_app_shell.py` pass
  (the two shell tests that run `main.py` now sign in first). With `DATABASE_URL` blank, only
  5 graph tests in `test_explain.py` / `test_graph_retrieve.py` fail, and they fail the same
  on `main`.
- Next: add `OPTEV_DEMO_PASSWORD` to the Community Cloud secrets; Gurneet to review.
