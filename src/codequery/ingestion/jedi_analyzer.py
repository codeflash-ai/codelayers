"""Jedi-based type inference and reference analysis."""

import asyncio
import logging
from pathlib import Path
import aiofiles

import jedi

from codequery.ingestion.models import ParsedPython


logger = logging.getLogger(__name__)


class JediAnalysis:
    """Enhanced analysis data from Jedi."""
    
    def __init__(
        self,
        file_path: str,
        module_path: str,
        type_annotations: dict[str, dict],  # symbol -> {type, inferred_type, line}
        references: dict[str, list[dict]],  # symbol -> [{file, line, context}]
        definitions: dict[str, dict],  # symbol -> {file, line, type}
    ):
        self.file_path = file_path
        self.module_path = module_path
        self.type_annotations = type_annotations
        self.references = references
        self.definitions = definitions


def _analyze_with_jedi(
    source: str,
    file_path: Path,
    repo_path: Path,
    parsed_data: ParsedPython,
) -> JediAnalysis | None:
    """
    Use Jedi to perform type inference and reference analysis.
    
    Args:
        source: Source code content
        file_path: Path to the file being analyzed
        repo_path: Repository root path
        parsed_data: Previously parsed data from LibCST
        
    Returns:
        JediAnalysis with type information and references
    """
    try:
        # Create Jedi project for better context
        project = jedi.Project(path=repo_path)
        script = jedi.Script(source, path=file_path, project=project)
        
        type_annotations: dict[str, dict] = {}
        references: dict[str, list[dict]] = {}
        definitions: dict[str, dict] = {}
        
        # Get all names in the file for comprehensive analysis
        names = script.get_names(all_scopes=True, definitions=True, references=True)
        
        for name in names:
            try:
                symbol_key = name.full_name or name.name
                
                # Store definition information
                if name.is_definition():
                    definitions[symbol_key] = {
                        "name": name.name,
                        "type": name.type,
                        "line": name.line,
                        "column": name.column,
                        "full_name": name.full_name,
                        "description": name.description if hasattr(name, "description") else None,
                    }
                    
                    inferred_types = [name.type] if name.type else []
                    
                    type_annotations[symbol_key] = {
                        "name": name.name,
                        "declared_type": name.type,
                        "inferred_types": inferred_types,
                        "line": name.line,
                        "column": name.column,
                    }
                
                # Track references (usages of symbols)
                else:
                    if symbol_key not in references:
                        references[symbol_key] = []
                    
                    references[symbol_key].append({
                        "line": name.line,
                        "column": name.column,
                        "context": name.get_line_code() if hasattr(name, "get_line_code") else "",
                    })
                    
            except Exception as e:
                logger.debug(f"Error analyzing name {name.name}: {e}")
                continue
        
        # Enhance function/method type annotations
        for func in parsed_data.functions:
            _enhance_function_types(script, func, type_annotations)
        
        for cls in parsed_data.classes:
            for method in cls.get("methods", []):
                _enhance_function_types(script, method, type_annotations)
        
        rel_path = str(file_path.relative_to(repo_path))
        return JediAnalysis(
            file_path=rel_path,
            module_path=parsed_data.module_path,
            type_annotations=type_annotations,
            references=references,
            definitions=definitions,
        )
        
    except jedi.InvalidPythonEnvironment as e:
        logger.warning(f"Invalid Python environment for {file_path.name}: {e}")
        return None
    except Exception as e:
        logger.warning(f"Error in Jedi analysis for {file_path.name}: {e}")
        return None


def _enhance_function_types(
    script: jedi.Script,
    func_data: dict,
    type_annotations: dict[str, dict],
) -> None:
    """
    Enhance function/method with inferred parameter and return types.
    
    Args:
        script: Jedi Script instance
        func_data: Function data dictionary from LibCST parser
        type_annotations: Dictionary to update with type information
    """
    try:
        func_name = func_data["name"]
        start_line = func_data.get("pos", {}).get("start")
        
        if not start_line:
            return
        
        # Try to get function definition from Jedi
        names = script.get_names(all_scopes=True, definitions=True)
        func_names = [n for n in names if n.name == func_name and n.line == start_line]
        
        if not func_names:
            return
        
        func_name_obj = func_names[0]
        
        # Get signatures to infer parameter types
        try:
            signatures = script.get_signatures(line=start_line, column=len(f"def {func_name}"))
            if signatures:
                sig = signatures[0]
                for param in sig.params:
                    param_key = f"{func_data['name']}.{param.name}"
                    
                    # Try to infer the parameter type
                    inferred_type = param.infer_annotation()
                    type_str = str(inferred_type) if inferred_type else None
                    
                    type_annotations[param_key] = {
                        "name": param.name,
                        "declared_type": "parameter",
                        "inferred_types": [type_str] if type_str else [],
                        "line": start_line,
                        "description": param.description if hasattr(param, "description") else None,
                    }
        except Exception as e:
            logger.debug(f"Could not get signatures for {func_name}: {e}")
        
        if func_data.get("return_annotation"):
            return_key = f"{func_data['name']}.__return__"
            type_annotations[return_key] = {
                "name": "__return__",
                "declared_type": func_data.get("return_annotation"),
                "inferred_types": [],
                "line": start_line,
            }
            
    except Exception as e:
        logger.debug(f"Error enhancing function types: {e}")


async def analyze_python_file_with_jedi(
    file_path: Path,
    repo_path: Path,
    parsed_data: ParsedPython,
) -> JediAnalysis | None:
    try:
        
        async with aiofiles.open(file_path, "r", encoding="utf-8", errors="replace") as f:
            source = await f.read()
        
        # Run Jedi analysis in thread pool to avoid blocking
        analysis = await asyncio.to_thread(
            _analyze_with_jedi,
            source,
            file_path,
            repo_path,
            parsed_data,
        )
        return analysis
        
    except Exception as e:
        logger.warning(f"Error in async Jedi analysis for {file_path.name}: {e}")
        return None
