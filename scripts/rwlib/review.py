"""Dependency invalidation (PLAN-log-first §3.4): when a fact is superseded, its dependents get marked.

`project-vendor-choice` still called a vendor "the one we are going with" five days after
`cursor-vendor` recorded that it had been dropped. The dependency was already written down -- the note links the cursor -- and nothing acted on it.

Two measurements shape this module, both on a live home (2026-09-28/29):

1. Following `[[links]]` finds only 35% of the notes a change makes stale. Grepping the changed note's
   NAMED THINGS -- companies, people, PR numbers, identifiers, note names -- finds 85%. The working graph
   is an index of named things, not of links and not of embeddings. So candidates come from names.
2. Precision is low: 263 candidates held 62 real dependents. So nothing is ever invalidated automatically.
   This module only builds a queue; an agent reads the snippets and decides, as StateAuditor (arXiv
   2608.01619) does -- propose with a model, but let deterministic checks (here: chronology, "was this
   note last changed before the event?") gate what is even proposed.

The queue lives in state, outside git: it is derived from the log and can be thrown away and rebuilt.
"""
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from . import gitlog, indexer

LINK = re.compile(r"\[\[([^\]\n]+)\]\]")
CODE = re.compile(r"`([A-Za-z0-9_][A-Za-z0-9_./-]{2,})`")
ISSUE = re.compile(r"#(\d{2,})")
PROPER = re.compile(r"\b([A-Z][A-Za-z0-9]{2,}(?:\s+[A-Z][A-Za-z0-9]{2,})*)\b")
# A named thing is multi-word ("Dana Ruiz") or carries internal capitals ("PayFlow", "API").
# A single plain-capitalised word ("Rejected", "Everything") is prose that happened to start a sentence.
ENTITY = re.compile(r"\s|[a-z][A-Z]|^[A-Z0-9]{2,}$")
SNIPPET = 140
MAX_NAMES = 40
MAX_CANDIDATES = 12
DF_MAX = 15  # a name shared by more notes than this is a topic, not an edge

# An explicit [[link]] is a dependency the author declared, so it outranks anything inferred however rare
# that inference is. Issue numbers and code identifiers name one thing exactly. A proper name is the
# recall booster and the loosest of the three, so it sorts last and leans on rarity within its tier.
TIER = {"link": 0, "issue": 1, "code": 1, "name": 2}
FOLD_CASE = {"link": True, "issue": True, "code": True, "name": False}

# Words that start sentences and headings in these notes; as "named things" they match everything.
COMMON = {
    "the", "this", "that", "what", "when", "where", "why", "how", "supersedes", "reopen", "receipts",
    "evidence", "status", "next", "note", "notes", "memory", "project", "reference", "feedback", "user",
    "cursor", "live", "closed", "done", "open", "plan", "and", "but", "not", "his", "her", "their", "our",
    "add", "added", "use", "used", "see", "was", "were", "one", "two", "three", "for", "from", "with",
    "after", "before", "still", "also", "only", "each", "both", "same", "into", "over", "under", "yes", "no",
}


def _clean(name):
    return " ".join(str(name).split()).strip(" .,:;—-")


def named_things(text):
    """The things a note is about, most distinctive first.

    Order matters because the search pattern is capped: an issue number or a note name identifies one
    thing, while a proper name like "Application" identifies a topic at best. Sorting by length would put
    the longest prose phrase first and drop the `#47898` that actually pins a dependency.
    """
    links, codes, issues, proper = [], [], [], []
    for raw in LINK.findall(text or ""):
        links.append(gitlog.slug(raw))
    for raw in ISSUE.findall(text or ""):
        issues.append(f"#{raw}")
    for raw in CODE.findall(text or ""):
        codes.append(_clean(raw))
    for raw in PROPER.findall(text or ""):
        name = _clean(raw)
        if name.lower() in COMMON or not ENTITY.search(name):
            continue  # a plain capitalised word is a sentence opener, not a named thing
        proper.append(name)
    ordered, seen = [], set()
    for group, kind in ((links, "link"), (issues, "issue"), (codes, "code"),
                        (sorted(proper, key=len, reverse=True), "name")):
        for name in group:
            if len(name) >= 3 and name not in seen:
                seen.add(name)
                ordered.append((name, kind))
    return ordered


def _patterns(names):
    """Two patterns, because case carries meaning here.

    A note name, an issue number and a code identifier mean the same thing however they are cased, so they
    match case-insensitively. A proper name does not: matching "Rejected" case-insensitively hits the word
    "rejected" in ordinary prose, and one supersede then queued 40 unrelated notes (measured 2026-09-29).
    Capitalisation is the only signal available for telling a name from a word, so it is respected.
    """
    groups = {}
    for name, kind in list(names)[:MAX_NAMES]:
        groups.setdefault(FOLD_CASE[kind], []).append(re.escape(name))
    out = []
    for fold, parts in groups.items():
        body = r"(?<![\w-])(" + "|".join(parts) + r")(?![\w-])"
        out.append(re.compile(body, re.I) if fold else re.compile(body))
    return out


def _search(patterns, text):
    for pattern in patterns:
        found = pattern.search(text)
        if found:
            return found
    return None


def last_changed(home, scan=400):
    """{rel: datetime} of the last commit that touched each memory file."""
    out = {}
    result = gitlog.git(home, "log", f"-{scan}", "--name-only", "--format=%x01%cI")
    when = None
    for line in result.stdout.splitlines():
        if line.startswith("\x01"):
            try:
                when = datetime.fromisoformat(line[1:])
            except ValueError:
                when = None
        elif line.strip() and when and line not in out:
            out[line.strip()] = when
    return out


def changed_things(old, new):
    """The named things of the lines this edit ADDED, falling back to the whole note.

    Using every name in the note is far too loose: a cursor that mentions `[[some-broad-topic]]`
    makes every note touching that topic a candidate and the queue fills with work nobody needs
    to do (40 candidates for one event, measured 2026-09-29). What makes other notes stale is the claim
    that changed, so the names come from the added lines -- in a supersede, the `Supersedes` line itself.
    """
    if not old:
        return named_things(new or "")
    before = set((old or "").splitlines())
    added = "\n".join(line for line in (new or "").splitlines() if line.strip() and line not in before)
    return named_things(added) or named_things(new or "")


def candidates(home, rel, text, event_time, changed=None, names=None):
    """Notes that mention these named things and have not been touched since the event.

    The chronology check is the deterministic gate: a note already rewritten after the event has had its
    chance to take the change into account, so it is not worth an agent's attention.
    """
    names = named_things(text) if names is None else names
    patterns = _patterns(names)
    if not patterns:
        return []
    changed = last_changed(home) if changed is None else changed
    own = Path(rel).name
    kind_of = {name.lower(): kind for name, kind in names}

    # One pass: which notes mention which names, and how many notes mention each name.
    found = {}
    frequency = {}
    for path in sorted((Path(home) / "memory").glob("*.md")):
        other = f"memory/{path.name}"
        if path.name == own or not indexer.is_note(other):
            continue
        try:
            body = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        here = {}
        for pattern in patterns:
            for match in pattern.finditer(body):
                here.setdefault(match.group(1).lower(), (match.group(1), match.start()))
        if here:
            found[other] = here
            for key in here:
                frequency[key] = frequency.get(key, 0) + 1

    # A name half the home mentions is a topic, not a dependency. One product name appeared in 42 notes
    # and only 15 of those were real dependents; the edges that matter run along names few notes share. Rank by rarity and cap,
    # so an agent gets the most specific dependents rather than an arbitrary slice of a long list.
    rare = {name: count for name, count in frequency.items() if count <= DF_MAX}
    if not rare:
        return []
    hits = []
    for other, here in found.items():
        # A note matching its own name is declaring itself, not depending on anything.
        mine = gitlog.slug(Path(other).name[:-3])
        scored = [(TIER[kind_of.get(key, "name")], rare[key], key)
                  for key in here if key in rare and key != mine]
        if not scored:
            continue
        when = changed.get(other)
        if when and event_time and when > event_time:
            continue  # already rewritten after the event
        tier, count, key = min(scored)
        name, offset = here[key]
        body_line = ""
        try:
            body = (Path(home) / other).read_text(encoding="utf-8", errors="replace")
            start = body.rfind("\n", 0, offset) + 1
            end = body.find("\n", offset)
            body_line = body[start:end if end != -1 else None].strip()
        except OSError:
            pass
        hits.append({"note": other, "name": name, "kind": kind_of.get(key, "name"),
                     "shared_by": count, "snippet": body_line[:SNIPPET]})
    hits.sort(key=lambda hit: (TIER[hit["kind"]], hit["shared_by"], hit["note"]))
    # Report only the strongest kind of evidence present. Proper names exist to find dependents when
    # nothing links the changed note at all; once a real link is found, adding name matches only dilutes
    # the queue. A dry run against the live home queued 12 notes, of which the 9 matched on "OSS" and
    # similar three-letter tokens were noise and the 3 matched on the note's name were the answer.
    if hits:
        best = TIER[hits[0]["kind"]]
        hits = [hit for hit in hits if TIER[hit["kind"]] == best]
    return hits[:MAX_CANDIDATES]


# -- the queue ------------------------------------------------------------

def _path(home):
    """Derived from the home passed in, not from the global config: callers may hold a different home."""
    return Path(home) / ".state" / "review.json"


def _load(home):
    try:
        data = json.loads(_path(home).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(home, data):
    path = _path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=1)
    os.replace(tmp, path)


def mark(home, rel, text, event, commit, event_time=None, changed=None, old=None):
    """Queue this note's dependents for review. Returns how many were queued."""
    event_time = event_time or datetime.now(timezone.utc)
    # The changed note's own name always comes first. Everything that references it depends on it, and a
    # `Supersedes` line rarely repeats the note's own name, so relying on the added lines alone finds
    # nothing at all for the commonest shape of edit.
    names = [(gitlog.slug(Path(rel).name[:-3]), "link")]
    names += [pair for pair in changed_things(old, text) if pair[0] != names[0][0]]
    hits = candidates(home, rel, text, event_time, changed=changed, names=names)
    if not hits:
        return 0
    data = _load(home)
    stamp = event_time.isoformat()
    for hit in hits:
        entry = data.setdefault(hit["note"], [])
        if any(item.get("because") == rel and item.get("commit") == commit for item in entry):
            continue
        entry.append({"because": rel, "event": event, "commit": commit, "at": stamp,
                      "name": hit["name"], "snippet": hit["snippet"]})
    _save(home, data)
    return len(hits)


def _changed_since(home, commit, cache):
    """Memory files changed in commit..HEAD.

    Ancestry, not timestamps. Git records commit times to the second, so a note rewritten a moment after
    the event carries the same second as the event itself and no comparison can separate the two. Which
    commits came after this one is exact and needs no clock.
    """
    if commit not in cache:
        result = gitlog.git(home, "log", f"{commit}..HEAD", "--name-only", "--format=")
        cache[commit] = ({line.strip() for line in result.stdout.splitlines() if line.strip()}
                         if result.returncode == 0 else set())
    return cache[commit]


def queue(home):
    """Open entries, dropping any whose note has been changed since it was queued (it has had its chance)."""
    data = _load(home)
    if not data:
        return []
    cache = {}
    out, kept = [], {}
    for rel, entries in data.items():
        if not (Path(home) / rel).exists():
            continue
        live = [item for item in entries
                if item.get("commit") and rel not in _changed_since(home, item["commit"], cache)]
        if live:
            kept[rel] = live
            out.append({"note": rel, "entries": live})
    if kept != data:
        _save(home, kept)
    out.sort(key=lambda row: max(item["at"] for item in row["entries"]), reverse=True)
    return out


def render(rows):
    if not rows:
        return "nothing waiting for review\n"
    lines = [f"{len(rows)} note(s) to check against a change they depend on:", ""]
    for row in rows:
        name = Path(row["note"]).name[:-3]
        lines.append(f"{name}")
        for item in row["entries"]:
            because = Path(item["because"]).name[:-3]
            lines.append(f"  {item['event']} in {because} [{item['commit']}] {item['at'][:10]}"
                         f" — mentions \"{item['name']}\"")
            if item.get("snippet"):
                lines.append(f"    {item['snippet']}")
        lines.append("")
    lines.append("Read each note, decide STALE / UPDATED / UNAFFECTED, and correct forward where it is stale.")
    lines.append("An entry clears by itself once its note is changed.")
    return "\n".join(lines) + "\n"
