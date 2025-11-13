"""Repository browser widget for selecting Python repositories to ingest."""

from pathlib import Path
from textual import on
from textual.app import ComposeResult
from textual.containers import Vertical, Container
from textual.widgets import Button, Input, Static, DirectoryTree
from textual.reactive import reactive


class RepoBrowserWidget(Container):
    """Widget for browsing and selecting repositories to ingest."""

    selected_path: reactive[Path | None] = reactive(None, init=False)

    DEFAULT_CSS = """
    RepoBrowserWidget {
        width: 1fr;
        height: 1fr;
        padding: 1;
        layout: vertical;
    }

    #browser_title {
        text-align: center;
        text-style: bold;
        color: $accent;
        height: 1;
    }

    #path_input {
        width: 1fr;
        height: 3;
    }

    #directory_tree {
        width: 1fr;
        height: 1fr;
    }

    #action_buttons {
        width: 1fr;
        height: auto;
        align: center middle;
        layout: horizontal;
    }

    .action_button {
        margin: 0 1;
    }
    """

    def compose(self) -> ComposeResult:
        """Compose the repository browser widget."""
        yield Static("📁 Select Repository to Ingest", id="browser_title")
        yield Input(
            placeholder="Enter path to repository or browse below...",
            id="path_input",
        )
        tree = DirectoryTree(str(Path.cwd()), id="directory_tree")
        tree.auto_expand = False
        yield tree
        with Vertical(id="action_buttons"):
            yield Button("Ingest Selected", variant="success", id="ingest_button", classes="action_button")
            yield Button("Query Existing DB", variant="primary", id="query_button", classes="action_button")

    def on_mount(self) -> None:
        """Handle widget mount."""
        self.query_one("#ingest_button", Button).disabled = True

    @on(Input.Changed, "#path_input")
    def on_path_input_changed(self, event: Input.Changed) -> None:
        """Handle manual path input."""
        path = Path(event.value.strip())
        if path.exists() and path.is_dir():
            self.selected_path = path
            self.query_one("#ingest_button", Button).disabled = False
        else:
            self.query_one("#ingest_button", Button).disabled = True

    @on(DirectoryTree.DirectorySelected)
    def on_directory_selected(self, event: DirectoryTree.DirectorySelected) -> None:
        """Handle directory selection from tree."""
        self.selected_path = event.path
        self.query_one("#path_input", Input).value = str(event.path)
        self.query_one("#ingest_button", Button).disabled = False

    @on(Button.Pressed, "#ingest_button")
    def on_ingest_button_pressed(self) -> None:
        """Handle ingest button press."""
        if self.selected_path:
            self.post_message(self.IngestRequested(self.selected_path))

    @on(Button.Pressed, "#query_button")
    def on_query_button_pressed(self) -> None:
        """Handle query button press."""
        self.post_message(self.QueryRequested())

    class IngestRequested(Button.Pressed):
        """Message sent when ingestion is requested."""

        def __init__(self, path: Path) -> None:
            super().__init__(Button())
            self.path = path

    class QueryRequested(Button.Pressed):
        """Message sent when query mode is requested."""

        def __init__(self) -> None:
            super().__init__(Button())
