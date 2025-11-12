"""Message creation from parsed code for Typeagent conversation."""

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from typeagent.knowpro.universal_message import ConversationMessageMeta

from codequery.ingestion.models import CodeMessage, ParsedPython

if TYPE_CHECKING:
    from codequery.ingestion.jedi_analyzer import JediAnalysis


logger = logging.getLogger(__name__)


# =============================================================================
# Message Creation
# =============================================================================


def create_module_message(
    parsed: ParsedPython, project_name: str | None
) -> CodeMessage:
    """Create a module-level message."""
    chunks = []

    # Module docstring
    if parsed.module_docstring:
        chunks.append(f"Module docstring:\n{parsed.module_docstring}")
    else:
        chunks.append("No module docstring")

    # Imports
    if parsed.imports:
        chunks.append("Imports:\n" + "\n".join(parsed.imports))

    # Overview
    class_names = [c["name"] for c in parsed.classes]
    func_names = [f["name"] for f in parsed.functions]
    overview_parts = []
    if class_names:
        overview_parts.append(f"Classes: {', '.join(class_names)}")
    if func_names:
        overview_parts.append(f"Functions: {', '.join(func_names)}")
    if overview_parts:
        chunks.append("Overview:\n" + "\n".join(overview_parts))

    # Filter out empty chunks
    chunks = [c for c in chunks if c and c.strip()]

    # Use ConversationMessageMeta
    metadata = ConversationMessageMeta(
        speaker=parsed.module_path or parsed.file_path, recipients=[]
    )

    return CodeMessage(
        text_chunks=chunks,
        metadata=metadata,
        tags=["module", "python", project_name or ""],
    )


def parse_text_file(
    file_path: Path, repo_path: Path, kind: str, project_name: str | None
) -> CodeMessage:
    """Create a message from a text/documentation file."""
    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")

        # Skip if content is empty
        if not content or not content.strip():
            return None

        rel_path = str(file_path.relative_to(repo_path))

        # Truncate if too large
        if len(content) > 50000:
            content = content[:50000] + "\n... (truncated)"

        metadata = ConversationMessageMeta(speaker=rel_path, recipients=[])

        return CodeMessage(
            text_chunks=[content],
            metadata=metadata,
            tags=[kind, file_path.suffix, rel_path],
        )

    except Exception as e:
        logger.warning(f"Error reading {file_path.name}: {e}")
        return None


def create_entity_messages_with_jedi(
    parsed: ParsedPython,
    jedi_analysis: "JediAnalysis | None",
    project_name: str | None,
) -> list[CodeMessage]:
    """
    Create enhanced messages with Jedi type information.

    Args:
        parsed: Parsed Python data from LibCST
        jedi_analysis: Jedi analysis results with type information (None if analysis failed)
        project_name: Name of the project

    Returns:
        List of enhanced CodeMessage objects
    """
    messages = []

    # If Jedi analysis is None, use empty containers
    if jedi_analysis is None:
        jedi_analysis = type(
            "EmptyJediAnalysis",
            (),
            {"type_annotations": {}, "references": {}, "definitions": {}},
        )()

    # Class messages with type info
    for cls in parsed.classes:
        chunks = []

        # Docstring
        if cls["docstring"]:
            chunks.append(cls["docstring"])

        # Class definition with bases
        bases_str = f"({', '.join(cls['bases'])})" if cls["bases"] else ""
        chunks.append(f"class {cls['name']}{bases_str}")

        # Add type information from Jedi if available
        cls_key = f"{parsed.module_path}.{cls['name']}"
        if cls_key in jedi_analysis.type_annotations:
            type_info = jedi_analysis.type_annotations[cls_key]
            if type_info.get("inferred_types"):
                chunks.append(f"Type: {', '.join(type_info['inferred_types'])}")

        # Add reference count
        if cls_key in jedi_analysis.references:
            ref_count = len(jedi_analysis.references[cls_key])
            chunks.append(f"Referenced {ref_count} times in codebase")

        chunks.append(cls["code_body"])

        # Filter out empty chunks
        chunks = [c for c in chunks if c and c.strip()]

        if not chunks:
            continue

        metadata = ConversationMessageMeta(
            speaker=f"{parsed.module_path}:{cls['name']}",
            recipients=[],
        )

        messages.append(
            CodeMessage(
                text_chunks=chunks,
                metadata=metadata,
                tags=["class", "python", cls["name"], parsed.module_path],
            )
        )

        # Method messages with type info
        for method in cls["methods"]:
            method_chunks = []

            if method["docstring"]:
                method_chunks.append(method["docstring"])

            method_chunks.append(method["signature"])

            # Add parameter type information
            method_key = f"{parsed.module_path}.{cls['name']}.{method['name']}"
            param_info = []
            for param in method.get("parameters", []):
                param_key = f"{method['name']}.{param}"
                if param_key in jedi_analysis.type_annotations:
                    type_data = jedi_analysis.type_annotations[param_key]
                    if type_data.get("inferred_types"):
                        param_info.append(
                            f"  {param}: {', '.join(type_data['inferred_types'])}"
                        )

            if param_info:
                method_chunks.append(
                    "Inferred parameter types:\n" + "\n".join(param_info)
                )

            method_chunks.append(method["code_body"])

            # Filter out empty chunks
            method_chunks = [c for c in method_chunks if c and c.strip()]

            if not method_chunks:
                continue

            method_metadata = ConversationMessageMeta(
                speaker=f"{parsed.module_path}:{cls['name']}.{method['name']}",
                recipients=[],
            )

            messages.append(
                CodeMessage(
                    text_chunks=method_chunks,
                    metadata=method_metadata,
                    tags=["method", "python", method["name"], cls["name"]],
                )
            )

    # Function messages with type info
    for func in parsed.functions:
        chunks = []

        if func["docstring"]:
            chunks.append(func["docstring"])

        chunks.append(func["signature"])

        # Add parameter type information
        func_key = f"{parsed.module_path}.{func['name']}"
        param_info = []
        for param in func.get("parameters", []):
            param_key = f"{func['name']}.{param}"
            if param_key in jedi_analysis.type_annotations:
                type_data = jedi_analysis.type_annotations[param_key]
                if type_data.get("inferred_types"):
                    param_info.append(
                        f"  {param}: {', '.join(type_data['inferred_types'])}"
                    )

        if param_info:
            chunks.append("Inferred parameter types:\n" + "\n".join(param_info))

        # Add return type if available
        return_key = f"{func['name']}.__return__"
        if return_key in jedi_analysis.type_annotations:
            ret_data = jedi_analysis.type_annotations[return_key]
            if ret_data.get("declared_type"):
                chunks.append(f"Return type: {ret_data['declared_type']}")

        chunks.append(func["code_body"])

        # Filter out empty chunks
        chunks = [c for c in chunks if c and c.strip()]

        if not chunks:
            continue

        metadata = ConversationMessageMeta(
            speaker=f"{parsed.module_path}:{func['name']}",
            recipients=[],
        )

        messages.append(
            CodeMessage(
                text_chunks=chunks,
                metadata=metadata,
                tags=["function", "python", func["name"], parsed.module_path],
            )
        )

    return messages
