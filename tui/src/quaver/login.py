"""Login screen: authenticate with email/password or an auth token."""

from __future__ import annotations

import os

import httpx
from textual import on, work
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.message import Message
from textual.screen import Screen
from textual.widgets import Button, Input, Label, RadioButton, RadioSet, Static, Switch
from textual.binding import Binding

from qobuz_downloader.qobuz import LiveQobuz

from . import __version__
from .input import SafeInput
from .settings import Settings, save as save_settings


class LoginInput(SafeInput):
    """Login text field: Ctrl+C quits, Ctrl+H deletes like Backspace."""


class LoginSucceeded(Message):
    def __init__(self, client: LiveQobuz, serial: int | None = None) -> None:
        super().__init__()
        self.client = client
        self.serial = serial


class LoginFailed(Message):
    def __init__(self, reason: str) -> None:
        super().__init__()
        self.reason = reason

def authenticate(
    mode: str,
    email: str = "",
    password: str = "",
    app_id: str = "",
    app_secret: str = "",
    token: str = "",
) -> LiveQobuz:
    if mode == "token":
        if not (app_id and app_secret and token):
            raise ValueError("token sign-in needs app id, app secret and user auth token")
        return LiveQobuz.from_token(app_id, app_secret, token)
    if not (email and password):
        raise ValueError("enter an email and password")
    client = LiveQobuz()
    client.login(email, password)
    return client


def credentials_from_env(settings: Settings) -> dict | None:
    """Credentials from the environment, falling back to remembered settings."""
    token = os.environ.get("QOBUZ_USER_AUTH_TOKEN")
    app_id = os.environ.get("QOBUZ_APP_ID")
    app_secret = os.environ.get("QOBUZ_APP_SECRET")
    if token and app_id and app_secret:
        return {"mode": "token", "app_id": app_id, "app_secret": app_secret, "token": token}
    if settings.token and settings.app_id and settings.app_secret:
        return {
            "mode": "token",
            "app_id": settings.app_id,
            "app_secret": settings.app_secret,
            "token": settings.token,
        }
    email = os.environ.get("QOBUZ_EMAIL") or settings.email
    password = os.environ.get("QOBUZ_PASSWORD") or settings.password
    if email and password:
        return {"mode": "email", "email": email, "password": password}
    return None


class LoginScreen(Screen):
    BINDINGS = [
        ("ctrl+c", "app.quit", "Quit"),
        ("ctrl+q", "app.quit", "Quit"),
        ("down", "app.focus_next", "Next field"),
        ("up", "app.focus_previous", "Previous field"),
    ]
    AUTO_FOCUS = "#mode"

    CSS = """
#login-grid {
    align: center middle;
}

.login-box {
    width: 76;
    height: auto;
    padding: 1 2;
    border: round $accent;
}

.login-title {
    text-style: bold;
    margin-bottom: 1;
}

#mode {
    margin-bottom: 1;
}

#email-row, #token-row {
    height: auto;
    margin-bottom: 1;
}

#email-row Input, #token-row Input {
    width: 1fr;
}

#options {
    height: auto;
    margin-bottom: 1;
}

#dir {
    width: 1fr;
}

.remember {
    width: auto;
    height: auto;
    margin-left: 1;
}

.remember-label {
    margin-left: 1;
}

#error {
    color: $error;
    margin-top: 1;
}

#hint {
    color: $text-muted;
    margin-top: 1;
}

#hint2 {
    color: $text-muted;
}

#login {
    margin-top: 1;
}


#token-row {
    display: none;
}
"""

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self._settings = settings

    def compose(self) -> ComposeResult:
        yield Container(
            Vertical(
                Static(f"Sign in to Qobuz  ·  quaver {__version__}", classes="login-title"),
                RadioSet(
                    RadioButton("Email & password", id="mode-email", value=True),
                    RadioButton("Auth token", id="mode-token"),
                    id="mode",
                ),
                Horizontal(
                    LoginInput(placeholder="email", id="email", value=self._settings.email),
                    LoginInput(
                        placeholder="password",
                        password=True,
                        id="password",
                        value=self._settings.password,
                    ),
                    id="email-row",
                ),
                Horizontal(
                    LoginInput(placeholder="app id", id="app-id", value=self._settings.app_id),
                    LoginInput(
                        placeholder="app secret",
                        password=True,
                        id="app-secret",
                        value=self._settings.app_secret,
                    ),
                    LoginInput(
                        placeholder="user auth token",
                        password=True,
                        id="token",
                        value=self._settings.token,
                    ),
                    id="token-row",
                ),
                Horizontal(
                    LoginInput(
                        placeholder="download directory",
                        id="dir",
                        value=self._settings.download_dir,
                    ),
                    Horizontal(
                        Switch(value=self._settings.remember, id="remember"),
                        Label("remember me", classes="remember-label"),
                        classes="remember",
                    ),
                    id="options",
                ),
                Button("Log in", variant="primary", id="login"),
                Label("", id="error"),
                Label(
                    "Shift+paste to paste here · Ctrl+V only pastes in-app copies",
                    id="hint",
                ),
                Label(
                    "Skip login: QOBUZ_* env vars or --token flags (see --help)",
                    id="hint2",
                ),
                classes="login-box",
            ),
            id="login-grid",
        )

    @on(RadioSet.Changed, "#mode")
    def mode_changed(self, event: RadioSet.Changed) -> None:
        token_mode = event.pressed.id == "mode-token"
        self.query_one("#email-row", Horizontal).display = not token_mode
        self.query_one("#token-row", Horizontal).display = token_mode
        # Drop focus straight into the first field of the revealed row so the
        # user can start typing immediately; arrow keys walk the form from there.
        self.query_one("#app-id" if token_mode else "#email", Input).focus()

    @on(Button.Pressed, "#login")
    def login_pressed(self) -> None:
        self.start_login()

    @on(Input.Submitted)
    def submit_anywhere(self) -> None:
        self.start_login()

    def start_login(self) -> None:
        token_mode = self.query_one("#mode-token", RadioButton).value
        button = self.query_one("#login", Button)
        button.disabled = True
        self._settings.download_dir = (
            self.query_one("#dir", Input).value.strip() or self._settings.download_dir
        )
        self._settings.remember = self.query_one("#remember", Switch).value
        if token_mode:
            args = {
                "mode": "token",
                "app_id": self.query_one("#app-id", Input).value.strip(),
                "app_secret": self.query_one("#app-secret", Input).value.strip(),
                "token": self.query_one("#token", Input).value.strip(),
            }
        else:
            args = {
                "mode": "email",
                "email": self.query_one("#email", Input).value.strip(),
                "password": self.query_one("#password", Input).value,
            }
        self.authenticate(**args)

    @work(thread=True, group="login")
    def authenticate(self, **args) -> None:
        try:
            client = authenticate(**args)
        except (ValueError, RuntimeError, httpx.HTTPError) as error:
            self.post_message(LoginFailed(str(error) or type(error).__name__))
            return
        if self._settings.remember:
            for key, value in args.items():
                if key != "mode":
                    setattr(self._settings, key, value)
        save_settings(self._settings)
        self.post_message(LoginSucceeded(client, serial=self.app.next_login_serial()))

    @on(LoginFailed)
    def login_failed(self, event: LoginFailed) -> None:
        self.query_one("#error", Label).update(f"login failed: {event.reason}")
        button = self.query_one("#login", Button)
        button.disabled = False
        button.focus()
        event.stop()
