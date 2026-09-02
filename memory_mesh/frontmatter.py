"""Strict YAML-subset frontmatter parsing and serialisation (stdlib only).

The vault's frontmatter is a controlled vocabulary (see _meta/spec/schema.md),
so a small strict parser is safer than a permissive one: anything outside the
subset is a schema error the lint wants to surface anyway (issues.md I-003).

Subset: block mappings (nested via indentation), inline lists `[a, b]`,
inline dicts `{a: 1}`, block lists (`- item`), scalars (null, bool, int,
float, single/double-quoted or bare strings). Dates remain strings.
"""

from __future__ import annotations

import re
from typing import Any

FM_DELIM = "---"


class FrontmatterError(ValueError):
    pass


# ---------------------------------------------------------------- scalars


def _parse_scalar(tok: str) -> Any:
    tok = tok.strip()
    if tok == "" or tok in ("null", "~", "None"):
        return None
    if len(tok) >= 2 and tok[0] == tok[-1] and tok[0] in "\"'":
        body = tok[1:-1]
        if tok[0] == '"':
            body = body.replace('\\"', '"').replace("\\\\", "\\")
        return body
    if tok in ("true", "True"):
        return True
    if tok in ("false", "False"):
        return False
    if re.fullmatch(r"[+-]?\d+", tok):
        return int(tok)
    if re.fullmatch(r"[+-]?\d*\.\d+", tok):
        return float(tok)
    return tok


def _strip_comment(line: str) -> str:
    """Remove a trailing ` # comment` that is not inside quotes."""
    out = []
    in_q: str | None = None
    for i, ch in enumerate(line):
        if in_q:
            if ch == in_q:
                in_q = None
            out.append(ch)
            continue
        if ch in "\"'":
            in_q = ch
            out.append(ch)
            continue
        if ch == "#" and (i == 0 or line[i - 1] in " \t"):
            break
        out.append(ch)
    return "".join(out).rstrip()


# ------------------------------------------------------- inline containers


def _split_inline(s: str) -> list[str]:
    """Split a bracket-free-at-top-level comma list, respecting nesting."""
    parts, depth, buf, in_q = [], 0, [], None
    for ch in s:
        if in_q:
            buf.append(ch)
            if ch == in_q:
                in_q = None
            continue
        if ch in "\"'":
            in_q = ch
            buf.append(ch)
        elif ch in "[{":
            depth += 1
            buf.append(ch)
        elif ch in "]}":
            depth -= 1
            buf.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if buf or parts:
        parts.append("".join(buf))
    return parts


def _parse_value(tok: str) -> Any:
    tok = tok.strip()
    if tok.startswith("[") and tok.endswith("]"):
        inner = tok[1:-1].strip()
        if not inner:
            return []
        return [_parse_value(p) for p in _split_inline(inner)]
    if tok.startswith("{") and tok.endswith("}"):
        inner = tok[1:-1].strip()
        d: dict[str, Any] = {}
        if not inner:
            return d
        for part in _split_inline(inner):
            if ":" not in part:
                raise FrontmatterError(f"bad inline mapping entry: {part!r}")
            k, v = part.split(":", 1)
            d[k.strip().strip("\"'")] = _parse_value(v)
        return d
    return _parse_scalar(tok)


# --------------------------------------------------------- block structure

_KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_.-]*)\s*:(.*)$")


def _parse_block(lines: list[tuple[int, str]], pos: int, indent: int) -> tuple[Any, int]:
    """Parse a block mapping or list starting at lines[pos] with `indent`."""
    if pos < len(lines) and lines[pos][1].startswith("- "):
        items = []
        while pos < len(lines) and lines[pos][0] == indent and lines[pos][1].startswith("- "):
            items.append(_parse_value(lines[pos][1][2:]))
            pos += 1
        return items, pos
    mapping: dict[str, Any] = {}
    while pos < len(lines):
        ind, content = lines[pos]
        if ind < indent:
            break
        if ind > indent:
            raise FrontmatterError(f"unexpected indentation: {content!r}")
        m = _KEY_RE.match(content)
        if not m:
            raise FrontmatterError(f"expected `key: value`, got {content!r}")
        key, rest = m.group(1), m.group(2).strip()
        pos += 1
        if rest:
            mapping[key] = _parse_value(rest)
        else:
            if pos < len(lines) and lines[pos][0] > ind:
                mapping[key], pos = _parse_block(lines, pos, lines[pos][0])
            else:
                mapping[key] = None
    return mapping, pos


def parse_yaml_subset(text: str) -> dict[str, Any]:
    lines: list[tuple[int, str]] = []
    for raw in text.splitlines():
        line = _strip_comment(raw.rstrip("\n"))
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        lines.append((indent, line.strip()))
    if not lines:
        return {}
    result, pos = _parse_block(lines, 0, lines[0][0])
    if pos != len(lines):
        raise FrontmatterError(f"trailing content at line {pos}")
    if not isinstance(result, dict):
        raise FrontmatterError("frontmatter must be a mapping")
    return result


# ------------------------------------------------------------ serialising

_BARE_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _./+@()→\-]*$")


def _dump_scalar(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v)
    if s and _BARE_OK.fullmatch(s) and s not in ("true", "false", "null", "~") and not s.endswith(" "):
        return s
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _dump_value(v: Any) -> str:
    if isinstance(v, list):
        return "[" + ", ".join(_dump_value(i) for i in v) + "]"
    if isinstance(v, dict):
        return "{" + ", ".join(f"{k}: {_dump_value(val)}" for k, val in v.items()) + "}"
    return _dump_scalar(v)


def dump_yaml_subset(data: dict[str, Any], indent: int = 0) -> str:
    out: list[str] = []
    pad = " " * indent
    for key, val in data.items():
        if isinstance(val, dict):
            if val and all(not isinstance(v, (dict, list)) for v in val.values()):
                out.append(f"{pad}{key}: {_dump_value(val)}")
            elif not val:
                out.append(f"{pad}{key}: {{}}")
            else:
                out.append(f"{pad}{key}:")
                out.append(dump_yaml_subset(val, indent + 2))
        elif isinstance(val, list):
            out.append(f"{pad}{key}: {_dump_value(val)}")
        else:
            out.append(f"{pad}{key}: {_dump_scalar(val)}")
    return "\n".join(out)


# ------------------------------------------------------------- documents


def parse(text: str) -> tuple[dict[str, Any], str]:
    """Split a Markdown document into (frontmatter dict, body)."""
    if not text.startswith(FM_DELIM + "\n") and text.strip() != FM_DELIM:
        return {}, text
    lines = text.split("\n")
    for i in range(1, len(lines)):
        if lines[i].strip() == FM_DELIM:
            fm_text = "\n".join(lines[1:i])
            body = "\n".join(lines[i + 1 :])
            return parse_yaml_subset(fm_text), body.lstrip("\n")
    raise FrontmatterError("unterminated frontmatter block")


def compose(meta: dict[str, Any], body: str) -> str:
    fm = dump_yaml_subset(meta)
    body = body.rstrip("\n")
    return f"{FM_DELIM}\n{fm}\n{FM_DELIM}\n\n{body}\n" if body else f"{FM_DELIM}\n{fm}\n{FM_DELIM}\n"
