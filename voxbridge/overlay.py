"""macOS overlay window and menu bar status item."""

from AppKit import (
    NSBackingStoreBuffered,
    NSColor,
    NSFont,
    NSMakeRect,
    NSMenu,
    NSMenuItem,
    NSPanel,
    NSScreen,
    NSStatusBar,
    NSTextField,
    NSVariableStatusItemLength,
    NSWindowStyleMaskBorderless,
)
from Foundation import NSObject
import objc

# NSPanel style: borderless + non-activating (shows without stealing focus)
_PANEL_STYLE = NSWindowStyleMaskBorderless | (1 << 7)  # NSNonactivatingPanelMask


class Overlay(NSObject):
    """Small floating overlay window showing status text (bottom-right).

    Inherits NSObject so that NSTimer selectors work correctly.
    """

    @classmethod
    @objc.python_method
    def create(cls, config: dict) -> "Overlay":
        """Factory method (NSObject subclasses use alloc().init())."""
        obj = cls.alloc().init()
        obj._setup(config)
        return obj

    @objc.python_method
    def _setup(self, config: dict):
        self._enabled = config.get("enabled", True)
        if not self._enabled:
            return

        width = config.get("width", 260)
        height = config.get("height", 36)
        margin = config.get("margin", 20)
        opacity = config.get("opacity", 0.88)
        self._auto_hide_delay = config.get("auto_hide_delay", 2.0)

        # Position: bottom-right of main screen
        screen = NSScreen.mainScreen().visibleFrame()
        x = screen.origin.x + screen.size.width - width - margin
        y = screen.origin.y + margin

        # Create non-activating floating panel
        self._window = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(x, y, width, height),
            _PANEL_STYLE,
            NSBackingStoreBuffered,
            False,
        )
        self._window.setFloatingPanel_(True)
        self._window.setHidesOnDeactivate_(False)
        self._window.setAlphaValue_(opacity)
        self._window.setOpaque_(False)
        self._window.setBackgroundColor_(
            NSColor.colorWithRed_green_blue_alpha_(0.1, 0.1, 0.1, 0.92)
        )
        self._window.setHasShadow_(True)
        self._window.setIgnoresMouseEvents_(True)
        self._window.setCollectionBehavior_(
            1 << 4  # NSWindowCollectionBehaviorCanJoinAllSpaces
        )

        # Rounded corners
        content_view = self._window.contentView()
        content_view.setWantsLayer_(True)
        content_view.layer().setCornerRadius_(8)
        content_view.layer().setMasksToBounds_(True)

        # Status label
        self._label = NSTextField.alloc().initWithFrame_(
            NSMakeRect(12, 6, width - 24, height - 12)
        )
        self._label.setStringValue_("")
        self._label.setTextColor_(NSColor.whiteColor())
        self._label.setFont_(NSFont.monospacedSystemFontOfSize_weight_(12.5, 0.0))
        self._label.setDrawsBackground_(False)
        self._label.setBezeled_(False)
        self._label.setEditable_(False)
        self._label.setSelectable_(False)
        content_view.addSubview_(self._label)

        self._window.orderOut_(None)  # Start hidden

    @objc.python_method
    def show(self, text: str, color: str = "default", auto_hide: bool = False) -> None:
        """Show overlay with status text. Must be called on main thread."""
        if not self._enabled:
            return

        self._label.setStringValue_(text)

        # Change background color based on state
        colors = {
            "recording": (0.6, 0.1, 0.1, 0.92),
            "success": (0.1, 0.4, 0.1, 0.92),
            "warning": (0.6, 0.5, 0.0, 0.92),
            "error": (0.6, 0.2, 0.0, 0.92),
            "default": (0.1, 0.1, 0.1, 0.92),
        }
        r, g, b, a = colors.get(color, colors["default"])
        self._window.setBackgroundColor_(
            NSColor.colorWithRed_green_blue_alpha_(r, g, b, a)
        )

        self._window.orderFrontRegardless()

        # Cancel any pending auto-hide
        NSObject.cancelPreviousPerformRequestsWithTarget_selector_object_(
            self, "hideOverlay:", None
        )

        if auto_hide:
            self.performSelector_withObject_afterDelay_(
                "hideOverlay:", None, self._auto_hide_delay
            )

    @objc.python_method
    def hide(self) -> None:
        """Hide overlay. Must be called on main thread."""
        if not self._enabled:
            return
        self._window.orderOut_(None)

    def hideOverlay_(self, timer) -> None:
        """Timer callback to hide overlay."""
        self.hide()


class StatusBarItem(NSObject):
    """Menu bar status item for VoxBridge."""

    @classmethod
    @objc.python_method
    def create(cls) -> "StatusBarItem":
        obj = cls.alloc().init()
        obj._setup()
        return obj

    @objc.python_method
    def _setup(self):
        self._status_bar = NSStatusBar.systemStatusBar()
        self._item = self._status_bar.statusItemWithLength_(
            NSVariableStatusItemLength
        )
        # Set title via button API (modern macOS) and direct API (fallback)
        button = self._item.button()
        print(f"[StatusBar] button={button}, item={self._item}")
        if button:
            button.setTitle_("VB")
        self._item.setTitle_("VB")

        menu = NSMenu.alloc().init()

        title_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "VoxBridge v0.1.0", None, ""
        )
        title_item.setEnabled_(False)
        menu.addItem_(title_item)

        menu.addItem_(NSMenuItem.separatorItem())

        quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Quit", "terminate:", "q"
        )
        menu.addItem_(quit_item)

        self._item.setMenu_(menu)
        print(f"[StatusBar] Menu bar item created with title='VB'")

    @objc.python_method
    def set_title(self, title: str) -> None:
        self._item.setTitle_(title)
