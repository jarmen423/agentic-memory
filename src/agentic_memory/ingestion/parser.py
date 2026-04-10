"""Tree-sitter-backed code extraction for the code-memory graph.

This module is the canonical structural extraction layer for code ingestion.
`KnowledgeGraphBuilder` should ask this parser for definitions, imports, and
per-function calls instead of re-implementing language-specific heuristics in
multiple places.

Why this exists:
- The old graph builder parsed each file in several different ways.
- Import extraction and call extraction used different logic paths.
- The call graph was especially noisy because file-level calls were copied onto
  every function in the file.

The parser now returns a single structured view of one source file so graph
ingestion can decide which relationships are safe to write.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, Iterator, List

from tree_sitter import Language, Node, Parser, Tree
import tree_sitter_javascript
import tree_sitter_python

logger = logging.getLogger(__name__)

class CodeParser:
    """Parse Python and JS-like source files into a normalized structure.

    Supported extensions:
    - `.py`
    - `.js`
    - `.jsx`
    - `.ts`
    - `.tsx`

    TypeScript and TSX currently use the JavaScript grammar available in this
    repo. That means extraction is "best effort" for TS-only syntax, but the
    parser still covers the common declaration shapes we need for graph quality:
    class methods, function declarations, arrow functions assigned to names, and
    function expressions assigned to names.
    """

    SUPPORTED_JS_EXTENSIONS = frozenset({".js", ".jsx", ".ts", ".tsx"})

    def __init__(self) -> None:
        """Initialize and cache one parser per supported extension."""
        self.parsers: dict[str, Parser] = {}
        self.languages: dict[str, Language] = {}
        self._init_parsers()

    def _init_parsers(self) -> None:
        """Create parser instances for each supported language."""
        try:
            python_language = Language(tree_sitter_python.language())
            self.languages[".py"] = python_language
            self.parsers[".py"] = Parser(python_language)

            javascript_language = Language(tree_sitter_javascript.language())
            for extension in self.SUPPORTED_JS_EXTENSIONS:
                self.languages[extension] = javascript_language
                self.parsers[extension] = Parser(javascript_language)
        except (ImportError, RuntimeError) as exc:
            logger.error("Failed to initialize tree-sitter parsers: %s", exc)

    def parse_file(self, code: str, extension: str) -> Dict[str, Any]:
        """Parse one source file into normalized graph-ingestion data.

        Returns:
            Dict with:
            - `classes`: `[{name, code, start_line}]`
            - `functions`: `[{name, qualified_name, parent_class, code, start_line, calls}]`
            - `imports`: `[module_specifier, ...]`
            - `calls`: flattened call-name list across the file
            - `env_vars`: Python env-var reads / dotenv loads
            - `diagnostics`: non-fatal extraction notes for unsupported syntax
        """
        default_result = {
            "classes": [],
            "functions": [],
            "imports": [],
            "calls": [],
            "env_vars": [],
            "diagnostics": [],
        }

        parser = self.parsers.get(extension)
        language = self.languages.get(extension)
        if parser is None or language is None:
            logger.warning("No parser configured for extension %s", extension)
            default_result["diagnostics"].append(
                {
                    "level": "warning",
                    "kind": "unsupported_extension",
                    "message": f"No parser configured for extension {extension}",
                }
            )
            return default_result

        try:
            tree = parser.parse(code.encode("utf8"))
        except (RuntimeError, ValueError, TypeError) as exc:
            logger.error("Failed to parse %s source: %s", extension, exc)
            default_result["diagnostics"].append(
                {
                    "level": "error",
                    "kind": "parse_error",
                    "message": str(exc),
                }
            )
            return default_result

        if extension == ".py":
            result = self._parse_python(tree, code)
        else:
            result = self._parse_javascript_like(tree, code)

        result["calls"] = [call for fn in result["functions"] for call in fn["calls"]]
        return result

    def _parse_python(self, tree: Tree, code: str) -> Dict[str, Any]:
        """Extract Python classes, functions, imports, calls, and env-var usage."""
        classes: list[dict[str, Any]] = []
        functions: list[dict[str, Any]] = []
        imports: list[str] = []
        env_vars: list[dict[str, Any]] = []
        diagnostics: list[dict[str, Any]] = []

        for node in self._walk(tree.root_node):
            if node.type == "class_definition":
                class_name = self._identifier_text(node, code)
                if class_name:
                    classes.append(
                        {
                            "name": class_name,
                            "code": self._node_text(node, code),
                            "start_line": node.start_point[0] + 1,
                        }
                    )
                continue

            if node.type == "function_definition":
                function_name = self._identifier_text(node, code)
                if not function_name:
                    continue

                parent_class = self._python_parent_class(node, code)
                qualified_name = (
                    f"{parent_class}.{function_name}" if parent_class else function_name
                )
                functions.append(
                    {
                        "name": function_name,
                        "qualified_name": qualified_name,
                        "parent_class": parent_class,
                        "code": self._node_text(node, code),
                        "start_line": node.start_point[0] + 1,
                        "calls": self._extract_python_calls(node, code),
                    }
                )
                continue

            if node.type == "import_statement":
                module_name = self._dotted_name_text(node, code)
                if module_name:
                    imports.append(module_name)
                continue

            if node.type == "import_from_statement":
                module_name = self._python_from_import_module(node, code)
                if module_name:
                    imports.append(module_name)
                else:
                    diagnostics.append(
                        {
                            "level": "info",
                            "kind": "ambiguous_import",
                            "message": self._node_text(node, code),
                        }
                    )
                continue

            env_var_event = self._extract_python_env_var_event(node, code)
            if env_var_event is not None:
                env_vars.append(env_var_event)

        return {
            "classes": classes,
            "functions": functions,
            "imports": self._stable_dedupe(imports),
            "calls": [],
            "env_vars": env_vars,
            "diagnostics": diagnostics,
        }

    def _parse_javascript_like(self, tree: Tree, code: str) -> Dict[str, Any]:
        """Extract JavaScript/JSX/TS/TSX structure using the JS grammar."""
        classes: list[dict[str, Any]] = []
        functions: list[dict[str, Any]] = []
        imports: list[str] = []
        diagnostics: list[dict[str, Any]] = []

        for node in self._walk(tree.root_node):
            if node.type == "class_declaration":
                class_name = self._identifier_text(node, code)
                if class_name:
                    classes.append(
                        {
                            "name": class_name,
                            "code": self._node_text(node, code),
                            "start_line": node.start_point[0] + 1,
                        }
                    )
                continue

            if node.type == "function_declaration":
                function_name = self._identifier_text(node, code)
                if function_name:
                    functions.append(
                        {
                            "name": function_name,
                            "qualified_name": function_name,
                            "parent_class": "",
                            "code": self._node_text(node, code),
                            "start_line": node.start_point[0] + 1,
                            "calls": self._extract_js_calls(node, code),
                        }
                    )
                continue

            if node.type == "method_definition":
                method_name = self._js_method_name(node, code)
                if not method_name:
                    continue

                parent_class = self._js_parent_class(node, code)
                qualified_name = f"{parent_class}.{method_name}" if parent_class else method_name
                functions.append(
                    {
                        "name": method_name,
                        "qualified_name": qualified_name,
                        "parent_class": parent_class,
                        "code": self._node_text(node, code),
                        "start_line": node.start_point[0] + 1,
                        "calls": self._extract_js_calls(node, code),
                    }
                )
                continue

            if node.type == "variable_declarator":
                variable_function = self._js_variable_function(node, code)
                if variable_function is not None:
                    functions.append(variable_function)
                continue

            import_value = self._extract_js_import(node, code)
            if import_value is not None:
                imports.append(import_value)
                continue

        return {
            "classes": classes,
            "functions": self._dedupe_function_rows(functions),
            "imports": self._stable_dedupe(imports),
            "calls": [],
            "env_vars": [],
            "diagnostics": diagnostics,
        }

    def _extract_python_calls(self, owner: Node, code: str) -> list[str]:
        """Return call names that belong to one Python function or method."""
        call_names: list[str] = []
        for node in self._walk_owned_descendants(
            owner,
            skip_types={"function_definition", "class_definition"},
        ):
            if node.type != "call":
                continue
            callee = node.child_by_field_name("function")
            call_name = self._callee_name(callee, code)
            if call_name:
                call_names.append(call_name)
        return self._stable_dedupe(call_names)

    def _extract_js_calls(self, owner: Node, code: str) -> list[str]:
        """Return call names that belong to one JS function-like owner."""
        call_names: list[str] = []
        for node in self._walk_owned_descendants(
            owner,
            skip_types={
                "function_declaration",
                "function_expression",
                "arrow_function",
                "method_definition",
                "class_declaration",
            },
        ):
            if node.type != "call_expression":
                continue
            callee = node.child_by_field_name("function")
            call_name = self._callee_name(callee, code)
            if call_name and call_name != "import":
                call_names.append(call_name)
        return self._stable_dedupe(call_names)

    def _extract_python_env_var_event(
        self,
        node: Node,
        code: str,
    ) -> dict[str, Any] | None:
        """Detect a narrow set of Python env-var access patterns."""
        if node.type != "call":
            return None

        callee = node.child_by_field_name("function")
        if callee is None:
            return None

        callee_name = self._full_callee_name(callee, code)
        if callee_name == "load_dotenv":
            return {"type": "load", "line": callee.start_point[0] + 1}

        if callee_name not in {"os.getenv", "os.environ.get"}:
            return None

        args_node = node.child_by_field_name("arguments")
        if args_node is None:
            return None

        for child in args_node.children:
            if child.type == "string":
                return {
                    "type": "read",
                    "name": self._string_literal_value(child, code),
                    "line": child.start_point[0] + 1,
                }
        return None

    def _python_from_import_module(self, node: Node, code: str) -> str:
        """Return the module portion of a Python `from ... import ...` statement."""
        for child in node.children:
            if child.type in {"dotted_name", "relative_import"}:
                return self._node_text(child, code)
        return ""

    def _js_variable_function(self, node: Node, code: str) -> dict[str, Any] | None:
        """Extract `const fn = () => {}` / `const fn = function(){}` shapes."""
        name_node = node.child_by_field_name("name")
        value_node = node.child_by_field_name("value")
        if name_node is None or value_node is None:
            return None

        if value_node.type not in {"arrow_function", "function_expression"}:
            return None

        function_name = self._node_text(name_node, code)
        if not function_name:
            return None

        return {
            "name": function_name,
            "qualified_name": function_name,
            "parent_class": "",
            "code": self._node_text(node, code),
            "start_line": node.start_point[0] + 1,
            "calls": self._extract_js_calls(value_node, code),
        }

    def _extract_js_import(self, node: Node, code: str) -> str | None:
        """Extract one JS import-like specifier from an AST node."""
        if node.type in {"import_statement", "export_statement"}:
            for child in node.children:
                if child.type == "string":
                    return self._string_literal_value(child, code)
            return None

        if node.type != "call_expression":
            return None

        callee = node.child_by_field_name("function")
        if callee is None:
            return None

        callee_name = self._full_callee_name(callee, code)
        if callee_name not in {"require", "import"}:
            return None

        args_node = node.child_by_field_name("arguments")
        if args_node is None:
            return None

        for child in args_node.children:
            if child.type == "string":
                return self._string_literal_value(child, code)
        return None

    def _identifier_text(self, node: Node, code: str) -> str:
        """Return the first identifier-like child text for a definition node."""
        for child in node.children:
            if child.type in {"identifier", "property_identifier"}:
                return self._node_text(child, code)
        return ""

    def _dotted_name_text(self, node: Node, code: str) -> str:
        """Return the first dotted-name child text for a Python import node."""
        for child in node.children:
            if child.type == "dotted_name":
                return self._node_text(child, code)
        return ""

    def _python_parent_class(self, node: Node, code: str) -> str:
        """Return the nearest containing Python class name, if any."""
        current = node.parent
        while current is not None:
            if current.type == "class_definition":
                return self._identifier_text(current, code)
            current = current.parent
        return ""

    def _js_parent_class(self, node: Node, code: str) -> str:
        """Return the nearest containing JS class name, if any."""
        current = node.parent
        while current is not None:
            if current.type == "class_declaration":
                return self._identifier_text(current, code)
            current = current.parent
        return ""

    def _js_method_name(self, node: Node, code: str) -> str:
        """Return the property name for a JS method definition."""
        name_node = node.child_by_field_name("name")
        if name_node is not None:
            return self._node_text(name_node, code)
        return self._identifier_text(node, code)

    def _callee_name(self, callee: Node | None, code: str) -> str:
        """Return a short call target name used for conservative call linking."""
        if callee is None:
            return ""
        if callee.type in {"identifier", "property_identifier"}:
            return self._node_text(callee, code)
        if callee.type == "attribute":
            attribute_child = callee.child_by_field_name("attribute")
            if attribute_child is not None:
                return self._node_text(attribute_child, code)
        if callee.type == "member_expression":
            property_child = callee.child_by_field_name("property")
            if property_child is not None:
                return self._node_text(property_child, code)
        if callee.type == "import":
            return "import"
        return ""

    def _full_callee_name(self, callee: Node, code: str) -> str:
        """Return a full dotted call expression when that is safer than the short name."""
        if callee.type in {"identifier", "property_identifier"}:
            return self._node_text(callee, code)
        if callee.type == "attribute":
            object_child = callee.child_by_field_name("object")
            attribute_child = callee.child_by_field_name("attribute")
            if object_child is not None and attribute_child is not None:
                return f"{self._node_text(object_child, code)}.{self._node_text(attribute_child, code)}"
        if callee.type == "member_expression":
            object_child = callee.child_by_field_name("object")
            property_child = callee.child_by_field_name("property")
            if object_child is not None and property_child is not None:
                return f"{self._node_text(object_child, code)}.{self._node_text(property_child, code)}"
        if callee.type == "import":
            return "import"
        return self._node_text(callee, code)

    def _string_literal_value(self, node: Node, code: str) -> str:
        """Strip surrounding quotes from a string literal node."""
        raw = self._node_text(node, code).strip()
        if len(raw) >= 2 and raw[0] in {"'", '"'} and raw[-1] == raw[0]:
            return raw[1:-1]
        return raw

    def _node_text(self, node: Node, code: str) -> str:
        """Return the source slice that corresponds to one node."""
        return code[node.start_byte:node.end_byte]

    def _walk(self, node: Node) -> Iterator[Node]:
        """Yield one node and all descendants depth-first."""
        yield node
        for child in node.children:
            yield from self._walk(child)

    def _walk_owned_descendants(
        self,
        owner: Node,
        *,
        skip_types: set[str],
    ) -> Iterator[Node]:
        """Yield descendants that belong to one function-like owner.

        Nested definitions are intentionally skipped so parent functions do not
        inherit calls from inner functions, inner classes, or nested methods.
        """
        for child in owner.children:
            if child.type in skip_types:
                continue
            yield child
            for descendant in self._walk_owned_descendants(child, skip_types=skip_types):
                yield descendant

    def _stable_dedupe(self, values: Iterable[str]) -> list[str]:
        """Return values with duplicates removed while preserving first-seen order."""
        seen: set[str] = set()
        ordered: list[str] = []
        for value in values:
            normalized = value.strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            ordered.append(normalized)
        return ordered

    def _dedupe_function_rows(self, rows: List[dict[str, Any]]) -> list[dict[str, Any]]:
        """Deduplicate function rows by qualified name and source line.

        JS extraction can encounter the same function through a wrapper node and
        the underlying declaration node. This keeps the first stable row only.
        """
        seen: set[tuple[str, int]] = set()
        ordered: list[dict[str, Any]] = []
        for row in rows:
            key = (str(row.get("qualified_name") or row.get("name") or ""), int(row.get("start_line") or 0))
            if key in seen:
                continue
            seen.add(key)
            ordered.append(row)
        return ordered
