from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

IssueClusterKey = tuple[str, str, str]
PERIOD_DAYS = 7


def build_issue_trends(
    records: list[dict[str, Any]],
    *,
    period: str = "7d",
    now: datetime | None = None,
) -> dict[str, Any]:
    del period
    current_end = _as_utc(now or datetime.now(UTC))
    current_start = current_end - timedelta(days=PERIOD_DAYS)
    previous_start = current_start - timedelta(days=PERIOD_DAYS)
    current_clusters: Counter[IssueClusterKey] = Counter()
    previous_clusters: Counter[IssueClusterKey] = Counter()
    current_total = 0
    previous_total = 0

    for record in records:
        created_at = _parse_created_at(record.get("created_at"))
        if created_at is None or created_at < previous_start or created_at > current_end:
            continue
        key = _issue_cluster_key(record)
        if created_at >= current_start:
            current_clusters[key] += 1
            current_total += 1
        else:
            previous_clusters[key] += 1
            previous_total += 1

    clusters = []
    for platform, issue_category, responsibility in current_clusters.keys() | previous_clusters.keys():
        key = (platform, issue_category, responsibility)
        current_count = current_clusters[key]
        previous_count = previous_clusters[key]
        delta = current_count - previous_count
        if delta == 0:
            continue
        clusters.append(
            {
                "platform": platform,
                "issue_category": issue_category,
                "responsibility": responsibility,
                "current_count": current_count,
                "previous_count": previous_count,
                "delta": delta,
                "significant_increase": current_count >= 3 and delta >= 2,
            }
        )

    clusters.sort(key=_cluster_sort_key)
    return {
        "period": "7d",
        "current_period": {
            "start": current_start.isoformat(),
            "end": current_end.isoformat(),
            "total_records": current_total,
        },
        "previous_period": {
            "start": previous_start.isoformat(),
            "end": current_start.isoformat(),
            "total_records": previous_total,
        },
        "total_delta": current_total - previous_total,
        "clusters": clusters,
    }


def _issue_cluster_key(record: dict[str, Any]) -> IssueClusterKey:
    analysis = _mapping(record.get("analysis"))
    request = _mapping(analysis.get("request"))
    attribution = _mapping(analysis.get("attribution"))
    return (
        _value(request.get("platform")),
        _value(attribution.get("issue_category")),
        _value(attribution.get("primary_responsibility")),
    )


def _cluster_sort_key(item: dict[str, Any]) -> tuple[Any, ...]:
    return (
        -abs(item["delta"]),
        -item["current_count"],
        item["platform"].casefold(),
        item["platform"],
        item["issue_category"].casefold(),
        item["issue_category"],
        item["responsibility"].casefold(),
        item["responsibility"],
    )


def _parse_created_at(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return _as_utc(parsed)
    except (OverflowError, TypeError, ValueError):
        return None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _value(value: object) -> str:
    if not isinstance(value, str):
        return "unknown"
    stripped = value.strip()
    return stripped or "unknown"
