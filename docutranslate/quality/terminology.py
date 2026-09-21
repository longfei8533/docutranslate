"""Deterministic glossary adherence checks over aligned source/target segments."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Sequence


_WHITESPACE = re.compile(r"\s+")
_ASCII_WORD_EDGE = re.compile(r"[A-Za-z0-9_]")


def _normalize(value: str) -> str:
    return _WHITESPACE.sub(" ", unicodedata.normalize("NFKC", value).casefold()).strip()


def _count(text: str, term: str) -> int:
    normalized_text = _normalize(text)
    normalized_term = _normalize(term)
    if not normalized_term:
        return 0
    escaped = re.escape(normalized_term).replace(r"\ ", r"\s+")
    prefix = r"(?<!\w)" if _ASCII_WORD_EDGE.fullmatch(normalized_term[0]) else ""
    suffix = r"(?!\w)" if _ASCII_WORD_EDGE.fullmatch(normalized_term[-1]) else ""
    return len(re.findall(prefix + escaped + suffix, normalized_text))


@dataclass(frozen=True, slots=True)
class TerminologyFinding:
    source_term: str
    expected_target: str
    segment_ids: tuple[str, ...]
    source_occurrences: int
    target_occurrences: int
    status: str

    def as_dict(self) -> dict:
        return {
            "source_term": self.source_term,
            "expected_target": self.expected_target,
            "segment_ids": list(self.segment_ids),
            "source_occurrences": self.source_occurrences,
            "target_occurrences": self.target_occurrences,
            "status": self.status,
        }


@dataclass(frozen=True, slots=True)
class TerminologyReport:
    applicable_terms: int
    matched_terms: int
    partial_terms: int
    missing_terms: int
    source_occurrences: int
    matched_occurrences: int
    findings: tuple[TerminologyFinding, ...] = field(default_factory=tuple)
    repair_attempted: bool = False
    repaired_terms: int = 0

    @property
    def coverage_percent(self) -> float | None:
        if self.source_occurrences == 0:
            return None
        return round(self.matched_occurrences * 100 / self.source_occurrences, 1)

    @property
    def unresolved_segment_ids(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(
            segment_id
            for finding in self.findings
            if finding.status != "matched"
            for segment_id in finding.segment_ids
        ))

    def with_repair_result(self, repaired: "TerminologyReport") -> "TerminologyReport":
        initial_unresolved = self.partial_terms + self.missing_terms
        final_unresolved = repaired.partial_terms + repaired.missing_terms
        return TerminologyReport(
            applicable_terms=repaired.applicable_terms,
            matched_terms=repaired.matched_terms,
            partial_terms=repaired.partial_terms,
            missing_terms=repaired.missing_terms,
            source_occurrences=repaired.source_occurrences,
            matched_occurrences=repaired.matched_occurrences,
            findings=repaired.findings,
            repair_attempted=True,
            repaired_terms=max(0, initial_unresolved - final_unresolved),
        )

    def as_dict(self) -> dict:
        status = "not_applicable" if self.applicable_terms == 0 else (
            "passed" if self.partial_terms == 0 and self.missing_terms == 0 else "warning"
        )
        unresolved = [finding for finding in self.findings if finding.status != "matched"]
        return {
            "status": status,
            "applicable_terms": self.applicable_terms,
            "matched_terms": self.matched_terms,
            "partial_terms": self.partial_terms,
            "missing_terms": self.missing_terms,
            "source_occurrences": self.source_occurrences,
            "matched_occurrences": self.matched_occurrences,
            "coverage_percent": self.coverage_percent,
            "repair_attempted": self.repair_attempted,
            "repaired_terms": self.repaired_terms,
            "findings": [finding.as_dict() for finding in unresolved[:100]],
            "findings_truncated": max(0, len(unresolved) - 100),
        }


def check_terminology(
    pairs: Sequence[tuple[str, str, str]] | Iterable[tuple[str, str, str]],
    glossary: Mapping[str, str] | None,
) -> TerminologyReport:
    """Check required target terms only inside their aligned translated segments."""
    materialized = list(pairs)
    findings: list[TerminologyFinding] = []
    matched_occurrences = 0
    source_occurrences = 0
    matched_terms = 0
    partial_terms = 0
    missing_terms = 0

    for source_term, expected_target in (glossary or {}).items():
        affected: list[str] = []
        source_count = 0
        target_count = 0
        for segment_id, source, target in materialized:
            occurrences = _count(source, source_term)
            if occurrences == 0:
                continue
            affected.append(str(segment_id))
            source_count += occurrences
            target_count += min(occurrences, _count(target, expected_target))
        if source_count == 0:
            continue
        source_occurrences += source_count
        matched_occurrences += target_count
        if target_count >= source_count:
            status = "matched"
            matched_terms += 1
        elif target_count:
            status = "partial"
            partial_terms += 1
        else:
            status = "missing"
            missing_terms += 1
        findings.append(TerminologyFinding(
            source_term=source_term,
            expected_target=expected_target,
            segment_ids=tuple(affected),
            source_occurrences=source_count,
            target_occurrences=target_count,
            status=status,
        ))

    return TerminologyReport(
        applicable_terms=len(findings),
        matched_terms=matched_terms,
        partial_terms=partial_terms,
        missing_terms=missing_terms,
        source_occurrences=source_occurrences,
        matched_occurrences=matched_occurrences,
        findings=tuple(findings),
    )
