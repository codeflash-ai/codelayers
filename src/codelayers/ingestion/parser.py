"""Python code parsing using LibCST."""

import asyncio
import logging
from pathlib import Path

import aiofiles
import libcst as cst
from libcst.metadata import MetadataWrapper, PositionProvider

from codelayers.ingestion.models import ParsedPython
from codelayers.ingestion.discovery import compute_module_path


logger = logging.getLogger(__name__)


class PythonExtractor(cst.CSTVisitor):
    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(self, module: cst.Module, module_path: str, rel_path: str):
        self.module = module
        self.module_path = module_path
        self.rel_path = rel_path
        self.class_stack: list[dict] = []
        self.function_stack: list[str] = []
        self.imports: list[str] = []
        self.classes: list[dict] = []
        self.functions: list[dict] = []
        self.calls: list[dict] = []
        self.module_docstring = ""

        # Extract module docstring
        if module.body and isinstance(module.body[0], cst.SimpleStatementLine):
            first_stmt = module.body[0].body[0]
            if isinstance(first_stmt, cst.Expr) and isinstance(
                first_stmt.value, cst.SimpleString
            ):
                self.module_docstring = first_stmt.value.evaluated_value

    def visit_Import(self, node: cst.Import) -> None:
        """Capture import statements."""
        if isinstance(node.names, cst.ImportStar):
            return
        for name in node.names:
            if isinstance(name, cst.ImportAlias):
                if isinstance(name.name, cst.Name):
                    mod_name = name.name.value
                elif isinstance(name.name, cst.Attribute):
                    mod_name = self._render_attribute(name.name)
                else:
                    mod_name = str(name.name)

                aspart = ""
                if name.asname:
                    if isinstance(name.asname.name, cst.Name):
                        aspart = f" as {name.asname.name.value}"
                    else:
                        aspart = f" as {name.asname.name}"

                self.imports.append(f"import {mod_name}{aspart}")

    def visit_ImportFrom(self, node: cst.ImportFrom) -> None:
        """Capture from...import statements."""
        relative = "." * len(node.relative) if node.relative else ""

        # Extract module name
        if node.module:
            if isinstance(node.module, cst.Name):
                module = node.module.value
            elif isinstance(node.module, cst.Attribute):
                module = self._render_attribute(node.module)
            else:
                module = str(node.module)
        else:
            module = ""

        mod_str = relative + module

        if isinstance(node.names, cst.ImportStar):
            self.imports.append(f"from {mod_str} import *")
        else:
            names = []
            for n in node.names:
                if isinstance(n, cst.ImportAlias):
                    # Extract imported name
                    if isinstance(n.name, cst.Name):
                        imp_name = n.name.value
                    else:
                        imp_name = str(n.name)

                    # Extract alias if present
                    alias = ""
                    if n.asname:
                        if isinstance(n.asname.name, cst.Name):
                            alias = f" as {n.asname.name.value}"
                        else:
                            alias = f" as {n.asname.name}"

                    names.append(imp_name + alias)
            if names:
                self.imports.append(f"from {mod_str} import {', '.join(names)}")

    def visit_ClassDef(self, node: cst.ClassDef) -> None:
        """Capture class definitions."""
        bases = [
            arg.value.value if isinstance(arg.value, cst.Name) else str(arg.value)
            for arg in node.bases
        ]
        decorators = []
        for d in node.decorators:
            if isinstance(d.decorator, cst.Name):
                decorators.append(d.decorator.value)
            elif isinstance(d.decorator, cst.Attribute):
                decorators.append(self._render_attribute(d.decorator))
            elif isinstance(d.decorator, cst.Call):
                # Handle decorators with arguments like @dataclass(frozen=True)
                if isinstance(d.decorator.func, cst.Name):
                    decorators.append(d.decorator.func.value)
                elif isinstance(d.decorator.func, cst.Attribute):
                    decorators.append(self._render_attribute(d.decorator.func))
            else:
                decorators.append(str(d.decorator))
        doc = node.get_docstring() or ""

        try:
            pos = self.get_metadata(PositionProvider, node)
            start_line = pos.start.line
            end_line = pos.end.line
        except:
            start_line = end_line = None

        # Get code body (truncate if too large)
        code_body = self.module.code_for_node(node)
        if len(code_body) > 10000:
            code_body = code_body[:10000] + "\n... (truncated)"

        cls = {
            "name": node.name.value,
            "docstring": doc,
            "bases": bases,
            "decorators": decorators,
            "methods": [],
            "code_body": code_body,
            "pos": {"start": start_line, "end": end_line},
        }
        self.classes.append(cls)
        self.class_stack.append(cls)

    def leave_ClassDef(self, node: cst.ClassDef) -> None:
        """Leave class context."""
        if self.class_stack:
            self.class_stack.pop()

    def visit_FunctionDef(self, node: cst.FunctionDef) -> None:
        """Capture function/method definitions."""
        decorators = []
        for d in node.decorators:
            if isinstance(d.decorator, cst.Name):
                decorators.append(d.decorator.value)
            elif isinstance(d.decorator, cst.Attribute):
                decorators.append(self._render_attribute(d.decorator))
            elif isinstance(d.decorator, cst.Call):
                # Handle decorators with arguments
                if isinstance(d.decorator.func, cst.Name):
                    decorators.append(d.decorator.func.value)
                elif isinstance(d.decorator.func, cst.Attribute):
                    decorators.append(self._render_attribute(d.decorator.func))
            else:
                decorators.append(str(d.decorator))
        doc = node.get_docstring() or ""
        is_async = node.asynchronous is not None

        # Build signature
        params = []
        if node.params.params:
            params.extend([p.name.value for p in node.params.params])
        if node.params.kwonly_params:
            params.append("*")
            params.extend([p.name.value for p in node.params.kwonly_params])
        if node.params.star_arg:
            # star_arg can be a Param or StarArg
            if hasattr(node.params.star_arg, "name"):
                param_name = node.params.star_arg.name
                if isinstance(param_name, cst.Name):
                    params.append(f"*{param_name.value}")
                else:
                    params.append(f"*{param_name}")
        if node.params.star_kwarg:
            # star_kwarg is a Param
            if hasattr(node.params.star_kwarg, "name"):
                param_name = node.params.star_kwarg.name
                if isinstance(param_name, cst.Name):
                    params.append(f"**{param_name.value}")
                else:
                    params.append(f"**{param_name}")

        ret_annotation = None
        if node.returns:
            if isinstance(node.returns.annotation, cst.Name):
                ret_annotation = node.returns.annotation.value
            elif isinstance(node.returns.annotation, cst.Attribute):
                ret_annotation = self._render_attribute(node.returns.annotation)
            else:
                # For complex annotations, get the code representation
                ret_annotation = self.module.code_for_node(
                    node.returns.annotation
                ).strip()

        sig = (
            f"{'async ' if is_async else ''}def {node.name.value}({', '.join(params)})"
        )
        if ret_annotation:
            sig += f" -> {ret_annotation}"

        try:
            pos = self.get_metadata(PositionProvider, node)
            start_line = pos.start.line
            end_line = pos.end.line
        except:
            start_line = end_line = None

        # Get code body (truncate if too large)
        code_body = self.module.code_for_node(node)
        if len(code_body) > 10000:
            code_body = code_body[:10000] + "\n... (truncated)"

        fn = {
            "name": node.name.value,
            "docstring": doc,
            "signature": sig,
            "decorators": decorators,
            "parameters": params,
            "return_annotation": ret_annotation,
            "code_body": code_body,
            "pos": {"start": start_line, "end": end_line},
        }

        if self.class_stack:
            # It's a method
            self.class_stack[-1]["methods"].append(fn)
        else:
            # It's a top-level function
            self.functions.append(fn)

        self.function_stack.append(node.name.value)

    def leave_FunctionDef(self, node: cst.FunctionDef) -> None:
        """Leave function context."""
        if self.function_stack:
            self.function_stack.pop()

    def visit_Call(self, node: cst.Call) -> None:
        """Capture function calls for call graph."""
        callee_text = None
        if isinstance(node.func, cst.Name):
            callee_text = node.func.value
        elif isinstance(node.func, cst.Attribute):
            callee_text = self._render_attribute(node.func)

        if callee_text:
            # Determine caller context
            caller_id = None
            if self.function_stack:
                if self.class_stack:
                    caller_id = f"{self.module_path}:{self.class_stack[-1]['name']}.{self.function_stack[-1]}"
                else:
                    caller_id = f"{self.module_path}:{self.function_stack[-1]}"

            try:
                pos = self.get_metadata(PositionProvider, node)
                line = pos.start.line
            except:
                line = None

            if caller_id and line:
                self.calls.append(
                    {"caller": caller_id, "callee": callee_text, "line": line}
                )

    def _render_attribute(self, node: cst.Attribute) -> str:
        """Render dotted attribute access."""
        parts = [node.attr.value]
        current = node.value
        while isinstance(current, cst.Attribute):
            parts.insert(0, current.attr.value)
            current = current.value
        if isinstance(current, cst.Name):
            parts.insert(0, current.value)
        return ".".join(parts)


# =============================================================================
# Parsing Functions
# =============================================================================


def _parse_with_libcst(
    source: str, file_path: Path, repo_path: Path
) -> ParsedPython | None:
    try:
        module = cst.parse_module(source)

        rel_path = str(file_path.relative_to(repo_path))
        module_path = compute_module_path(file_path, repo_path)

        # Wrap with metadata
        wrapper = MetadataWrapper(module)
        extractor = PythonExtractor(module, module_path, rel_path)
        wrapper.visit(extractor)

        return ParsedPython(
            file_path=rel_path,
            module_path=module_path,
            module_docstring=extractor.module_docstring,
            imports=extractor.imports,
            classes=extractor.classes,
            functions=extractor.functions,
            calls=extractor.calls,
            source_code=source,
        )

    except cst.ParserSyntaxError as e:
        logger.warning(f"Syntax error parsing {file_path.name}: {e}")
        return None
    except Exception as e:
        logger.warning(f"Error parsing {file_path.name}: {e}")
        import traceback

        traceback.print_exc()
        return None


async def parse_python_file(file_path: Path, repo_path: Path) -> ParsedPython | None:
    try:
        async with aiofiles.open(
            file_path, "r", encoding="utf-8", errors="replace"
        ) as f:
            source = await f.read()

        parsed = await asyncio.to_thread(
            _parse_with_libcst, source, file_path, repo_path
        )
        return parsed

    except Exception as e:
        logger.warning(f"Error reading/parsing {file_path.name}: {e}")
        return None
