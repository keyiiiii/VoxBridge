"""Main VoxBridge application - orchestrates all components."""

import signal
import threading

import numpy as np
from AppKit import NSApplication, NSApplicationActivationPolicyAccessory
from pynput import keyboard
from PyObjCTools import AppHelper

from .config import load_config
from .formatter import Formatter
from .injector import Injector
from .overlay import Overlay, StatusBarItem
from .recorder import Recorder
from .stt import STT


class VoxBridgeApp:
    """Push-to-talk voice input application for macOS."""

    def __init__(self, config_path: str | None = None):
        self.config = load_config(config_path)

        # NSApplication setup (accessory = no dock icon)
        self._nsapp = NSApplication.sharedApplication()
        self._nsapp.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

        # UI components (main thread)
        self.overlay = Overlay.create(self.config["overlay"])
        self.status_bar = StatusBarItem()

        # Core components
        self.recorder = Recorder(
            sample_rate=self.config["recording"]["sample_rate"],
            max_duration=self.config["recording"]["max_duration"],
        )
        self.injector = Injector(self.config["injector"])

        # Lazy-loaded (heavy resources)
        self._stt: STT | None = None
        self._formatter: Formatter | None = None

        # State
        self._recording = False
        self._processing = False

        # Hotkey listener
        self._setup_hotkey()

    @property
    def stt(self) -> STT:
        if self._stt is None:
            self._stt = STT(self.config["stt"])
        return self._stt

    @property
    def formatter(self) -> Formatter:
        if self._formatter is None:
            self._formatter = Formatter(self.config["formatter"])
        return self._formatter

    def _setup_hotkey(self) -> None:
        """Configure the global push-to-talk hotkey."""
        hotkey_name = self.config.get("hotkey", "alt_r")
        try:
            self._hotkey = getattr(keyboard.Key, hotkey_name)
        except AttributeError:
            self._hotkey = keyboard.KeyCode.from_char(hotkey_name)

        print(f"[VoxBridge] Hotkey: {hotkey_name} (push-to-talk)")

        self._listener = keyboard.Listener(
            on_press=self._on_press,
            on_release=self._on_release,
        )
        self._listener.daemon = True
        self._listener.start()

    def _on_press(self, key) -> None:
        """Hotkey press handler - start recording."""
        if key == self._hotkey and not self._recording and not self._processing:
            self._recording = True
            AppHelper.callAfter(
                lambda: self.overlay.show("Recording...", color="recording")
            )
            self.recorder.start()

    def _on_release(self, key) -> None:
        """Hotkey release handler - stop recording and process."""
        if key == self._hotkey and self._recording:
            self._recording = False
            audio = self.recorder.stop()

            if audio is not None and len(audio) > 1600:  # > 0.1s of audio
                self._processing = True
                thread = threading.Thread(
                    target=self._process, args=(audio,), daemon=True
                )
                thread.start()
            else:
                AppHelper.callAfter(
                    lambda: self.overlay.show(
                        "Too short", color="default", auto_hide=True
                    )
                )

    def _process(self, audio: np.ndarray) -> None:
        """Background: transcribe, format, inject."""
        try:
            # Step 1: STT
            AppHelper.callAfter(
                lambda: self.overlay.show("Transcribing...", color="default")
            )
            text = self.stt.transcribe(audio, language=self.config["language"])
            print(f"[STT] Raw: {text}")

            if not text or not text.strip():
                AppHelper.callAfter(
                    lambda: self.overlay.show(
                        "No speech detected", color="default", auto_hide=True
                    )
                )
                return

            # Step 2: Format (optional)
            if self.config["formatter"]["enabled"]:
                AppHelper.callAfter(
                    lambda: self.overlay.show("Formatting...", color="default")
                )
                formatted = self.formatter.format(text)
                print(f"[Formatter] Result: {formatted}")
            else:
                formatted = text

            # Step 3: Inject into active app
            AppHelper.callAfter(
                lambda: self.overlay.show("Typing...", color="default")
            )
            self.injector.inject(formatted)

            AppHelper.callAfter(
                lambda: self.overlay.show("Done", color="success", auto_hide=True)
            )

        except Exception as e:
            msg = str(e)[:60]
            print(f"[VoxBridge] Error: {e}")
            AppHelper.callAfter(
                lambda: self.overlay.show(
                    f"Error: {msg}", color="error", auto_hide=True
                )
            )
        finally:
            self._processing = False

    def run(self) -> None:
        """Start the application (blocks on main thread)."""
        hotkey = self.config.get("hotkey", "alt_r")
        print("[VoxBridge] Starting...")
        print(f"[VoxBridge] STT model: {self.config['stt']['model']}")
        print(f"[VoxBridge] LLM model: {self.config['formatter']['model']}")
        print(f"[VoxBridge] Language: {self.config['language']}")
        print("[VoxBridge] Ready. Hold the hotkey to record, release to process.")

        # Show startup notification in overlay
        self.overlay.show(f"VoxBridge Ready ({hotkey})", color="success", auto_hide=True)

        # Handle Ctrl+C gracefully
        signal.signal(signal.SIGINT, lambda *_: AppHelper.stopEventLoop())

        AppHelper.runEventLoop()
