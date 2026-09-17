"""Find notes by topic, whatever the working directory.

Areas decide which index a session loads, but work crosses directories: a PostHog session may start in
any folder. This ranks every active note against a piece of text (a prompt or a query) with BM25 over the
note body plus a boosted name-and-description field, so a session can reach the notes on its topic
without knowing where they are filed.
"""
import math
import re
from collections import Counter

from . import frontmatter, gitlog, indexer, related

K1 = 1.2
B = 0.75
LABEL_WEIGHT = 3.0
WIKILINK = re.compile(r"\[\[([^\]|#]+)")


def words(text):
    return [w for w in re.findall(r"[a-z0-9]+", str(text or "").lower()) if len(w) >= 3 and w not in related.STOPWORDS]


class Corpus:
    def __init__(self, home):
        self.items = [item for item in indexer.notes(home) if item["status"] != "retired"]
        self.label = []
        self.body = []
        for item in self.items:
            _, body = frontmatter.split(item["text"])
            self.label.append(Counter(words(f"{item['name']} {item['description']} {item['file'][:-3]}")))
            self.body.append(Counter(words(body)))
        count = len(self.items) or 1
        self.average = sum(sum(c.values()) for c in self.body) / count or 1.0
        seen = Counter()
        for label, body in zip(self.label, self.body):
            seen.update(set(label) | set(body))
        self.idf = {w: math.log(1 + (count - n + 0.5) / (n + 0.5)) for w, n in seen.items()}

    def rank(self, text, limit=8, minimum=0.0):
        """[(score, item)] best first. A word that occurs in most notes adds almost nothing."""
        query = set(words(text))
        if not query:
            return []
        scored = []
        for item, label, body in zip(self.items, self.label, self.body):
            length = sum(body.values())
            score = 0.0
            for w in query & (set(label) | set(body)):
                idf = self.idf.get(w, 0.0)
                tf = body.get(w, 0)
                score += idf * tf * (K1 + 1) / (tf + K1 * (1 - B + B * length / self.average))
                if w in label:
                    score += LABEL_WEIGHT * idf
            if score > minimum:
                scored.append((score, item))
        scored.sort(key=lambda pair: (-pair[0], pair[1]["name"].lower()))
        return scored[:limit]


def note_words(item):
    return set(words(f"{item['name']} {item['description']} {item['file'][:-3]} {item['text']}"))


def _slugs(item):
    return {gitlog.slug(item["name"]), gitlog.slug(item["file"][:-3])}


def cursors_linking(corpus, items):
    """Active cursor notes that link any of items, or are among them."""
    wanted = set().union(*(_slugs(item) for item in items)) if items else set()
    found = []
    for item in corpus.items:
        if item["type"] != "cursor":
            continue
        links = {gitlog.slug(link) for link in WIKILINK.findall(item["text"])}
        if (links | _slugs(item)) & wanted:
            found.append(item)
    return found


SAME_TOPIC = 3.5


def same_topic(home, rel, text, limit=3, minimum=SAME_TOPIC):
    """Existing notes whose content matches this note's name and description.

    The score is divided by the number of distinct query words, so a long description does not match
    everything. On a 203-note home, 3.5 put the known duplicate pairs in the top tenth.
    """
    fm, _ = frontmatter.split(text)
    query = f"{frontmatter.get(fm, 'name') or ''} {frontmatter.get(fm, 'description') or ''}"
    size = len(set(words(query)))
    if size < 2:
        return []
    own = rel.rsplit("/", 1)[-1]
    ranked = Corpus(home).rank(query, limit=limit + 1)
    return [f"memory/{item['file']}" for score, item in ranked if item["file"] != own and score / size >= minimum][:limit]
