"""Demo sign-in: one fixed account, fails closed without a configured password."""

from optev.app import auth as A
from optev.app import data as D


def test_check_accepts_only_the_demo_account():
    assert A.check("Admin", "s3cret", "s3cret")
    assert A.check(" Admin ", "s3cret", "s3cret")  # stray spaces around the username
    assert not A.check("admin", "s3cret", "s3cret")
    assert not A.check("Admin", "wrong", "s3cret")
    assert not A.check("someone", "s3cret", "s3cret")


def test_check_fails_closed_without_a_password():
    assert not A.check("Admin", "", None)
    assert not A.check("Admin", "", "")


def test_signed_out_the_app_shows_only_the_sign_in_form(monkeypatch, tmp_path):
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(D, "ENV_FILE", tmp_path / ".env")
    monkeypatch.setenv(A.PASSWORD_ENV, "s3cret")
    at = AppTest.from_file(str(Path(D.__file__).with_name("main.py")), default_timeout=60).run()
    assert not at.exception
    assert [t.label for t in at.text_input] == ["Username", "Password"]
    assert not at.metric  # no page content before sign-in
    assert A.LOGO.is_file() and at.get("image")  # the OptEV+ logo, beside the form

    at.text_input[0].set_value("Admin")
    at.text_input[1].set_value("s3cret")
    at.button[-1].click().run()
    assert at.session_state[A.SESSION_KEY]
    assert at.metric  # the Overview


def test_demo_password_reads_the_environment(monkeypatch, tmp_path):
    monkeypatch.setattr(D, "ENV_FILE", tmp_path / ".env")
    monkeypatch.delenv(A.PASSWORD_ENV, raising=False)
    assert A.demo_password() is None
    monkeypatch.setenv(A.PASSWORD_ENV, "s3cret")
    assert A.demo_password() == "s3cret"
