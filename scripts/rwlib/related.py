"""Related-note hints for the capture hook.

Two bands by word overlap between note names and descriptions: a strong match suggests a possible
duplicate or contradiction, a weak match is only mentioned. Overlap cannot tell "use X" from
"don't use X", so hints never change anything; the agent reads and decides.
"""
import re
from pathlib import Path

from . import frontmatter

STRONG = 0.5
WEAK = 0.25
HEAD_BYTES = 4096

STOPWORDS = set(
    "the and for with that this from into when then than are was were not but use used using have has had "
    "its our your you they them their about after before over under only also will would should could can "
    "may might must each any all some more most other such same very just via per new old note notes memory "
    "project feedback reference user type name description".split()
)


def tokens(text):
    return {w for w in re.findall(r"[a-z0-9]+", str(text or "").lower()) if len(w) >= 3 and w not in STOPWORDS}


def _summary(text):
    fm, body = frontmatter.split(text)
    status = str(frontmatter.get(fm, "status", "metadata.status") or "")
    label = f"{frontmatter.get(fm, 'name') or ''} {frontmatter.get(fm, 'description') or ''}"
    if not label.strip():
        label = body[:300]
    return tokens(label), status


def candidates(home, rel, text, limit=3):
    mine, _ = _summary(text)
    if len(mine) < 2:
        return [], []
    scored = []
    for path in sorted((Path(home) / "memory").glob("*.md")):
        other = str(Path("memory") / path.name)
        if other == rel or path.name == "MEMORY.md" or path.name.startswith("index-"):
            continue
        try:
            head = path.read_text(encoding="utf-8", errors="replace")[:HEAD_BYTES]
        except OSError:
            continue
        theirs, status = _summary(head)
        if status == "retired" or not theirs:
            continue
        score = len(mine & theirs) / len(mine | theirs)
        if score >= WEAK:
            scored.append((score, other))
    scored.sort(key=lambda item: (-item[0], item[1]))
    strong = [other for score, other in scored if score >= STRONG][:limit]
    weak = [other for score, other in scored if WEAK <= score < STRONG][:limit]
    return strong, weak
