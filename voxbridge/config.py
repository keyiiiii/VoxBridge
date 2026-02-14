"""Configuration loading and defaults."""

import os
import yaml

_DEFAULT_CONFIG = {
    "hotkey": "alt_r",
    "language": "ja",
    "recording": {
        "sample_rate": 16000,
        "max_duration": 60,
    },
    "stt": {
        "model": "small",
        "device": "cpu",
        "compute_type": "int8",
    },
    "formatter": {
        "enabled": True,
        "model": "qwen2.5:7b",
        "prompt_file": "prompts/format.txt",
        "timeout": 30,
    },
    "injector": {
        "send_enter_for": ["Terminal", "iTerm2", "Alacritty", "kitty", "Warp"],
        "enter_delay": 0.15,
        "clipboard_restore_delay": 0.3,
    },
    "overlay": {
        "enabled": True,
        "width": 260,
        "height": 36,
        "margin": 20,
        "opacity": 0.88,
        "auto_hide_delay": 2.0,
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(path: str | None = None) -> dict:
    """Load configuration from YAML file, merged with defaults."""
    if path is None:
        # Look for config.yaml relative to the project root
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(project_root, "config.yaml")

    config = _DEFAULT_CONFIG.copy()

    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            user_config = yaml.safe_load(f) or {}
        config = _deep_merge(config, user_config)

    # Resolve prompt_file path relative to project root
    prompt_file = config["formatter"]["prompt_file"]
    if not os.path.isabs(prompt_file):
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config["formatter"]["prompt_file"] = os.path.join(project_root, prompt_file)

    return config
