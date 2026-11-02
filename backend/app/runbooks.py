import re
from pathlib import Path

from app.schemas import RunbookEvidence

RUNBOOK_DIR = Path(__file__).resolve().parent / "runbooks"
RUNBOOK_FILES = (
    "database.md",
    "latency.md",
    "healthy.md",
)
SECTION_PATTERN = re.compile(r"^## \[([A-Z]+-\d+)\] (.+)$", re.MULTILINE)
TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "the",
    "this",
    "to",
    "with",
}
MINIMUM_SCORE = 2
MINIMUM_RELATIVE_SCORE = 0.5


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in TOKEN_PATTERN.findall(text.lower())
        if token not in STOP_WORDS and len(token) > 1
    }


def _load_sections() -> list[tuple[str, str, str, str]]:
    sections: list[tuple[str, str, str, str]] = []
    for filename in RUNBOOK_FILES:
        path = RUNBOOK_DIR / filename
        text = path.read_text(encoding="utf-8")
        matches = list(SECTION_PATTERN.finditer(text))
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            content = text[match.end() : end].strip()
            sections.append(
                (match.group(1), match.group(2).strip(), filename, content)
            )
    return sections


def retrieve_runbooks(query: str, limit: int = 3) -> list[RunbookEvidence]:
    if limit < 1:
        raise ValueError("limit must be at least one")

    query_terms = _tokens(query)
    if not query_terms:
        return []

    matches: list[tuple[int, RunbookEvidence]] = []
    for source_id, title, filename, content in _load_sections():
        title_terms = _tokens(title)
        content_terms = _tokens(content)
        matched_terms = sorted(query_terms & (title_terms | content_terms))
        score = sum(2 if term in title_terms else 1 for term in matched_terms)
        if score < MINIMUM_SCORE:
            continue
        matches.append(
            (
                score,
                RunbookEvidence(
                    source_id=source_id,
                    title=title,
                    source_file=filename,
                    content=content,
                    score=score,
                    matched_terms=matched_terms,
                ),
            )
        )

    matches.sort(key=lambda result: (-result[0], result[1].source_id))
    best_score = matches[0][0] if matches else 0
    return [
        evidence
        for score, evidence in matches
        if score >= best_score * MINIMUM_RELATIVE_SCORE
    ][:limit]
