#!/usr/bin/env python3
"""
Judge0 execution self-test for one compiler node (Compiler-1 / Compiler-2 / Compiler-3).

Runs real submissions against a compiler machine's Judge0 API and verifies that
every advertised language works and that the failure modes are classified
correctly. Language ids are resolved from GET /languages (highest version), so
nothing is hard-coded.

Usage:
  python3 judge0_check.py --url http://<COMPILER_IP>:2358 \
      [--token <AUTHN_TOKEN>] [--header X-Judge0-Token] [--timeout 90]

Output: one line per check —
  PASS <label> :: <detail>
  FAIL <label> :: <detail>
Exit code: 0 when every check passed, 1 otherwise.
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import sys
import time
import urllib.error
import urllib.request

# ── Judge0 vocabulary (CE 1.13.1 reports ids 1-14; see judge0/README.md) ─────
STATUS_NAMES = {
    1: "In Queue", 2: "Processing", 3: "Accepted", 4: "Wrong Answer",
    5: "Time Limit Exceeded", 6: "Compilation Error", 7: "Runtime Error (SIGSEGV)",
    8: "Runtime Error (SIGXFSZ)", 9: "Runtime Error (SIGFPE)",
    10: "Runtime Error (SIGABRT)", 11: "Runtime Error (NZEC)",
    12: "Runtime Error (Other)", 13: "Internal Error", 14: "Exec Format Error",
}
RUNTIME_ERROR_IDS = {7, 8, 9, 10, 11, 12}

LANGUAGE_PATTERNS = {
    "python": re.compile(r"^Python \(3\.(\d+)(\.\d+)?\)"),
    "cpp": re.compile(r"^C\+\+ \(GCC (\d+\.\d+\.?\d*)\)"),
    "java": re.compile(r"^Java \(OpenJDK (\d+\.\d+\.?\d*)\)"),
}

PYTHON_SRC = 'print("hello-from-judge0")\n'
CPP_SRC = (
    '#include <iostream>\n'
    'int main() { std::cout << "hello-from-judge0"; return 0; }\n'
)
JAVA_SRC = (
    'public class Main {\n'
    '  public static void main(String[] args) { System.out.print("hello-from-judge0"); }\n'
    '}\n'
)
CPP_COMPILE_ERROR = 'int main( { this is not c++ }\n'
CPP_RUNTIME_ERROR = 'int main() { int *p = nullptr; *p = 1; return 0; }\n'
PYTHON_TLE = 'while True:\n    pass\n'


class Judge0Error(Exception):
    pass


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _deb64(value):
    if not value:
        return ""
    try:
        return base64.b64decode(value.encode("ascii")).decode("utf-8", "replace")
    except Exception:
        return str(value)


def request(url: str, method: str = "GET", body=None, token: str = "", header: str = "X-Judge0-Token", timeout: float = 30.0):
    headers = {"Accept": "application/json"}
    if token:
        headers[header] = token
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", "replace")
    return json.loads(raw) if raw else {}


def resolve_language_ids(list_url: str, token: str, header: str) -> dict:
    languages = request(list_url, token=token, header=header)
    resolved: dict = {}
    for family, pattern in LANGUAGE_PATTERNS.items():
        best = None
        for lang in languages:
            if lang.get("is_archived"):
                continue
            match = pattern.match(lang.get("name", ""))
            if not match:
                continue
            version = tuple(int(p) for p in re.findall(r"\d+", match.group(1)))
            if best is None or version > best[0]:
                best = (version, int(lang["id"]))
        resolved[family] = best[1] if best else None
    return resolved


def run_submission(base: str, language_id: int, source: str, token: str, header: str,
                   cpu_time_limit: float = 4.0, memory_limit_kb: int = 262144,
                   wait_budget: float = 75.0) -> dict:
    """Submit one program synchronously and return the Judge0 result."""
    payload = {
        "language_id": language_id,
        "source_code": _b64(source),
        "stdin": "",
        "cpu_time_limit": cpu_time_limit,
        "wall_time_limit": cpu_time_limit + 6,
        "memory_limit": memory_limit_kb,
        "stack_limit": 65536,
        "max_processes_and_or_threads": 60,
        "max_file_size": 1024,
        "number_of_runs": 1,
        "enable_network": False,
    }
    created = request(f"{base}/submissions?base64_encoded=true&wait=false", "POST", payload, token, header)
    submission_token = created.get("token")
    if not submission_token:
        raise Judge0Error(f"Judge0 did not return a submission token: {created}")

    deadline = time.monotonic() + wait_budget
    while time.monotonic() < deadline:
        data = request(f"{base}/submissions/{submission_token}?base64_encoded=true", token=token, header=header)
        status_id = int(data.get("status", {}).get("id", 1))
        if status_id >= 3:
            data["_status_id"] = status_id
            return data
        time.sleep(0.4)
    raise Judge0Error(f"submission {submission_token} did not finish within {wait_budget}s")


def main() -> int:
    parser = argparse.ArgumentParser(description="Judge0 compiler-node self-test")
    parser.add_argument("--url", required=True, help="Judge0 base URL, e.g. http://10.0.0.13:2358")
    parser.add_argument("--token", default="", help="API auth token (AUTHN_TOKEN)")
    parser.add_argument("--header", default="X-Judge0-Token", help="auth header name")
    parser.add_argument("--label", default="", help="prefix for the reported check labels")
    args = parser.parse_args()

    base = args.url.rstrip("/")
    prefix = f"{args.label} " if args.label else ""
    results: list[tuple[bool, str, str]] = []

    def record(ok: bool, label: str, detail: str) -> None:
        results.append((ok, label, detail))

    # ── Reachability + language map ─────────────────────────────────────────
    try:
        about = request(f"{base}/about", token=args.token, header=args.header)
        record(True, "Judge0 /about responds", f"version {about.get('version', '?')}")
    except Exception as exc:  # noqa: BLE001
        record(False, "Judge0 /about responds", f"{type(exc).__name__}: {exc}")
        _print(results, prefix)
        return 1

    try:
        ids = resolve_language_ids(f"{base}/languages", args.token, args.header)
    except Exception as exc:  # noqa: BLE001
        record(False, "GET /languages responds", f"{type(exc).__name__}: {exc}")
        _print(results, prefix)
        return 1

    for family, lang_id in ids.items():
        if lang_id is None:
            record(False, f"{family} language available", "not advertised by GET /languages")
        else:
            record(True, f"{family} language available", f"language_id {lang_id}")

    # ── Real executions ────────────────────────────────────────────────────
    def execute(label: str, family: str, source: str, expect, **kwargs) -> None:
        lang_id = ids.get(family)
        if lang_id is None:
            record(False, label, f"{family} not available on this node")
            return
        try:
            data = run_submission(base, lang_id, source, args.token, args.header, **kwargs)
        except Exception as exc:  # noqa: BLE001
            record(False, label, f"{type(exc).__name__}: {exc}")
            return
        status_id = data["_status_id"]
        stdout = _deb64(data.get("stdout"))
        stderr = _deb64(data.get("stderr")) or _deb64(data.get("compile_output")) or _deb64(data.get("message"))
        detail = f"{STATUS_NAMES.get(status_id, status_id)}"
        if stdout.strip():
            detail += f", stdout={stdout.strip()[:40]!r}"
        if stdout.strip() == "hello-from-judge0":
            detail += ""
        ok = expect(status_id, stdout, stderr)
        if not ok and stderr:
            detail += f", stderr={stderr.strip()[:120]!r}"
        record(ok, label, detail)

    execute("Python executes", "python", PYTHON_SRC,
            lambda sid, out, err: sid == 3 and out.strip() == "hello-from-judge0")
    execute("C++ executes", "cpp", CPP_SRC,
            lambda sid, out, err: sid == 3 and out.strip() == "hello-from-judge0")
    execute("Java executes", "java", JAVA_SRC,
            lambda sid, out, err: sid == 3 and out.strip() == "hello-from-judge0",
            cpu_time_limit=10.0, memory_limit_kb=2097152)
    execute("Compilation error is reported", "cpp", CPP_COMPILE_ERROR,
            lambda sid, out, err: sid == 6)
    execute("Runtime error is reported", "cpp", CPP_RUNTIME_ERROR,
            lambda sid, out, err: sid in RUNTIME_ERROR_IDS)
    execute("Time limit is enforced (no infinite loop escapes)", "python", PYTHON_TLE,
            lambda sid, out, err: sid == 5, cpu_time_limit=2.0)

    _print(results, prefix)
    return 0 if all(ok for ok, _, _ in results) else 1


def _print(results, prefix: str) -> None:
    for ok, label, detail in results:
        print(f"{'PASS' if ok else 'FAIL'} {prefix}{label} :: {detail}")


if __name__ == "__main__":
    sys.exit(main())
