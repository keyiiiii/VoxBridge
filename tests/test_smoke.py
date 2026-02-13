"""Smoke tests for VoxBridge components.

Run: python -m tests.test_smoke
Each test can be run independently.
"""

import sys
import time
import numpy as np


def test_config():
    """Test: configuration loading."""
    print("=== Config ===")
    from voxbridge.config import load_config

    config = load_config()
    assert config["hotkey"] == "alt_r"
    assert config["language"] == "ja"
    assert config["stt"]["model"] in ("tiny", "base", "small", "medium", "large-v3")
    print(f"  Hotkey: {config['hotkey']}")
    print(f"  STT model: {config['stt']['model']}")
    print(f"  LLM model: {config['formatter']['model']}")
    print("  OK")


def test_recorder():
    """Test: record 2 seconds of audio from microphone."""
    print("\n=== Recorder ===")
    from voxbridge.recorder import Recorder

    rec = Recorder(sample_rate=16000, max_duration=60)

    print("  Recording 2 seconds... (speak now)")
    rec.start()
    time.sleep(2)
    audio = rec.stop()

    assert audio is not None, "No audio captured"
    assert audio.dtype == np.float32
    duration = len(audio) / 16000
    print(f"  Captured: {len(audio)} samples ({duration:.1f}s)")
    print(f"  Peak amplitude: {np.abs(audio).max():.4f}")
    print("  OK")
    return audio


def test_stt(audio: np.ndarray | None = None):
    """Test: transcribe audio with faster-whisper."""
    print("\n=== STT ===")
    from voxbridge.stt import STT

    if audio is None:
        # Generate 1s of silence as fallback
        audio = np.zeros(16000, dtype=np.float32)

    stt = STT({"model": "small", "device": "cpu", "compute_type": "int8"})
    print("  Loading model and transcribing...")
    t0 = time.time()
    text = stt.transcribe(audio, language="ja")
    elapsed = time.time() - t0
    print(f"  Result: '{text}'")
    print(f"  Time: {elapsed:.2f}s")
    print("  OK")
    return text


def test_formatter(text: str | None = None):
    """Test: format text with Ollama."""
    print("\n=== Formatter ===")
    from voxbridge.formatter import Formatter
    from voxbridge.config import load_config

    config = load_config()
    formatter = Formatter(config["formatter"])

    if not text:
        text = "えーとですね、あの、Pythonで関数を作りたいんですけど、まあ、引数が二つあって、足し算するやつです"

    print(f"  Input:  '{text}'")
    t0 = time.time()
    result = formatter.format(text)
    elapsed = time.time() - t0
    print(f"  Output: '{result}'")
    print(f"  Time: {elapsed:.2f}s")
    print("  OK")
    return result


def test_injector():
    """Test: check active app detection (no actual injection)."""
    print("\n=== Injector ===")
    from voxbridge.injector import Injector

    injector = Injector({"send_enter_for": ["Terminal", "iTerm2"]})
    app_name = injector.get_active_app_name()
    should_enter = injector._should_send_enter()
    print(f"  Active app: '{app_name}'")
    print(f"  Would send Enter: {should_enter}")
    print("  OK (no text injected)")


def test_full_pipeline():
    """Test: full pipeline (record → STT → format → display, no injection)."""
    print("\n=== Full Pipeline (no injection) ===")
    audio = test_recorder()
    text = test_stt(audio)
    if text:
        formatted = test_formatter(text)
        print(f"\n  Final output: '{formatted}'")
    else:
        print("\n  No speech detected - skipping formatter")
    print("  Pipeline OK")


if __name__ == "__main__":
    tests = {
        "config": test_config,
        "recorder": test_recorder,
        "stt": test_stt,
        "formatter": test_formatter,
        "injector": test_injector,
        "full": test_full_pipeline,
    }

    if len(sys.argv) > 1:
        name = sys.argv[1]
        if name in tests:
            tests[name]()
        else:
            print(f"Unknown test: {name}")
            print(f"Available: {', '.join(tests.keys())}")
            sys.exit(1)
    else:
        print("VoxBridge Smoke Tests")
        print("=" * 40)
        test_config()
        test_injector()
        print("\nTo run full pipeline: python -m tests.test_smoke full")
        print("To run specific test: python -m tests.test_smoke <name>")
        print(f"Available tests: {', '.join(tests.keys())}")
