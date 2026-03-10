"""User preferences persistence (~/Library/Application Support/VoxBridge)."""

import os

from .constants import FORMAT_LEVELS, MODIFIER_KEY_CODES

_SUPPORT_DIR = os.path.join(
    os.path.expanduser("~"), "Library", "Application Support", "VoxBridge"
)
_HOTKEY_FILE = os.path.join(_SUPPORT_DIR, "hotkey")
_MODEL_FILE = os.path.join(_SUPPORT_DIR, "stt_model")
_FORMAT_LEVEL_FILE = os.path.join(_SUPPORT_DIR, "formatter_level")
_LAUNCH_AT_LOGIN_FILE = os.path.join(_SUPPORT_DIR, "launch_at_login")

USER_PROMPT_FILE = os.path.join(_SUPPORT_DIR, "format_prompt.txt")


def _read(path: str) -> str | None:
    """Read a single-value preference file. Returns None if missing."""
    try:
        with open(path, "r") as f:
            return f.read().strip() or None
    except FileNotFoundError:
        return None


def _write(path: str, value: str) -> None:
    """Write a single-value preference file."""
    os.makedirs(_SUPPORT_DIR, exist_ok=True)
    with open(path, "w") as f:
        f.write(value)


def get_hotkey(default: str = "alt_r") -> str:
    """Return hotkey: user override > default."""
    saved = _read(_HOTKEY_FILE)
    if saved and saved in MODIFIER_KEY_CODES:
        return saved
    return default


def set_hotkey(key: str) -> None:
    _write(_HOTKEY_FILE, key)


def get_model(default: str = "small") -> str:
    """Return STT model: user override > default."""
    return _read(_MODEL_FILE) or default


def set_model(model: str) -> None:
    _write(_MODEL_FILE, model)


def get_format_level(config_enabled: bool = True) -> str:
    """Return format level: saved > config enabled flag > 'on'."""
    saved = _read(_FORMAT_LEVEL_FILE)
    if saved in FORMAT_LEVELS:
        return saved
    return "on" if config_enabled else "off"


def set_format_level(level: str) -> None:
    _write(_FORMAT_LEVEL_FILE, level)


def is_launch_at_login() -> bool:
    return os.path.isfile(_LAUNCH_AT_LOGIN_FILE)


def set_launch_at_login_flag(enabled: bool) -> None:
    """Set or remove the launch-at-login flag file."""
    os.makedirs(_SUPPORT_DIR, exist_ok=True)
    if enabled:
        with open(_LAUNCH_AT_LOGIN_FILE, "w") as f:
            f.write("1")
    elif os.path.isfile(_LAUNCH_AT_LOGIN_FILE):
        os.remove(_LAUNCH_AT_LOGIN_FILE)
