from __future__ import annotations

import ast
import re


def validate_indicator_source(language: str, source_code: str) -> tuple[bool, str]:
    """Structural check before persisting indicator source."""
    code = source_code or ""
    if not code.strip():
        return False, "سورس کد خالی است."
    lang = (language or "pine").strip().lower()
    if lang == "python":
        return _validate_python(code)
    if lang == "pine":
        return _validate_pine(code)
    return True, ""


def _validate_python(code: str) -> tuple[bool, str]:
    try:
        ast.parse(code)
    except SyntaxError as e:
        line = e.lineno or "?"
        msg = e.msg or "خطای نحوی"
        return False, f"خطای ساختاری Python (خط {line}): {msg}"
    return True, ""


def _validate_pine(code: str) -> tuple[bool, str]:
    if not re.search(r"//@version\s*=", code, re.IGNORECASE):
        return False, "Pine Script: خط //@version=... یافت نشد."
    if not re.search(r"\b(indicator|strategy|library)\s*\(", code):
        return False, "Pine Script: باید indicator()، strategy() یا library() داشته باشید."
    err = _bracket_balance_error(code)
    if err:
        return False, f"Pine Script: {err}"
    return True, ""


def _bracket_balance_error(code: str) -> str:
    """Naive balance check; skips // comments and double-quoted strings."""
    i = 0
    n = len(code)
    stack: list[str] = []
    pairs = {")": "(", "]": "[", "}": "{"}

    while i < n:
        ch = code[i]
        if ch == "/" and i + 1 < n and code[i + 1] == "/":
            while i < n and code[i] != "\n":
                i += 1
            continue
        if ch == '"':
            i += 1
            while i < n:
                if code[i] == "\\" and i + 1 < n:
                    i += 2
                    continue
                if code[i] == '"':
                    i += 1
                    break
                i += 1
            continue
        if ch in "([{":
            stack.append(ch)
        elif ch in ")]}":
            if not stack or stack[-1] != pairs[ch]:
                return "پرانتز یا آکولاد بسته‌نشده یا جفت‌نشده."
            stack.pop()
        i += 1

    if stack:
        return "پرانتز یا آکولاد بسته نشده."
    return ""
