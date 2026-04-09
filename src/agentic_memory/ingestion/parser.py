"""
Tree-sitter-based source code parser for the Agentic Memory ingestion pipeline.

Extracts structural elements from Python and JavaScript/TypeScript source files —
classes, functions, imports, function calls, and environment variable references —
using the tree-sitter incremental parsing library.  Results feed the Neo4j
knowledge graph via ``KnowledgeGraphBuilder``.

Extended:
    The parser is language-aware: Python and JS/TS use different tree-sitter
    grammars and query patterns.  Unsupported extensions are handled gracefully
    (empty result dict returned with a warning log rather than raising).

    Extracted data flows:
    - ``classes`` and ``functions`` → ``Class`` and ``Function`` Neo4j nodes
    - ``imports`` → ``IMPORTS`` relationships between ``File`` nodes
    - ``calls`` → ``CALLS`` relationships between ``Function`` nodes
    - ``env_vars`` → ``EnvVar`` nodes (documents runtime configuration surface)

Role:
    Instantiated once per ``KnowledgeGraphBuilder`` instance.  The ``parse_file``
    method is called for every source file encountered during indexing and
    incremental watch-mode updates.

Dependencies:
    - tree-sitter >= 0.22 (``Language``, ``Parser``, ``Query``, ``QueryCursor``)
    - tree-sitter-python (Python grammar)
    - tree-sitter-javascript (JS/TS grammar — used for .js, .jsx, .ts, .tsx)

Key Technologies:
    tree-sitter (incremental concrete syntax tree parsing), S-expression query DSL.
"""

import logging
from typing import Dict, List, Any
from tree_sitter import Language, Parser, Query, QueryCursor, Node, Tree
import tree_sitter_python
import tree_sitter_javascript

logger = logging.getLogger(__name__)

class CodeParser:
    """Tree-sitter parser that extracts structural code elements from source files.

    Maintains one tree-sitter ``Parser`` and ``Language`` instance per supported
    file extension.  Parsers are initialized once at construction time; subsequent
    calls to ``parse_file`` reuse those instances for efficiency.

    Supported extensions:
        - ``.py`` — Python (tree-sitter-python grammar)
        - ``.js``, ``.jsx``, ``.ts``, ``.tsx`` — JavaScript/TypeScript
          (tree-sitter-javascript grammar; TypeScript-specific syntax is parsed
          on a best-effort basis since a separate grammar is not loaded)

    Note:
        This class is not thread-safe.  The ``KnowledgeGraphBuilder`` that owns
        it should not share an instance across threads.
    """

    def __init__(self):
        """Initialize tree-sitter parsers for all supported languages."""
        self.parsers = {}
        self.languages = {}
        self._init_parsers()

    def _init_parsers(self):
        try:
            # Python
            py_lang = Language(tree_sitter_python.language())
            self.languages['.py'] = py_lang
            self.parsers['.py'] = Parser(py_lang)

            # JS/TS
            js_lang = Language(tree_sitter_javascript.language())
            for ext in ['.js', '.jsx', '.ts', '.tsx']:
                self.languages[ext] = js_lang
                self.parsers[ext] = Parser(js_lang)
        except (ImportError, RuntimeError) as e:
            logger.error(f"Failed to initialize parsers: {e}")

    def parse_file(self, code: str, extension: str) -> Dict[str, Any]:
        """Parse source code and return a dict of extracted structural elements.

        Runs the tree-sitter parser for the given extension, then applies
        language-specific S-expression queries to extract classes, functions,
        imports, function calls, and environment variable reads.

        Args:
            code: Raw source code text to parse.
            extension: File extension including the leading dot (e.g. ``".py"``).
                Must be one of the extensions registered during ``__init__``.

        Returns:
            Dict with keys:
                - ``classes``: List of ``{name, code, start_line}`` dicts.
                - ``functions``: List of ``{name, code, parent_class, start_line}`` dicts.
                - ``imports``: List of module name strings (Python only).
                - ``calls``: List of called function name strings.
                - ``env_vars``: List of ``{type, name, line}`` dicts for env reads
                  (Python only; ``type`` is ``"read"`` or ``"load"``).
            Returns the empty-list default dict on unsupported extension or
            any parsing error.
        """
        default_result = {
            "classes": [],
            "functions": [],
            "imports": [],
            "calls": [],
            "env_vars": [],
        }
        parser = self.parsers.get(extension)
        if not parser:
            logger.warning(f"No parser found for extension {extension}")
            return default_result

        try:
            tree = parser.parse(bytes(code, "utf8"))
            lang = self.languages[extension]

            return {
                "classes": self._extract_classes(tree, code, lang, extension),
                "functions": self._extract_functions(tree, code, lang, extension),
                "imports": self._extract_imports(tree, code, lang, extension),
                "calls": self._extract_calls(tree, code, lang, extension),
                "env_vars": self._extract_env_vars(tree, code, lang, extension)
            }
        except (ValueError, RuntimeError, AttributeError, TypeError) as e:
            logger.error(f"Error parsing file with extension {extension}: {e}")
            return default_result

    def _extract_classes(self, tree: Tree, code: str, lang: Language, extension: str) -> List[Dict[str, Any]]:
        classes = []
        if extension == '.py':
            query_scm = """
            (class_definition
                name: (identifier) @name
                body: (block) @body) @class_def
            """
        else: # JS/TS
            query_scm = """
            (class_declaration name: (identifier) @name) @class_def
            """

        try:
            query = Query(lang, query_scm)
            cursor = QueryCursor(query)
            matches = cursor.matches(tree.root_node)

            for match_id, match_map in matches:
                if 'name' not in match_map: continue

                name_node = match_map['name'][0]
                name = code[name_node.start_byte:name_node.end_byte]

                def_node = match_map['class_def'][0]

                classes.append({
                    "name": name,
                    "code": code[def_node.start_byte:def_node.end_byte],
                    "start_line": def_node.start_point[0] + 1
                })

        except (RuntimeError, AttributeError, IndexError) as e:
            logger.error(f"Error extracting classes: {e}")

        return classes

    def _extract_functions(self, tree: Tree, code: str, lang: Language, extension: str) -> List[Dict[str, Any]]:
        functions = []
        if extension == '.py':
            query_scm = """
            (function_definition
                name: (identifier) @name
                body: (block) @body) @function_def
            """
        else:
            query_scm = """
            (function_declaration name: (identifier) @name) @function_def
            """

        try:
            query = Query(lang, query_scm)
            cursor = QueryCursor(query)
            matches = cursor.matches(tree.root_node)

            for match_id, match_map in matches:
                if 'name' not in match_map: continue

                name_node = match_map['name'][0]
                name = code[name_node.start_byte:name_node.end_byte]

                def_node = match_map['function_def'][0]

                # Determine parent class
                parent_class = self._get_parent_class(def_node, code)

                functions.append({
                    "name": name,
                    "code": code[def_node.start_byte:def_node.end_byte],
                    "parent_class": parent_class,
                    "start_line": def_node.start_point[0] + 1
                })
        except (RuntimeError, AttributeError, IndexError) as e:
            logger.error(f"Error extracting functions: {e}")

        return functions

    def _extract_imports(self, tree: Tree, code: str, lang: Language, extension: str) -> List[str]:
        imports = []
        if extension != '.py': return imports # Only Python supported for now

        query_scm = """
        (import_statement name: (dotted_name) @module)
        (import_from_statement module_name: (dotted_name) @module)
        """

        try:
            query = Query(lang, query_scm)
            cursor = QueryCursor(query)
            captures = cursor.captures(tree.root_node)
            for node in captures.get("module", []):
                module_name = code[node.start_byte:node.end_byte]
                imports.append(module_name)
        except (RuntimeError, AttributeError, IndexError) as e:
            logger.error(f"Error extracting imports: {e}")

        return imports

    def _extract_calls(self, tree: Tree, code: str, lang: Language, extension: str) -> List[str]:
        calls = []
        if extension == ".py":
            query_scm = """(call function: (identifier) @name)"""
        else:
            query_scm = """(call_expression function: (identifier) @name)"""

        try:
            query = Query(lang, query_scm)
            cursor = QueryCursor(query)
            captures = cursor.captures(tree.root_node)

            for node in captures.get("name", []):
                call_name = code[node.start_byte:node.end_byte]
                calls.append(call_name)
        except (RuntimeError, AttributeError) as e:
            logger.error(f"Error extracting calls: {e}")

        return calls

    def _extract_env_vars(self, tree: Tree, code: str, lang: Language, extension: str) -> List[Dict[str, Any]]:
        env_vars = []
        if extension != '.py': return env_vars

        # Query 1: os.getenv
        query_scm_1 = """
        (call
            function: (attribute
                attribute: (identifier) @method)
            arguments: (argument_list
                (string) @var_name)) @env_call
        """

        try:
            query = Query(lang, query_scm_1)
            cursor = QueryCursor(query)
            matches = cursor.matches(tree.root_node)

            for match_id, match_map in matches:
                if 'method' not in match_map or 'var_name' not in match_map: continue

                method_node = match_map['method'][0]
                method_name = code[method_node.start_byte:method_node.end_byte]

                if method_name in ["getenv", "get"]:
                    var_node = match_map['var_name'][0]
                    var_name = code[var_node.start_byte:var_node.end_byte].strip("'\"")

                    env_vars.append({
                        "type": "read",
                        "name": var_name,
                        "line": method_node.start_point[0] + 1
                    })
        except (RuntimeError, AttributeError, IndexError) as e:
            logger.error(f"Error extracting env vars (read): {e}")

        # Query 2: load_dotenv
        query_scm_2 = """
        (call
            function: (identifier) @func
            arguments: (argument_list) @args) @load_call
        """

        try:
            query = Query(lang, query_scm_2)
            cursor = QueryCursor(query)
            matches = cursor.matches(tree.root_node)

            for match_id, match_map in matches:
                if 'func' not in match_map: continue

                func_node = match_map['func'][0]
                func_name = code[func_node.start_byte:func_node.end_byte]

                if func_name == "load_dotenv":
                     env_vars.append({
                        "type": "load",
                        "line": func_node.start_point[0] + 1
                    })
        except (RuntimeError, AttributeError, IndexError) as e:
             logger.error(f"Error extracting env vars (load): {e}")

        return env_vars

    def _get_name_from_node(self, node: Node, code: str) -> str:
        # Try to find 'identifier' child
        for child in node.children:
            if child.type == 'identifier':
                return code[child.start_byte:child.end_byte]
        return ""

    def _get_parent_class(self, node: Node, code: str) -> str:
        current = node.parent
        while current:
            if current.type == 'class_definition' or current.type == 'class_declaration':
                 name = self._get_name_from_node(current, code)
                 if name: return name
            current = current.parent
        return ""
