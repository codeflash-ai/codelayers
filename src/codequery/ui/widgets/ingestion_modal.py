"""Ingestion modal for repository processing with live progress updates."""

import asyncio
import logging
from pathlib import Path
from textual import work
from textual.app import ComposeResult
from textual.containers import Vertical, Container, Horizontal
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Button, Static, ProgressBar, Label
from textual.reactive import reactive

from codequery.ingestion.runner import (
    StageState,
    IngestionProgress,
    IngestionComplete,
    IngestionError,
    run_ingestion,
)

logger = logging.getLogger(__name__)


class StageWidget(Widget):
    """A reusable widget for displaying ingestion stage progress."""

    DEFAULT_CSS = """
    StageWidget {
        width: 1fr;
        height: auto;
        padding: 1;
        background: $boost;
        margin-bottom: 1;
    }

    StageWidget.-active {
        background: $warning 10%;
    }

    StageWidget.-complete {
        background: $success 10%;
    }

    StageWidget.-error {
        background: $error 10%;
    }

    StageWidget .stage-header {
        width: 1fr;
        height: auto;
        margin-bottom: 1;
    }

    StageWidget .stage-title-row {
        width: 1fr;
        height: auto;
    }

    StageWidget .stage-label {
        color: $text;
        text-style: bold;
    }

    StageWidget .stage-status {
        color: $text-muted;
        text-align: right;
        dock: right;
    }

    StageWidget .stage-status.-pending {
        color: $text-muted;
    }

    StageWidget .stage-status.-active {
        color: $warning;
        text-style: bold;
    }

    StageWidget .stage-status.-complete {
        color: $success;
        text-style: bold;
    }

    StageWidget .stage-status.-error {
        color: $error;
        text-style: bold;
    }

    StageWidget .stage-progress {
        width: 1fr;
        margin-top: 1;
        margin-bottom: 1;
    }

    StageWidget .stage-detail {
        width: 1fr;
        color: $text-muted;
        text-align: left;
        padding-left: 1;
    }
    """

    # Reactive state
    state: reactive[StageState] = reactive(
        StageState("pending", 0.0, "Waiting to start..."),
        init=False
    )

    def __init__(
        self,
        title: str,
        icon: str,
        initial_detail: str,
        **kwargs
    ) -> None:
        """Initialize the stage widget.

        Args:
            title: The title of the stage (e.g., "Discovery Phase")
            icon: The icon emoji for the stage (e.g., "🔍")
            initial_detail: Initial detail text
        """
        super().__init__(**kwargs)
        self.title = title
        self.icon = icon
        self.initial_detail = initial_detail

    def compose(self) -> ComposeResult:
        """Compose the stage widget."""
        with Vertical(classes="stage-header"):
            with Horizontal(classes="stage-title-row"):
                yield Label(f"{self.icon} {self.title}", classes="stage-label")
                yield Static("⏳ Pending", classes="stage-status -pending")
            yield Static(self.initial_detail, classes="stage-detail")
        yield ProgressBar(total=100, show_eta=False, classes="stage-progress")

    def watch_state(self, state: StageState) -> None:
        """Update UI when state changes."""
        # Update container state classes
        self.remove_class("-active", "-complete", "-error")
        if state.status != "pending":
            self.add_class(f"-{state.status}")

        # Update status text and classes
        status_map = {
            "pending": "⏳ Pending",
            "active": "🔄 Active",
            "complete": "✅ Complete",
            "error": "❌ Error"
        }
        status_widget = self.query_one(".stage-status", Static)
        status_widget.update(status_map.get(state.status, state.status))
        status_widget.remove_class("-pending", "-active", "-complete", "-error")
        status_widget.add_class(f"-{state.status}")

        # Update progress bar
        progress_bar = self.query_one(ProgressBar)
        progress_bar.update(progress=state.progress)

        # Update detail text
        detail_widget = self.query_one(".stage-detail", Static)
        detail_widget.update(state.detail)


class IngestionModal(ModalScreen[Path | None]):
    """Modal screen for repository ingestion with progress updates.

    Returns:
        Path to the generated database file if successful, None otherwise.
    """

    BINDINGS = [("escape", "dismiss", "Cancel")]

    # Reactive flags
    is_complete: reactive[bool] = reactive(False)
    is_cancelled: reactive[bool] = reactive(False)

    DEFAULT_CSS = """
    IngestionModal {
        align: center middle;
    }

    IngestionModal > #modal-container {
        width: 100;
        height: auto;
        max-width: 140;
        max-height: 95vh;
        background: $surface;
        padding: 2;
        overflow-y: auto;
        scrollbar-gutter: stable;
    }

    IngestionModal #header-section {
        width: 1fr;
        height: auto;
        margin-bottom: 1;
        padding: 1;
        background: $boost;
    }

    IngestionModal #modal-title {
        text-align: center;
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
        content-align: center middle;
    }

    IngestionModal #repo-path-label {
        text-align: center;
        color: $text;
        text-style: italic;
    }

    IngestionModal #stages-container {
        width: 1fr;
        height: auto;
        margin-bottom: 1;
        overflow-y: auto;
    }

    IngestionModal #summary-container {
        width: 1fr;
        height: auto;
        padding: 1;
        background: $success 15%;
        margin-bottom: 1;
    }

    IngestionModal #summary-title {
        text-align: center;
        text-style: bold;
        color: $success;
        margin-bottom: 1;
    }

    IngestionModal #summary-stats {
        width: 1fr;
        text-align: left;
        color: $text;
        padding: 0;
    }

    IngestionModal #action-buttons {
        width: 1fr;
        height: auto;
        align: center middle;
    }

    IngestionModal #action-buttons Button {
        min-width: 20;
        margin: 0 1;
    }

    IngestionModal #error-message {
        width: 1fr;
        height: auto;
        padding: 2;
        background: $error 15%;
        color: $error;
        text-align: center;
        margin-bottom: 1;
        display: none;
    }

    IngestionModal #error-message.-visible {
        display: block;
    }
    """

    def __init__(self, repo_path: Path, **kwargs) -> None:
        """Initialize the ingestion modal.

        Args:
            repo_path: Path to the repository to ingest
        """
        super().__init__(**kwargs)
        self.repo_path = repo_path
        self.output_db = Path(f"{repo_path.name}_codebase.db")
        self._cancel_event = asyncio.Event()

        # Create stage widgets (will be added in compose)
        self._discovery_stage: StageWidget | None = None
        self._parsing_stage: StageWidget | None = None
        self._type_analysis_stage: StageWidget | None = None
        self._message_creation_stage: StageWidget | None = None
        self._indexing_stage: StageWidget | None = None

    def compose(self) -> ComposeResult:
        """Compose the ingestion modal."""
        with Container(id="modal-container"):
            with Vertical(id="header-section"):
                yield Static("⚡ Repository Ingestion", id="modal-title")
                yield Static(f"📁 {self.repo_path}", id="repo-path-label")

            with Vertical(id="stages-container"):
                self._discovery_stage = StageWidget(
                    title="Discovery Phase",
                    icon="🔍",
                    initial_detail="Scanning repository for Python files...",
                    id="discovery-stage"
                )
                yield self._discovery_stage

                self._parsing_stage = StageWidget(
                    title="Parsing Phase",
                    icon="📝",
                    initial_detail="Waiting for discovery...",
                    id="parsing-stage"
                )
                yield self._parsing_stage

                self._type_analysis_stage = StageWidget(
                    title="Type Analysis Phase",
                    icon="🔬",
                    initial_detail="Waiting for parsing...",
                    id="type-analysis-stage"
                )
                yield self._type_analysis_stage

                self._message_creation_stage = StageWidget(
                    title="Message Creation Phase",
                    icon="💬",
                    initial_detail="Waiting for type analysis...",
                    id="message-creation-stage"
                )
                yield self._message_creation_stage

                self._indexing_stage = StageWidget(
                    title="Indexing Phase",
                    icon="🗄️",
                    initial_detail="Waiting for message creation...",
                    id="indexing-stage"
                )
                yield self._indexing_stage

            yield Static("", id="error-message")

            with Vertical(id="summary-container") as summary:
                summary.display = False
                yield Static("✅ Ingestion Complete!", id="summary-title")
                yield Static("", id="summary-stats")

            with Horizontal(id="action-buttons"):
                yield Button("✖ Cancel Ingestion", variant="error", id="cancel-button")
                with Button("✓ Done", variant="success", id="close-button") as close_btn:
                    close_btn.display = False

    def on_mount(self) -> None:
        """Start ingestion when modal is mounted."""
        self._start_ingestion()

    @work(exclusive=True)
    async def _start_ingestion(self) -> None:
        """Execute the ingestion process."""
        try:
            async for event in run_ingestion(
                self.repo_path,
                self.output_db,
                cancel_event=self._cancel_event
            ):
                if isinstance(event, IngestionProgress):
                    # Update stage widget state
                    stage_widget = self._get_stage_widget(event.stage)
                    if stage_widget:
                        stage_widget.state = event.state

                elif isinstance(event, IngestionComplete):
                    self.is_complete = True
                    self._show_summary(event.summary_text)
                    self._show_close_button()

                elif isinstance(event, IngestionError):
                    self._handle_error(event.error, event.stage)

        except asyncio.CancelledError:
            self.is_cancelled = True
            self._show_error_message("Ingestion cancelled by user")
            self._show_close_button()
        except Exception as e:
            logger.error("Ingestion error", exc_info=True)
            self._show_error_message(f"An error occurred during ingestion: {str(e)}")
            self._show_close_button()

    def _get_stage_widget(self, stage: str) -> StageWidget | None:
        """Get the stage widget for a given stage name."""
        stage_map = {
            "discovery": self._discovery_stage,
            "parsing": self._parsing_stage,
            "type_analysis": self._type_analysis_stage,
            "message_creation": self._message_creation_stage,
            "indexing": self._indexing_stage,
        }
        return stage_map.get(stage)

    def _handle_error(self, error: str, stage: str) -> None:
        """Handle ingestion error."""
        stage_widget = self._get_stage_widget(stage)
        if stage_widget:
            # Update the stage to show error state
            stage_widget.state = StageState("error", stage_widget.state.progress, error)

        self._show_error_message(error)
        self._show_close_button()

    def _show_summary(self, summary_text: str) -> None:
        """Show the summary container with results."""
        summary_container = self.query_one("#summary-container")
        summary_container.display = True
        self.query_one("#summary-stats", Static).update(summary_text)

    def _show_error_message(self, message: str) -> None:
        """Show error message at the top of modal."""
        error_widget = self.query_one("#error-message", Static)
        error_widget.update(f"❌ {message}")
        error_widget.add_class("-visible")

    def _show_close_button(self) -> None:
        """Show the close button when complete."""
        cancel_btn = self.query_one("#cancel-button", Button)
        close_btn = self.query_one("#close-button", Button)
        cancel_btn.display = False
        close_btn.display = True

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press."""
        if event.button.id == "close-button":
            self.dismiss(self.output_db if self.is_complete else None)
        elif event.button.id == "cancel-button":
            self.is_cancelled = True
            if self._cancel_event:
                self._cancel_event.set()
            self._show_error_message("Ingestion cancelled by user")
            self._show_close_button()

    def action_dismiss(self) -> None:
        """Handle escape key."""
        if self.is_complete or self.is_cancelled:
            self.dismiss(self.output_db if self.is_complete else None)
        else:
            # Cancel the ingestion if still running
            self.is_cancelled = True
            if self._cancel_event:
                self._cancel_event.set()
            self.dismiss(None)
