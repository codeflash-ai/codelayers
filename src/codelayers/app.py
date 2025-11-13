"""Main TUI application for CodeQuery - Semantic Code Search."""

from pathlib import Path
from textual import on
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer
from textual.reactive import reactive
from textual.binding import Binding

from codelayers.ui import RepoBrowserWidget, QueryInterfaceWidget, IngestionModal


class CodeQueryApp(App):
    """A TUI for semantic code search and repository ingestion."""

    TITLE = "CodeQuery - Semantic Code Search"
    CSS_PATH = "ui/styles.tcss"
    
    BINDINGS = [
        Binding("q", "quit", "Quit", priority=True),
        Binding("ctrl+c", "quit", "Quit", show=False),
        ("h", "show_help", "Help"),
    ]

    current_mode: reactive[str] = reactive("browser", init=False)
    current_db: reactive[Path | None] = reactive(None, init=False)

    def compose(self) -> ComposeResult:
        """Compose the main application layout."""
        yield Header(show_clock=True)
        yield RepoBrowserWidget(id="repo_browser")
        yield Footer()

    def on_mount(self) -> None:
        """Handle application mount."""
        self.query_one(Header).tall = False

    @on(RepoBrowserWidget.IngestRequested)
    def handle_ingest_requested(self, message: RepoBrowserWidget.IngestRequested) -> None:
        """Handle repository ingestion request."""
        
        def handle_ingestion_result(result: Path | None) -> None:
            """Handle the result of ingestion modal."""
            if result:
                self.current_db = result
                self._switch_to_query_mode(result)
        
        self.push_screen(IngestionModal(message.path), handle_ingestion_result)

    @on(RepoBrowserWidget.QueryRequested)
    def handle_query_requested(self, message: RepoBrowserWidget.QueryRequested) -> None:
        """Handle query mode request."""
        self._switch_to_query_mode()

    @on(QueryInterfaceWidget.BackRequested)
    def handle_back_requested(self, message: QueryInterfaceWidget.BackRequested) -> None:
        """Handle back button from query mode."""
        self._switch_to_browser_mode()

    def _switch_to_query_mode(self, db_path: Path | None = None) -> None:
        """Switch to query interface mode."""
        if self.current_mode == "query":
            return
        
        # Remove browser widget
        browser = self.query_one("#repo_browser", RepoBrowserWidget)
        browser.remove()
        
        # Mount query widget
        query_widget = QueryInterfaceWidget(db_path=db_path or self.current_db, id="query_interface")
        self.mount(query_widget, before=self.query_one(Footer))
        
        self.current_mode = "query"

    def _switch_to_browser_mode(self) -> None:
        """Switch to repository browser mode."""
        if self.current_mode == "browser":
            return
        
        # Remove query widget
        query = self.query_one("#query_interface", QueryInterfaceWidget)
        query.remove()
        
        # Mount browser widget
        browser = RepoBrowserWidget(id="repo_browser")
        self.mount(browser, before=self.query_one(Footer))
        
        self.current_mode = "browser"

    def action_show_help(self) -> None:
        """Show help information."""
        help_text = """
        CodeQuery - Semantic Code Search
        
        Browser Mode:
        - Select a repository directory to ingest
        - Click "Ingest Selected" to index the repository
        - Click "Query Existing DB" to search indexed databases
        
        Query Mode:
        - Type your question in the search box
        - Press Enter or click "Search" to query
        - Select different databases from the dropdown
        - Click "← Back" to return to browser
        
        Keyboard Shortcuts:
        - q: Quit application
        - h: Show this help
        - Esc: Close modal/dialog
        """
        self.notify(help_text, title="Help", timeout=10)


def main():
    """Entry point for the TUI application."""
    app = CodeQueryApp()
    app.run()


if __name__ == "__main__":
    main()
