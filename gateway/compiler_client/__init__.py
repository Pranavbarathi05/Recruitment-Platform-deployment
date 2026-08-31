"""
Compiler Client – HTTP client library for Compiler 1.

This module provides a Python client that wraps Compiler 1's HTTP API
and can be used by the application to submit code for execution.

Usage:
    from compiler_client import CompilerClient

    client = CompilerClient(url="http://compiler-1:8000")
    result = await client.execute(
        language="python",
        source_code="print(42)",
        test_cases=[{"input": "", "expected_output": "42"}],
    )
"""
from .client import CompilerClient, CompilerError

__all__ = ["CompilerClient", "CompilerError"]
