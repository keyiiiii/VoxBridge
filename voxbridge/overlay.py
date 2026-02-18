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


# Display labels for hotkey options
_HOTKEY_LABELS = {
    "alt_r": "Right Option",
    "alt_l": "Left Option",
    "ctrl_r": "Right Control",
    "ctrl_l": "Left Control",
    "shift_r": "Right Shift",
    "shift_l": "Left Shift",
}


# Available STT model sizes
_STT_MODELS = ["tiny", "base", "small", "medium", "large-v3"]

# Formatting level options
_FORMAT_LEVELS = ["off", "on"]
_FORMAT_LEVEL_LABELS = {
    "off": "Off",
    "on": "On",
}


class StatusBarItem(NSObject):
    """Menu bar status item for VoxBridge."""

    @classmethod
    @objc.python_method
    def create(cls, current_hotkey: str = "alt_r",
               current_model: str = "small",
               current_format_level: str = "on",
               launch_at_login: bool = False,
               ollama_available: bool = False,
               model_available: bool = False,
               on_hotkey_change=None,
               on_model_change=None,
               on_format_level_change=None,
               on_launch_at_login_change=None,
               on_install_ollama=None,
               on_download_model=None,
               on_edit_prompt=None) -> "StatusBarItem":
        obj = cls.alloc().init()
        obj._setup(current_hotkey, current_model, current_format_level,
                    launch_at_login, ollama_available, model_available,
                    on_hotkey_change, on_model_change, on_format_level_change,
                    on_launch_at_login_change, on_install_ollama,
                    on_download_model, on_edit_prompt)
        return obj

    @objc.python_method
    def _setup(self, current_hotkey, current_model, current_format_level,
               launch_at_login, ollama_available, model_available,
               on_hotkey_change, on_model_change, on_format_level_change,
               on_launch_at_login_change, on_install_ollama,
               on_download_model, on_edit_prompt):
        self._on_hotkey_change = on_hotkey_change
        self._on_model_change = on_model_change
        self._on_format_level_change = on_format_level_change
        self._on_launch_at_login_change = on_launch_at_login_change
        self._on_install_ollama = on_install_ollama
        self._on_download_model = on_download_model
        self._on_edit_prompt = on_edit_prompt
        self._current_hotkey = current_hotkey
        self._current_model = current_model
        self._current_format_level = current_format_level
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
            "VoxBridge", None, ""
        )
        title_item.setEnabled_(False)
        menu.addItem_(title_item)

        menu.addItem_(NSMenuItem.separatorItem())

        # Hotkey submenu
        hotkey_menu = NSMenu.alloc().init()
        self._hotkey_items = {}
        for key, label in _HOTKEY_LABELS.items():
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                label, "hotkeySelected:", ""
            )
            item.setTarget_(self)
            item.setRepresentedObject_(key)
            if key == current_hotkey:
                item.setState_(1)  # NSOnState
            hotkey_menu.addItem_(item)
            self._hotkey_items[key] = item

        hotkey_parent = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Hotkey", None, ""
        )
        hotkey_parent.setSubmenu_(hotkey_menu)
        menu.addItem_(hotkey_parent)

        # Model submenu
        model_menu = NSMenu.alloc().init()
        self._model_items = {}
        for model_name in _STT_MODELS:
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                model_name, "modelSelected:", ""
            )
            item.setTarget_(self)
            item.setRepresentedObject_(model_name)
            if model_name == current_model:
                item.setState_(1)
            model_menu.addItem_(item)
            self._model_items[model_name] = item

        model_parent = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Speech Model", None, ""
        )
        model_parent.setSubmenu_(model_menu)
        menu.addItem_(model_parent)

        # Formatting submenu
        format_menu = NSMenu.alloc().init()
        format_menu.setAutoenablesItems_(False)
        self._format_items = {}
        formatter_ready = ollama_available and model_available
        for level in _FORMAT_LEVELS:
            label = _FORMAT_LEVEL_LABELS[level]
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                label, "formatLevelSelected:", ""
            )
            item.setTarget_(self)
            item.setRepresentedObject_(level)
            if level == current_format_level:
                item.setState_(1)
            # Disable "On" when Ollama or model is not available
            if level == "on" and not formatter_ready:
                item.setEnabled_(False)
            format_menu.addItem_(item)
            self._format_items[level] = item

        format_parent = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Formatting", None, ""
        )
        format_parent.setSubmenu_(format_menu)
        menu.addItem_(format_parent)

        menu.addItem_(NSMenuItem.separatorItem())

        # Edit Formatting Prompt
        self._edit_prompt_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Edit Formatting Prompt...", "editPromptClicked:", ""
        )
        self._edit_prompt_item.setTarget_(self)
        menu.addItem_(self._edit_prompt_item)

        # Install Ollama (hidden by default, shown when Ollama not found)
        self._install_ollama_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Install Ollama...", "installOllamaClicked:", ""
        )
        self._install_ollama_item.setTarget_(self)
        self._install_ollama_item.setHidden_(ollama_available)
        menu.addItem_(self._install_ollama_item)

        # Download Qwen model (hidden by default, shown when Ollama available but model missing)
        self._download_model_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Download Qwen model...", "downloadModelClicked:", ""
        )
        self._download_model_item.setTarget_(self)
        self._download_model_item.setHidden_(not ollama_available or model_available)
        menu.addItem_(self._download_model_item)

        menu.addItem_(NSMenuItem.separatorItem())

        # Launch at Login toggle
        self._login_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Launch at Login", "toggleLaunchAtLogin:", ""
        )
        self._login_item.setTarget_(self)
        self._login_item.setState_(1 if launch_at_login else 0)
        menu.addItem_(self._login_item)

        menu.addItem_(NSMenuItem.separatorItem())

        quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Quit", "terminate:", "q"
        )
        menu.addItem_(quit_item)

        self._item.setMenu_(menu)
        print(f"[StatusBar] Menu bar item created with title='VB'")

    def hotkeySelected_(self, sender):
        """Menu callback when a hotkey option is selected."""
        key = sender.representedObject()
        if key == self._current_hotkey:
            return
        for k, item in self._hotkey_items.items():
            item.setState_(1 if k == key else 0)
        self._current_hotkey = key
        if self._on_hotkey_change:
            self._on_hotkey_change(key)

    def modelSelected_(self, sender):
        """Menu callback when a model option is selected."""
        model_name = sender.representedObject()
        if model_name == self._current_model:
            return
        for m, item in self._model_items.items():
            item.setState_(1 if m == model_name else 0)
        self._current_model = model_name
        if self._on_model_change:
            self._on_model_change(model_name)

    def formatLevelSelected_(self, sender):
        """Menu callback when a formatting level is selected."""
        level = sender.representedObject()
        if level == self._current_format_level:
            return
        for lv, item in self._format_items.items():
            item.setState_(1 if lv == level else 0)
        self._current_format_level = level
        if self._on_format_level_change:
            self._on_format_level_change(level)

    def editPromptClicked_(self, sender):
        """Menu callback for Edit Formatting Prompt."""
        if self._on_edit_prompt:
            self._on_edit_prompt()

    def installOllamaClicked_(self, sender):
        """Menu callback for Install Ollama."""
        if self._on_install_ollama:
            self._on_install_ollama()

    def downloadModelClicked_(self, sender):
        """Menu callback for Download Qwen model."""
        if self._on_download_model:
            self._on_download_model()

    def toggleLaunchAtLogin_(self, sender):
        """Menu callback for launch-at-login toggle."""
        new_state = sender.state() == 0  # toggle
        sender.setState_(1 if new_state else 0)
        if self._on_launch_at_login_change:
            self._on_launch_at_login_change(new_state)

    @objc.python_method
    def set_title(self, title: str) -> None:
        self._item.setTitle_(title)

    @objc.python_method
    def set_ollama_available(self, available: bool) -> None:
        """Show/hide the Install Ollama menu item."""
        self._install_ollama_item.setHidden_(available)
        self._update_format_on_enabled()

    @objc.python_method
    def set_model_available(self, available: bool) -> None:
        """Show/hide the Download Qwen model menu item."""
        # Only show when Ollama is available (install item hidden) but model missing
        ollama_present = self._install_ollama_item.isHidden()
        self._download_model_item.setHidden_(not ollama_present or available)
        self._update_format_on_enabled()

    @objc.python_method
    def _update_format_on_enabled(self) -> None:
        """Enable/disable Formatting 'On' based on Ollama+model availability.

        When formatter becomes unavailable while 'On' is selected,
        automatically switches to 'Off'.
        """
        ollama_present = self._install_ollama_item.isHidden()
        model_present = self._download_model_item.isHidden()
        formatter_ready = ollama_present and model_present
        on_item = self._format_items.get("on")
        if on_item:
            on_item.setEnabled_(formatter_ready)
            # Auto-switch to Off if On is selected but unavailable
            if not formatter_ready and self._current_format_level == "on":
                on_item.setState_(0)
                off_item = self._format_items.get("off")
                if off_item:
                    off_item.setState_(1)
                self._current_format_level = "off"
                if self._on_format_level_change:
                    self._on_format_level_change("off")

    @objc.python_method
    def set_download_in_progress(self, in_progress: bool) -> None:
        """Disable/enable the Download Qwen model menu item during download."""
        if in_progress:
            self._download_model_item.setTitle_("Downloading model...")
            self._download_model_item.setEnabled_(False)
        else:
            self._download_model_item.setTitle_("Download Qwen model...")
            self._download_model_item.setEnabled_(True)
