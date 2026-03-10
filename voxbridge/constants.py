"""Shared constants for VoxBridge."""

# --- Audio thresholds (sample count at 16kHz) ---
MIN_AUDIO_SAMPLES = 1600      # ~0.1s — minimum to process after recording
MIN_PREVIEW_SAMPLES = 8000    # ~0.5s — minimum for live preview STT

# --- Recording timers ---
PREVIEW_INTERVAL_SEC = 1.5    # Live preview STT interval
COUNTDOWN_INTERVAL_SEC = 1.0  # Countdown tick interval
COUNTDOWN_START_SEC = 10      # Countdown begins at this many seconds remaining

# --- macOS virtual key codes for modifier keys ---
MODIFIER_KEY_CODES = {
    "alt_r": 61,
    "alt_l": 58,
    "ctrl_r": 62,
    "ctrl_l": 59,
    "shift_r": 60,
    "shift_l": 56,
}

# --- NSEvent masks ---
NS_FLAGS_CHANGED_MASK = 1 << 12
NS_KEY_DOWN_MASK = 1 << 10

# --- Key codes ---
KEY_ESCAPE = 53

# --- Modifier flags ---
MODIFIER_FLAGS = {
    "alt_r": 1 << 19,   # NSAlternateKeyMask
    "alt_l": 1 << 19,
    "ctrl_r": 1 << 18,  # NSControlKeyMask
    "ctrl_l": 1 << 18,
    "shift_r": 1 << 17, # NSShiftKeyMask
    "shift_l": 1 << 17,
}

# --- NSPanel style ---
NS_NON_ACTIVATING_PANEL_MASK = 1 << 7
NS_WINDOW_CAN_JOIN_ALL_SPACES = 1 << 4

# --- Formatting levels ---
FORMAT_LEVELS = ["off", "on", "translate_ja_en", "translate_en_ja"]
FORMAT_LEVEL_LABELS = {
    "off": "Off",
    "on": "On",
    "translate_ja_en": "Translate (JA → EN)",
    "translate_en_ja": "Translate (EN → JA)",
}

# --- Hotkey display labels ---
HOTKEY_LABELS = {
    "alt_r": "Right Option",
    "alt_l": "Left Option",
    "ctrl_r": "Right Control",
    "ctrl_l": "Left Control",
    "shift_r": "Right Shift",
    "shift_l": "Left Shift",
}

# --- STT model sizes ---
STT_MODELS = ["tiny", "base", "small", "medium", "large-v3"]
