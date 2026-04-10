"""Unit tests for the canonical code parser used by code ingestion."""

from __future__ import annotations

import pytest

from agentic_memory.ingestion.parser import CodeParser


@pytest.fixture()
def parser() -> CodeParser:
    """Create a reusable parser instance for unit tests."""
    return CodeParser()


def test_extract_python_classes(parser: CodeParser) -> None:
    """Python class extraction should keep declaration order and names."""
    code = """
class MyClass:
    def __init__(self):
        pass

class OtherClass:
    pass
"""

    result = parser.parse_file(code, ".py")
    assert [cls["name"] for cls in result["classes"]] == ["MyClass", "OtherClass"]


def test_extract_python_functions_include_parent_class(parser: CodeParser) -> None:
    """Python function rows should keep class ownership for methods."""
    code = """
def my_func():
    pass

class MyClass:
    def method(self):
        pass
"""

    result = parser.parse_file(code, ".py")
    functions = {row["qualified_name"]: row for row in result["functions"]}

    assert set(functions) == {"my_func", "MyClass.method"}
    assert functions["my_func"]["parent_class"] == ""
    assert functions["MyClass.method"]["parent_class"] == "MyClass"
    assert functions["my_func"]["name_line"] == 2
    assert functions["my_func"]["name_column"] == 5


def test_extract_python_imports_preserves_relative_modules(parser: CodeParser) -> None:
    """Python imports should preserve relative prefixes for repo-aware resolution."""
    code = """
import os
from datetime import datetime
from .helpers import helper
from ..pkg.mod import tool
"""

    result = parser.parse_file(code, ".py")
    assert result["imports"] == ["os", "datetime", ".helpers", "..pkg.mod"]


def test_extract_python_calls_are_scoped_per_function(parser: CodeParser) -> None:
    """Nested function calls should not bleed into the outer function's call list."""
    code = """
def outer():
    print("outer")

    def inner():
        hidden()

    helper()
"""

    result = parser.parse_file(code, ".py")
    functions = {row["qualified_name"]: row for row in result["functions"]}

    assert functions["outer"]["calls"] == ["print", "helper"]
    assert functions["inner"]["calls"] == ["hidden"]
    assert result["calls"] == ["print", "helper", "hidden"]


def test_extract_python_env_vars(parser: CodeParser) -> None:
    """Env-var reads and dotenv loads should remain detectable."""
    code = """
import os

value = os.getenv("MY_VAR")
other = os.environ.get("OTHER_VAR")
load_dotenv()
"""

    result = parser.parse_file(code, ".py")
    reads = [row["name"] for row in result["env_vars"] if row.get("type") == "read"]
    loads = [row for row in result["env_vars"] if row.get("type") == "load"]

    assert reads == ["MY_VAR", "OTHER_VAR"]
    assert len(loads) == 1


def test_extract_js_classes_and_methods(parser: CodeParser) -> None:
    """JS method definitions should be captured as class-owned functions."""
    code = """
class MyClass {
  constructor() {}
  method() {
    helper();
  }
}
"""

    result = parser.parse_file(code, ".js")
    assert [row["name"] for row in result["classes"]] == ["MyClass"]

    functions = {row["qualified_name"]: row for row in result["functions"]}
    assert "MyClass.constructor" in functions
    assert "MyClass.method" in functions
    assert functions["MyClass.method"]["calls"] == ["helper"]
    assert functions["MyClass.method"]["name_line"] == 4
    assert functions["MyClass.method"]["name_column"] == 3


def test_extract_js_function_like_assignments(parser: CodeParser) -> None:
    """Arrow functions and function expressions assigned to names should be extracted."""
    code = """
const arrowFn = () => service.run();
const exprFn = function () {
  helper();
};
function declared() {
  arrowFn();
}
"""

    result = parser.parse_file(code, ".js")
    functions = {row["qualified_name"]: row for row in result["functions"]}

    assert {"arrowFn", "exprFn", "declared"} <= set(functions)
    assert functions["arrowFn"]["calls"] == ["run"]
    assert functions["exprFn"]["calls"] == ["helper"]
    assert functions["declared"]["calls"] == ["arrowFn"]


def test_extract_js_import_forms(parser: CodeParser) -> None:
    """JS import extraction should cover static, export-from, require, and dynamic import."""
    code = """
import React from "react";
export { helper } from "./helpers";
const fs = require("fs");
await import("./lazy");
"""

    result = parser.parse_file(code, ".js")
    assert result["imports"] == ["react", "./helpers", "fs", "./lazy"]


def test_unsupported_extension_returns_diagnostic(parser: CodeParser) -> None:
    """Unsupported extensions should degrade cleanly instead of throwing."""
    result = parser.parse_file("hello", ".go")
    assert result["classes"] == []
    assert result["functions"] == []
    assert result["diagnostics"][0]["kind"] == "unsupported_extension"
