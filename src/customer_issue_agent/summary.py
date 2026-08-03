from __future__ import annotations

from collections import Counter
from typing import Any

IssueClusterKey = tuple[str, str, str]


def build_records_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    platforms: Counter[str] = Counter()
    issue_categories: Counter[str] = Counter()
    responsibilities: Counter[str] = Counter()
    evidence_strengths: Counter[str] = Counter()
    feedback_statuses: Counter[str] = Counter()
    issue_clusters: Counter[IssueClusterKey] = Counter()
    reviewed_records = 0
    corrected_records = 0

    for record in records:
        analysis = record.get("analysis") or {}
        request = analysis.get("request") or {}
        attribution = analysis.get("attribution") or {}
        platform = _value(request.get("platform"))
        issue_category = _value(attribution.get("issue_category"))
        responsibility = _value(attribution.get("primary_responsibility"))
        platforms[platform] += 1
        issue_categories[issue_category] += 1
        responsibilities[responsibility] += 1
        evidence_strengths[_value(attribution.get("evidence_strength"))] += 1
        issue_clusters[(platform, issue_category, responsibility)] += 1

        status = _feedback_status(record.get("feedback"))
        feedback_statuses[status] += 1
        if status != "unreviewed":
            reviewed_records += 1
        if status == "corrected":
            corrected_records += 1

    return {
        "total_records": len(records),
        "reviewed_records": reviewed_records,
        "corrected_records": corrected_records,
        "platforms": _rank(platforms),
        "issue_categories": _rank(issue_categories),
        "responsibilities": _rank(responsibilities),
        "evidence_strengths": _rank(evidence_strengths),
        "feedback_statuses": _rank(feedback_statuses),
        "top_issue_clusters": _rank_issue_clusters(issue_clusters),
    }


def _feedback_status(feedback: object) -> str:
    if not isinstance(feedback, dict):
        return "unreviewed"
    return "accepted" if feedback.get("accepted") else "corrected"


def _rank(counter: Counter[str]) -> list[dict[str, int | str]]:
    return [
        {"value": value, "count": count}
        for value, count in sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    ]


def _rank_issue_clusters(
    counter: Counter[IssueClusterKey], limit: int = 5
) -> list[dict[str, int | str]]:
    return [
        {
            "platform": platform,
            "issue_category": issue_category,
            "responsibility": responsibility,
            "count": count,
        }
        for (platform, issue_category, responsibility), count in sorted(
            counter.items(),
            key=lambda item: (
                -item[1],
                item[0][0].casefold(),
                item[0][0],
                item[0][1].casefold(),
                item[0][1],
                item[0][2].casefold(),
                item[0][2],
            ),
        )[:limit]
    ]


def _value(value: object) -> str:
    if value is None:
        return "unknown"
    stripped = str(value).strip()
    return stripped or "unknown"
