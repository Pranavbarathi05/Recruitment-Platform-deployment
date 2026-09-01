"""
Language registry and adapters for the Compiler 1 execution service.

Each language is registered through a LanguageAdapter that defines:
  - how to compile (if needed)
  - how to generate a run script
  - version detection

New languages are added by creating a LanguageAdapter and registering it.
No giant conditional blocks.
"""
from __future__ import annotations

import shutil
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ── Base adapter ─────────────────────────────────────────────────────────────

class LanguageAdapter(ABC):
    """Base class for language execution adapters."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable language name."""

    @property
    @abstractmethod
    def file_extension(self) -> str:
        """Source file extension (e.g. '.py', '.cpp')."""

    @abstractmethod
    def compile(self, source_path: Path, work_dir: Path) -> tuple[bool, str]:
        """
        Compile source code if needed.
        Returns (success, error_message).
        Interpreted languages return (True, "").
        """

    @abstractmethod
    def run_script(self, source_path: Path, work_dir: Path) -> str:
        """Return a bash script string that runs the program."""

    @abstractmethod
    def is_available(self) -> bool:
        """Check if this language's compiler/interpreter is installed."""

    @abstractmethod
    def version(self) -> Optional[str]:
        """Return the compiler/interpreter version string, or None."""


# ── C++ ──────────────────────────────────────────────────────────────────────

class CppAdapter(LanguageAdapter):
    name = "cpp"
    file_extension = ".cpp"
    _binary = "solution"
    _compiler = "g++"

    def compile(self, source_path: Path, work_dir: Path) -> tuple[bool, str]:
        binary = work_dir / self._binary
        result = subprocess.run(
            [self._compiler, "-O2", "-std=c++17", "-o", str(binary), str(source_path)],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return False, result.stderr.strip()
        return True, ""

    def run_script(self, source_path: Path, work_dir: Path) -> str:
        binary = work_dir / self._binary
        return f'exec "{binary}"\n'

    def is_available(self) -> bool:
        return shutil.which(self._compiler) is not None

    def version(self) -> Optional[str]:
        try:
            r = subprocess.run([self._compiler, "--version"], capture_output=True, text=True, timeout=5)
            return r.stdout.splitlines()[0] if r.returncode == 0 else None
        except Exception:
            return None


# ── C ────────────────────────────────────────────────────────────────────────

class CAdapter(LanguageAdapter):
    name = "c"
    file_extension = ".c"
    _binary = "solution"
    _compiler = "gcc"

    def compile(self, source_path: Path, work_dir: Path) -> tuple[bool, str]:
        binary = work_dir / self._binary
        result = subprocess.run(
            [self._compiler, "-O2", "-std=c11", "-o", str(binary), str(source_path)],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return False, result.stderr.strip()
        return True, ""

    def run_script(self, source_path: Path, work_dir: Path) -> str:
        binary = work_dir / self._binary
        return f'exec "{binary}"\n'

    def is_available(self) -> bool:
        return shutil.which(self._compiler) is not None

    def version(self) -> Optional[str]:
        try:
            r = subprocess.run([self._compiler, "--version"], capture_output=True, text=True, timeout=5)
            return r.stdout.splitlines()[0] if r.returncode == 0 else None
        except Exception:
            return None


# ── Java ─────────────────────────────────────────────────────────────────────

class JavaAdapter(LanguageAdapter):
    name = "java"
    file_extension = ".java"
    _class_name = "Solution"
    _compiler = "javac"
    _runtime = "java"

    def compile(self, source_path: Path, work_dir: Path) -> tuple[bool, str]:
        # Java requires filename to match public class name.
        # Rename source to Solution.java to match the expected class name.
        target = work_dir / f"{self._class_name}.java"
        if source_path != target:
            import shutil as _shutil
            _shutil.copy2(str(source_path), str(target))
        result = subprocess.run(
            [self._compiler, "-d", str(work_dir), str(target)],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return False, result.stderr.strip()
        return True, ""

    def run_script(self, source_path: Path, work_dir: Path) -> str:
        return f'exec java -cp "{work_dir}" {self._class_name}\n'

    def is_available(self) -> bool:
        return shutil.which(self._compiler) is not None and shutil.which(self._runtime) is not None

    def version(self) -> Optional[str]:
        try:
            r = subprocess.run([self._compiler, "--version"], capture_output=True, text=True, timeout=5)
            return r.stdout.splitlines()[0] if r.returncode == 0 else None
        except Exception:
            return None


# ── Python ───────────────────────────────────────────────────────────────────

class PythonAdapter(LanguageAdapter):
    name = "python"
    file_extension = ".py"
    _interpreter = "python3"

    def compile(self, source_path: Path, work_dir: Path) -> tuple[bool, str]:
        return True, ""  # Interpreted

    def run_script(self, source_path: Path, work_dir: Path) -> str:
        return f'exec python3 "{source_path}"\n'

    def is_available(self) -> bool:
        return shutil.which(self._interpreter) is not None

    def version(self) -> Optional[str]:
        try:
            r = subprocess.run([self._interpreter, "--version"], capture_output=True, text=True, timeout=5)
            return r.stdout.strip() if r.returncode == 0 else None
        except Exception:
            return None


# ── SQL (SQLite) ────────────────────────────────────────────────────────────

class SqlAdapter(LanguageAdapter):
    """SQL adapter using SQLite as the execution engine.

    Source code contains SQL statements (DDL + DML) that set up the database.
    Each test case's `input` is a SQL query to run against the database.
    The query output is compared against `expected_output`.

    The source code is executed first to create schema and insert data.
    Then each test case runs its query and captures results.
    """
    name = "sql"
    file_extension = ".sql"
    _interpreter = "sqlite3"

    def compile(self, source_path: Path, work_dir: Path) -> tuple[bool, str]:
        # SQL doesn't need compilation, but we validate syntax by
        # attempting to execute the source against an empty database.
        db_path = work_dir / "test.db"
        try:
            result = subprocess.run(
                [self._interpreter, str(db_path)],
                input=source_path.read_text(encoding="utf-8"),
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                return False, result.stderr.strip()
            return True, ""
        except FileNotFoundError:
            return False, "sqlite3 not found"
        except subprocess.TimeoutExpired:
            return False, "SQL validation timed out"

    def run_script(self, source_path: Path, work_dir: Path) -> str:
        # SQL adapter uses a custom execution model via executor.py,
        # not a bash script. This is a placeholder.
        return f'exec cat "{source_path}"\n'

    def is_available(self) -> bool:
        return shutil.which(self._interpreter) is not None

    def version(self) -> Optional[str]:
        try:
            r = subprocess.run([self._interpreter, "--version"], capture_output=True, text=True, timeout=5)
            return r.stdout.strip() if r.returncode == 0 else None
        except Exception:
            return None

    def init_database(self, source_path: Path, work_dir: Path) -> tuple[bool, str]:
        """Execute the source SQL to set up the database schema and data.

        Returns (success, error_message).
        """
        db_path = work_dir / "test.db"
        # Remove any existing database
        db_path.unlink(missing_ok=True)
        try:
            result = subprocess.run(
                [self._interpreter, str(db_path)],
                input=source_path.read_text(encoding="utf-8"),
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                return False, result.stderr.strip()
            return True, ""
        except FileNotFoundError:
            return False, "sqlite3 not found"
        except subprocess.TimeoutExpired:
            return False, "SQL setup timed out"

    def run_query(self, query: str, work_dir: Path, max_output_bytes: int = 65536) -> tuple[bool, str, str]:
        """Execute a SQL query and return (success, stdout, stderr).

        Args:
            query: SQL query to execute.
            work_dir: Working directory containing test.db.
            max_output_bytes: Max output size before truncation.

        Returns:
            (success, stdout, stderr)
        """
        db_path = work_dir / "test.db"
        if not db_path.exists():
            return False, "", "Database not initialized"

        # Run query in CSV mode for predictable output
        full_query = f".mode csv\n.headers on\n{query}"
        try:
            result = subprocess.run(
                [self._interpreter, str(db_path)],
                input=full_query,
                capture_output=True, text=True, timeout=10,
            )
            stdout = result.stdout
            stderr = result.stderr
            if len(stdout.encode("utf-8")) > max_output_bytes:
                stdout = stdout[:max_output_bytes] + f"\n... [truncated at {max_output_bytes} bytes]"
            return result.returncode == 0, stdout.strip(), stderr.strip()
        except subprocess.TimeoutExpired:
            return False, "", "Query timed out"
        except Exception as e:
            return False, "", f"Internal error: {e}"


# ── Registry ─────────────────────────────────────────────────────────────────

_REGISTRY: dict[str, LanguageAdapter] = {
    "cpp": CppAdapter(),
    "c": CAdapter(),
    "java": JavaAdapter(),
    "python": PythonAdapter(),
    "sql": SqlAdapter(),
}


def get_adapter(language: str) -> Optional[LanguageAdapter]:
    """Return the adapter for the given language, or None."""
    return _REGISTRY.get(language)


def get_all_adapters() -> dict[str, LanguageAdapter]:
    """Return a copy of the full registry."""
    return dict(_REGISTRY)
