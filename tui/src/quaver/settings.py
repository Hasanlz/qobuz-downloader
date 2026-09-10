import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(slots=True)
class Settings:
    download_dir: str = str(Path.home() / "Music" / "Qobuz")
    quality: str = "hires"  # cd | hires96 | hires
    dir_template: str = "{artist}/{album}"
    file_template: str = "{tracknumber} - {title}"
    lyrics: bool = True
    remember: bool = True
    email: str = ""
    password: str = ""
    token: str = ""
    app_id: str = ""
    app_secret: str = ""


def _path() -> Path:
    return config_dir() / "settings.json"


def config_dir() -> Path:
    base = os.environ.get("QUAVER_CONFIG_DIR")
    return Path(base) if base else Path.home() / ".config" / "quaver"



def _migrate_legacy(target: Path) -> None:
    """Move pre-rename settings (~/.config/qobuz-tui) to the new location."""
    if os.environ.get("QUAVER_CONFIG_DIR"):
        return  # custom dir requested; leave legacy files alone
    legacy = Path.home() / ".config" / "qobuz-tui" / "settings.json"
    if legacy.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            legacy.replace(target)
            target.chmod(0o600)
            legacy.parent.rmdir()
        except OSError:
            pass


def load() -> Settings:
    path = _path()
    if not path.exists():
        _migrate_legacy(path)
    if not path.exists():
        return Settings()
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return Settings()
    settings = Settings()
    for key, value in data.items():
        if hasattr(settings, key) and isinstance(value, type(getattr(settings, key))):
            setattr(settings, key, value)
    return settings


def save(settings: Settings) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(settings)
    if not settings.remember:
        for key in ("email", "password", "token", "app_id", "app_secret"):
            payload[key] = ""
    path.write_text(json.dumps(payload, indent=2))
    path.chmod(0o600)
