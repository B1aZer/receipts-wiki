"""Reads the small frontmatter subset that memory notes use.

Supported: `key: value`, one level of nesting (`metadata:` then indented keys),
inline lists (`receipts: [a, b]`) and dash lists. Keys come back dotted: `metadata.area`.
"""
import re

KEY = re.compile(r"([A-Za-z0-9_\-]+):\s*(.*)$")


def split(text):
    """Return (frontmatter dict, body)."""
    if not text or not text.startswith("---"):
        return {}, text or ""
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    block = text[3:end].strip("\n")
    body = text[end + 4:].lstrip("\n")
    return parse(block), body


def parse(block):
    flat = {}
    parent = None
    list_key = None
    for raw in block.splitlines():
        if not raw.strip():
            continue
        indent = len(raw) - len(raw.lstrip())
        line = raw.strip()
        if line.startswith("- ") and list_key:
            items = flat.setdefault(list_key, [])
            if isinstance(items, list):
                items.append(_scalar(line[2:]))
            continue
        match = KEY.match(line)
        if not match:
            continue
        key, value = match.group(1), match.group(2).strip()
        if indent == 0:
            parent = None
        dotted = f"{parent}.{key}" if parent and indent > 0 else key
        if value == "":
            if indent == 0:
                parent = key
            list_key = dotted
            continue
        list_key = None
        flat[dotted] = _inline_list(value) if value.startswith("[") and value.endswith("]") else _scalar(value)
    return flat


def get(flat, *keys, default=None):
    for key in keys:
        value = flat.get(key)
        if value not in (None, "", []):
            return value
    return default


def _scalar(value):
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _inline_list(value):
    return [_scalar(item) for item in value[1:-1].split(",") if item.strip()]
