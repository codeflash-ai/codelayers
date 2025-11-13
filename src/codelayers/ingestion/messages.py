"""Message creation from parsed code for Typeagent conversation."""

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from typeagent.knowpro.universal_message import ConversationMessageMeta

from codelayers.ingestion.models import CodeMessage, ParsedPython

if TYPE_CHECKING:
    from codelayers.ingestion.jedi_analyzer import JediAnalysis


logger = logging.getLogger(__name__)


# =============================================================================
# Message Creation
# =============================================================================


def create_module_message(
    parsed: ParsedPython, project_name: str | None
) -> CodeMessage:
    """Create a module-level message with the expected chunk layout."""

    if parsed.module_docstring:
        summary_text = f"Module docstring:\n{parsed.module_docstring.strip()}"
    else:
        summary_text = "Module docstring: (none provided)"

    detail_sections: list[str] = []
    if parsed.imports:
        detail_sections.append("Imports:\n" + "\n".join(parsed.imports))

    class_names = [c["name"] for c in parsed.classes]
    func_names = [f["name"] for f in parsed.functions]
    overview_parts = []
    if class_names:
        overview_parts.append(f"Classes: {', '.join(class_names)}")
    if func_names:
        overview_parts.append(f"Functions: {', '.join(func_names)}")
    if overview_parts:
        detail_sections.append("Overview:\n" + "\n".join(overview_parts))

    detail_text = "\n\n".join(s for s in detail_sections if s.strip())
    if not detail_text:
        detail_text = "No imports or symbol overview available."

    code_text = parsed.source_code or ""
    if code_text and len(code_text) > 50000:
        code_text = code_text[:50000] + "\n... (truncated)"
    if not code_text.strip():
        code_text = "Module source unavailable."

    metadata = ConversationMessageMeta(
        speaker=parsed.module_path or parsed.file_path,
        recipients=[],
    )

    return CodeMessage(
        text_chunks=[summary_text, detail_text, code_text],
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

        summary_bits: list[str] = []
        if cls["docstring"] and cls["docstring"].strip():
            summary_bits.append(cls["docstring"].strip())

        cls_key = f"{parsed.module_path}.{cls['name']}"
        if cls_key in jedi_analysis.type_annotations:
            type_info = jedi_analysis.type_annotations[cls_key]
            inferred = [t for t in type_info.get("inferred_types", []) if t]
            if inferred:
                summary_bits.append(f"Type hints: {', '.join(inferred)}")

        if cls_key in jedi_analysis.references:
            ref_count = len(jedi_analysis.references[cls_key])
            summary_bits.append(f"Referenced {ref_count} time(s) in codebase")

        if cls.get("decorators"):
            summary_bits.append(
                "Decorators: " + ", ".join(d for d in cls["decorators"] if d)
            )

        summary_text = "\n\n".join(bit for bit in summary_bits if bit)
        if not summary_text:
            summary_text = f"Class {cls['name']} summary unavailable."

        bases_str = f"({', '.join(cls['bases'])})" if cls["bases"] else ""
        signature_text = f"class {cls['name']}{bases_str}".strip()
        if not signature_text:
            signature_text = f"class {cls['name']}"

        code_text = cls["code_body"] or ""
        if not code_text.strip():
            code_text = f"class {cls['name']} body unavailable."

        metadata = ConversationMessageMeta(
            speaker=f"{parsed.module_path}:{cls['name']}",
            recipients=[],
        )

        messages.append(
            CodeMessage(
                text_chunks=[summary_text, signature_text, code_text],
                metadata=metadata,
                tags=["class", "python", cls["name"], parsed.module_path],
            )
        )

        # Method messages with type info
        for method in cls["methods"]:
            summary_bits: list[str] = []
            if method["docstring"] and method["docstring"].strip():
                summary_bits.append(method["docstring"].strip())

            method_key = f"{parsed.module_path}.{cls['name']}.{method['name']}"
            param_info = []
            for param in method.get("parameters", []):
                param_key = f"{method['name']}.{param}"
                if param_key in jedi_analysis.type_annotations:
                    type_data = jedi_analysis.type_annotations[param_key]
                    inferred = [t for t in type_data.get("inferred_types", []) if t]
                    if inferred:
                        param_info.append(f"{param}: {', '.join(inferred)}")

            if param_info:
                summary_bits.append(
                    "Inferred parameter types:\n" + "\n".join(param_info)
                )

            summary_text = "\n\n".join(bit for bit in summary_bits if bit)
            if not summary_text:
                summary_text = f"Method {method['name']} summary unavailable."

            signature_text = method["signature"].strip() or method["name"]

            code_text = method["code_body"] or ""
            if not code_text.strip():
                code_text = f"Method {method['name']} body unavailable."

            method_metadata = ConversationMessageMeta(
                speaker=f"{parsed.module_path}:{cls['name']}.{method['name']}",
                recipients=[],
            )

            messages.append(
                CodeMessage(
                    text_chunks=[summary_text, signature_text, code_text],
                    metadata=method_metadata,
                    tags=["method", "python", method["name"], cls["name"]],
                )
            )

    # Function messages with type info
    for func in parsed.functions:
        summary_bits: list[str] = []
        if func["docstring"] and func["docstring"].strip():
            summary_bits.append(func["docstring"].strip())

        func_key = f"{parsed.module_path}.{func['name']}"
        param_info = []
        for param in func.get("parameters", []):
            param_key = f"{func['name']}.{param}"
            if param_key in jedi_analysis.type_annotations:
                type_data = jedi_analysis.type_annotations[param_key]
                inferred = [t for t in type_data.get("inferred_types", []) if t]
                if inferred:
                    param_info.append(f"{param}: {', '.join(inferred)}")

        if param_info:
            summary_bits.append("Inferred parameter types:\n" + "\n".join(param_info))

        return_key = f"{func['name']}.__return__"
        if return_key in jedi_analysis.type_annotations:
            ret_data = jedi_analysis.type_annotations[return_key]
            if ret_data.get("declared_type"):
                summary_bits.append(f"Return type: {ret_data['declared_type']}")

        summary_text = "\n\n".join(bit for bit in summary_bits if bit)
        if not summary_text:
            summary_text = f"Function {func['name']} summary unavailable."

        signature_text = func["signature"].strip() or func["name"]

        code_text = func["code_body"] or ""
        if not code_text.strip():
            code_text = f"Function {func['name']} body unavailable."

        metadata = ConversationMessageMeta(
            speaker=f"{parsed.module_path}:{func['name']}",
            recipients=[],
        )

        messages.append(
            CodeMessage(
                text_chunks=[summary_text, signature_text, code_text],
                metadata=metadata,
                tags=["function", "python", func["name"], parsed.module_path],
            )
        )

    return messages
