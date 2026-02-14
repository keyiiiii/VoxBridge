"""Text injection into the active application via clipboard + CGEvent."""

import time

from AppKit import NSPasteboard, NSPasteboardTypeString, NSWorkspace
from ApplicationServices import AXIsProcessTrusted
from Quartz import (
    CGEventCreateKeyboardEvent,
    CGEventPost,
    CGEventSetFlags,
    kCGEventFlagMaskCommand,
    kCGHIDEventTap,
)


# macOS virtual key codes
_KEY_V = 0x09       # 'v'
_KEY_RETURN = 0x24  # Return/Enter


class Injector:
    """Injects text into the active application."""

    def __init__(self, config: dict):
        self.send_enter_for = config.get(
            "send_enter_for", ["Terminal", "iTerm2"]
        )
        self.enter_delay = config.get("enter_delay", 0.15)
        self.clipboard_restore_delay = config.get("clipboard_restore_delay", 0.3)

    def inject(self, text: str) -> bool:
        """Inject text into the active application via paste.

        Returns True if text was injected (Cmd+V), False if only copied
        to clipboard (Accessibility permission missing).
        """
        trusted = AXIsProcessTrusted()
        active = self.get_active_app_name()
        print(f"[Injector] AXIsProcessTrusted={trusted}, target={active}")

        pb = NSPasteboard.generalPasteboard()

        # Save existing clipboard content
        old_content = pb.stringForType_(NSPasteboardTypeString)

        # Set new text
        pb.clearContents()
        pb.setString_forType_(text, NSPasteboardTypeString)
        time.sleep(0.05)

        # Verify clipboard was set
        verify = pb.stringForType_(NSPasteboardTypeString)
        print(f"[Injector] Clipboard set: {verify is not None}")

        if not trusted:
            # No Accessibility permission – leave text in clipboard for manual paste
            print("[Injector] Skipping CGEventPost (no Accessibility permission)")
            return False

        # Paste via Cmd+V
        _send_keystroke(_KEY_V, flags=kCGEventFlagMaskCommand)
        time.sleep(0.05)

        # Send Enter if active app is a terminal
        if self._should_send_enter():
            time.sleep(self.enter_delay)
            _send_keystroke(_KEY_RETURN)

        # Restore previous clipboard
        time.sleep(self.clipboard_restore_delay)
        pb.clearContents()
        if old_content:
            pb.setString_forType_(old_content, NSPasteboardTypeString)

        return True

    def _should_send_enter(self) -> bool:
        """Check if the active application is a terminal that should receive Enter."""
        try:
            active_app = NSWorkspace.sharedWorkspace().frontmostApplication()
            app_name = active_app.localizedName()
            return app_name in self.send_enter_for
        except Exception:
            return False

    @staticmethod
    def get_active_app_name() -> str:
        """Return the name of the frontmost application."""
        try:
            active_app = NSWorkspace.sharedWorkspace().frontmostApplication()
            return active_app.localizedName() or ""
        except Exception:
            return ""


def _send_keystroke(key_code: int, flags: int = 0) -> None:
    """Send a single keystroke via CGEvent."""
    event_down = CGEventCreateKeyboardEvent(None, key_code, True)
    event_up = CGEventCreateKeyboardEvent(None, key_code, False)

    if flags:
        CGEventSetFlags(event_down, flags)
        CGEventSetFlags(event_up, flags)

    CGEventPost(kCGHIDEventTap, event_down)
    CGEventPost(kCGHIDEventTap, event_up)
