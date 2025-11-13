from pathlib import Path
from textual import on, work
from textual.app import ComposeResult
from textual.containers import Vertical, Container, Horizontal
from textual.widgets import Button, Input, Static, Select, Markdown
from textual.reactive import reactive
from typeagent import create_conversation
from typeagent.knowpro.universal_message import ConversationMessage


class QueryInterfaceWidget(Container):
    """Widget for querying the indexed codebase."""

    current_db: reactive[Path | None] = reactive(None, init=False)

    DEFAULT_CSS = """
    QueryInterfaceWidget {
        width: 1fr;
        height: 1fr;
        padding: 1;
    }

    #query_container {
        width: 100%;
        height: 1fr;
        padding: 1;
    }

    #query_title {
        text-align: center;
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
    }

    #db_selector_container {
        width: 1fr;
        height: auto;
        margin-bottom: 1;
        layout: horizontal;
    }

    #db_select {
        width: 3fr;
        margin-right: 1;
    }

    #back_button {
        width: auto;
    }

    #query_input_container {
        width: 1fr;
        height: auto;
        margin-bottom: 1;
        layout: horizontal;
    }

    #query_input {
        width: 4fr;
        margin-right: 1;
    }

    #query_button {
        width: auto;
    }

    #status_label {
        width: 1fr;
        color: $text-muted;
        text-align: center;
        margin-bottom: 1;
    }

    #results_container {
        width: 1fr;
        height: 1fr;
        padding: 1;
    }

    #results_display {
        width: 1fr;
        height: 1fr;
    }
    """

    def __init__(self, db_path: Path | None = None, **kwargs):
        """Initialize the query interface."""
        super().__init__(**kwargs)
        self.current_db = db_path
        self._available_dbs: list[Path] = []

    def compose(self) -> ComposeResult:
        """Compose the query interface widget."""
        with Vertical(id="query_container"):
            yield Static("🔍 Semantic Code Search", id="query_title")

            with Horizontal(id="db_selector_container"):
                yield Select(
                    [(str(db), str(db)) for db in self._available_dbs]
                    if self._available_dbs
                    else [("No databases found", "")],
                    id="db_select",
                    prompt="Select database",
                    allow_blank=False,
                )
                yield Button("← Back", variant="default", id="back_button")

            with Horizontal(id="query_input_container"):
                yield Input(
                    placeholder="Ask a question about the codebase...",
                    id="query_input",
                )
                yield Button("Search", variant="primary", id="query_button")

            yield Static("Ready to query", id="status_label")

            with Vertical(id="results_container"):
                yield Markdown("*No results yet. Enter a query to search the codebase.*", id="results_display")

    def on_mount(self) -> None:
        self._scan_for_databases()
        self.query_one("#query_input", Input).focus()

    def _scan_for_databases(self) -> None:
        self._available_dbs = list(Path.cwd().glob("*.db"))

        if self._available_dbs:
            db_select = self.query_one("#db_select", Select)
            db_select.set_options(
                [(str(db.name), str(db)) for db in self._available_dbs]
            )
            if self.current_db and self.current_db in self._available_dbs:
                db_select.value = str(self.current_db)
            else:
                db_select.value = str(self._available_dbs[0])
                self.current_db = self._available_dbs[0]
            self.query_one("#status_label", Static).update(
                f"Connected to: [bold]{self.current_db.name}[/]"
            )
        else:
            self.query_one("#status_label", Static).update(
                "[yellow]No databases found. Please ingest a repository first.[/]"
            )
            self.query_one("#query_button", Button).disabled = True

    @on(Select.Changed, "#db_select")
    def on_db_selected(self, event: Select.Changed) -> None:
        if event.value and event.value != "":
            self.current_db = Path(event.value)
            self.query_one("#status_label", Static).update(
                f"Connected to: [bold]{self.current_db.name}[/]"
            )
            self.query_one("#query_button", Button).disabled = False

    @on(Button.Pressed, "#back_button")
    def on_back_button_pressed(self) -> None:
        """Handle back button press."""
        self.post_message(self.BackRequested())

    @on(Input.Submitted, "#query_input")
    def on_query_submitted(self, event: Input.Submitted) -> None:
        """Handle query submission via Enter key."""
        if event.value.strip():
            self._execute_query(event.value.strip())

    @on(Button.Pressed, "#query_button")
    def on_query_button_pressed(self) -> None:
        """Handle query button press."""
        query_input = self.query_one("#query_input", Input)
        if query_input.value.strip():
            self._execute_query(query_input.value.strip())

    @work(exclusive=True)
    async def _execute_query(self, query: str) -> None:
        if not self.current_db or not self.current_db.exists():
            self._update_status("[red]No valid database selected[/]")
            return

        self._update_status(f"[cyan]Searching for:[/] {query}")
        results_display = self.query_one("#results_display", Markdown)

        try:
            conversation = await create_conversation(
                str(self.current_db), ConversationMessage
            )
            answer = await conversation.query(query)

            # Format and display result
            markdown_content = f"""
## Answer
{answer}
"""
            await results_display.update(markdown_content)

            self._update_status("[green]Query completed[/]")

        except Exception as e:
            # Display error
            error_content = f"""# Error

**Query:** {query}

**Error:** {str(e)}

---
*Database: {self.current_db.name if self.current_db else 'Unknown'}*
"""
            await results_display.update(error_content)
            self._update_status(f"[red]Query failed: {str(e)}[/]")

    def _update_status(self, message: str) -> None:
        """Update the status label."""
        self.query_one("#status_label", Static).update(message)

    class BackRequested(Button.Pressed):
        """Message sent when back button is pressed."""

        def __init__(self) -> None:
            super().__init__(Button())
