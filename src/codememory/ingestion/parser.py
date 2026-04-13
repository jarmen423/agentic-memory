"""Tree-sitter parsing for code ingestion: structured metadata from source text.

``CodeParser`` is the **parse-only** front half of the code ingestion story: it
turns file contents into a stable dict of classes, functions, imports, call
sites, and (Python-only) environment reads. Downstream, ``KnowledgeGraphBuilder``
in ``codememory.ingestion.graph`` may embed overlapping logic for historical
reasons; this class is the reusable, query-centric extraction surface.

Why tree-sitter:
    Fault-tolerant CST parsing, multi-language grammars, fast enough for full
    repository scans.

Supported extensions:
    ``.py``, ``.js``, ``.jsx``, ``.ts``, ``.tsx``. Import and env-var extraction
    are implemented for Python; JS/TS import lists remain empty in the current
    implementation.

Dependencies:
    ``tree-sitter``, ``tree-sitter-python``, ``tree-sitter-javascript``.
"""

import logging
from typing import Dict, List, Any
from tree_sitter import Language, Parser, Query, QueryCursor, Node, Tree
import tree_sitter_python
import tree_sitter_javascript

logger = logging.getLogger(__name__)

class CodeParser:
    """tree-sitter-based parser that extracts structured metadata from source files.

    Instantiate once per process (parsers are stateless after initialisation)
    and call ``parse_file`` for each source file during ingestion. The returned
    dict is consumed by ``KnowledgeGraphBuilder`` to create Neo4j nodes and
    relationships for the code knowledge graph.

    Supported file extensions: ``.py``, ``.js``, ``.jsx``, ``.ts``, ``.tsx``.
    Files with unsupported extensions return the default empty-result dict so
    that callers never need to branch on parser availability.

    Attributes:
        parsers: Dict mapping file extension -> tree-sitter ``Parser`` instance.
        languages: Dict mapping file extension -> tree-sitter ``Language``
            grammar object (used to compile S-expression queries).
    """

    def __init__(self):
        self.parsers = {}
        self.languages = {}
        self._init_parsers()

    def _init_parsers(self):
        """Load Python and JavaScript grammars and populate ``parsers`` / ``languages``.

        Logs and swallows initialization errors so ``parse_file`` can still
        return empty structures when grammars fail to load.
        """
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
        """Parse source code and return structured metadata for graph ingestion.

        Builds a tree-sitter CST from ``code``, then runs five focused S-expression
        queries to extract different structural elements. Returns a consistent
        dict shape regardless of language or whether parsing succeeds, so
        callers never need to guard against missing keys.

        Args:
            code: Raw source code as a string (any encoding is transcoded to
                UTF-8 internally before passing to tree-sitter).
            extension: File extension including the leading dot (e.g., ".py",
                ".ts"). Controls which grammar and query patterns are used.

        Returns:
            Dict with five keys:
              - ``classes``: List of dicts ``{name, code, start_line}`` for
                each class definition found in the file.
              - ``functions``: List of dicts ``{name, code, parent_class,
                start_line}`` for each function/method definition.
              - ``imports``: List of module name strings (Python only; empty
                list for JS/TS files in the current implementation).
              - ``calls``: List of called function name strings (bare
                identifiers only — method calls on objects are not captured).
              - ``env_vars``: List of dicts ``{type, name, line}`` for
                ``os.getenv`` / ``os.environ.get`` reads and ``load_dotenv``
                invocations (Python only).

            Returns the default empty-list dict on unsupported extensions or
            parse errors so the pipeline can continue without crashing.
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
        """Run class-definition queries and return name, span text, and start line."""
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
        """Run function-declaration queries; attach optional parent class name for methods."""
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
        """Return dotted module names from Python import/from-import statements only."""
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
        """Collect callee identifiers from simple call nodes (no dotted methods)."""
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
        """Detect Python env reads (getenv/get) and ``load_dotenv`` calls for graph hints."""
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
        """Return the first child ``identifier`` text slice, or empty string."""
        # Try to find 'identifier' child
        for child in node.children:
            if child.type == 'identifier':
                return code[child.start_byte:child.end_byte]
        return ""

    def _get_parent_class(self, node: Node, code: str) -> str:
        """Walk ancestors for a class_definition/class_declaration and read its name."""
        current = node.parent
        while current:
            if current.type == 'class_definition' or current.type == 'class_declaration':
                 name = self._get_name_from_node(current, code)
                 if name: return name
            current = current.parent
        return ""
