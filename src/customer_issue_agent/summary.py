from __future__ import annotations

from collections import Counter
from typing import Any

IssueClusterKey = tuple[str, str, str]
SkuIssueClusterKey = tuple[str, str, str, str]


def build_records_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    platforms: Counter[str] = Counter()
    issue_categories: Counter[str] = Counter()
    responsibilities: Counter[str] = Counter()
    evidence_strengths: Counter[str] = Counter()
    feedback_statuses: Counter[str] = Counter()
    issue_clusters: Counter[IssueClusterKey] = Counter()
    sku_display: dict[str, str] = {}
    sku_counts: Counter[str] = Counter()
    sku_platforms: dict[str, dict[str, str]] = {}
    sku_issue_clusters: Counter[SkuIssueClusterKey] = Counter()
    sku_issue_display: dict[SkuIssueClusterKey, str] = {}
    sku_issue_platform_display: dict[SkuIssueClusterKey, str] = {}
    missing_sku = 0
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
        sku = _optional_value(request.get("sku"))
        if not sku:
            missing_sku += 1
        else:
            sku_key = sku.casefold()
            sku_display.setdefault(sku_key, sku)
            sku_counts[sku_key] += 1
            sku_platforms.setdefault(sku_key, {}).setdefault(
                platform.casefold(),
                platform,
            )
            cluster_key = (
                platform.casefold(),
                sku_key,
                issue_category,
                responsibility,
            )
            sku_issue_clusters[cluster_key] += 1
            sku_issue_display.setdefault(cluster_key, sku)
            sku_issue_platform_display.setdefault(cluster_key, platform)

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
        "product_coverage": {
            "with_sku": sum(sku_counts.values()),
            "missing_sku": missing_sku,
        },
        "top_skus": _rank_skus(sku_counts, sku_display, sku_platforms),
        "top_sku_issue_clusters": _rank_sku_issue_clusters(
            sku_issue_clusters,
            sku_issue_display,
            sku_issue_platform_display,
        ),
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


def _rank_skus(
    counts: Counter[str],
    display: dict[str, str],
    platforms: dict[str, dict[str, str]],
) -> list[dict[str, object]]:
    return [
        {
            "sku": display[key],
            "count": count,
            "platform_count": len(platforms[key]),
            "platforms": [
                value
                for _, value in sorted(
                    platforms[key].items(),
                    key=lambda item: (item[0], item[1]),
                )
            ],
        }
        for key, count in sorted(
            counts.items(),
            key=lambda item: (-item[1], item[0], display[item[0]]),
        )
    ]


def _rank_sku_issue_clusters(
    counter: Counter[SkuIssueClusterKey],
    sku_display: dict[SkuIssueClusterKey, str],
    platform_display: dict[SkuIssueClusterKey, str],
    limit: int = 5,
) -> list[dict[str, int | str]]:
    ranked = sorted(
        counter.items(),
        key=lambda item: (
            -item[1],
            item[0][0],
            item[0][1],
            item[0][2].casefold(),
            item[0][2],
            item[0][3].casefold(),
            item[0][3],
        ),
    )[:limit]
    return [
        {
            "platform": platform_display[key],
            "sku": sku_display[key],
            "issue_category": key[2],
            "responsibility": key[3],
            "count": count,
        }
        for key, count in ranked
    ]


def _optional_value(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()


def _value(value: object) -> str:
    if value is None:
        return "unknown"
    stripped = str(value).strip()
    return stripped or "unknown"
