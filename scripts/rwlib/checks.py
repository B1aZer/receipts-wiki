"""Checks on the notes a turn wrote, reported to the agent at its next prompt.

The write gate blocks what must never be saved. These checks catch what makes memory drift: a note no index
lists, a cursor left behind when the work it tracks moved, a note grown into a log, and links that lead nowhere.
"""
import re
from pathlib import Path

from . import gitlog, indexer

MAX_NOTE_BYTES = 12000
WIKILINK = re.compile(r"\[\[([^\]|#]+)")


def _index_texts(home):
    memory = Path(home) / "memory"
    texts = []
    for path in [memory / "MEMORY.md", *sorted(memory.glob("index-*.md"))]:
        try:
            texts.append(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
    return texts


def _listed(file, index_texts):
    link = re.compile(r"\((?:\./)?" + re.escape(file) + r"[)#]")
    return any(link.search(text) for text in index_texts)


def _hand_written_index(home, area):
    rel = f"memory/index-{area}.md"
    if (Path(home) / rel).exists() and not indexer.is_generated_index(home, rel):
        return rel
    return None


def turn_notices(home, rels):
    """Notices about the notes in rels, as they are on disk after the turn's commit."""
    rels = set(rels)
    items = indexer.notes(home)
    written = [item for item in items if f"memory/{item['file']}" in rels and item["status"] != "retired"]
    if not written:
        return []
    known, bare = set(), {}
    for item in items:
        known |= {gitlog.slug(item["name"]), gitlog.slug(Path(item["file"]).stem)}
        bare.setdefault(_bare(item["name"]), item["name"])
        bare.setdefault(_bare(Path(item["file"]).stem), item["name"])
    cursors = [item for item in items if item["type"] == "cursor" and item["status"] != "retired"]
    index_texts = _index_texts(home)

    notices = []
    for item in written:
        rel = f"memory/{item['file']}"
        if item["type"] != "cursor" and not _listed(item["file"], index_texts):
            where = _hand_written_index(home, item["area"])
            fix = (f"{where} is written by hand, so add one line linking ({item['file']}) there"
                   if where else f"check that metadata.area is set; the generated index for area '{item['area']}' should list it")
            notices.append(f"{rel} is not linked from any index, so later sessions will not find it: {fix}.")
        if item["type"] != "cursor":
            for cursor in cursors:
                linked = {gitlog.slug(link) for link in WIKILINK.findall(cursor["text"])}
                if f"memory/{cursor['file']}" not in rels and linked & {gitlog.slug(item["name"]), gitlog.slug(Path(item["file"]).stem)}:
                    notices.append(f"you changed {rel}, which cursor note memory/{cursor['file']} points to, but not the cursor. "
                                   f"It still says: \"{cursor['description']}\". If that is no longer where the work stands, "
                                   "rewrite the cursor in place.")
        size = len(item["text"].encode("utf-8"))
        if size > MAX_NOTE_BYTES:
            notices.append(f"{rel} is {size // 1000} KB, over the {MAX_NOTE_BYTES // 1000} KB note budget, so it reads as a log. "
                           "Keep the current belief at the top and move finished or separate facts into their own notes.")
        misspelled = {}
        for link in WIKILINK.findall(item["text"]):
            if gitlog.slug(link) not in known and _bare(link) in bare:
                misspelled[link.strip()] = bare[_bare(link)]
        if misspelled:
            fixes = ", ".join(f"[[{link}]] should be [[{name}]]" for link, name in sorted(misspelled.items()))
            notices.append(f"{rel} has links that match no note name: {fixes}.")
    return notices


def _bare(text):
    """A name without its type prefix, so project-x, project_x and x compare equal."""
    return re.sub(r"^(project|feedback|reference|user|cursor)-", "", gitlog.slug(text))
