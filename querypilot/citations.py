"""Citation extraction and verification against evidence retrieved during a run."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

CITATION = re.compile(r"\[([A-Z0-9][A-Z0-9-]*@v\d+#c\d+)\]")


def extract_citations(text: str) -> list[str]:
    return list(dict.fromkeys(CITATION.findall(text or "")))


@dataclass
class CitationCheck:
    ok: bool
    cited: list[str] = field(default_factory=list)
    invalid: list[str] = field(default_factory=list)
    problem: str | None = None


def check_citations(answer: str, evidence: dict[str, dict]) -> CitationCheck:
    """Every citation must reference a chunk retrieved in this run; if document
    evidence was retrieved, the answer must cite at least one chunk."""
    cited = extract_citations(answer)
    invalid = [c for c in cited if c not in evidence]
    if invalid:
        return CitationCheck(False, cited, invalid,
                             "Citations not backed by retrieved evidence: " + ", ".join(invalid))
    if evidence and not cited:
        return CitationCheck(False, cited, [],
                             "Document evidence was retrieved but the answer cites none of it.")
    return CitationCheck(True, cited)
