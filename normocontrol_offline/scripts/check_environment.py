from __future__ import annotations

import importlib
import json
import platform
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path


REQUIRED_IMPORTS = {
    "customtkinter": "desktop window",
    "fitz": "PDF OCR rendering",
    "pypdf": "PDF text extraction",
    "matplotlib": "evaluation charts",
}


def check_import(module: str) -> dict:
    try:
        imported = importlib.import_module(module)
        return {
            "name": module,
            "ok": True,
            "version": getattr(imported, "__version__", "unknown"),
        }
    except Exception as exc:
        return {"name": module, "ok": False, "error": str(exc)}


def check_tkinter() -> dict:
    try:
        import tkinter

        return {"ok": True, "version": str(tkinter.TkVersion)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def check_sqlite_fts() -> dict:
    try:
        connection = sqlite3.connect(":memory:")
        connection.execute("CREATE VIRTUAL TABLE test_fts USING fts5(text)")
        connection.close()
        return {"ok": True, "version": sqlite3.sqlite_version}
    except Exception as exc:
        return {"ok": False, "version": sqlite3.sqlite_version, "error": str(exc)}


def run_command(command: list[str], timeout: int = 10) -> tuple[int, str, str]:
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    return result.returncode, result.stdout, result.stderr


def check_tesseract() -> dict:
    binary = shutil.which("tesseract")
    if not binary:
        return {"ok": False, "error": "tesseract not found in PATH"}
    try:
        code, stdout, stderr = run_command([binary, "--list-langs"])
    except Exception as exc:
        return {"ok": False, "path": binary, "error": str(exc)}
    languages = {
        line.strip()
        for line in stdout.splitlines()
        if line.strip() and "List of available languages" not in line
    }
    required = {"rus", "eng"}
    return {
        "ok": code == 0 and required.issubset(languages),
        "path": binary,
        "languages": sorted(languages),
        "missing": sorted(required - languages),
        "stderr": stderr.strip(),
    }


def check_libreoffice() -> dict:
    binary = shutil.which("soffice") or shutil.which("libreoffice")
    if binary:
        return {"ok": True, "partial": False, "path": binary}
    textutil = shutil.which("textutil")
    if textutil:
        return {
            "ok": False,
            "partial": True,
            "path": textutil,
            "warning": "macOS textutil fallback; LibreOffice is better for old DOC",
        }
    return {
        "ok": False,
        "partial": False,
        "error": "LibreOffice not found; old DOC import may fail",
    }


def check_llama_tools() -> dict:
    tools = {
        "llama-server": shutil.which("llama-server"),
        "llama-completion": shutil.which("llama-completion"),
    }
    return {"ok": any(tools.values()), "tools": tools}


def main() -> None:
    checks = {
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python": sys.version,
            "python_ok": sys.version_info >= (3, 11),
            "cwd": str(Path.cwd()),
        },
        "tkinter": check_tkinter(),
        "sqlite_fts5": check_sqlite_fts(),
        "imports": {
            name: {**check_import(name), "purpose": purpose}
            for name, purpose in REQUIRED_IMPORTS.items()
        },
        "tesseract": check_tesseract(),
        "libreoffice": check_libreoffice(),
        "llama_cpp": check_llama_tools(),
    }
    required_ok = [
        checks["platform"]["python_ok"],
        checks["tkinter"]["ok"],
        checks["sqlite_fts5"]["ok"],
        all(item["ok"] for item in checks["imports"].values()),
    ]
    checks["summary"] = {
        "desktop_core_ok": all(required_ok),
        "ocr_ok": checks["tesseract"]["ok"],
        "legacy_doc_ok": checks["libreoffice"]["ok"],
        "legacy_doc_partial": checks["libreoffice"].get("partial", False),
        "local_llm_available": checks["llama_cpp"]["ok"],
    }
    print(json.dumps(checks, ensure_ascii=False, indent=2))
    if not checks["summary"]["desktop_core_ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
