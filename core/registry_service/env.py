"""Registry service env loading helpers."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


@lru_cache(maxsize=1)
def load_root_env() -> str | None:
    """
    Load project-root .env once.

    Existing process environment values keep priority.
    """
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists() or not env_path.is_file():
        return None
    load_dotenv(dotenv_path=env_path, override=False)
    return str(env_path)
