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


# ── JavaScript ───────────────────────────────────────────────────────────────

class JavaScriptAdapter(LanguageAdapter):
    name = "javascript"
    file_extension = ".js"
    _interpreter = "node"

    def compile(self, source_path: Path, work_dir: Path) -> tuple[bool, str]:
        return True, ""  # Interpreted

    def run_script(self, source_path: Path, work_dir: Path) -> str:
        return f'exec node "{source_path}"\n'

    def is_available(self) -> bool:
        return shutil.which(self._interpreter) is not None

    def version(self) -> Optional[str]:
        try:
            r = subprocess.run([self._interpreter, "--version"], capture_output=True, text=True, timeout=5)
            return r.stdout.strip() if r.returncode == 0 else None
        except Exception:
            return None


# ── Registry ─────────────────────────────────────────────────────────────────

_REGISTRY: dict[str, LanguageAdapter] = {
    "cpp": CppAdapter(),
    "c": CAdapter(),
    "java": JavaAdapter(),
    "python": PythonAdapter(),
    "javascript": JavaScriptAdapter(),
}


def get_adapter(language: str) -> Optional[LanguageAdapter]:
    """Return the adapter for the given language, or None."""
    return _REGISTRY.get(language)


def get_all_adapters() -> dict[str, LanguageAdapter]:
    """Return a copy of the full registry."""
    return dict(_REGISTRY)
