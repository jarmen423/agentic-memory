"""
DEBUG SCRIPT: GraphRAG V2 Topology Extraction verification.
Run this to see what 'GraphTopologyExtractor' actually extracts from a sample code snippet.
"""

import os
from tree_sitter import Language, Parser, Query, QueryCursor
import tree_sitter_python

# Import logic from the actual script (mocking the class method)
# We will just copy-paste the critical _extract_structure_from_file logic here for rapid testing
# without needing the full LlamaIndex dependecy stack to be perfect.

def test_python_extraction():
    code = """
def my_func(a: int, b: str) -> bool:
    "This is a docstring."
    outer_helper()
    return True

class MyClass:
    def method_one(self):
        my_func(1, "test")
        
    def method_two(self):
        # Should call method_one, but NOT my_func directly (unless we trace deep, which we don't yet)
        self.method_one()
"""
    
    print("--- 🧪 Testing Python Extraction ---")
    
    # Init Parser
    lang = Language(tree_sitter_python.language())
    parser = Parser(lang)
    tree = parser.parse(bytes(code, "utf8"))
    
    # Query (Same as 5_continuous_ingestion.py)
    query_scm = """
    (function_definition
        name: (identifier) @name
        parameters: (parameters) @args
        return_type: (type)? @ret
        body: (block . (expression_statement (string) @doc)?)?
    ) @def
    (class_definition
        name: (identifier) @name
    ) @def
    """
    
    query = Query(lang, query_scm)
    cursor = QueryCursor(query)
    matches = cursor.matches(tree.root_node)
    
    definitions = []
    
    print(f"Code Length: {len(code)}")
    print(f"Found {len(matches)} matches (approx definition count)")

    for match_id, match_map in matches:
        if 'def' not in match_map or 'name' not in match_map:
            continue
            
        def_node = match_map['def'][0]
        name_node = match_map['name'][0]
        
        func_name = code[name_node.start_byte:name_node.end_byte]
        print(f"\n📍 Found Definition: {func_name}")
        
        # Metadata
        if 'doc' in match_map:
            doc = code[match_map['doc'][0].start_byte:match_map['doc'][0].end_byte]
            print(f"   📝 Docstring: {doc}")
            
        if 'args' in match_map:
            args = code[match_map['args'][0].start_byte:match_map['args'][0].end_byte]
            print(f"   🔧 Args: {args}")
            
        if 'ret' in match_map:
            ret = code[match_map['ret'][0].start_byte:match_map['ret'][0].end_byte]
            print(f"   🔙 Return: {ret}")

        # SCOPE AWARE CALLS
        print("   📞 Calls in scope:")
        call_query = Query(lang, """(call function: (identifier) @callee)""")
        call_cursor = QueryCursor(call_query)
        call_captures = call_cursor.captures(def_node)
        
        for tag, nodes in call_captures.items():
            if tag == 'callee':
                for node in nodes:
                    callee = code[node.start_byte:node.end_byte]
                    print(f"      -> {callee}")

if __name__ == "__main__":
    test_python_extraction()
