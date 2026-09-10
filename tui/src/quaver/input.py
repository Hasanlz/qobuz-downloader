"""Text inputs that let Ctrl+C quit instead of copying."""

from __future__ import annotations

from textual.binding import Binding
from textual.widgets import Input


class SafeInput(Input):
    """Text field where Ctrl+C quits the app and Ctrl+H deletes like Backspace."""

    BINDINGS = Input.BINDINGS + [
        Binding("ctrl+c", "app.quit", "Quit", show=False),
        Binding("ctrl+h", "delete_left", "Delete character left", show=False),
    ]
