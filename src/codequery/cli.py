"""Command-line interface for CodeQuery - Semantic Code Search."""

import asyncio
import sys
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.panel import Panel
from rich.table import Table
from rich.markdown import Markdown

from codequery.ingestion.runner import (
    run_ingestion,
    IngestionProgress,
    IngestionComplete,
    IngestionError,
)
from typeagent import create_conversation
from typeagent.knowpro.universal_message import ConversationMessage

console = Console()


@click.group()
@click.version_option(version="0.1.0", prog_name="codequery")
def cli():
    """CodeQuery - Semantic Code Search for Python repositories.
    
    Index Python codebases and query them with natural language.
    """
    pass


@cli.command()
@click.argument("repo_path", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option(
    "-o",
    "--output",
    type=click.Path(path_type=Path),
    help="Output database path (defaults to {repo_name}_codebase.db)",
)
@click.option(
    "--quiet",
    "-q",
    is_flag=True,
    help="Minimal output (only show summary)",
)
def ingest(repo_path: Path, output: Optional[Path], quiet: bool):
    """Ingest a Python repository and create a searchable database.
    
    REPO_PATH: Path to the Python repository to index
    
    Example:
        codequery ingest /path/to/my/project
        codequery ingest ~/code/django -o django.db
    """
    asyncio.run(_run_ingest(repo_path, output, quiet))


async def _run_ingest(repo_path: Path, output_db: Optional[Path], quiet: bool):
    """Run the ingestion process with progress display."""
    
    if not quiet:
        console.print(Panel.fit(
            f"[bold cyan]Starting ingestion of:[/] {repo_path}",
            border_style="cyan"
        ))
    
    stage_tasks = {}
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
        disable=quiet,
    ) as progress:
        
        async for event in run_ingestion(repo_path, output_db):
            if isinstance(event, IngestionProgress):
                stage = event.stage
                state = event.state
                
                if stage not in stage_tasks:
                    stage_tasks[stage] = progress.add_task(
                        f"[cyan]{stage.title()}[/]", total=100
                    )
                
                progress.update(
                    stage_tasks[stage],
                    completed=state.progress,
                    description=f"[cyan]{stage.title()}:[/] {state.detail}"
                )
                
            elif isinstance(event, IngestionComplete):
                if not quiet:
                    console.print()
                    console.print(Panel(
                        event.summary_text,
                        title="[bold green]✓ Ingestion Complete[/]",
                        border_style="green"
                    ))
                else:
                    result = event.result
                    console.print(f"✓ Indexed {result.files_processed} files → {result.db_path}")
                
                return
                
            elif isinstance(event, IngestionError):
                console.print()
                console.print(f"[bold red]✗ Error during {event.stage}:[/] {event.error}")
                sys.exit(1)


@cli.command()
@click.argument("query")
@click.option(
    "-d",
    "--database",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Path to database file (defaults to first *.db in current directory)",
)
@click.option(
    "--markdown",
    "-m",
    is_flag=True,
    help="Output result as markdown",
)
def query(query: str, database: Optional[Path], markdown: bool):
    """Query an indexed codebase with natural language.
    
    QUERY: Natural language question about the code
    
    Example:
        codequery query "How does authentication work?"
        codequery query "Find all API endpoints" -d myproject.db
        codequery query "Where is the user model defined?" --markdown
    """
    asyncio.run(_run_query(query, database, markdown))


async def _run_query(query_text: str, db_path: Optional[Path], markdown_output: bool):
    """Execute a query against the indexed codebase."""
    
    # Find database if not specified
    if db_path is None:
        db_files = list(Path.cwd().glob("*.db"))
        if not db_files:
            console.print("[red]✗ No database files found in current directory[/]")
            console.print("Run 'codequery ingest' first or specify a database with -d")
            sys.exit(1)
        db_path = db_files[0]
        if len(db_files) > 1:
            console.print(f"[yellow]Found {len(db_files)} databases, using: {db_path.name}[/]")
    
    if not db_path.exists():
        console.print(f"[red]✗ Database not found: {db_path}[/]")
        sys.exit(1)
    
    with console.status(f"[cyan]Searching {db_path.name}...[/]"):
        try:
            conversation = await create_conversation(
                str(db_path), ConversationMessage
            )
            answer = await conversation.query(query_text)
        except Exception as e:
            console.print(f"[red]✗ Query failed: {e}[/]")
            sys.exit(1)
    
    console.print()
    
    if markdown_output:
        console.print(Markdown(answer))
    else:
        console.print(Panel(
            answer,
            title=f"[bold cyan]Query:[/] {query_text}",
            border_style="cyan",
            padding=(1, 2)
        ))


@cli.command()
@click.option(
    "-d",
    "--directory",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path.cwd(),
    help="Directory to search for databases (defaults to current directory)",
)
def list_dbs(directory: Path):
    """List all indexed databases in a directory.
    
    Example:
        codequery list-dbs
        codequery list-dbs -d ~/projects
    """
    db_files = list(directory.glob("*.db"))
    
    if not db_files:
        console.print(f"[yellow]No database files found in {directory}[/]")
        return
    
    table = Table(title=f"Indexed Databases in {directory}")
    table.add_column("Database", style="cyan", no_wrap=True)
    table.add_column("Size", justify="right", style="green")
    
    for db in sorted(db_files):
        size_mb = db.stat().st_size / (1024 * 1024)
        table.add_row(db.name, f"{size_mb:.2f} MB")
    
    console.print(table)


@cli.command()
@click.argument("database", type=click.Path(exists=True, dir_okay=False, path_type=Path))
def info(database: Path):
    """Show information about an indexed database.
    
    DATABASE: Path to the database file
    
    Example:
        codequery info myproject.db
    """
    asyncio.run(_show_db_info(database))


async def _show_db_info(db_path: Path):
    """Display detailed information about a database."""
    
    try:
        conversation = await create_conversation(
            str(db_path), ConversationMessage
        )
        
        # Get basic stats
        size_mb = db_path.stat().st_size / (1024 * 1024)
        
        table = Table(title=f"Database Info: {db_path.name}")
        table.add_column("Property", style="cyan")
        table.add_column("Value", style="green")
        
        table.add_row("File", str(db_path))
        table.add_row("Size", f"{size_mb:.2f} MB")
        table.add_row("Name", conversation.name or "N/A")
        table.add_row("Tags", ", ".join(conversation.tags) if conversation.tags else "None")
        
        console.print(table)
        
    except Exception as e:
        console.print(f"[red]✗ Failed to read database: {e}[/]")
        sys.exit(1)


@cli.command()
def tui():
    """Launch the interactive TUI interface.
    
    Opens the full Textual-based UI for browsing and querying.
    
    Example:
        codequery tui
    """
    from codequery.app import main as tui_main
    tui_main()


def main():
    """Entry point for the CLI."""
    cli()


if __name__ == "__main__":
    main()
