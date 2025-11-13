"""Core ingestion logic separated from UI concerns."""

import asyncio
import logging
import time
from collections import defaultdict
from pathlib import Path
from typing import AsyncGenerator, NamedTuple, Literal
from dataclasses import dataclass

from codelayers.ingestion.discovery import discover_files
from codelayers.ingestion.parser import parse_python_file
from codelayers.ingestion.messages import (
    create_module_message,
    create_entity_messages_with_jedi,
    parse_text_file,
)
from codelayers.ingestion.models import CodeMessage, IngestResult
from codelayers.ingestion.jedi_analyzer import analyze_python_file_with_jedi
from typeagent import create_conversation

logger = logging.getLogger(__name__)


class StageState(NamedTuple):
    """State of a single ingestion stage."""

    status: Literal["pending", "active", "complete", "error"]
    progress: float
    detail: str


@dataclass
class IngestionProgress:
    """Progress update for a specific stage."""

    stage: str
    state: StageState


@dataclass
class IngestionComplete:
    """Ingestion completed successfully."""

    result: IngestResult
    summary_text: str


@dataclass
class IngestionError:
    """Ingestion encountered an error."""

    error: str
    stage: str


async def run_ingestion(
    repo_path: Path,
    output_db: Path | None = None,
    cancel_event: asyncio.Event | None = None,
) -> AsyncGenerator[IngestionProgress | IngestionComplete | IngestionError, None]:
    """
    Run the ingestion process, yielding progress updates.

    Args:
        repo_path: Path to the repository to ingest
        output_db: Path to output database (defaults to {repo_name}_codebase.db)
        cancel_event: Event to check for cancellation

    Yields:
        Progress updates, completion, or error messages
    """
    start_time = time.time()

    try:
        if not repo_path.exists():
            yield IngestionError(
                error=f"Repository path does not exist: {repo_path}", stage="discovery"
            )
            return

        repo_name = repo_path.name
        project_name = repo_name

        # Discovery Phase
        yield IngestionProgress(
            stage="discovery",
            state=StageState("active", 0.0, "Scanning repository for Python files..."),
        )

        if cancel_event and cancel_event.is_set():
            return

        files = discover_files(repo_path, [])

        file_counts = defaultdict(int)
        for f in files:
            file_counts[f["kind"]] += 1

        type_str = ", ".join([f"{k}: {v}" for k, v in file_counts.items()])
        yield IngestionProgress(
            stage="discovery",
            state=StageState(
                "complete", 100.0, f"✓ Found {len(files)} files ({type_str})"
            ),
        )

        if cancel_event and cancel_event.is_set():
            return

        # Parsing Phase
        yield IngestionProgress(
            stage="parsing", state=StageState("active", 0.0, "Starting file parsing...")
        )

        all_parsed = []
        all_jedi_analyses = []
        all_messages = []
        failures = []

        # Parse Python files
        python_files = [f["path"] for f in files if f["kind"] == "python"]
        tasks = [parse_python_file(path, repo_path) for path in python_files]

        for i, result in enumerate(await asyncio.gather(*tasks)):
            if cancel_event and cancel_event.is_set():
                return

            if result:
                all_parsed.append((python_files[i], result))
            else:
                failures.append((str(python_files[i]), "Parse failed"))

            # Report progress periodically
            if (i + 1) % 50 == 0 or i == len(python_files) - 1:
                progress = (i + 1) / len(python_files) * 100
                yield IngestionProgress(
                    stage="parsing",
                    state=StageState(
                        "active",
                        progress,
                        f"⚙️ Processing: {i + 1}/{len(python_files)} Python files ({progress:.1f}%)",
                    ),
                )

        yield IngestionProgress(
            stage="parsing",
            state=StageState("complete", 100.0, f"✓ Parsed {len(all_parsed)} files"),
        )

        if all_parsed:
            if cancel_event and cancel_event.is_set():
                return

            yield IngestionProgress(
                stage="type_analysis",
                state=StageState("active", 0.0, "Starting Jedi type analysis..."),
            )

            jedi_tasks = [
                analyze_python_file_with_jedi(file_path, repo_path, parsed)
                for file_path, parsed in all_parsed
            ]

            for i, jedi_result in enumerate(await asyncio.gather(*jedi_tasks)):
                if cancel_event and cancel_event.is_set():
                    return

                all_jedi_analyses.append(jedi_result)

                # Report progress periodically
                if (i + 1) % 25 == 0 or i == len(all_parsed) - 1:
                    progress = (i + 1) / len(all_parsed) * 100
                    yield IngestionProgress(
                        stage="type_analysis",
                        state=StageState(
                            "active",
                            progress,
                            f"⚙️ Analyzing: {i + 1}/{len(all_parsed)} files ({progress:.1f}%)",
                        ),
                    )

            yield IngestionProgress(
                stage="type_analysis",
                state=StageState(
                    "complete",
                    100.0,
                    f"✓ Analyzed {len([j for j in all_jedi_analyses if j])} files with Jedi",
                ),
            )

        # Message Creation Phase
        if cancel_event and cancel_event.is_set():
            return

        yield IngestionProgress(
            stage="message_creation",
            state=StageState("active", 0.0, "Creating messages from parsed code..."),
        )

        # Process Python files
        total_items = len(all_parsed) + len(
            [f for f in files if f["kind"] in ["documentation", "configuration"]]
        )
        processed = 0

        for i, (file_path, parsed) in enumerate(all_parsed):
            if cancel_event and cancel_event.is_set():
                return

            # Create module message
            module_message = create_module_message(parsed, project_name)
            if module_message.text_chunks:
                all_messages.append(module_message)

            # Create entity messages with Jedi type information
            jedi_analysis = all_jedi_analyses[i]
            entity_messages = create_entity_messages_with_jedi(
                parsed, jedi_analysis, project_name
            )

            for entity_msg in entity_messages:
                if entity_msg.text_chunks:
                    all_messages.append(entity_msg)

            processed += 1

            # Report progress periodically
            if (processed) % 25 == 0 or processed == len(all_parsed):
                progress = processed / total_items * 100
                yield IngestionProgress(
                    stage="message_creation",
                    state=StageState(
                        "active",
                        progress,
                        f"⚙️ Processing: {processed}/{total_items} files ({progress:.1f}%) - {len(all_messages)} messages created",
                    ),
                )

        # Process text files
        for f in files:
            if cancel_event and cancel_event.is_set():
                return

            if f["kind"] in ["documentation", "configuration"]:
                msg = parse_text_file(f["path"], repo_path, f["kind"], project_name)
                if msg and msg.text_chunks:
                    all_messages.append(msg)
                processed += 1

        yield IngestionProgress(
            stage="message_creation",
            state=StageState(
                "complete",
                100.0,
                f"✓ Created {len(all_messages)} messages from {total_items} files",
            ),
        )

        if cancel_event and cancel_event.is_set():
            return

        # Count symbols
        symbols_count = sum(len(p.classes) + len(p.functions) for _, p in all_parsed)

        # Indexing Phase
        yield IngestionProgress(
            stage="indexing",
            state=StageState(
                "active", 0.0, "Creating Typeagent conversation and indexing..."
            ),
        )

        db_path = output_db or Path(f"{repo_name}_codebase.db")

        conversation = await create_conversation(
            str(db_path),
            CodeMessage,
            name=f"{repo_name}-codebase",
            tags=[repo_name, "codebase", "python"],
        )

        # Add messages in smaller batches for more frequent progress updates
        # Smaller batches mean more updates but slightly more overhead
        # Balance: 50 messages per batch gives good granularity without too much overhead
        batch_size = 50
        total_batches = (len(all_messages) + batch_size - 1) // batch_size
        semrefs_added = 0
        messages_added_total = 0

        for batch_num, i in enumerate(range(0, len(all_messages), batch_size), 1):
            if cancel_event and cancel_event.is_set():
                return

            batch = all_messages[i : i + batch_size]

            # Show batch start with preliminary progress
            pre_progress = (batch_num - 1) / total_batches * 100
            yield IngestionProgress(
                stage="indexing",
                state=StageState(
                    "active",
                    pre_progress,
                    f"⚙️ Batch {batch_num}/{total_batches}: Processing {len(batch)} messages - Extracting knowledge...",
                ),
            )

            result = await conversation.add_messages_with_indexing(batch)
            semrefs_added += result.semrefs_added
            messages_added_total += result.messages_added

            progress = batch_num / total_batches * 100
            yield IngestionProgress(
                stage="indexing",
                state=StageState(
                    "active",
                    progress,
                    f"✓ Batch {batch_num}/{total_batches} done ({progress:.1f}%) | Total: {messages_added_total} messages, {semrefs_added} refs",
                ),
            )

        yield IngestionProgress(
            stage="indexing", state=StageState("complete", 100.0, "✓ Indexing complete")
        )

        duration = time.time() - start_time

        # Create summary
        summary_text = f"""📊 Ingestion Statistics:

📄 Files Processed: {len(files)}
💬 Messages Created: {len(all_messages)}
🔤 Symbols Indexed: {symbols_count}
🔗 Semantic References: {semrefs_added}
⏱️  Duration: {duration:.2f}s
💾 Database: {db_path}"""

        if failures:
            summary_text += f"\n\n⚠️  Warning: {len(failures)} files failed to process"

        # Yield completion
        yield IngestionComplete(
            result=IngestResult(
                files_processed=len(files),
                messages_created=len(all_messages),
                symbols_indexed=symbols_count,
                semrefs_added=semrefs_added,
                duration=duration,
                db_path=db_path,
                failures=failures,
            ),
            summary_text=summary_text,
        )

    except Exception as e:
        logger.error("Ingestion error", exc_info=True)
        yield IngestionError(error=str(e), stage="unknown")
