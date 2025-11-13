"""Data models and type definitions for repository ingestion."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, TypedDict

from pydantic import Field
from pydantic.dataclasses import dataclass as pydantic_dataclass

from typeagent.knowpro.interfaces import IMessageMetadata, IKnowledgeSource
from typeagent.knowpro.universal_message import ConversationMessage
from typeagent.knowpro import kplib


MessageType = Literal[
    "module", "class", "function", "method", "documentation", "configuration"
]


@pydantic_dataclass
class CodeMessageMeta(IKnowledgeSource, IMessageMetadata):
    file_path: str = Field(default="")
    message_type: MessageType = Field(default="module")
    imports: list[str] | None = Field(default=None)
    defined_classes: list[str] | None = Field(default=None)
    defined_functions: list[str] | None = Field(default=None)
    entity_name: str | None = Field(default=None)
    parent_entity: str | None = Field(default=None)
    decorators: list[str] | None = Field(default=None)
    parameters: list[str] | None = Field(default=None)
    file_type: str | None = Field(default=None)
    language: str | None = Field(default="python")
    module_path: str | None = Field(default=None)
    start_line: int | None = Field(default=None)
    end_line: int | None = Field(default=None)
    project_name: str | None = Field(default=None)
    inferred_types: list[str] | None = Field(default=None)
    references: list[dict] | None = Field(default=None)
    type_info: dict | None = Field(default=None)

    @property
    def source(self) -> str | None:
        """IMessageMetadata.source property."""
        return self.entity_name or self.file_path

    @property
    def dest(self) -> str | list[str] | None:
        """IMessageMetadata.dest property."""
        return None

    def get_knowledge(self) -> kplib.KnowledgeResponse:
        return kplib.KnowledgeResponse(
            entities=[], actions=[], inverse_actions=[], topics=[]
        )


CodeMessage = ConversationMessage


@dataclass
class ProgressUpdate:
    """Progress update for UI."""

    stage: str  # e.g., "discovering", "parsing", "indexing", "complete"
    message: str
    progress: float  # 0-100
    details: dict | None = None


@dataclass
class IngestOptions:
    """Options for repository ingestion."""

    output_db: Path | None = None
    exclude_dirs: list[str] = field(default_factory=list)
    verbose: bool = False
    emit_sidecar: bool = False
    sidecar_dir: Path | None = None
    project_name: str | None = None
    max_workers: int = 4
    no_index: bool = False


@dataclass
class IngestResult:
    """Result of repository ingestion."""

    files_processed: int
    messages_created: int
    symbols_indexed: int
    semrefs_added: int
    duration: float
    db_path: Path
    failures: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class ParsedPython:
    """Parsed Python file data."""

    file_path: str
    module_path: str
    module_docstring: str
    imports: list[str]
    classes: list[dict]
    functions: list[dict]
    calls: list[dict]
    source_code: str


class FileKind(TypedDict):
    """File classification."""

    path: Path
    kind: Literal["python", "documentation", "configuration"]
