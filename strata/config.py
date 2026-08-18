"""Environment-driven settings.

Everything configurable lives here so a later deploy is a config change:
STRATA_DATA_DIR, STRATA_PASSWORD, STRATA_SECRET, STRATA_PORT, ANTHROPIC_API_KEY.
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_PORT = 8020


def _resolve_data_dir() -> Path:
    raw = os.environ.get("STRATA_DATA_DIR")
    if raw:
        d = Path(raw).expanduser()
    else:
        d = Path.home() / ".strata"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _resolve_secret(data_dir: Path) -> str:
    env = os.environ.get("STRATA_SECRET")
    if env:
        return env
    # Persist a generated secret so sessions survive restarts.
    f = data_dir / "secret"
    if f.exists():
        return f.read_text().strip()
    s = secrets.token_hex(32)
    f.write_text(s)
    try:
        f.chmod(0o600)
    except OSError:
        pass
    return s


@dataclass
class Settings:
    data_dir: Path = field(default_factory=_resolve_data_dir)
    password: str = field(default_factory=lambda: os.environ.get("STRATA_PASSWORD", ""))
    port: int = field(default_factory=lambda: int(os.environ.get("STRATA_PORT", DEFAULT_PORT)))
    anthropic_api_key: str = field(default_factory=lambda: os.environ.get("ANTHROPIC_API_KEY", ""))
    capture_token: str = field(default_factory=lambda: os.environ.get("STRATA_CAPTURE_TOKEN", ""))
    canvas_base_url: str = field(
        default_factory=lambda: os.environ.get("CANVAS_BASE_URL", "").rstrip("/")
    )
    canvas_token: str = field(default_factory=lambda: os.environ.get("CANVAS_TOKEN", ""))
    secret: str = ""

    def __post_init__(self) -> None:
        if not self.secret:
            self.secret = _resolve_secret(self.data_dir)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "strata.db"

    @property
    def auth_enabled(self) -> bool:
        return bool(self.password)

    @property
    def ai_enabled(self) -> bool:
        return bool(self.anthropic_api_key)

    @property
    def canvas_enabled(self) -> bool:
        return bool(self.canvas_base_url and self.canvas_token)
