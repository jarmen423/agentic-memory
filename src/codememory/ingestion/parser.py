import logging
import sys
from typing import Dict, List, Any, Optional
from tree_sitter import Language, Parser, Query, QueryCursor, Node, Tree
import tree_sitter_python
import tree_sitter_javascript

logger = logging.getLogger(__name__)

class CodeParser:
    def __init__(self):
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
        except Exception as e:
            logger.error(f"Failed to initialize parsers: {e}")

    def parse_file(self, code: str, extension: str) -> Dict[str, Any]:
        parser = self.parsers.get(extension)
        if not parser:
            logger.warning(f"No parser found for extension {extension}")
            return {}

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
        except Exception as e:
            logger.error(f"Error parsing file with extension {extension}: {e}")
            return {}

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

        except Exception as e:
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
        except Exception as e:
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

            # captures returns dict {name: [nodes]}
            if isinstance(captures, dict):
                nodes = captures.get('module', [])
                for node in nodes:
                    module_name = code[node.start_byte:node.end_byte]
                    imports.append(module_name)
        except Exception as e:
            logger.error(f"Error extracting imports: {e}")

        return imports

    def _extract_calls(self, tree: Tree, code: str, lang: Language, extension: str) -> List[str]:
        calls = []
        query_scm = """(call function: (identifier) @name)"""

        try:
            query = Query(lang, query_scm)
            cursor = QueryCursor(query)
            captures = cursor.captures(tree.root_node)

            if isinstance(captures, dict):
                nodes = captures.get('name', [])
                for node in nodes:
                    call_name = code[node.start_byte:node.end_byte]
                    calls.append(call_name)
        except Exception as e:
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
        except Exception as e:
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
        except Exception as e:
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
