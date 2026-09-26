"""The AppKit calls Qt does not make for us. macOS only; imports AppKit lazily
so the rest of the package still imports on Windows."""

from __future__ import annotations


def hide_dock_icon() -> None:
    """Run as a menu-bar-only app: no Dock icon, no entry in Cmd+Tab.

    A bundled app would say this with ``LSUIElement`` in its ``Info.plist``; a
    plain ``python -m`` launch has no plist, so it is set at runtime.
    """
    from AppKit import NSApplication, NSApplicationActivationPolicyAccessory

    NSApplication.sharedApplication().setActivationPolicy_(
        NSApplicationActivationPolicyAccessory
    )


def yield_activation() -> None:
    """Hand keyboard focus back to the app the user was working in.

    Showing the popup activates this app, and hiding the popup does not undo
    that: macOS leaves a windowless app frontmost. Keystrokes then go nowhere,
    and the next hotkey would post Cmd+C to *this* app instead of the one with
    the selection. Windows moves activation to the next window by itself.

    A no-op when the app is already inactive, i.e. when the user clicked into
    another app.
    """
    from AppKit import NSApplication

    app = NSApplication.sharedApplication()
    if app.isActive():
        app.hide_(None)
