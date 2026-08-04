from customer_issue_agent.summary import build_records_summary


def _record(
    *,
    platform: object = "Amazon",
    sku: object = "",
    issue_category: object = "function_use",
    responsibility: object = "customer_service_training",
    evidence: object = "likely",
    feedback: dict | None = None,
) -> dict:
    return {
        "analysis": {
            "request": {"platform": platform, "sku": sku},
            "attribution": {
                "issue_category": issue_category,
                "primary_responsibility": responsibility,
                "evidence_strength": evidence,
            },
        },
        "feedback": feedback,
    }


def test_build_records_summary_counts_totals_and_dimensions():
    records = [
        _record(
            platform="Amazon",
            issue_category="function_use",
            responsibility="customer_service_training",
            feedback={"accepted": True},
        ),
        _record(
            platform="TikTok Shop",
            issue_category="function_use",
            responsibility="product",
            evidence="clear",
            feedback={"accepted": False},
        ),
        _record(
            platform="Amazon",
            issue_category="product_fault",
            responsibility="product",
            feedback=None,
        ),
    ]

    summary = build_records_summary(records)

    assert summary["total_records"] == 3
    assert summary["reviewed_records"] == 2
    assert summary["corrected_records"] == 1
    assert summary["platforms"] == [
        {"value": "Amazon", "count": 2},
        {"value": "TikTok Shop", "count": 1},
    ]
    assert summary["issue_categories"] == [
        {"value": "function_use", "count": 2},
        {"value": "product_fault", "count": 1},
    ]
    assert summary["responsibilities"] == [
        {"value": "product", "count": 2},
        {"value": "customer_service_training", "count": 1},
    ]
    assert summary["evidence_strengths"] == [
        {"value": "likely", "count": 2},
        {"value": "clear", "count": 1},
    ]
    assert summary["feedback_statuses"] == [
        {"value": "accepted", "count": 1},
        {"value": "corrected", "count": 1},
        {"value": "unreviewed", "count": 1},
    ]


def test_build_records_summary_returns_top_issue_clusters():
    records = [
        _record(platform="Amazon", issue_category="function_use", responsibility="customer_service_training"),
        _record(platform="Amazon", issue_category="function_use", responsibility="customer_service_training"),
        _record(platform="TikTok Shop", issue_category="product_fault", responsibility="product"),
        _record(platform="TikTok Shop", issue_category="product_fault", responsibility="product"),
        _record(platform="Amazon", issue_category="installation", responsibility="customer"),
        _record(platform="eBay", issue_category="logistics", responsibility="platform_policy"),
        _record(platform="Walmart Marketplace", issue_category="quality_expectation", responsibility="product"),
        _record(platform="Shopee", issue_category="function_use", responsibility="customer_service_training"),
        _record(platform="Temu", issue_category="installation", responsibility="customer"),
    ]

    summary = build_records_summary(records)

    assert summary["top_issue_clusters"] == [
        {
            "platform": "Amazon",
            "issue_category": "function_use",
            "responsibility": "customer_service_training",
            "count": 2,
        },
        {
            "platform": "TikTok Shop",
            "issue_category": "product_fault",
            "responsibility": "product",
            "count": 2,
        },
        {
            "platform": "Amazon",
            "issue_category": "installation",
            "responsibility": "customer",
            "count": 1,
        },
        {
            "platform": "eBay",
            "issue_category": "logistics",
            "responsibility": "platform_policy",
            "count": 1,
        },
        {
            "platform": "Shopee",
            "issue_category": "function_use",
            "responsibility": "customer_service_training",
            "count": 1,
        },
    ]


def test_build_records_summary_handles_empty_and_unknown_values():
    assert build_records_summary([]) == {
        "total_records": 0,
        "reviewed_records": 0,
        "corrected_records": 0,
        "platforms": [],
        "issue_categories": [],
        "responsibilities": [],
        "evidence_strengths": [],
        "feedback_statuses": [],
        "top_issue_clusters": [],
        "product_coverage": {"with_sku": 0, "missing_sku": 0},
        "top_skus": [],
        "top_sku_issue_clusters": [],
    }

    summary = build_records_summary(
        [
            {"analysis": {"request": {}, "attribution": {}}, "feedback": None},
            {"analysis": {"request": {"platform": "   "}, "attribution": {}}, "feedback": None},
        ]
    )

    assert summary["platforms"] == [{"value": "unknown", "count": 2}]
    assert summary["issue_categories"] == [{"value": "unknown", "count": 2}]
    assert summary["responsibilities"] == [{"value": "unknown", "count": 2}]
    assert summary["evidence_strengths"] == [{"value": "unknown", "count": 2}]
    assert summary["feedback_statuses"] == [{"value": "unreviewed", "count": 2}]
    assert summary["top_issue_clusters"] == [
        {
            "platform": "unknown",
            "issue_category": "unknown",
            "responsibility": "unknown",
            "count": 2,
        }
    ]
    assert summary["product_coverage"] == {"with_sku": 0, "missing_sku": 2}
    assert summary["top_skus"] == []
    assert summary["top_sku_issue_clusters"] == []


def test_summary_reports_sku_coverage_and_cross_platform_top_skus():
    records = [
        _record(platform="Amazon", sku="SKU-01"),
        _record(platform="TikTok Shop", sku="sku-01"),
        _record(platform="Amazon", sku="SKU-02"),
        _record(platform="Amazon"),
    ]

    summary = build_records_summary(records)

    assert summary["product_coverage"] == {"with_sku": 3, "missing_sku": 1}
    assert summary["top_skus"][0] == {
        "sku": "SKU-01",
        "count": 2,
        "platform_count": 2,
        "platforms": ["Amazon", "TikTok Shop"],
    }
    assert summary["top_skus"][1]["sku"] == "SKU-02"


def test_summary_ranks_sku_issue_clusters_by_platform_and_sku():
    records = [
        _record(
            platform="Amazon",
            sku="SKU-01",
            issue_category="function_use",
            responsibility="customer_service_training",
        )
        for _ in range(3)
    ]
    records.extend(
        [
            _record(
                platform="TikTok Shop",
                sku="sku-01",
                issue_category="product_fault",
                responsibility="supply_chain_quality",
            ),
            _record(platform="Amazon"),
        ]
    )

    clusters = build_records_summary(records)["top_sku_issue_clusters"]

    assert clusters[0] == {
        "platform": "Amazon",
        "sku": "SKU-01",
        "issue_category": "function_use",
        "responsibility": "customer_service_training",
        "count": 3,
    }
    assert all(item["sku"] != "unknown" for item in clusters)
