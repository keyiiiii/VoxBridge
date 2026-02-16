"""Main VoxBridge application - orchestrates all components."""

import signal
import threading

import numpy as np
from AppKit import NSApplication, NSApplicationActivationPolicyAccessory, NSEvent
from ApplicationServices import AXIsProcessTrustedWithOptions
from Foundation import NSObject
from PyObjCTools import AppHelper
import objc

from .config import load_config
from .formatter import Formatter
from .injector import Injector
from .overlay import Overlay, StatusBarItem
from .recorder import Recorder
from .stt import STT

# macOS virtual key codes for modifier keys
_MODIFIER_KEY_CODES = {
    "alt_r": 61,
    "alt_l": 58,
    "ctrl_r": 62,
    "ctrl_l": 59,
    "shift_r": 60,
    "shift_l": 56,
}

# NSEvent masks
_NSFlagsChangedMask = 1 << 12

# Modifier flags
_MODIFIER_FLAGS = {
    "alt_r": 1 << 19,   # NSAlternateKeyMask
    "alt_l": 1 << 19,
    "ctrl_r": 1 << 18,  # NSControlKeyMask
    "ctrl_l": 1 << 18,
    "shift_r": 1 << 17, # NSShiftKeyMask
    "shift_l": 1 << 17,
}


class _AppDelegate(NSObject):
    """NSApplication delegate – creates UI after the app finishes launching."""

    @objc.python_method
    def setApp(self, voxbridge_app):
        self._voxbridge = voxbridge_app

    def applicationDidFinishLaunching_(self, notification):
        """Called by macOS after the app is fully launched."""
        self.performSelector_withObject_afterDelay_("createUI:", None, 0.3)

    def createUI_(self, _):
        """Create UI components (called after event loop is fully running)."""
        app = self._voxbridge
        app.overlay = Overlay.create(app.config["overlay"])
        app.status_bar = StatusBarItem.create()

        # Start hotkey listener now that event loop is running
        app._setup_hotkey()

        # Check accessibility permission (required for text injection)
        trusted = AXIsProcessTrustedWithOptions(
            {"AXTrustedCheckOptionPrompt": True}
        )
        if trusted:
            print("[VoxBridge] Accessibility: granted")
        else:
            print("[VoxBridge] Accessibility: NOT granted - text injection disabled")
            print("[VoxBridge] Please grant Accessibility permission in System Settings")

        # Background preload if requested
        if app._preload:
            app._start_preload()
        else:
            hotkey = app.config.get("hotkey", "alt_r")
            app.overlay.show(
                f"VoxBridge Ready ({hotkey})", color="success", auto_hide=True,
            )

        # Background Ollama check
        if app.config["formatter"]["enabled"]:
            threading.Thread(target=app._check_ollama, daemon=True).start()

        print("[VoxBridge] UI initialized.")


class VoxBridgeApp:
    """Push-to-talk voice input application for macOS."""

    def __init__(self, config_path: str | None = None, preload: bool = False):
        self.config = load_config(config_path)
        self._preload = preload

        # NSApplication setup – Accessory policy (no Dock icon, menu bar only).
        self._nsapp = NSApplication.sharedApplication()
        self._nsapp.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

        # Delegate handles UI creation after app finishes launching
        self._delegate = _AppDelegate.alloc().init()
        self._delegate.setApp(self)
        self._nsapp.setDelegate_(self._delegate)

        # Placeholders (created by delegate in applicationDidFinishLaunching_)
        self.overlay = None
        self.status_bar = None

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

    def _start_preload(self) -> None:
        """Start STT model preload in a background thread with status overlay."""
        cached = self.stt.is_model_cached()
        msg = "Loading STT model..." if cached else "Downloading STT model..."
        self._show_overlay(msg, color="default")
        print(f"[VoxBridge] {msg}")

        def _do_preload():
            try:
                self.stt.preload()
                hotkey = self.config.get("hotkey", "alt_r")
                AppHelper.callAfter(
                    lambda: self._show_overlay(
                        f"VoxBridge Ready ({hotkey})",
                        color="success",
                        auto_hide=True,
                    )
                )
                print("[VoxBridge] STT model preloaded.")
            except Exception as e:
                print(f"[VoxBridge] Preload error: {e}")
                AppHelper.callAfter(
                    lambda: self._show_overlay(
                        f"Preload error: {str(e)[:40]}",
                        color="error",
                        auto_hide=True,
                    )
                )

        threading.Thread(target=_do_preload, daemon=True).start()

    def _check_ollama(self) -> None:
        """Check Ollama availability in background; warn if unreachable."""
        import time
        # Delay to avoid conflicting with preload overlay messages
        time.sleep(3)
        if not self.formatter.is_available():
            print("[VoxBridge] Ollama is not running - formatting will be disabled")
            AppHelper.callAfter(
                lambda: self._show_overlay(
                    "Ollama not running (formatting disabled)",
                    color="warning",
                    auto_hide=True,
                )
            )

    def _setup_hotkey(self) -> None:
        """Configure the global push-to-talk hotkey using NSEvent monitors."""
        hotkey_name = self.config.get("hotkey", "alt_r")
        self._hotkey_code = _MODIFIER_KEY_CODES.get(hotkey_name)
        self._hotkey_flag = _MODIFIER_FLAGS.get(hotkey_name, 0)

        if self._hotkey_code is not None:
            # Modifier key (Option, Ctrl, Shift) – monitor flag changes
            NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
                _NSFlagsChangedMask, self._on_flags_changed,
            )
            NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
                _NSFlagsChangedMask, self._on_flags_changed_local,
            )
            print(f"[VoxBridge] Hotkey: {hotkey_name} (push-to-talk, NSEvent monitor)")
        else:
            print(f"[VoxBridge] WARNING: Unsupported hotkey '{hotkey_name}'")

    def _on_flags_changed(self, event) -> None:
        """Global monitor callback for modifier key changes."""
        if event.keyCode() == self._hotkey_code:
            if event.modifierFlags() & self._hotkey_flag:
                self._on_press()
            else:
                self._on_release()

    def _on_flags_changed_local(self, event):
        """Local monitor callback (when VoxBridge window is focused)."""
        self._on_flags_changed(event)
        return event  # Local monitors must return the event

    def _show_overlay(self, text, color="default", auto_hide=False):
        """Show overlay if available (safe to call before UI init)."""
        if self.overlay:
            self.overlay.show(text, color=color, auto_hide=auto_hide)

    def _on_press(self) -> None:
        """Hotkey press handler - start recording."""
        if not self._recording and not self._processing:
            self._recording = True
            self._show_overlay("Recording...", color="recording")
            self.recorder.start()

    def _on_release(self) -> None:
        """Hotkey release handler - stop recording and process."""
        if self._recording:
            self._recording = False
            audio = self.recorder.stop()

            if audio is not None and len(audio) > 1600:  # > 0.1s of audio
                self._processing = True
                thread = threading.Thread(
                    target=self._process, args=(audio,), daemon=True
                )
                thread.start()
            else:
                self._show_overlay("Too short", color="default", auto_hide=True)

    def _process(self, audio: np.ndarray) -> None:
        """Background: transcribe, format, inject."""
        try:
            # Step 1: STT
            if self._stt is None:
                cached = STT(self.config["stt"]).is_model_cached()
                stt_msg = "Loading STT model..." if cached else "Downloading STT model..."
            else:
                stt_msg = "Transcribing..."
            AppHelper.callAfter(
                lambda: self._show_overlay(stt_msg, color="default")
            )
            text = self.stt.transcribe(audio, language=self.config["language"])
            print(f"[STT] Raw: {text}")

            if not text or not text.strip():
                AppHelper.callAfter(
                    lambda: self._show_overlay(
                        "No speech detected", color="default", auto_hide=True
                    )
                )
                return

            # Step 2: Format (optional)
            if self.config["formatter"]["enabled"]:
                AppHelper.callAfter(
                    lambda: self._show_overlay("Formatting...", color="default")
                )
                formatted = self.formatter.format(text)
                print(f"[Formatter] Result: {formatted}")
            else:
                formatted = text

            # Step 3: Inject into active app
            AppHelper.callAfter(
                lambda: self._show_overlay("Typing...", color="default")
            )
            injected = self.injector.inject(formatted)

            if injected:
                AppHelper.callAfter(
                    lambda: self._show_overlay("Done", color="success", auto_hide=True)
                )
            else:
                AppHelper.callAfter(
                    lambda: self._show_overlay(
                        "Copied (要 Accessibility 許可)",
                        color="warning", auto_hide=True,
                    )
                )

        except Exception as e:
            msg = str(e)[:60]
            print(f"[VoxBridge] Error: {e}")
            AppHelper.callAfter(
                lambda: self._show_overlay(
                    f"Error: {msg}", color="error", auto_hide=True
                )
            )
        finally:
            self._processing = False
            print("[VoxBridge] Ready for next input.")

    def run(self) -> None:
        """Start the application (blocks on main thread)."""
        print("[VoxBridge] Starting...")
        print(f"[VoxBridge] STT model: {self.config['stt']['model']}")
        print(f"[VoxBridge] LLM model: {self.config['formatter']['model']}")
        print(f"[VoxBridge] Language: {self.config['language']}")
        print("[VoxBridge] Ready. Hold the hotkey to record, release to process.")

        # Handle Ctrl+C gracefully
        signal.signal(signal.SIGINT, lambda *_: AppHelper.stopEventLoop())

        # runEventLoop calls finishLaunching → delegate creates UI
        AppHelper.runEventLoop()
