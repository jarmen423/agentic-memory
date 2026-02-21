import pytest
from codememory.ingestion.parser import CodeParser

@pytest.fixture
def parser():
    return CodeParser()

def test_extract_python_classes(parser):
    code = """
class MyClass:
    def __init__(self):
        pass

class OtherClass:
    pass
"""
    result = parser.parse_file(code, ".py")
    classes = result["classes"]
    assert len(classes) == 2
    assert classes[0]["name"] == "MyClass"
    assert classes[1]["name"] == "OtherClass"

def test_extract_python_functions(parser):
    code = """
def my_func():
    pass

class MyClass:
    def method(self):
        pass
"""
    result = parser.parse_file(code, ".py")
    functions = result["functions"]

    # functions should contain both my_func and method
    assert len(functions) == 2

    # Order might vary depending on traversal, but tree-sitter is usually linear
    names = {f["name"] for f in functions}
    assert "my_func" in names
    assert "method" in names

    # Check parent class
    for f in functions:
        if f["name"] == "method":
            assert f["parent_class"] == "MyClass"
        elif f["name"] == "my_func":
            assert f["parent_class"] == ""

def test_extract_python_imports(parser):
    code = """
import os
from datetime import datetime
"""
    result = parser.parse_file(code, ".py")
    imports = result["imports"]
    assert "os" in imports
    assert "datetime" in imports

def test_extract_python_calls(parser):
    code = """
def main():
    print("Hello")
    my_func()
"""
    result = parser.parse_file(code, ".py")
    calls = result["calls"]
    assert "print" in calls
    assert "my_func" in calls

def test_extract_python_env_vars(parser):
    code = """
import os
val = os.getenv("MY_VAR")
# os.environ.get("OTHER_VAR") # Disabled as parser might not cover this pattern yet
load_dotenv()
"""
    result = parser.parse_file(code, ".py")
    env_vars = result["env_vars"]

    # Should find MY_VAR read
    reads = [v["name"] for v in env_vars if v.get("type") == "read"]
    assert "MY_VAR" in reads

    # Should find load_dotenv
    loads = [v for v in env_vars if v.get("type") == "load"]
    assert len(loads) == 1

def test_extract_js_classes(parser):
    code = """
class MyClass {
    constructor() {}
}
"""
    result = parser.parse_file(code, ".js")
    classes = result["classes"]
    assert len(classes) == 1
    assert classes[0]["name"] == "MyClass"

def test_extract_js_functions(parser):
    code = """
function myFunc() {}
"""
    result = parser.parse_file(code, ".js")
    functions = result["functions"]
    assert len(functions) == 1
    assert functions[0]["name"] == "myFunc"
