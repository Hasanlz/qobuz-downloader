#!/usr/bin/env python3
"""Quaver setup wizard — cross-platform installer for qobuz-downloader + TUI.

Run from anywhere inside a checkout:

    python wizard.py            (Windows)
    python3 wizard.py           (macOS / Linux)

Flags:
    --defaults     accept defaults for every prompt (keeps saved values)
    --check        health-check an existing setup; change nothing
    --skip-install skip venv/pip stages (use with --check or a ready venv)
    --no-test      skip the live credential test

Walks the human through the stages only a person can do (Qobuz account,
credentials from the browser), runs the mechanical stages (venv, pip, global
command), writes the app's own settings file, and ends with a real login test.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import shutil
import subprocess
import sys
import textwrap
import webbrowser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
MIN_PYTHON = (3, 12)

if sys.stdout.isatty() and os.name != "nt":
    BOLD, DIM, RESET = "\033[1m", "\033[2m", "\033[0m"
    BLUE, GREEN, YELLOW, RED = "\033[34m", "\033[32m", "\033[33m", "\033[31m"
else:
    BOLD = DIM = RESET = BLUE = GREEN = YELLOW = RED = ""

TOTAL_STAGES = 7
_stage_index = 0
skipped: list[str] = []
written: list[str] = []


# ── wizard library ─────────────────────────────────────────────────────────


def _tty():
    """Reading terminal, even when stdin is a pipe (curl | bash)."""
    if sys.stdin.isatty():
        return sys.stdin
    if os.name != "nt":
        try:
            return open("/dev/tty", "r")
        except OSError:
            pass
    return sys.stdin


def _read(prompt: str = "") -> str:
    handle = _tty()
    try:
        if prompt:
            print(prompt, end="", flush=True)
        line = handle.readline()
    except OSError:
        return ""
    return line.rstrip("\n")


def clear() -> None:
    if sys.stdout.isatty():
        os.system("cls" if os.name == "nt" else "clear")


def say(text: str = "") -> None:
    print(f"  {text}")


def step(text: str) -> None:
    print(f"  {BLUE}•{RESET} {text}")


def note(text: str) -> None:
    print(f"  {DIM}{text}{RESET}")


def good(text: str) -> None:
    print(f"  {GREEN}✓{RESET} {text}")


def warn(text: str) -> None:
    print(f"  {YELLOW}⚠ {text}{RESET}")


def fail(text: str) -> None:
    print(f"  {RED}✗ {text}{RESET}")


def banner(title: str) -> None:
    clear()
    print(f"\n{BOLD}{BLUE}  {title}{RESET}")
    print(f"  {DIM}{TOTAL_STAGES} stages{RESET}\n")
    print(f"  {DIM}This wizard drives the browser and asks you for the few values only")
    print("  you can provide. Stop with Ctrl-C any time; it remembers saved values.")
    print(f"{RESET}")
    pause("Ready to start?")


def stage(name: str) -> None:
    global _stage_index
    _stage_index += 1
    clear()
    print(f"\n{BOLD}{BLUE}▸ Stage {_stage_index}/{TOTAL_STAGES} · {name}{RESET}\n")


def pause(text: str = "Press Enter to continue") -> None:
    if DEFAULTS:
        return
    answer = _read(f"  {DIM}{text}{RESET} ")
    if answer == "":
        cancel()


def confirm(text: str) -> bool:
    if DEFAULTS:
        return True
    reply = _read(f"  {YELLOW}? {text} [y/N]{RESET} ").strip().lower()
    return reply in ("y", "yes")


def ask(prompt: str, default: str = "") -> str:
    if DEFAULTS:
        return default
    suffix = f" {DIM}[Enter = {default}]{RESET}" if default else ""
    return _read(f"  {BOLD}{prompt}{RESET}{suffix} ").strip() or default


def ask_secret(prompt: str) -> str:
    if DEFAULTS:
        return ""  # keep the stored secret
    try:
        return getpass.getpass(f"  {BOLD}{prompt}{RESET} ").strip()
    except (EOFError, OSError):
        cancel()


def open_url(url: str) -> None:
    step(f"opening {url}")
    try:
        webbrowser.open(url)
    except Exception:
        warn(f"could not open a browser — visit it manually: {url}")


def cancel() -> None:
    print(f"\n  {RED}cancelled — re-run the wizard any time{RESET}\n")
    raise SystemExit(130)


def run(cmd: list[str], cwd: Path | None = None) -> int:
    note("$ " + " ".join(str(c) for c in cmd))
    try:
        return subprocess.run([str(c) for c in cmd], cwd=cwd).returncode
    except OSError as error:
        fail(str(error))
        return 1


# ── settings (same file the app reads) ─────────────────────────────────────


def settings_path() -> Path:
    base = os.environ.get("QUAVER_CONFIG_DIR")
    root = Path(base) if base else Path.home() / ".config" / "quaver"
    return root / "settings.json"


def load_settings() -> dict:
    path = settings_path()
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        data = {}
    base = {
        "download_dir": str(Path.home() / "Music" / "Qobuz"),
        "quality": "hires",
        "dir_template": "{artist}/{album}",
        "file_template": "{tracknumber} - {title}",
        "lyrics": True,
        "remember": True,
        "email": "",
        "password": "",
        "token": "",
        "app_id": "",
        "app_secret": "",
    }
    for key, value in data.items():
        if key in base:
            base[key] = value
    return base


def save_settings(settings: dict) -> None:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2))
    if os.name != "nt":
        try:
            path.chmod(0o600)
        except OSError:
            pass
    written.append(str(path))
    good(f"wrote settings → {path}")


# ── install plumbing ───────────────────────────────────────────────────────


def venv_dir() -> Path:
    return REPO_ROOT / ".venv"


def venv_python(venv: Path) -> Path:
    return venv / ("Scripts" if os.name == "nt" else "bin") / (
        "python.exe" if os.name == "nt" else "python"
    )


def venv_script(venv: Path, name: str) -> Path:
    return venv / ("Scripts" if os.name == "nt" else "bin") / (
        f"{name}.exe" if os.name == "nt" else name
    )


# ── flags ──────────────────────────────────────────────────────────────────

DEFAULTS = False
NO_TEST = False


def has_package(venv: Path, name: str) -> bool:
    probe = (
        "import importlib.util,sys;"
        f"sys.exit(0 if importlib.util.find_spec({name!r}) else 1)"
    )
    return run([venv_python(venv), "-c", probe]) == 0


# ── stages ─────────────────────────────────────────────────────────────────


def stage_system() -> None:
    stage("System check")
    say(f"Python {sys.version.split()[0]} · {os.name} · {sys.platform}")
    if sys.version_info < MIN_PYTHON:
        fail(f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ is required "
             f"(found {sys.version_info.major}.{sys.version_info.minor}).")
        say("Install a newer Python, then re-run the wizard:")
        if os.name == "nt":
            step("winget install Python.Python.3.12")
        elif sys.platform == "darwin":
            step("brew install python@3.12")
        else:
            step("sudo apt install python3.12  (or your distro's equivalent)")
        raise SystemExit(1)
    good("Python version OK")
    say(f"Repository: {REPO_ROOT}")
    if not (REPO_ROOT / "pyproject.toml").exists() or not (REPO_ROOT / "tui").is_dir():
        fail("run the wizard from a clone of qobuz-downloader (pyproject.toml + tui/ "
             "must be next to this script).")
        say("git clone https://github.com/Hasanlz/qobuz-downloader && cd qobuz-downloader && python wizard.py")
        raise SystemExit(1)
    good("repository layout OK")
    pause()


def stage_install(venv: Path) -> bool:
    stage("Virtual environment & packages")
    if venv_python(venv).exists():
        say(f"venv already exists at {venv}")
        if not confirm("reuse it"):
            if confirm("delete and recreate it"):
                shutil.rmtree(venv, ignore_errors=True)
            else:
                return False
    if not venv_python(venv).exists():
        step(f"creating venv → {venv}")
        if run([sys.executable, "-m", "venv", str(venv)]) != 0:
            fail("venv creation failed")
            return False
    if run([venv_python(venv), "-m", "pip", "install", "--upgrade", "pip"]) != 0:
        warn("pip upgrade failed (offline?); continuing")
    step("installing the downloader library")
    if run([venv_python(venv), "-m", "pip", "install", "-e", str(REPO_ROOT)]) != 0:
        fail("library install failed — check network / Python version")
        return False
    step("installing the terminal UI (quaver)")
    if run([venv_python(venv), "-m", "pip", "install", "-e", str(REPO_ROOT / "tui")]) != 0:
        fail("TUI install failed")
        return False
    good("quaver installed into the venv")
    return True


def stage_subscription() -> None:
    stage("Qobuz account")
    say("Downloading needs an ACTIVE Qobuz subscription — free accounts cannot")
    say("download, and Hi-Res (24-bit) files need the Studio plan.")
    if not DEFAULTS:
        open_url("https://www.qobuz.com/gb/shop/account")
    if not confirm("I have an active Qobuz subscription"):
        warn("without a subscription the app cannot download — get one at qobuz.com")
        say("The wizard will finish setup anyway; come back once subscribed.")
        skipped.append("active Qobuz subscription")


def stage_credentials(settings: dict) -> dict:
    stage("Credentials")
    say("Recommended: email + password. The app signs in, fetches its app id and")
    say("secret automatically, and refreshes the session token for you.")
    say("Expert: you can paste a user-auth token + app id/secret from browser")
    say("developer tools instead — choose that only if you know where they are.")
    existing = settings["email"] or settings["token"]
    if existing:
        say("")
        if settings["email"]:
            good(f"remembered email: {settings['email']}")
        else:
            good("remembered auth token is configured")
        if DEFAULTS or not confirm("replace credentials"):
            return settings
    say("")
    if not DEFAULTS and confirm("sign in with email + password (recommended)"):
        settings["token"] = settings["app_id"] = settings["app_secret"] = ""
        settings["email"] = ask("Qobuz email:")
        settings["password"] = ask_secret("Qobuz password (hidden):")
        settings["remember"] = True
        return settings
    note("token mode: in the browser's developer tools (F12) on qobuz.com while")
    note("logged in, open any request to www.qobuz.com/api.json/0.2/... and copy")
    note("app_id and user_auth_token from it; the app secret comes from your")
    note("token provider / tool that issued the token.")
    settings["email"] = settings["password"] = ""
    settings["app_id"] = ask("app id (9 digits):")
    settings["app_secret"] = ask_secret("app secret (32 chars):")
    settings["token"] = ask_secret("user auth token:")
    settings["remember"] = True
    return settings


def stage_preferences(settings: dict) -> dict:
    stage("Preferences")
    settings["download_dir"] = ask("download directory", settings["download_dir"])
    say("")
    say("quality ceiling — files download at the best available up to this:")
    say("   cd = 16-bit/44.1 kHz · hires96 = 24-bit/96 kHz · hires = 24-bit/192 kHz")
    quality = ask("quality (cd/hires96/hires)", settings["quality"]).lower()
    settings["quality"] = quality if quality in ("cd", "hires96", "hires") else "hires"
    lyrics = ask("save synced lyrics (.lrc) alongside files? (y/n)",
                 "y" if settings["lyrics"] else "n").lower()
    settings["lyrics"] = lyrics != "n"
    return settings


def stage_global_command(venv: Path) -> None:
    stage("Make `quaver` run anywhere")
    exe = venv_script(venv, "quaver")
    if not exe.exists():
        warn("quaver script not found — install stage may have failed")
        return
    if os.name == "nt":
        good(f"installed: {exe}")
        say("")
        step("Run it with the full path, or activate the venv:")
        step("    " + str(venv) + "\\Scripts\\activate")
        step("    quaver")
        note("or add the Scripts folder to your PATH to use it anywhere:")
        note("    " + str(exe.parent))
        if confirm("add this to your user PATH now"):
            if run(["powershell", "-NoProfile", "-Command",
                    "[Environment]::SetEnvironmentVariable("
                    f"'PATH', [Environment]::GetEnvironmentVariable('PATH','User') "
                    f"+ ';" + str(exe.parent) + "', 'User')"]) == 0:
                good("added to user PATH — open a new terminal")
            else:
                skipped.append("PATH registration (set it manually as shown above)")
    else:
        target = Path.home() / ".local" / "bin" / "quaver"
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_symlink() or target.exists():
            target.unlink()
        target.symlink_to(exe)
        good(f"linked → {target}")
        path_dirs = os.environ.get("PATH", "").split(os.pathsep)
        if str(target.parent) not in path_dirs:
            warn(f"{target.parent} is not on PATH")
            rc = Path.home() / (".zshrc" if "zsh" in os.environ.get("SHELL", "")
                                else ".bashrc")
            if confirm(f"add export PATH to {rc.name} now"):
                with open(rc, "a") as handle:
                    handle.write(f'\nexport PATH="$HOME/.local/bin:$PATH"\n')
                written.append(f"PATH export in {rc}")
                good("added — open a new shell (or `source " + str(rc) + "`)")
            else:
                skipped.append(f"PATH (add: export PATH=\"$HOME/.local/bin:$PATH\")")
        else:
            good("~/.local/bin is on PATH — `quaver` will just work")


def stage_test(settings: dict, venv: Path) -> None:
    stage("Test sign-in")
    if NO_TEST:
        skipped.append("live sign-in test (--no-test)")
        return
    if not (settings["email"] or settings["token"]):
        warn("no credentials stored — run `quaver` and log in via its login screen")
        return
    say("contacting Qobuz with your credentials…")
    snippet = textwrap.dedent(
        """
        import json, sys
        settings = json.load(sys.stdin)
        sys.path.insert(0, %r)
        from quaver.login import authenticate
        try:
            mode = "token" if settings.get("token") else "email"
            client = authenticate(mode, email=settings.get("email", ""),
                                  password=settings.get("password", ""))
            tracks = client.search_tracks("never gonna give", 1)
            print("OK", len(tracks))
        except Exception as error:
            print("FAIL", type(error).__name__, str(error)[:200])
            raise SystemExit(1)
        """
    ) % str(REPO_ROOT / "tui" / "src")
    result = subprocess.run(
        [str(venv_python(venv)), "-c", snippet],
        input=json.dumps(settings),
        capture_output=True, text=True,
    )
    line = (result.stdout + result.stderr).strip().splitlines()
    last = line[-1] if line else ""
    if result.returncode == 0:
        good("sign-in works — Qobuz API reachable")
    else:
        fail(f"sign-in test failed: {last}")
        note("check subscription / credentials, or your proxy (socks:// is fine —")
        note("quaver normalizes it), then run `quaver` to try again interactively.")
        skipped.append("live sign-in test")


def summary(settings: dict, venv: Path) -> None:
    clear()
    print(f"\n{BOLD}{GREEN}  ✓ Setup complete{RESET}\n")
    for item in written:
        note(f"wrote: {item}")
    exe = venv_script(venv, "quaver")
    step(f"start the app:  {exe if os.name == 'nt' else 'quaver'}")
    note(f"downloads land in: {settings['download_dir']}")
    note(f"settings: {settings_path()}")
    say("")
    extra = shutil.which("mpv") or shutil.which("ffplay")
    if extra:
        good("audio playback available (player bar works)")
    else:
        warn("no audio player found — playback needs ffplay or mpv:")
        if os.name == "nt":
            step("winget install Gyan.FFmpeg")
        elif sys.platform == "darwin":
            step("brew install ffmpeg   (or: brew install mpv)")
        else:
            step("sudo apt install ffmpeg   (or: sudo apt install mpv)")
    if skipped:
        print("")
        warn("still to do by hand:")
        for item in skipped:
            note(f"  - {item}")
    print("")


def health_check(venv: Path) -> int:
    print("quaver health check\n")
    problems = 0
    if sys.version_info < MIN_PYTHON:
        fail(f"python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ required"); problems += 1
    else:
        good(f"python {sys.version.split()[0]}")
    if venv_python(venv).exists():
        good(f"venv: {venv}")
        if has_package(venv, "quaver") and has_package(venv, "qobuz_downloader"):
            good("packages installed")
        else:
            fail("packages missing in venv — re-run wizard.py"); problems += 1
    else:
        fail(f"no venv at {venv} — run wizard.py"); problems += 1
    path = settings_path()
    if path.exists():
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            fail(f"unreadable settings: {path}"); problems += 1
        else:
            good(f"settings: {path}")
            if data.get("email") or data.get("token"):
                good("credentials remembered")
            else:
                warn("no credentials — log in inside quaver or re-run wizard.py")
    else:
        warn(f"no settings file ({path})")
    return 1 if problems else 0


def main() -> int:
    global DEFAULTS, NO_TEST
    parser = argparse.ArgumentParser(prog="wizard.py",
                                     description="Quaver cross-platform setup wizard")
    parser.add_argument("--defaults", action="store_true",
                        help="accept defaults for every prompt")
    parser.add_argument("--check", action="store_true",
                        help="health-check an existing setup; change nothing")
    parser.add_argument("--skip-install", action="store_true")
    parser.add_argument("--no-test", action="store_true")
    args = parser.parse_args()
    DEFAULTS = args.defaults
    NO_TEST = args.no_test
    venv = venv_dir()
    if args.check:
        return health_check(venv)

    banner("Quaver setup — qobuz-downloader + terminal UI")
    stage_system()
    if args.skip_install:
        installed = venv_python(venv).exists()
        if not installed:
            warn("--skip-install set but no venv exists; later stages may fail")
    else:
        installed = stage_install(venv)
    if not installed:
        warn("install skipped/failed — continuing with setup anyway")
    settings = load_settings()
    stage_subscription()
    settings = stage_credentials(settings)
    settings = stage_preferences(settings)
    save_settings(settings)
    if installed:
        stage_global_command(venv)
        stage_test(settings, venv)
    summary(settings, venv)
    return 0


if __name__ == "__main__":
    main()
