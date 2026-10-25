"""Demo sign-in (SYSTEM_DESIGN.md §4.6): one fixed account, no sign-up, no password reset.

The username is fixed here; the password is read from OPTEV_DEMO_PASSWORD (.env locally, the
app's secrets on Streamlit Community Cloud) and never written into the repository. With no
password set, nobody can sign in: the gate fails closed.
"""

import hmac
import os
from pathlib import Path

import streamlit as st

LOGO = Path(__file__).with_name("logo-signin.png")  # the OptEV+ logo from the final deck
USERNAME = "Admin"
PASSWORD_ENV = "OPTEV_DEMO_PASSWORD"
SESSION_KEY = "signed_in"


def demo_password() -> str | None:
    """The configured demo password, or None if it is not set."""
    from dotenv import load_dotenv

    from optev.app import data

    load_dotenv(data.ENV_FILE)  # never overrides a variable already set
    return os.environ.get(PASSWORD_ENV) or None


def check(username: str, password: str, expected: str | None) -> bool:
    """True only for the one demo account. Constant-time, so a wrong guess takes as long as a
    nearly right one."""
    if not expected:
        return False
    user_ok = hmac.compare_digest(username.strip().encode(), USERNAME.encode())
    pass_ok = hmac.compare_digest(password.encode(), expected.encode())
    return user_ok and pass_ok


def require_login() -> None:
    """Show the sign-in form and stop the page until the visitor signs in; once signed in, put
    a Log Out button in the sidebar."""
    if st.session_state.get(SESSION_KEY):
        if st.sidebar.button("Log Out", icon=":material/logout:", key="logout"):
            st.session_state[SESSION_KEY] = False
            st.rerun()
        return

    # a navigation of one hidden page, so the app's page links disappear after Log Out
    st.navigation([st.Page(_sign_in_form, title="Sign In", icon=":material/login:")],
                  position="hidden").run()
    st.stop()


def _sign_in_form() -> None:
    expected = demo_password()
    st.markdown('<div style="height: 9vh"></div>', unsafe_allow_html=True)
    # the brand on the left, the form on the right; they stack on a phone
    brand, _, form = st.columns([1.25, 0.15, 1], vertical_alignment="center")
    with brand:
        st.image(str(LOGO), width="stretch")
        st.markdown('<div class="ox-lead">Where Singapore\'s next public EV charging points '
                    'should go, how many at each site, and the evidence behind every one.</div>',
                    unsafe_allow_html=True)
    with form:
        st.markdown('<div class="ox-title">Sign <span class="ox-grad">In</span></div>'
                    '<div class="ox-sub">OptEV+ demo access.</div>', unsafe_allow_html=True)
        if expected is None:
            st.error(f"Sign-in is not configured: set `{PASSWORD_ENV}` in `.env` or the app's "
                     "secrets.")
        with st.form("sign_in"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Sign In", type="primary", width="stretch")
        if submitted:
            if check(username, password, expected):
                st.session_state[SESSION_KEY] = True
                st.rerun()
            st.error("Wrong username or password.")
