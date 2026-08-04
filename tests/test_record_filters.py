from datetime import UTC, datetime

from customer_issue_agent.record_filters import filter_records


def _record(
    record_id: str,
    *,
    platform: str = "Amazon",
    store_name: str = "",
    sku: str = "",
    platform_product_id: str = "",
    issue_category: str = "function_use",
    responsibility: str = "customer_service_training",
    evidence_strength: str = "likely",
    report: str = "客户反馈无法连接，客服需要补问设备型号。",
    feedback: dict | None = None,
) -> dict:
    return {
        "id": record_id,
        "analysis": {
            "request": {
                "platform": platform,
                "store_name": store_name,
                "sku": sku,
                "platform_product_id": platform_product_id,
            },
            "attribution": {
                "customer_problem": report,
                "issue_category": issue_category,
                "primary_responsibility": responsibility,
                "evidence_strength": evidence_strength,
                "recommended_actions": ["补问设备型号"],
                "missing_information": ["错误提示截图"],
            },
            "report": report,
        },
        "feedback": feedback,
    }


def test_filter_records_returns_all_when_no_filters():
    records = [_record("one"), _record("two", platform="TikTok Shop")]

    assert filter_records(records) == records


def test_filter_records_matches_platform_keyword_case_insensitively():
    records = [_record("one", platform="Amazon"), _record("two", platform="TikTok Shop")]

    filtered = filter_records(records, platform="amazon")

    assert [record["id"] for record in filtered] == ["one"]


def test_filter_records_supports_exact_platform_match_without_changing_keyword_default():
    records = [
        _record("amazon", platform="Amazon"),
        _record("amazon-us", platform="Amazon US"),
    ]

    keyword_matches = filter_records(records, platform="amazon")
    exact_matches = filter_records(records, platform="amazon", platform_match="exact")

    assert [record["id"] for record in keyword_matches] == ["amazon", "amazon-us"]
    assert [record["id"] for record in exact_matches] == ["amazon"]


def test_filter_records_matches_enums_and_feedback_status():
    records = [
        _record("one", issue_category="function_use", responsibility="customer_service_training"),
        _record(
            "two",
            issue_category="product_fault",
            responsibility="product",
            feedback={"accepted": False, "note": "质量团队复核"},
        ),
        _record("three", issue_category="product_fault", responsibility="product", feedback={"accepted": True}),
    ]

    filtered = filter_records(
        records,
        issue_category="product_fault",
        responsibility="product",
        feedback_status="corrected",
    )

    assert [record["id"] for record in filtered] == ["two"]


def test_filter_records_searches_record_text_and_feedback_note():
    records = [
        _record("one", report="客户反馈安装失败"),
        _record("two", report="客户反馈缺少配件", feedback={"accepted": False, "note": "需要配件补发"}),
    ]

    assert [record["id"] for record in filter_records(records, q="安装")] == ["one"]
    assert [record["id"] for record in filter_records(records, q="补发")] == ["two"]


def test_filter_records_unknown_feedback_status_matches_nothing():
    records = [_record("one"), _record("two", feedback={"accepted": True})]

    assert filter_records(records, feedback_status="archived") == []


def test_filter_records_matches_recent_7_day_range():
    now = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
    records = [
        {**_record("recent"), "created_at": "2026-07-25T12:00:00+00:00"},
        {**_record("old"), "created_at": "2026-07-10T12:00:00+00:00"},
    ]

    filtered = filter_records(records, range="7d", now=now)

    assert [record["id"] for record in filtered] == ["recent"]


def test_filter_records_active_range_excludes_future_records():
    now = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
    records = [
        {**_record("recent"), "created_at": "2026-07-29T12:00:00+00:00"},
        {**_record("future"), "created_at": "2026-07-29T12:00:01+00:00"},
    ]

    filtered = filter_records(records, range="7d", now=now)

    assert [record["id"] for record in filtered] == ["recent"]


def test_filter_records_matches_recent_30_day_range():
    now = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
    records = [
        {**_record("recent"), "created_at": "2026-07-01T12:00:00+00:00"},
        {**_record("old"), "created_at": "2026-06-01T12:00:00+00:00"},
    ]

    filtered = filter_records(records, range="30d", now=now)

    assert [record["id"] for record in filtered] == ["recent"]


def test_filter_records_all_and_unknown_range_keep_existing_behavior():
    now = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
    records = [
        {**_record("missing-created-at")},
        {**_record("invalid-created-at"), "created_at": "not-a-date"},
    ]

    assert filter_records(records, range="all", now=now) == records
    assert filter_records(records, range="custom", now=now) == records


def test_filter_records_active_range_excludes_missing_or_invalid_created_at():
    now = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
    records = [
        {**_record("missing-created-at")},
        {**_record("invalid-created-at"), "created_at": "not-a-date"},
    ]

    assert filter_records(records, range="7d", now=now) == []


def test_product_filters_use_store_contains_and_exact_identifiers():
    records = [
        _record(
            "one",
            store_name="US Flagship",
            sku="SKU-1",
            platform_product_id="B001",
        ),
        _record(
            "two",
            store_name="EU Outlet",
            sku="SKU-10",
            platform_product_id="B0010",
        ),
        _record("legacy"),
    ]

    assert [item["id"] for item in filter_records(records, store_name="flag")] == ["one"]
    assert [item["id"] for item in filter_records(records, sku="sku-1")] == ["one"]
    assert [
        item["id"] for item in filter_records(records, platform_product_id="b001")
    ] == ["one"]
    assert filter_records(records, sku="SKU") == []


def test_product_metadata_is_in_keyword_search():
    record = _record(
        "one",
        store_name="US Flagship",
        sku="SKU-1",
        platform_product_id="B001",
    )

    assert filter_records([record], q="flagship") == [record]
    assert filter_records([record], q="sku-1") == [record]
    assert filter_records([record], q="b001") == [record]
