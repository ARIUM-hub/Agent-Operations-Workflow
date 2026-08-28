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
    current_sku_clusters: Counter[tuple[str, str, str, str]] = Counter()
    previous_sku_clusters: Counter[tuple[str, str, str, str]] = Counter()
    sku_display: dict[tuple[str, str, str, str], str] = {}
    current_total = 0
    previous_total = 0

    for record in records:
        created_at = _parse_created_at(record.get("created_at"))
        if created_at is None or created_at < previous_start or created_at > current_end:
            continue
        key = _issue_cluster_key(record)
        sku_key = _sku_cluster_key(record)
        if sku_key is not None:
            analysis = _mapping(record.get("analysis"))
            request = _mapping(analysis.get("request"))
            sku_display.setdefault(sku_key, _optional_value(request.get("sku")))
        if created_at >= current_start:
            current_clusters[key] += 1
            current_total += 1
            if sku_key is not None:
                current_sku_clusters[sku_key] += 1
        else:
            previous_clusters[key] += 1
            previous_total += 1
            if sku_key is not None:
                previous_sku_clusters[sku_key] += 1

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
        "sku_clusters": _build_sku_clusters(
            current_sku_clusters,
            previous_sku_clusters,
            sku_display,
        ),
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


def _sku_cluster_key(
    record: dict[str, Any],
) -> tuple[str, str, str, str] | None:
    analysis = _mapping(record.get("analysis"))
    request = _mapping(analysis.get("request"))
    attribution = _mapping(analysis.get("attribution"))
    sku = _optional_value(request.get("sku"))
    if not sku:
        return None
    return (
        _value(request.get("platform")),
        sku.casefold(),
        _value(attribution.get("issue_category")),
        _value(attribution.get("primary_responsibility")),
    )


def _build_sku_clusters(
    current: Counter[tuple[str, str, str, str]],
    previous: Counter[tuple[str, str, str, str]],
    display: dict[tuple[str, str, str, str], str],
) -> list[dict[str, Any]]:
    result = []
    for key in current.keys() | previous.keys():
        platform, _, issue_category, responsibility = key
        current_count = current[key]
        previous_count = previous[key]
        delta = current_count - previous_count
        if delta == 0:
            continue
        result.append(
            {
                "platform": platform,
                "sku": display[key],
                "issue_category": issue_category,
                "responsibility": responsibility,
                "current_count": current_count,
                "previous_count": previous_count,
                "delta": delta,
                "significant_increase": current_count >= 3 and delta >= 2,
            }
        )
    result.sort(key=_sku_cluster_sort_key)
    return result


def _sku_cluster_sort_key(item: dict[str, Any]) -> tuple[Any, ...]:
    return (
        -abs(item["delta"]),
        -item["current_count"],
        item["platform"].casefold(),
        item["platform"],
        item["sku"].casefold(),
        item["sku"],
        item["issue_category"].casefold(),
        item["issue_category"],
        item["responsibility"].casefold(),
        item["responsibility"],
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


def _optional_value(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()
