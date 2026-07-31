from datetime import UTC, datetime, timedelta

from customer_issue_agent.trends import build_issue_trends


NOW = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)


def _record(
    created_at: datetime | str | None,
    *,
    platform: object = "Amazon",
    issue_category: object = "function_use",
    responsibility: object = "customer_service_training",
) -> dict:
    value = created_at.isoformat() if isinstance(created_at, datetime) else created_at
    record = {
        "analysis": {
            "request": {"platform": platform},
            "attribution": {
                "issue_category": issue_category,
                "primary_responsibility": responsibility,
            },
        }
    }
    if value is not None:
        record["created_at"] = value
    return record


def test_build_issue_trends_uses_two_disjoint_seven_day_periods():
    records = [
        _record(NOW),
        _record(NOW - timedelta(days=7)),
        _record(NOW - timedelta(days=7, seconds=1)),
        _record(NOW - timedelta(days=14)),
        _record(NOW - timedelta(days=14, seconds=1)),
        _record(NOW + timedelta(seconds=1)),
        _record("not-a-date"),
        _record(None),
        _record("2026-07-30T12:00:00"),
    ]

    result = build_issue_trends(records, now=NOW)

    assert result["period"] == "7d"
    assert result["current_period"] == {
        "start": (NOW - timedelta(days=7)).isoformat(),
        "end": NOW.isoformat(),
        "total_records": 3,
    }
    assert result["previous_period"] == {
        "start": (NOW - timedelta(days=14)).isoformat(),
        "end": (NOW - timedelta(days=7)).isoformat(),
        "total_records": 2,
    }
    assert result["total_delta"] == 1


def test_build_issue_trends_returns_union_threshold_and_stable_order():
    records = []
    records.extend(
        _record(NOW - timedelta(days=1), platform="Amazon")
        for _ in range(3)
    )
    records.append(_record(NOW - timedelta(days=8), platform="Amazon"))
    records.extend(
        _record(
            NOW - timedelta(days=8),
            platform="TikTok Shop",
            issue_category="product_fault",
            responsibility="product",
        )
        for _ in range(3)
    )
    records.extend(
        _record(
            NOW - timedelta(days=1),
            platform="eBay",
            issue_category="installation",
            responsibility="operations",
        )
        for _ in range(2)
    )
    records.extend(
        _record(
            created_at,
            platform="Shopee",
            issue_category="accessory",
            responsibility="product",
        )
        for created_at in (NOW - timedelta(days=1), NOW - timedelta(days=8))
    )

    result = build_issue_trends(records, now=NOW)

    assert result["clusters"] == [
        {
            "platform": "TikTok Shop",
            "issue_category": "product_fault",
            "responsibility": "product",
            "current_count": 0,
            "previous_count": 3,
            "delta": -3,
            "significant_increase": False,
        },
        {
            "platform": "Amazon",
            "issue_category": "function_use",
            "responsibility": "customer_service_training",
            "current_count": 3,
            "previous_count": 1,
            "delta": 2,
            "significant_increase": True,
        },
        {
            "platform": "eBay",
            "issue_category": "installation",
            "responsibility": "operations",
            "current_count": 2,
            "previous_count": 0,
            "delta": 2,
            "significant_increase": False,
        },
    ]


def test_build_issue_trends_handles_empty_unknown_and_period_fallback():
    empty = build_issue_trends([], period="30d", now=NOW)

    assert empty == {
        "period": "7d",
        "current_period": {
            "start": (NOW - timedelta(days=7)).isoformat(),
            "end": NOW.isoformat(),
            "total_records": 0,
        },
        "previous_period": {
            "start": (NOW - timedelta(days=14)).isoformat(),
            "end": (NOW - timedelta(days=7)).isoformat(),
            "total_records": 0,
        },
        "total_delta": 0,
        "clusters": [],
    }

    unknown = build_issue_trends(
        [
            _record(
                NOW - timedelta(days=1),
                platform=" ",
                issue_category=None,
                responsibility=[],
            ),
            {
                "created_at": (NOW - timedelta(days=2)).isoformat(),
                "analysis": [],
            },
        ],
        now=NOW,
    )

    assert unknown["clusters"] == [
        {
            "platform": "unknown",
            "issue_category": "unknown",
            "responsibility": "unknown",
            "current_count": 2,
            "previous_count": 0,
            "delta": 2,
            "significant_increase": False,
        }
    ]
