"""Named checks on memory notes.

The write gate blocks what must never be saved. These checks catch what makes memory drift: a note no index
lists, a cursor left behind when the work it tracks moved, a note grown into a log, links that lead nowhere,
and a note nothing else connects to.

Every finding names its rule, and the per-note rules run in two places: over the notes a turn wrote (reported
to the agent at its next prompt) and over every note (`rw.py lint`), so a sweep sees what a turn would have.
"""
import os
import re
import subprocess
from pathlib import Path

from . import frontmatter, gitlog, indexer

RULES = {
    "index-unlisted": "note that no index links, so later sessions will not find it",
    "note-too-big": "note over the size budget, so it reads as a log rather than a fact",
    "cursor-too-long": "cursor description over the budget; every session start loads it",
    "link-misspelled": "[[link]] that matches no note name but names an existing note",
    "orphan-note": "note with no [[link]] in or out: nothing in memory connects it to anything (sweep only)",
    "cursor-not-updated": "a note changed while the cursor pointing at it did not (turn only)",
    "doc-unnamed": "document in a folder memory names that no note names (turn check, or the `lint --docs` sweep)",
    "cursor-ended-in-prose": "cursor whose own text says the work ended while its status still says active",
    "field-duplicated": "a note restating its own name or description inside metadata, where nothing reads it",
    "rank-in-prose": "a note stating a rank in words when rank is owned by metadata.priority",
    "frontmatter-lost": "frontmatter the parser accepts but silently drops or overwrites",
    "link-wrong-form": "[[link]] used for a note's filename or for a skill, where a path link belongs",
    "decision-without-alternative": "a decision note naming no rejected option, which makes it a conclusion in the wrong type",
    "decision-without-evidence": "a decision note with no pointer to where the option was ruled out",
    "done-when-vague": "a completion criterion the agent could satisfy by writing, rather than one the world decides",
}

MAX_NOTE_BYTES = 12000
# A cursor's description is shown at every session start and in MEMORY.md, so it must stay one line.
MAX_CURSOR_DESCRIPTION = 250
WIKILINK = re.compile(r"\[\[([^\]|#]+)")
# Rank is owned by metadata.priority. Stated in words it is a copy: on another note it contradicts the
# owner (2026-09-30, one cursor ranked another and disagreed with it a day later), and on the owner
# itself it simply goes stale the moment the field changes. \b cannot precede "#", hence the lookbehind.
RANK = re.compile(r"(?<![\w#])(TOP PRIORITY|#\d+ PRIORITY|PRIORITY[: ]+#?\d)", re.I)
# A cursor states its own state in prose; when that prose says the work ended, the status field should
# agree, or the session-start block keeps presenting finished work as live.
ENDED = re.compile(r"\b(CLOSED|REJECTED|RETIRED|ABANDONED|SHIPPED AND DONE|WORK ENDED)\b")


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


SKILLS = Path("~/.claude/skills").expanduser()
FENCE = re.compile(r"```.*?```", re.S)
CODE_SPAN = re.compile(r"`[^`\n]*`")
# What a decision note must carry. "Rejected" is the house word; the alternatives are the forms a
# session actually writes when it means the same thing.
# A criterion is only worth stating if the agent cannot make it true by writing text. These are the
# referents the world decides: an issue or PR number, a URL, a command or identifier in backticks, a
# path, a threshold, a count, a date. "Done when the PR is merged" passes; "done when the code is
# clean" does not, whoever wrote it.
EXTERNAL = re.compile(r"(#\d+|https?://|`[^`]+`|\b[\w./-]+\.(?:py|md|json|ts|tsv|jsonl|yml|yaml|sh|html)\b"
                      r"|\b\d+(?:\.\d+)?\s*(?:%|x\b)|[<>=]\s*\d|\b\d{4}-\d{2}-\d{2}\b"
                      r"|\bexit(?:s)?\s+\d|\breturns\s+\d{3}\b"
                      # ...or an EVENT. The line that holds, after widening this twice: an event
                      # either happened or it did not, while a judgement ("clean", "right", "good")
                      # is satisfiable by assertion. No script can grep an inbox, but the agent
                      # still cannot make Supabase reply by writing text. The test is "could I make
                      # this true by writing?", not "can a tool verify it?". Widening past events
                      # into judgements would empty the rule, so treat further additions as suspect.
                      r"|\b(merged|replied|repl(?:y|ies) received|response received|received|published|"
                      r"approved|issued|invited|offered|accepted|rejected|signed|paid|granted|landed|"
                      r"submitted|sent|posted|deployed|delivered|filed|opened|closed|shipped|scheduled)\b)", re.I)

REJECTED = re.compile(r"\b(rejected|ruled out|not chosen|discarded|declined|instead of|considered and)\b", re.I)
# An origin the reader can open: a session/turn id, a commit sha, a file path, an arXiv id, a URL,
# a measured number, or an absolute date.
EVIDENCE = re.compile(r"(\b[0-9a-f]{7,40}\b|\barXiv[: ]|https?://|\bturn\b|\bsession\b|"
                      r"\b\d{4}-\d{2}-\d{2}\b|\b\d+(\.\d+)?%|\b[\w./-]+\.(py|md|json|ts|tsv|jsonl):?\d*)", re.I)


def prose_only(text):
    """The text with fenced blocks and inline code blanked out, lengths preserved.

    A note documenting the link syntax writes `[[link]]` or `[[id]]` in a code span. Those are
    examples, not references; counting them would make this check cry wolf on four notes here.
    """
    text = FENCE.sub(lambda m: " " * len(m.group(0)), text or "")
    return CODE_SPAN.sub(lambda m: " " * len(m.group(0)), text)


def _bare(text):
    """A name without its type prefix, so project-x, project_x and x compare equal."""
    return re.sub(r"^(project|feedback|reference|user|cursor|decision)-", "", gitlog.slug(text))


def _slugs(item):
    return {gitlog.slug(item["name"]), gitlog.slug(Path(item["file"]).stem)}


# A new note usually has no inbound link yet, so the graph rule belongs to the sweep, not to the turn.
SWEEP_ONLY = ("orphan-note",)


def note_rules(home, subjects, items=None, skip=()):
    """[(rule, rel, message)] for the per-note rules, judged against the whole home.

    subjects are the notes to report on; items is every note, for link and name lookups; skip names rules
    to leave out (the turn checks skip the sweep-only ones).
    """
    items = items if items is not None else indexer.notes(home)
    known, bare = set(), {}
    linked_from_elsewhere = set()
    for item in items:
        known |= _slugs(item)
        bare.setdefault(_bare(item["name"]), item["name"])
        bare.setdefault(_bare(Path(item["file"]).stem), item["name"])
    for item in items:
        for link in WIKILINK.findall(item["text"]):
            target = gitlog.slug(link)
            if target not in _slugs(item):
                linked_from_elsewhere.add(target)
    index_texts = _index_texts(home)

    found = []
    for item in subjects:
        rel = f"memory/{item['file']}"
        if item["type"] != "cursor" and not _listed(item["file"], index_texts):
            where = _hand_written_index(home, item["area"])
            fix = (f"{where} is written by hand, so add one line linking ({item['file']}) there"
                   if where else f"check that metadata.area is set; the generated index for area '{item['area']}' should list it")
            found.append(("index-unlisted", rel, f"{rel} is not linked from any index, so later sessions will not find it: {fix}."))
        # The body, not the whole file: "priority: 1" in the frontmatter is the field, not a copy of it.
        for problem in frontmatter.problems(item["text"]):
            found.append(("frontmatter-lost", rel, f"{rel}: {problem}"))
        rank = RANK.search(item["description"]) or RANK.search(prose_only(frontmatter.split(item["text"])[1]))
        if rank:
            owns = item.get("priority") is not None
            fix = ("its own metadata.priority already says so, and the words stay behind when the field changes"
                   if owns else
                   "it owns no metadata.priority, so this is a copy of a rank another note owns")
            found.append(("rank-in-prose", rel,
                          f"{rel} says \"{rank.group(0)}\" in words: {fix}. "
                          "Set or read metadata.priority instead; the session-start block orders by it."))
        for key in ("name", "description"):
            inner = item["frontmatter"].get(f"metadata.{key}")
            if inner and str(inner).strip() != str(item[key]).strip():
                found.append(("field-duplicated", rel,
                              f"{rel} sets both {key} and metadata.{key}, and they differ. Only the top-level "
                              f"one is read, so the metadata copy is invisible and free to drift: "
                              f"\"{str(inner)[:90]}\". Keep one."))
        if item["type"] == "cursor" and item["status"] != "retired":
            ended = ENDED.search(item["description"])
            if ended:
                found.append(("cursor-ended-in-prose", rel,
                              f"{rel} says \"{ended.group(0)}\" in its description but its status is "
                              f"'{item['status']}', so every session start still lists it among live work. "
                              "Set metadata.status: retired when the workstream has ended, or reword the "
                              "description if it has not."))
        if item["type"] == "cursor" and len(item["description"]) > MAX_CURSOR_DESCRIPTION:
            found.append(("cursor-too-long", rel,
                          f"{rel}'s description is {len(item['description'])} characters; every session start shows it, so keep it "
                          f"under {MAX_CURSOR_DESCRIPTION}: where the work stands and the next action. Move the rest into the note's body."))
        size = len(item["text"].encode("utf-8"))
        if size > MAX_NOTE_BYTES:
            found.append(("note-too-big", rel,
                          f"{rel} is {size // 1000} KB, over the {MAX_NOTE_BYTES // 1000} KB note budget, so it reads as a log. "
                          "Keep the current belief at the top and move finished or separate facts into their own notes."))
        # A [[link]] to a note that does not exist yet is deliberate: it marks something worth writing
        # later. So this reports only the two cases that cannot be that — a link naming an existing note
        # by its filename, and a link naming a skill, which is a thing on disk and wants a path instead.
        for raw in WIKILINK.findall(prose_only(item["text"])):
            target = raw.strip()
            if gitlog.slug(target) in known or _bare(target) in bare:
                continue
            if target.lower().endswith(".md") and gitlog.slug(target[:-3]) in known:
                found.append(("link-wrong-form", rel, f"{rel} links [[{target}]] with a .md suffix; the link form is "
                                                      f"the note's name, so write [[{gitlog.slug(target[:-3])}]]."))
            elif (SKILLS / gitlog.slug(target)).is_dir():
                found.append(("link-wrong-form", rel,
                              f"{rel} links [[{target}]], which is a skill rather than a note. [[ ]] means a memory "
                              f"note; anything on disk is a path link — [{target}](~/.claude/skills/{target}/SKILL.md)."))
        # A decision note exists to stop an option being re-litigated, so it is only worth its type if it
        # names what lost and points at where that happened. Writing what it rejected is a write policy,
        # and policy execution is the measured failure of memory agents (AdaMem, arXiv 2606.21144), so it
        # is checked rather than documented. The pointer matters for a second reason: LLM-written design
        # rationale scores ~0.27 precision with 1.6-3.2% of arguments actively misleading (arXiv
        # 2504.20781), so a reason with no origin is not trustworthy enough to act on later.
        # Who writes a criterion matters less than whether the world can settle it: an agent that
        # both states and judges its own completion is self-reporting. Approval stays cheap only
        # while every criterion is one line and externally checkable.
        for criterion in item.get("done_when") or []:
            if not EXTERNAL.search(criterion):
                found.append(("done-when-vague", rel,
                              f"{rel} has a criterion nothing outside can settle: {criterion!r}. Name something the "
                              "world decides — a PR or issue number, a URL, a command in backticks, a file, a "
                              "threshold or a date."))
        if item["type"] == "decision":
            body = prose_only(item["text"])
            if not REJECTED.search(body):
                found.append(("decision-without-alternative", rel,
                              f"{rel} is a decision note but names no rejected option. Add a `Rejected:` line per "
                              "option with the reason it lost, or make this an ordinary note about the conclusion."))
            if not EVIDENCE.search(body):
                found.append(("decision-without-evidence", rel,
                              f"{rel} states a decision with nothing to check it against. Cite where it was ruled "
                              "out: a session and turn, a commit, a measurement, or a file and line."))
        misspelled = {}
        for link in WIKILINK.findall(item["text"]):
            if gitlog.slug(link) not in known and _bare(link) in bare:
                misspelled[link.strip()] = bare[_bare(link)]
        if misspelled:
            fixes = ", ".join(f"[[{link}]] should be [[{name}]]" for link, name in sorted(misspelled.items()))
            found.append(("link-misspelled", rel, f"{rel} has links that match no note name: {fixes}."))
        outbound = {gitlog.slug(link) for link in WIKILINK.findall(item["text"])} & known
        if "orphan-note" not in skip and item["type"] != "cursor" and not outbound and not (_slugs(item) & linked_from_elsewhere):
            found.append(("orphan-note", rel,
                          f"{rel} has no [[link]] in or out, so nothing in memory connects it to related work. "
                          "Link it from the notes it belongs with, or link them from it."))
    return found


def turn_notices(home, rels):
    """Notices about the notes in rels, as they are on disk after the turn's commit."""
    rels = set(rels)
    items = indexer.notes(home)
    written = [item for item in items if f"memory/{item['file']}" in rels and item["status"] != "retired"]
    if not written:
        return []
    cursors = [item for item in items if item["type"] == "cursor" and item["status"] != "retired"]

    notices = []
    for item in written:
        rel = f"memory/{item['file']}"
        if item["type"] == "cursor":
            continue
        for cursor in cursors:
            linked = {gitlog.slug(link) for link in WIKILINK.findall(cursor["text"])}
            if f"memory/{cursor['file']}" not in rels and linked & _slugs(item):
                notices.append(f"cursor-not-updated: you changed {rel}, which cursor note memory/{cursor['file']} points to, "
                               f"but not the cursor. It still says: \"{cursor['description']}\". If that is no longer where the "
                               "work stands, rewrite the cursor in place.")
    notices += [f"{rule}: {message}" for rule, _, message in note_rules(home, written, items, skip=SWEEP_ONLY)]
    return notices


# Documents written outside memory: a session can finish a piece of research, leave it in a file, and never tell
# memory it exists. On the author's machine 42 of 78 new markdown files from one week were named by no note.
SKIP_DOC_PARTS = ("/scratchpad/", "/.claude/", "/node_modules/", "/.git/")


def is_doc_candidate(path, home):
    """A markdown file outside the memory home and outside scratch or tool folders."""
    text = str(path)
    if not text.endswith(".md") or any(part in text for part in SKIP_DOC_PARTS):
        return False
    try:
        Path(text).resolve().relative_to(Path(home).resolve())
        return False
    except ValueError:
        return True


def unnamed_docs(home, paths):
    """Of the given document paths, those that still exist and that no memory file names."""
    memory = Path(home) / "memory"
    corpus = ""
    for path in memory.glob("*.md"):
        try:
            corpus += path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
    return [p for p in paths if Path(p).exists() and Path(p).name not in corpus]


def docs_notice(paths):
    shown = ", ".join(paths[:5]) + (f" and {len(paths) - 5} more" if len(paths) > 5 else "")
    return (f"doc-unnamed: your last turn created {shown}, and no memory note names {'it' if len(paths) == 1 else 'them'}. "
            "If a later session should find one, add a line naming the file and what it holds to the note for that work "
            "(`receipts-wiki find <topic>` shows which note); skip scratch files.")


# Folders memory already names are where its documents live. Everything else on disk is not memory's business,
# which is why the sweep follows the paths notes mention rather than scanning the machine.
# Any absolute or ~-rooted path of two segments or more. A loose pattern is safe because every candidate
# is then checked against the filesystem: what does not exist is not a folder memory names.
PATH_IN_TEXT = re.compile(r"(?:~|\$HOME)?/[A-Za-z0-9._\-]+(?:/[A-Za-z0-9._\-]+)+")
# Files a repository carries by convention: they belong to the repo, not to memory.
REPO_FILES = {"README.md", "CHANGELOG.md", "CONTRIBUTING.md", "LICENSE.md", "CODE_OF_CONDUCT.md",
              "SECURITY.md", "CLAUDE.md", "AGENTS.md", "TODO.md"}


def _memory_text(home):
    parts = []
    for path in sorted((Path(home) / "memory").glob("*.md")):
        try:
            parts.append(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
    return "\n".join(parts)


def mentioned_dirs(home, corpus=None, limit=200):
    """Existing folders that memory names, by path or through a file in them."""
    corpus = corpus if corpus is not None else _memory_text(home)
    home = Path(home).resolve()
    found = set()
    for raw in PATH_IN_TEXT.findall(corpus):
        candidate = Path(os.path.expanduser(raw.rstrip("`.,;:)")))
        folder = candidate if candidate.is_dir() else candidate.parent
        try:
            folder = folder.resolve()
        except (OSError, RuntimeError):
            continue
        if not folder.is_dir() or folder == home or home in folder.parents:
            continue
        # A folder directly under the home directory (Downloads, Dropbox, Sites) is too broad to be
        # "where memory's documents live"; a path with a space in it also truncates to one of these.
        if folder == Path.home() or folder.parent == Path.home():
            continue
        if any(part in str(folder) for part in SKIP_DOC_PARTS):
            continue
        found.add(folder)
        if len(found) >= limit:
            break
    return sorted(found)


def _git_tracked(path):
    try:
        return subprocess.run(["git", "-C", str(path.parent), "ls-files", "--error-unmatch", path.name],
                              capture_output=True, check=False).returncode == 0
    except OSError:
        return False


def unnamed_docs_in_dirs(home, corpus=None):
    """[(folder, [paths])] for markdown files in folders memory names that no note names.

    A file a repository tracks is documentation of that repository and is found there; the sweep is for the
    working documents a session wrote and never told memory about.
    """
    corpus = corpus if corpus is not None else _memory_text(home)
    out = []
    for folder in mentioned_dirs(home, corpus):
        unnamed = [path for path in sorted(folder.glob("*.md"))
                   if path.name not in corpus and path.stem not in corpus
                   and path.name not in REPO_FILES and not _git_tracked(path)]
        if unnamed:
            out.append((folder, unnamed))
    return out
