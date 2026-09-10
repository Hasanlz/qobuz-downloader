"""Entry point for the quaver command."""

from __future__ import annotations

import argparse
from pathlib import Path

from .net import normalize_proxy_env
from .settings import Settings, load as load_settings


def build_cli_creds(args: argparse.Namespace) -> dict | None:
    """Credentials passed on the command line (one-shot, never saved)."""
    if args.token or args.app_id or args.app_secret:
        return {
            "mode": "token",
            "app_id": args.app_id or "",
            "app_secret": args.app_secret or "",
            "token": args.token or "",
        }
    if args.email or args.password:
        return {
            "mode": "email",
            "email": args.email or "",
            "password": args.password or "",
        }
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="quaver", description="Terminal UI for qobuz-downloader."
    )
    parser.add_argument(
        "directory",
        nargs="?",
        default=None,
        help="download directory (default: from settings, originally ~/Music/Qobuz)",
    )
    parser.add_argument("--token", default=None, help="Qobuz user auth token (skips login)")
    parser.add_argument("--app-id", default=None, help="Qobuz app id (skips login)")
    parser.add_argument("--app-secret", default=None, help="Qobuz app secret (skips login)")
    parser.add_argument("--email", default=None, help="Qobuz email (skips login)")
    parser.add_argument("--password", default=None, help="Qobuz password (skips login)")
    args = parser.parse_args(argv)
    normalize_proxy_env()
    settings: Settings = load_settings()
    if args.directory:
        settings.download_dir = str(Path(args.directory).expanduser())
    from .app import QuaverApp

    app = QuaverApp(settings=settings, cli_creds=build_cli_creds(args))
    try:
        app.run()
    except KeyboardInterrupt:
        # Ctrl+C during startup/teardown: Textual restores the terminal itself;
        # exit quietly instead of spilling a traceback.
        return 130
    return 0
