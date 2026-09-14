"""What the write gate refuses to store in memory.

The first fourteen secret patterns come from agentmemory
(https://github.com/rohitg00/agentmemory, src/functions/privacy.ts, Apache-2.0).
The rest cover shapes found in real agent memory: inline database passwords,
credentials inside connection strings, RPC URLs carrying keys, and private keys.

Functions return a label or the matched phrase, never a secret value.
"""
import re

SECRET_PATTERNS = [
    ("key or token assignment", re.compile(r"(?:api[_-]?key|secret|token|password|credential|auth)\s*[=:]\s*[\"']?[A-Za-z0-9_\-/.+]{20,}[\"']?", re.I)),
    ("bearer token", re.compile(r"Bearer\s+[A-Za-z0-9._\-+/=]{20,}", re.I)),
    ("OpenAI project key", re.compile(r"sk-proj-[A-Za-z0-9\-_]{20,}")),
    ("provider key", re.compile(r"(?:sk|pk|rk|ak)-[A-Za-z0-9][A-Za-z0-9\-_]{19,}")),
    ("Anthropic key", re.compile(r"sk-ant-[A-Za-z0-9\-_]{20,}")),
    ("GitHub token", re.compile(r"gh[pus]_[A-Za-z0-9]{36,}")),
    ("GitHub fine-grained token", re.compile(r"github_pat_[A-Za-z0-9_]{22,}")),
    ("Slack bot token", re.compile(r"xoxb-[A-Za-z0-9\-]+")),
    ("AWS access key id", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("Google API key", re.compile(r"AIza[A-Za-z0-9\-_]{35}")),
    ("JWT", re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    ("npm token", re.compile(r"npm_[A-Za-z0-9]{36}")),
    ("GitLab token", re.compile(r"glpat-[A-Za-z0-9\-_]{20,}")),
    ("DigitalOcean token", re.compile(r"dop_v1_[A-Za-z0-9]{64}")),
    ("inline password", re.compile(r"\b(?:PG|POSTGRES_|MYSQL_|DB_)?PASSWORD\s*=\s*[\"']?[^\s\"'`$<{][^\s\"'`]{5,}", re.I)),
    ("credentials in a connection string", re.compile(r"\b[a-z][a-z0-9+.\-]*://[^\s:/@]+:(?![$<{])[^\s@/]{3,}@", re.I)),
    ("RPC URL with a key", re.compile(r"(?:quiknode\.pro|alchemy\.com/v2|infura\.io/v3|helius-rpc\.com/?\?api-key=)/?[A-Za-z0-9_\-]{20,}", re.I)),
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
]

INJECTED_TAG = re.compile(r"</?(system-reminder|task-notification|local-command-stdout|command-name)\b", re.I)
INJECTED_BLOCK = re.compile(r"<(system-reminder|task-notification|local-command-stdout|command-name)\b[^>]*>.*?</\1>", re.I | re.S)

RELATIVE_DATE = re.compile(
    r"\b(today|yesterday|tomorrow|tonight|this (?:morning|afternoon|evening|week|month|year)"
    r"|last (?:night|week|month|year)|next (?:week|month|year)|\d+ (?:days?|weeks?|months?) ago)\b",
    re.I,
)


def find_secret(text):
    for label, pattern in SECRET_PATTERNS:
        if pattern.search(text or ""):
            return label
    return None


def find_injected_tag(text):
    match = INJECTED_TAG.search(text or "")
    return match.group(1).lower() if match else None


def find_relative_date(text):
    match = RELATIVE_DATE.search(text or "")
    return match.group(0) if match else None


def redact(text):
    """Remove injected system blocks and replace secret values with [REDACTED]."""
    text = INJECTED_BLOCK.sub("", text or "")
    for _, pattern in SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text
