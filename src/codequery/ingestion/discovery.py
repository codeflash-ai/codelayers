"""File discovery and classification for repository ingestion."""

from pathlib import Path

from codequery.ingestion.models import FileKind


# =============================================================================
# Constants
# =============================================================================

DEFAULT_EXCLUDE_DIRS = {
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "node_modules",
    ".pytest_cache",
    ".mypy_cache",
    ".tox",
    "dist",
    "build",
    "env",
    ".eggs",
    "*.egg-info",
    ".ruff_cache",
    ".hypothesis",
}

PYTHON_EXTS = {".py"}
DOC_EXTS = {".md", ".rst", ".txt"}
CONFIG_FILES = {
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "requirements.txt",
    "Pipfile",
    "poetry.lock",
    "tox.ini",
    "pytest.ini",
}

def discover_files(repo_path: Path, extra_excludes: list[str] = None) -> list[FileKind]:
    """
    Discover relevant files in the repository.

    Args:
        repo_path: Root path of the repository
        extra_excludes: Additional directory patterns to exclude

    Returns:
        List of (path, kind) tuples with repo-relative paths
    """
    excludes = DEFAULT_EXCLUDE_DIRS.copy()
    if extra_excludes:
        excludes.update(extra_excludes)

    files: list[FileKind] = []

    for path in repo_path.rglob("*"):
        # Skip if in excluded directory
        if any(excl in path.parts for excl in excludes):
            continue

        if not path.is_file():
            continue

        # Classify file
        if path.suffix in PYTHON_EXTS:
            files.append({"path": path, "kind": "python"})
        elif path.suffix in DOC_EXTS:
            files.append({"path": path, "kind": "documentation"})
        elif path.name in CONFIG_FILES:
            files.append({"path": path, "kind": "configuration"})

    return files


def compute_module_path(file_path: Path, repo_path: Path) -> str:
    """
    Compute Python module path from file path.

    Treats directories with __init__.py as packages.
    """
    rel_path = file_path.relative_to(repo_path)
    parts = list(rel_path.parts[:-1])  # exclude filename

    # Add filename without extension if not __init__
    if rel_path.stem != "__init__":
        parts.append(rel_path.stem)

    return ".".join(parts) if parts else rel_path.stem
