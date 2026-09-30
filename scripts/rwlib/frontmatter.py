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


def problems(text):
    """Frontmatter this parser accepts but does not mean what it says. Returns a list of messages.

    The supported subset is deliberate (§ module docstring), but everything outside it is skipped in
    silence, which is the dangerous part: the value is simply gone and every later check sees a note
    that looks fine. These three are what a person or a YAML-aware editor actually writes.
    """
    if not text or not text.startswith("---"):
        return []
    end = text.find("\n---", 3)
    if end == -1:
        return ["frontmatter opens with --- but never closes, so none of it is read"]
    found, seen, parent = [], {}, None
    for raw in text[3:end].strip("\n").splitlines():
        line = raw.strip()
        if not line or line.startswith("- ") or line.startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())
        if indent == 0:
            parent = None
        match = KEY.match(line)
        if not match:
            if re.match(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_.-]+\s*:", line):
                found.append(f"`{line[:60]}` is dropped: a dotted key only works as a nested one "
                             f"(`metadata:` on its own line, then the key indented under it)")
            else:
                # A value wrapped onto a second line. The parser keeps the first line and skips this
                # one, so the value is quietly truncated -- and an edit to the first line can leave
                # the remainder orphaned, which is how it usually shows up.
                found.append(f"`{line[:60]}` is dropped: it is not `key: value`, so if it continues "
                             f"the line above, that value is silently truncated. Keep a value on one line.")
            continue
        key, value = match.group(1), match.group(2).strip()
        if value == "" and indent == 0:
            parent = key
            continue
        if value in ("|", ">", "|-", ">-"):
            found.append(f"`{key}` is a YAML block scalar; this parser stores the marker itself, so the "
                         f"value becomes \"{value}\" and the lines under it are lost. Put it on one line.")
        dotted = f"{parent}.{key}" if parent and indent > 0 else key
        if dotted in seen:
            found.append(f"`{dotted}` is set twice; the last one silently wins")
        seen[dotted] = value
    return found


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
