from __future__ import annotations

import re
from typing import Any


_INPUT_LINE = re.compile(
    r"^\s*(?P<var>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*input\.(?P<kind>int|float|bool|color|string|timeframe|source)\s*\(",
    re.MULTILINE,
)
_TITLE = re.compile(r"""title\s*=\s*["']([^"']+)["']|,\s*["']([^"']+)["']\s*[,)]""")
_OVERLAY = re.compile(
    r"indicator\s*\([^)]*overlay\s*=\s*(true|false)",
    re.IGNORECASE | re.DOTALL,
)


def _parse_default(raw: str, kind: str) -> Any:
    s = (raw or "").strip()
    if kind == "bool":
        return s.lower() in ("true", "1")
    if kind == "int":
        try:
            return int(re.sub(r"[^0-9-]", "", s.split(",")[0]) or "0")
        except ValueError:
            return 0
    if kind == "float":
        try:
            return float(re.sub(r"[^0-9.-]", "", s.split(",")[0]) or "0")
        except ValueError:
            return 0.0
    if kind == "color":
        m = re.search(r"#([0-9a-fA-F]{6,8})", s)
        if m:
            return "#" + m.group(1)[:6]
        return "#7E57C2"
    if kind == "string":
        m = re.search(r'["\']([^"\']*)["\']', s)
        return m.group(1) if m else ""
    return s.split(",")[0].strip() or "close"


def parse_pine_inputs(source: str) -> list[dict[str, Any]]:
    """Extract TradingView-style input.* declarations from Pine source."""
    code = source or ""
    out: list[dict[str, Any]] = []
    for m in _INPUT_LINE.finditer(code):
        var = m.group("var")
        kind = m.group("kind")
        start = m.end()
        depth = 1
        i = start
        while i < len(code) and depth:
            if code[i] == "(":
                depth += 1
            elif code[i] == ")":
                depth -= 1
            i += 1
        args = code[start : i - 1]
        title_m = _TITLE.search(args)
        title = (title_m.group(1) or title_m.group(2) if title_m else "") or var
        default = _parse_default(args, kind)
        field: dict[str, Any] = {
            "id": var,
            "type": kind,
            "title": title,
            "default": default,
        }
        min_m = re.search(r"minval\s*=\s*(-?\d+(?:\.\d+)?)", args)
        max_m = re.search(r"maxval\s*=\s*(-?\d+(?:\.\d+)?)", args)
        if min_m and kind in ("int", "float"):
            field["min"] = float(min_m.group(1))
        if max_m and kind in ("int", "float"):
            field["max"] = float(max_m.group(1))
        out.append(field)
    return out


def pine_overlay_on_chart(source: str) -> bool:
    m = _OVERLAY.search(source or "")
    if m:
        return m.group(1).lower() == "true"
    return False
