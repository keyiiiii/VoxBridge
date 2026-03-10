"""Main VoxBridge application - orchestrates all components."""

import hashlib
import os
import signal
import subprocess
import threading
import time
import webbrowser

import numpy as np
from AppKit import NSApplication, NSApplicationActivationPolicyAccessory, NSEvent, NSBundle
from ApplicationServices import AXIsProcessTrustedWithOptions
from Foundation import NSObject
from PyObjCTools import AppHelper
import objc

from .config import load_config
from .constants import (
    COUNTDOWN_INTERVAL_SEC,
    COUNTDOWN_START_SEC,
    FORMAT_LEVEL_LABELS,
    HOTKEY_LABELS,
    KEY_ESCAPE,
    MIN_AUDIO_SAMPLES,
    MIN_PREVIEW_SAMPLES,
    MODIFIER_FLAGS,
    MODIFIER_KEY_CODES,
    NS_FLAGS_CHANGED_MASK,
    NS_KEY_DOWN_MASK,
    PREVIEW_INTERVAL_SEC,
)
from .formatter import Formatter
from .injector import Injector
from .overlay import Overlay, StatusBarItem
from . import preferences as prefs
from .recorder import Recorder
from .stt import STT


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
        # Ensure user prompt file exists (copy bundled template on first launch)
        app.formatter.ensure_user_prompt(prefs.USER_PROMPT_FILE)
        hotkey = prefs.get_hotkey(app.config.get("hotkey", "alt_r"))
        model = prefs.get_model(app.config["stt"].get("model", "small"))
        format_level = prefs.get_format_level(
            app.config["formatter"].get("enabled", True)
        )
        app.status_bar = StatusBarItem.create(
            current_hotkey=hotkey,
            current_model=model,
            current_format_level=format_level,
            launch_at_login=prefs.is_launch_at_login(),
            on_hotkey_change=app._on_hotkey_change,
            on_model_change=app._on_model_change,
            on_format_level_change=app._on_format_level_change,
            on_launch_at_login_change=app._set_launch_at_login,
            on_install_ollama=app._on_install_ollama,
            on_download_model=app._on_download_model,
            on_edit_prompt=app._on_edit_prompt,
        )

        # Start hotkey listener now that event loop is running
        app._setup_hotkey()

        # Reset stale accessibility permission if app binary changed (e.g. update)
        app._reset_accessibility_if_needed()

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
            app.overlay.show(
                f"VoxBridge Ready ({hotkey})", color="success", auto_hide=True,
            )

        # Background Ollama check (always run to update menu items)
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
            on_max_reached=self._on_max_duration_reached,
        )
        self.injector = Injector(self.config["injector"])

        # Lazy-loaded (heavy resources)
        self._stt: STT | None = None
        self._formatter: Formatter | None = None

        # State
        self._recording = False
        self._processing = False
        self._live_preview_timer: threading.Timer | None = None
        self._countdown_timer: threading.Timer | None = None
        self._last_preview_text = ""
        self._recording_start_time: float = 0.0

    @property
    def stt(self) -> STT:
        if self._stt is None:
            stt_config = dict(self.config["stt"])
            stt_config["model"] = prefs.get_model(
                self.config["stt"].get("model", "small")
            )
            self._stt = STT(stt_config)
        return self._stt

    @property
    def formatter(self) -> Formatter:
        if self._formatter is None:
            self._formatter = Formatter(self.config["formatter"])
        return self._formatter

    # --- Accessibility ---

    def _reset_accessibility_if_needed(self) -> None:
        """Reset accessibility permission if the app binary has changed.

        macOS ties accessibility permissions to the app's code signature.
        With ad-hoc signing, each build gets a new signature, so stale
        permissions from a previous version won't work. This detects
        binary changes and resets the TCC entry so macOS prompts again.
        """
        _BUNDLE_ID = "com.voxbridge.app"
        support_dir = os.path.join(
            os.path.expanduser("~"), "Library", "Application Support", "VoxBridge"
        )
        sig_file = os.path.join(support_dir, "last_signature")

        # Compute hash of the current executable
        # __file__ = .app/Contents/Resources/voxbridge/app.py
        # executable = .app/Contents/MacOS/VoxBridge
        contents_dir = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        exe_path = os.path.join(contents_dir, "MacOS", "VoxBridge")
        if not os.path.isfile(exe_path):
            # Running as CLI (python -m voxbridge), not .app — skip
            return

        with open(exe_path, "rb") as f:
            current_hash = hashlib.sha256(f.read()).hexdigest()

        # Compare with stored hash
        previous_hash = None
        if os.path.isfile(sig_file):
            with open(sig_file, "r") as f:
                previous_hash = f.read().strip()

        if previous_hash != current_hash:
            if previous_hash is not None:
                print("[VoxBridge] Binary changed — resetting accessibility permission")
                subprocess.run(
                    ["tccutil", "reset", "Accessibility", _BUNDLE_ID],
                    capture_output=True,
                )
            # Store current hash
            os.makedirs(support_dir, exist_ok=True)
            with open(sig_file, "w") as f:
                f.write(current_hash)

    # --- Preload & Ollama ---

    def _start_preload(self) -> None:
        """Start STT model preload in a background thread with status overlay."""
        cached = self.stt.is_model_cached()
        msg = "Loading STT model..." if cached else "Downloading STT model..."
        self._show_overlay(msg, color="default")
        print(f"[VoxBridge] {msg}")

        def _do_preload():
            try:
                self.stt.preload()
                hotkey = prefs.get_hotkey(self.config.get("hotkey", "alt_r"))
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
        """Check Ollama and model availability; update menu items."""
        # Delay to avoid conflicting with preload overlay messages
        time.sleep(3)
        ollama_ok, model_ok = self.formatter.check_status()

        if self.status_bar:
            AppHelper.callAfter(
                lambda: self.status_bar.set_ollama_available(ollama_ok)
            )
            AppHelper.callAfter(
                lambda: self.status_bar.set_model_available(model_ok)
            )

        if not ollama_ok:
            print("[VoxBridge] Ollama is not running")
            AppHelper.callAfter(
                lambda: self._show_overlay(
                    "Ollama not found",
                    color="warning",
                    auto_hide=True,
                )
            )
        elif not model_ok:
            model = self.formatter.model
            print(f"[VoxBridge] Ollama running but model '{model}' not found")
            AppHelper.callAfter(
                lambda: self._show_overlay(
                    f"Model not found: {model}",
                    color="warning",
                    auto_hide=True,
                )
            )
        else:
            print("[VoxBridge] Ollama and model ready")

    # --- Menu callbacks ---

    def _on_model_change(self, model_name: str) -> None:
        """Called when user selects a new STT model from the menu."""
        prefs.set_model(model_name)
        self._stt = None  # Reset so next transcription uses the new model
        self._show_overlay(f"STT Model: {model_name}", color="success", auto_hide=True)
        print(f"[VoxBridge] STT model changed to: {model_name}")

    def _on_format_level_change(self, level: str) -> None:
        """Called when user selects a new formatting level from the menu."""
        prefs.set_format_level(level)
        label = FORMAT_LEVEL_LABELS.get(level, level)
        self._show_overlay(
            f"Formatting: {label}", color="success", auto_hide=True
        )
        print(f"[VoxBridge] Format level changed to: {level}")

    def _on_install_ollama(self) -> None:
        """Open the Ollama download page in the default browser."""
        webbrowser.open("https://ollama.com/download")

    def _on_download_model(self) -> None:
        """Download the configured Ollama model in the background."""
        if self.status_bar:
            AppHelper.callAfter(
                lambda: self.status_bar.set_download_in_progress(True)
            )
        self._show_overlay("Downloading model...", color="default")

        def on_progress(line):
            AppHelper.callAfter(
                lambda l=line: self._show_overlay(l[:40], color="default")
            )

        def on_complete():
            AppHelper.callAfter(lambda: self._show_overlay(
                "Model downloaded", color="success", auto_hide=True
            ))
            if self.status_bar:
                AppHelper.callAfter(lambda: self.status_bar.set_download_in_progress(False))
                AppHelper.callAfter(lambda: self.status_bar.set_model_available(True))
            print("[VoxBridge] Model download complete.")

        def on_error(err):
            AppHelper.callAfter(lambda: self._show_overlay(
                f"Download error: {err[:40]}", color="error", auto_hide=True
            ))
            if self.status_bar:
                AppHelper.callAfter(lambda: self.status_bar.set_download_in_progress(False))
            print(f"[VoxBridge] Model download error: {err}")

        self.formatter.pull_model(
            on_progress=on_progress,
            on_complete=on_complete,
            on_error=on_error,
        )

    def _on_edit_prompt(self) -> None:
        """Open user's prompt file in the default text editor."""
        path = prefs.USER_PROMPT_FILE
        # ensure_user_prompt already called at startup, but just in case
        self.formatter.ensure_user_prompt(path)
        subprocess.Popen(["open", "-t", path])

    def _set_launch_at_login(self, enabled: bool) -> None:
        """Enable or disable launch-at-login via macOS Login Items."""
        bundle_path = NSBundle.mainBundle().bundlePath()
        if not bundle_path.endswith(".app"):
            self._show_overlay("Login item: .app only", color="warning", auto_hide=True)
            return

        if enabled:
            subprocess.run([
                "osascript", "-e",
                f'tell application "System Events" to make login item at end '
                f'with properties {{path:"{bundle_path}", hidden:false}}'
            ], capture_output=True)
            prefs.set_launch_at_login_flag(True)
            self._show_overlay("Launch at login: ON", color="success", auto_hide=True)
            print(f"[VoxBridge] Launch at login enabled: {bundle_path}")
        else:
            app_name = os.path.basename(bundle_path).replace(".app", "")
            subprocess.run([
                "osascript", "-e",
                f'tell application "System Events" to delete login item "{app_name}"'
            ], capture_output=True)
            prefs.set_launch_at_login_flag(False)
            self._show_overlay("Launch at login: OFF", color="success", auto_hide=True)
            print("[VoxBridge] Launch at login disabled")

    def _on_hotkey_change(self, key: str) -> None:
        """Called when user selects a new hotkey from the menu."""
        self._hotkey_code = MODIFIER_KEY_CODES.get(key)
        self._hotkey_flag = MODIFIER_FLAGS.get(key, 0)
        prefs.set_hotkey(key)
        label = HOTKEY_LABELS.get(key, key)
        self._show_overlay(f"Hotkey: {label}", color="success", auto_hide=True)
        print(f"[VoxBridge] Hotkey changed to: {key}")

    # --- Hotkey ---

    def _setup_hotkey(self) -> None:
        """Configure the global push-to-talk hotkey using NSEvent monitors."""
        hotkey_name = prefs.get_hotkey(self.config.get("hotkey", "alt_r"))
        self._hotkey_code = MODIFIER_KEY_CODES.get(hotkey_name)
        self._hotkey_flag = MODIFIER_FLAGS.get(hotkey_name, 0)

        if self._hotkey_code is not None:
            NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
                NS_FLAGS_CHANGED_MASK, self._on_flags_changed,
            )
            NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
                NS_FLAGS_CHANGED_MASK, self._on_flags_changed_local,
            )
            NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
                NS_KEY_DOWN_MASK, self._on_key_down,
            )
            NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
                NS_KEY_DOWN_MASK, self._on_key_down_local,
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
        return event

    def _on_key_down(self, event) -> None:
        """Global monitor for key-down events (Esc to cancel)."""
        if event.keyCode() == KEY_ESCAPE and self._recording:
            self._cancel_recording()

    def _on_key_down_local(self, event):
        """Local monitor for key-down events."""
        self._on_key_down(event)
        return event

    # --- Recording ---

    def _cancel_recording(self) -> None:
        """Cancel the current recording and discard audio."""
        self._recording = False
        self._stop_live_preview()
        self.recorder.stop()
        self._show_overlay("Cancelled", color="default", auto_hide=True)
        print("[VoxBridge] Recording cancelled.")

    def _show_overlay(self, text, color="default", auto_hide=False):
        """Show overlay if available (safe to call before UI init)."""
        if self.overlay:
            self.overlay.show(text, color=color, auto_hide=auto_hide)

    def _on_max_duration_reached(self, audio) -> None:
        """Called when recording reaches max duration (audio already stopped)."""
        self._recording = False
        self._stop_live_preview()
        max_sec = self.config["recording"]["max_duration"]
        print(f"[VoxBridge] Max recording duration reached ({max_sec}s)")

        if audio is not None and len(audio) > MIN_AUDIO_SAMPLES:
            self._processing = True
            AppHelper.callAfter(
                lambda: self._show_overlay(
                    f"⏱ Max {max_sec}s reached — processing...", color="warning"
                )
            )
            threading.Thread(
                target=self._process, args=(audio,), daemon=True
            ).start()

    def _on_press(self) -> None:
        """Hotkey press handler - start recording."""
        if not self._recording and not self._processing:
            self._recording = True
            self._show_overlay("Recording...", color="recording")
            self.recorder.start()
            if self._stt is not None:
                self._start_live_preview()

    def _on_release(self) -> None:
        """Hotkey release handler - stop recording and process."""
        if self._recording:
            self._recording = False
            self._stop_live_preview()
            audio = self.recorder.stop()

            if audio is not None and len(audio) > MIN_AUDIO_SAMPLES:
                self._processing = True
                threading.Thread(
                    target=self._process, args=(audio,), daemon=True
                ).start()
            else:
                self._show_overlay("Too short", color="default", auto_hide=True)

    # --- Live preview ---

    def _get_remaining_time(self) -> float:
        """Return remaining recording time in seconds."""
        max_duration = self.config["recording"]["max_duration"]
        return max_duration - (time.time() - self._recording_start_time)

    def _start_live_preview(self) -> None:
        """Start periodic live transcription preview during recording."""
        self._last_preview_text = ""
        self._recording_start_time = time.time()

        self._schedule_preview_tick()
        self._schedule_countdown()

    def _schedule_preview_tick(self) -> None:
        """Schedule the next live preview STT tick."""
        self._live_preview_timer = threading.Timer(
            PREVIEW_INTERVAL_SEC, self._preview_tick
        )
        self._live_preview_timer.daemon = True
        self._live_preview_timer.start()

    def _preview_tick(self) -> None:
        """Run one live preview STT cycle."""
        if not self._recording:
            return
        snapshot = self.recorder.get_audio_snapshot()
        if snapshot is not None and len(snapshot) > MIN_PREVIEW_SAMPLES:
            try:
                text = self.stt.transcribe(
                    snapshot, language=self.config.get("language")
                )
                if text and text.strip() and text != self._last_preview_text:
                    self._last_preview_text = text
                    remaining = self._get_remaining_time()
                    if remaining <= COUNTDOWN_START_SEC:
                        suffix = f"\n⏱ {int(remaining)}s remaining"
                        color = "warning"
                    else:
                        suffix = ""
                        color = "recording"
                    AppHelper.callAfter(
                        lambda d=text, s=suffix, c=color: self._show_overlay(
                            f"🎤 {d}{s}", color=c
                        )
                    )
            except Exception:
                pass
        if self._recording:
            self._schedule_preview_tick()

    def _schedule_countdown(self) -> None:
        """Schedule the countdown timer for the last N seconds."""
        max_duration = self.config["recording"]["max_duration"]
        wait = max(0.0, max_duration - COUNTDOWN_START_SEC)
        self._countdown_timer = threading.Timer(wait, self._countdown_tick)
        self._countdown_timer.daemon = True
        self._countdown_timer.start()

    def _countdown_tick(self) -> None:
        """Show countdown in the last seconds of recording."""
        if not self._recording:
            return
        remaining = self._get_remaining_time()
        if remaining <= COUNTDOWN_START_SEC:
            display_text = self._last_preview_text or "Recording..."
            AppHelper.callAfter(
                lambda r=int(remaining), d=display_text: self._show_overlay(
                    f"🎤 {d}\n⏱ {r}s remaining", color="warning"
                )
            )
        if remaining > 0 and self._recording:
            self._countdown_timer = threading.Timer(
                COUNTDOWN_INTERVAL_SEC, self._countdown_tick
            )
            self._countdown_timer.daemon = True
            self._countdown_timer.start()

    def _stop_live_preview(self) -> None:
        """Stop live transcription preview and countdown."""
        if self._live_preview_timer:
            self._live_preview_timer.cancel()
            self._live_preview_timer = None
        if self._countdown_timer:
            self._countdown_timer.cancel()
            self._countdown_timer = None
        self._last_preview_text = ""

    # --- Processing pipeline ---

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
            language = self.config.get("language")
            text = self.stt.transcribe(audio, language=language)
            print(f"[STT] Raw: {text}")

            if not text or not text.strip():
                AppHelper.callAfter(
                    lambda: self._show_overlay(
                        "No speech detected", color="default", auto_hide=True
                    )
                )
                return

            # Step 2: Format / Translate (optional)
            format_level = prefs.get_format_level(
                self.config["formatter"].get("enabled", True)
            )
            if format_level == "on":
                AppHelper.callAfter(
                    lambda: self._show_overlay("Formatting...", color="default")
                )
                formatted = self.formatter.format(text)
                print(f"[Formatter] Result: {formatted}")
            elif format_level.startswith("translate_"):
                direction = "JA→EN" if format_level == "translate_ja_en" else "EN→JA"
                AppHelper.callAfter(
                    lambda d=direction: self._show_overlay(f"Translating ({d})...", color="default")
                )
                formatted = self.formatter.format(text, mode=format_level)
                print(f"[Translator] {direction}: {formatted}")
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

    # --- Entry point ---

    def run(self) -> None:
        """Start the application (blocks on main thread)."""
        print("[VoxBridge] Starting...")
        print(f"[VoxBridge] STT model: {self.config['stt']['model']}")
        print(f"[VoxBridge] LLM model: {self.config['formatter']['model']}")
        lang = self.config.get("language") or "auto-detect"
        print(f"[VoxBridge] Language: {lang}")
        print("[VoxBridge] Ready. Hold the hotkey to record, release to process.")

        # Handle Ctrl+C gracefully
        signal.signal(signal.SIGINT, lambda *_: AppHelper.stopEventLoop())

        # runEventLoop calls finishLaunching → delegate creates UI
        AppHelper.runEventLoop()
