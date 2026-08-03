import json
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from customer_issue_agent import __version__
from customer_issue_agent.app import create_app


def test_package_imports():
    assert __version__ == "0.1.0"


def test_analyze_text_endpoint_returns_report(tmp_path):
    app = create_app(storage_path=tmp_path / "analyses.jsonl")
    client = TestClient(app)

    response = client.post(
        "/api/analyze",
        data={
            "platform": "Other overseas platform",
            "conversation_text": (
                "Customer: I followed the instructions but it still will not connect.\n"
                "Agent: Please try again later."
            ),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["record_id"]
    assert "客户问题" in payload["analysis"]["report"]
    assert payload["analysis"]["request"]["platform"] == "Other overseas platform"


def test_analyze_rejects_empty_text(tmp_path):
    app = create_app(storage_path=tmp_path / "analyses.jsonl")
    client = TestClient(app)

    response = client.post("/api/analyze", data={"platform": "Other", "conversation_text": "   "})

    assert response.status_code == 422


def test_index_renders_workbench(tmp_path):
    app = create_app(storage_path=tmp_path / "analyses.jsonl")
    client = TestClient(app)

    response = client.get("/")

    assert response.status_code == 200
    assert "客户使用问题归因智能体" in response.text
    assert "conversation_text" in response.text


def test_analyze_text_response_exposes_fields_for_ui(tmp_path):
    app = create_app(storage_path=tmp_path / "analyses.jsonl")
    client = TestClient(app)

    response = client.post(
        "/api/analyze",
        data={
            "platform": "Other overseas platform",
            "conversation_text": (
                "Customer: I followed the instructions but it still will not connect.\n"
                "Agent: Please try again later."
            ),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    attribution = payload["analysis"]["attribution"]
    assert payload["record_id"]
    assert attribution["customer_problem"]
    assert attribution["issue_category"] == "function_use"
    assert attribution["primary_responsibility"] == "customer_service_training"
    assert attribution["evidence_strength"] == "likely"
    assert attribution["recommended_actions"]
    assert attribution["missing_information"]


def test_analyze_file_upload_returns_report(tmp_path):
    app = create_app(storage_path=tmp_path / "analyses.jsonl")
    client = TestClient(app)

    response = client.post(
        "/api/analyze-file",
        data={"platform": "Other overseas platform"},
        files={
            "file": (
                "conversation.txt",
                (
                    "Customer: I followed the instructions but it still will not connect.\n"
                    "Agent: Please try again later."
                ),
                "text/plain",
            )
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["record_id"]
    assert "客户问题" in payload["analysis"]["report"]
    assert payload["analysis"]["request"]["platform"] == "Other overseas platform"


def test_index_contains_tabs_forms_result_region_and_script(tmp_path):
    app = create_app(storage_path=tmp_path / "analyses.jsonl")
    client = TestClient(app)

    response = client.get("/")

    assert response.status_code == 200
    html = response.text
    assert 'data-tab-target="paste-panel"' in html
    assert 'data-tab-target="upload-panel"' in html
    assert 'id="paste-form"' in html
    assert 'id="upload-form"' in html
    assert 'id="analysis-result"' in html
    assert 'id="recent-records"' in html
    assert 'role="alert"' in html
    assert '<script src="/static/app.js" defer></script>' in html


def test_static_app_js_contains_progressive_enhancement_hooks(tmp_path):
    app = create_app(storage_path=tmp_path / "analyses.jsonl")
    client = TestClient(app)

    response = client.get("/static/app.js")

    assert response.status_code == 200
    script = response.text
    assert "bindTabs" in script
    assert "submitAnalysisForm" in script
    assert "renderAnalysisResult" in script
    assert "prependRecentRecord" in script
    assert "fetch(form.dataset.endpoint" in script


def test_styles_cover_enhanced_workbench_components(tmp_path):
    app = create_app(storage_path=tmp_path / "analyses.jsonl")
    client = TestClient(app)

    response = client.get("/static/styles.css")

    assert response.status_code == 200
    css = response.text
    assert ".workspace-grid" in css
    assert ".tabs" in css
    assert ".result-grid" in css
    assert ".result-card" in css
    assert ".form-message.is-visible" in css
    assert ".batch-summary" in css
    assert ".batch-summary-grid" in css
    assert ".batch-summary-card" in css
    assert "@media (max-width: 720px)" in css


def test_analyze_batch_file_returns_multiple_records(tmp_path):
    app = create_app(storage_path=tmp_path / "analyses.jsonl")
    client = TestClient(app)

    response = client.post(
        "/api/analyze-batch-file",
        data={"platform": "Other overseas platform"},
        files={
            "file": (
                "batch.txt",
                "Customer: It will not connect\n\n---\n\nCustomer: Missing cable",
                "text/plain",
            )
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["batch_id"]
    assert payload["count"] == 2
    assert len(payload["records"]) == 2
    assert payload["records"][0]["record_id"]
    assert payload["records"][1]["analysis"]["request"]["platform"] == "Other overseas platform"


def test_feedback_endpoint_updates_record_feedback(tmp_path):
    app = create_app(storage_path=tmp_path / "analyses.jsonl")
    client = TestClient(app)
    analysis_response = client.post(
        "/api/analyze",
        data={"platform": "Other", "conversation_text": "Customer: not working"},
    )
    record_id = analysis_response.json()["record_id"]

    response = client.post(
        f"/api/records/{record_id}/feedback",
        data={
            "accepted": "false",
            "corrected_issue_category": "product_fault",
            "corrected_responsibility": "supply_chain_quality",
            "note": "需要质量团队复核。",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["record_id"] == record_id
    assert payload["feedback"]["accepted"] is False
    assert payload["feedback"]["corrected_issue_category"] == "product_fault"
    assert payload["feedback"]["corrected_responsibility"] == "supply_chain_quality"
    assert payload["feedback"]["note"] == "需要质量团队复核。"


def test_feedback_endpoint_returns_404_for_missing_record(tmp_path):
    app = create_app(storage_path=tmp_path / "analyses.jsonl")
    client = TestClient(app)

    response = client.post("/api/records/missing/feedback", data={"accepted": "true"})

    assert response.status_code == 404


def test_index_contains_batch_upload_and_feedback_controls(tmp_path):
    app = create_app(storage_path=tmp_path / "analyses.jsonl")
    client = TestClient(app)

    response = client.get("/")

    assert response.status_code == 200
    html = response.text
    assert 'data-tab-target="batch-panel"' in html
    assert 'id="batch-form"' in html
    assert 'data-endpoint="/api/analyze-batch-file"' in html
    assert 'id="batch-results"' in html
    assert 'data-feedback-template' in html


def test_static_app_js_contains_batch_and_feedback_hooks(tmp_path):
    app = create_app(storage_path=tmp_path / "analyses.jsonl")
    client = TestClient(app)

    response = client.get("/static/app.js")

    assert response.status_code == 200
    script = response.text
    assert "submitBatchForm" in script
    assert "renderBatchResults" in script
    assert "bindFeedbackForms" in script
    assert "submitFeedbackForm" in script
    assert "buildBatchSummary" in script
    assert "batchSummaryHtml" in script
    assert "batchSummaryDistribution" in script
    assert "本批次摘要" in script
    assert "待复核" in script
    assert "feedbackUiState" in script
    assert "syncFeedbackUi" in script
    assert "updateRecordFeedbackView" in script
    assert "updateFeedbackPill" in script
    assert "updateBatchPendingCount" in script


def test_recent_records_expose_feedback_sync_dom_contract(tmp_path):
    storage_path = tmp_path / "analyses.jsonl"
    app = create_app(storage_path=storage_path)
    client = TestClient(app)
    analysis_response = client.post(
        "/api/analyze",
        data={"platform": "Amazon", "conversation_text": "Customer: not working"},
    )
    record_id = analysis_response.json()["record_id"]
    client.post(
        f"/api/records/{record_id}/feedback",
        data={"accepted": "false", "note": "旧备注"},
    )

    response = client.get("/")

    assert response.status_code == 200
    html = response.text
    assert "data-record-meta" in html
    assert "data-record-feedback-status" in html
    assert "data-record-feedback-note" in html
    assert "data-search-base-text=" in html
    assert f'data-record-id="{record_id}"' in html
    assert 'data-feedback-status="corrected"' in html


def test_dynamic_record_renderers_expose_feedback_sync_dom_contract(tmp_path):
    app = create_app(storage_path=tmp_path / "analyses.jsonl")
    client = TestClient(app)

    response = client.get("/static/app.js")

    assert response.status_code == 200
    script = response.text
    assert "result.dataset.recordId = payload.record_id" in script
    assert 'result.dataset.feedbackStatus = "unreviewed"' in script
    assert 'article.dataset.feedbackStatus = "unreviewed"' in script
    assert "article.dataset.searchBaseText = searchBaseText" in script
    assert "data-record-meta" in script
    assert "data-batch-pending-count" in script
    assert "data-record-feedback-status" in script
    assert "data-record-feedback-note" in script


def test_feedback_success_path_refreshes_local_views_and_summary(tmp_path):
    app = create_app(storage_path=tmp_path / "analyses.jsonl")
    client = TestClient(app)

    response = client.get("/static/app.js")

    assert response.status_code == 200
    script = response.text
    assert "syncFeedbackUi(payload.record_id, payload.feedback);" in script
    assert "refreshRecordFilterViews();" in script
    assert "loadRecordsSummary();" in script


def test_export_records_csv_endpoint_returns_bom_csv_with_feedback(tmp_path):
    app = create_app(storage_path=tmp_path / "analyses.jsonl")
    client = TestClient(app)
    analysis_response = client.post(
        "/api/analyze",
        data={"platform": "Amazon", "conversation_text": "Customer: not working"},
    )
    record_id = analysis_response.json()["record_id"]
    client.post(
        f"/api/records/{record_id}/feedback",
        data={
            "accepted": "false",
            "corrected_issue_category": "product_fault",
            "corrected_responsibility": "supply_chain_quality",
            "note": "需要质量团队复核。",
        },
    )

    response = client.get("/api/records/export.csv")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "customer-issue-records.csv" in response.headers["content-disposition"]
    assert response.content.startswith(b"\xef\xbb\xbf")
    text = response.content.decode("utf-8-sig")
    assert "记录 ID,创建时间,平台" in text
    assert "Amazon" in text
    assert "需要质量团队复核。" in text


def test_export_records_csv_endpoint_returns_header_when_empty(tmp_path):
    app = create_app(storage_path=tmp_path / "analyses.jsonl")
    client = TestClient(app)

    response = client.get("/api/records/export.csv")

    assert response.status_code == 200
    text = response.content.decode("utf-8-sig")
    assert text.startswith("记录 ID,创建时间,平台")


def test_index_contains_export_csv_link(tmp_path):
    app = create_app(storage_path=tmp_path / "analyses.jsonl")
    client = TestClient(app)

    response = client.get("/")

    assert response.status_code == 200
    assert 'href="/api/records/export.csv"' in response.text
    assert "导出 CSV" in response.text


def test_index_contains_recent_record_filter_controls(tmp_path):
    app = create_app(storage_path=tmp_path / "analyses.jsonl")
    client = TestClient(app)

    response = client.get("/")

    assert response.status_code == 200
    html = response.text
    assert 'id="record-filter"' in html
    assert 'id="record-search"' in html
    assert 'id="platform-filter"' in html
    assert 'name="platform"' in html
    assert 'id="platform-filter" name="platform" list="platform-presets"' in html
    assert 'id="issue-filter"' in html
    assert 'id="responsibility-filter"' in html
    assert 'id="feedback-filter"' in html
    assert "只看待复核" in html
    assert 'data-review-queue-toggle' in html
    assert 'class="secondary-action review-queue-toggle"' in html
    assert 'aria-pressed="false"' in html
    assert 'id="filter-count"' in html
    assert 'id="filter-empty"' in html
    assert 'data-filter-reset' in html
    assert 'id="export-filter-summary"' in html
    assert 'class="export-filter-summary"' in html
    assert 'aria-live="polite"' in html
    assert "将导出全部记录" in html
    assert 'id="export-count-preview"' in html
    assert 'class="export-count-preview"' in html
    assert "预计导出数量加载中..." in html


def test_recent_records_include_filter_data_attributes(tmp_path):
    app = create_app(storage_path=tmp_path / "analyses.jsonl")
    client = TestClient(app)
    response = client.post(
        "/api/analyze",
        data={"platform": "Amazon", "conversation_text": "Customer: not working"},
    )
    record_id = response.json()["record_id"]
    client.post(f"/api/records/{record_id}/feedback", data={"accepted": "true"})

    html = client.get("/").text

    assert 'data-record-id="' in html
    assert 'data-platform="Amazon"' in html
    assert 'data-issue-category="' in html
    assert 'data-responsibility="' in html
    assert 'data-feedback-status="accepted"' in html
    assert 'data-search-text="' in html


def test_static_app_js_contains_recent_record_filter_hooks(tmp_path):
    app = create_app(storage_path=tmp_path / "analyses.jsonl")
    client = TestClient(app)

    response = client.get("/static/app.js")

    assert response.status_code == 200
    script = response.text
    assert "bindRecordFilters" in script
    assert "applyRecordFilters" in script
    assert "resetRecordFilters" in script
    assert "recordMatchesFilters" in script
    assert "platform-filter" in script
    assert "matchesPlatform" in script
    assert "filters.platform" in script
    assert "updateExportFilterSummary" in script
    assert "export-filter-summary" in script
    assert "将导出全部记录" in script
    assert "筛选导出将应用" in script
    assert "updateExportFilterSummary();" in script
    assert 'labelFor("issue_category", issue)' in script
    assert "updateExportCountPreview();" in script
    assert "bindReviewQueueToggle" in script
    assert "toggleReviewQueueFilter" in script
    assert "updateReviewQueueToggle" in script
    assert "refreshRecordFilterViews" in script
    assert "data-review-queue-toggle" in script
    assert 'feedbackFilter.value = "unreviewed"' in script
    assert 'feedbackFilter.value = ""' in script
    assert 'aria-pressed' in script
    assert "is-active" in script
    assert "只看待复核" in script
    assert 'data-feedback-status="unreviewed"' in script


def test_styles_cover_recent_record_filter_components(tmp_path):
    app = create_app(storage_path=tmp_path / "analyses.jsonl")
    client = TestClient(app)

    response = client.get("/static/styles.css")

    assert response.status_code == 200
    css = response.text
    assert ".record-filter" in css
    assert ".filter-field" in css
    assert ".filter-count" in css
    assert ".filter-empty" in css
    assert ".export-filter-summary" in css
    assert ".export-count-preview" in css
    assert ".review-queue-toggle" in css
    assert ".review-queue-toggle.is-active" in css


def test_records_summary_endpoint_returns_counts(tmp_path):
    app = create_app(storage_path=tmp_path / "analyses.jsonl")
    client = TestClient(app)
    analysis_response = client.post(
        "/api/analyze",
        data={"platform": "Amazon", "conversation_text": "Customer: not working"},
    )
    record_id = analysis_response.json()["record_id"]
    client.post(f"/api/records/{record_id}/feedback", data={"accepted": "false"})

    response = client.get("/api/records/summary")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_records"] == 1
    assert payload["reviewed_records"] == 1
    assert payload["corrected_records"] == 1
    assert payload["platforms"] == [{"value": "Amazon", "count": 1}]
    assert payload["issue_categories"]
    assert payload["responsibilities"]
    assert payload["evidence_strengths"]
    assert payload["feedback_statuses"] == [{"value": "corrected", "count": 1}]
    assert payload["top_issue_clusters"]
    assert payload["top_issue_clusters"][0]["platform"] == "Amazon"
    assert payload["top_issue_clusters"][0]["count"] == 1


def test_records_summary_endpoint_returns_empty_summary(tmp_path):
    app = create_app(storage_path=tmp_path / "analyses.jsonl")
    client = TestClient(app)

    response = client.get("/api/records/summary")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_records"] == 0
    assert payload["reviewed_records"] == 0
    assert payload["corrected_records"] == 0
    assert payload["platforms"] == []
    assert payload["issue_categories"] == []
    assert payload["top_issue_clusters"] == []


def test_index_contains_summary_dashboard_region(tmp_path):
    app = create_app(storage_path=tmp_path / "analyses.jsonl")
    client = TestClient(app)

    response = client.get("/")

    assert response.status_code == 200
    html = response.text
    assert 'id="records-summary"' in html
    assert 'id="summary-content"' in html
    assert "运营概览" in html
    assert "概览加载中..." in html


def test_static_app_js_contains_summary_dashboard_hooks(tmp_path):
    app = create_app(storage_path=tmp_path / "analyses.jsonl")
    client = TestClient(app)

    response = client.get("/static/app.js")

    assert response.status_code == 200
    script = response.text
    assert "loadRecordsSummary" in script
    assert "renderRecordsSummary" in script
    assert "summaryMetric" in script
    assert "summaryDistribution" in script
    assert "平台分布" in script
    assert "summary.platforms" in script
    assert "summary.top_issue_clusters" in script
    assert "summaryIssueClusters" in script
    assert "高频问题" in script
    assert "bindSummaryPlatformFilters" in script
    assert "applySummaryPlatformFilter" in script
    assert "data-summary-platform-filter" in script
    assert "scrollIntoView" in script
    assert "summaryIssueClusterRow" in script
    assert "isSummaryIssueClusterFilterable" in script
    assert "selectHasOption" in script
    assert "data-summary-issue-cluster-filter" in script
    assert "data-summary-cluster-platform" in script
    assert "data-summary-cluster-issue-category" in script
    assert "data-summary-cluster-responsibility" in script
    assert "bindSummaryIssueClusterFilters" in script
    assert "applySummaryIssueClusterFilter" in script
    assert "scrollToRecentRecords" in script


def test_styles_cover_summary_dashboard_components(tmp_path):
    app = create_app(storage_path=tmp_path / "analyses.jsonl")
    client = TestClient(app)

    response = client.get("/static/styles.css")

    assert response.status_code == 200
    css = response.text
    assert ".summary-dashboard" in css
    assert ".summary-metrics" in css
    assert ".summary-card" in css
    assert ".distribution-list" in css
    assert ".summary-filter-link" in css
    assert ".issue-cluster-card" in css
    assert ".issue-cluster-label" in css
    assert ".issue-cluster-filter" in css
    assert ".issue-cluster-filter:hover" in css
    assert ".issue-cluster-filter:focus-visible" in css


def test_export_records_csv_endpoint_filters_by_query_params(tmp_path):
    app = create_app(storage_path=tmp_path / "analyses.jsonl")
    client = TestClient(app)
    amazon_response = client.post(
        "/api/analyze",
        data={"platform": "Amazon", "conversation_text": "Customer: not working"},
    )
    tiktok_response = client.post(
        "/api/analyze",
        data={"platform": "TikTok Shop", "conversation_text": "Customer: missing cable"},
    )
    client.post(
        f"/api/records/{amazon_response.json()['record_id']}/feedback",
        data={"accepted": "false", "note": "需要产品团队复核"},
    )
    client.post(
        f"/api/records/{tiktok_response.json()['record_id']}/feedback",
        data={"accepted": "true"},
    )

    response = client.get(
        "/api/records/export.csv",
        params={"platform": "amazon", "feedback_status": "corrected", "q": "产品团队"},
    )

    assert response.status_code == 200
    text = response.content.decode("utf-8-sig")
    assert "Amazon" in text
    assert "TikTok Shop" not in text
    assert "需要产品团队复核" in text


def test_export_records_csv_endpoint_filtered_empty_returns_header(tmp_path):
    app = create_app(storage_path=tmp_path / "analyses.jsonl")
    client = TestClient(app)
    client.post(
        "/api/analyze",
        data={"platform": "Amazon", "conversation_text": "Customer: not working"},
    )

    response = client.get("/api/records/export.csv", params={"feedback_status": "archived"})

    assert response.status_code == 200
    assert response.content.startswith(b"\xef\xbb\xbf")
    text = response.content.decode("utf-8-sig")
    lines = [line for line in text.splitlines() if line]
    assert len(lines) == 1


def test_index_contains_filtered_export_button(tmp_path):
    app = create_app(storage_path=tmp_path / "analyses.jsonl")
    client = TestClient(app)

    response = client.get("/")

    assert response.status_code == 200
    html = response.text
    assert "导出筛选 CSV" in html
    assert "data-filter-export" in html


def test_static_app_js_contains_filtered_export_hooks(tmp_path):
    app = create_app(storage_path=tmp_path / "analyses.jsonl")
    client = TestClient(app)

    response = client.get("/static/app.js")

    assert response.status_code == 200
    script = response.text
    assert "bindFilteredExport" in script
    assert "buildFilteredExportUrl" in script
    assert "data-filter-export" in script
    assert "feedback_status" in script
    assert "platform-filter" in script
    assert 'params.set("platform", platform)' in script
    assert "时间" in script
    assert "最近 7 天" in script
    assert "最近 30 天" in script
    assert "buildExportFilterParams" in script
    assert "buildExportCountPreviewUrl" in script
    assert "updateExportCountPreview" in script
    assert "/api/records/export-count" in script
    assert "export-count-preview" in script
    assert "预计导出" in script
    assert "预计数量暂不可用" in script
    assert "latestExportCountRequestId" in script


def _stored_record(record_id: str, *, platform: str, created_at: datetime, issue_category: str = "function_use") -> dict:
    return {
        "id": record_id,
        "created_at": created_at.isoformat(),
        "analysis": {
            "request": {"platform": platform, "conversation_text": "Customer: not working"},
            "attribution": {
                "customer_problem": f"{platform} 客户反馈无法使用",
                "issue_category": issue_category,
                "root_causes": ["unclear_instructions"],
                "primary_responsibility": "customer_service_training",
                "evidence_strength": "likely",
                "recommended_actions": ["补问设备型号"],
                "missing_information": ["错误提示截图"],
            },
            "report": f"{platform} 客户反馈无法使用",
        },
        "feedback": None,
    }


def _write_jsonl_records(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def test_records_summary_endpoint_filters_by_time_range(tmp_path):
    storage_path = tmp_path / "analyses.jsonl"
    now = datetime.now(UTC)
    _write_jsonl_records(
        storage_path,
        [
            _stored_record("recent", platform="Amazon", created_at=now - timedelta(days=2)),
            _stored_record("old", platform="TikTok Shop", created_at=now - timedelta(days=40)),
        ],
    )
    app = create_app(storage_path=storage_path)
    client = TestClient(app)

    response = client.get("/api/records/summary", params={"range": "7d"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_records"] == 1
    assert payload["platforms"] == [{"value": "Amazon", "count": 1}]
    assert payload["issue_categories"] == [{"value": "function_use", "count": 1}]


def test_export_records_csv_endpoint_filters_by_time_range_and_query(tmp_path):
    storage_path = tmp_path / "analyses.jsonl"
    now = datetime.now(UTC)
    _write_jsonl_records(
        storage_path,
        [
            _stored_record("recent-amazon", platform="Amazon", created_at=now - timedelta(days=2)),
            _stored_record("recent-tiktok", platform="TikTok Shop", created_at=now - timedelta(days=2)),
            _stored_record("old-amazon", platform="Amazon", created_at=now - timedelta(days=40)),
        ],
    )
    app = create_app(storage_path=storage_path)
    client = TestClient(app)

    response = client.get("/api/records/export.csv", params={"range": "30d", "platform": "amazon"})

    assert response.status_code == 200
    text = response.content.decode("utf-8-sig")
    assert "recent-amazon" in text
    assert "recent-tiktok" not in text
    assert "old-amazon" not in text


def test_export_records_count_endpoint_matches_filtered_export_scope(tmp_path):
    storage_path = tmp_path / "analyses.jsonl"
    now = datetime.now(UTC)
    _write_jsonl_records(
        storage_path,
        [
            _stored_record("recent-amazon", platform="Amazon", created_at=now - timedelta(days=2)),
            _stored_record("recent-tiktok", platform="TikTok Shop", created_at=now - timedelta(days=2)),
            _stored_record("old-amazon", platform="Amazon", created_at=now - timedelta(days=40)),
        ],
    )
    app = create_app(storage_path=storage_path)
    client = TestClient(app)

    response = client.get("/api/records/export-count", params={"range": "30d", "platform": "amazon"})

    assert response.status_code == 200
    assert response.json() == {"count": 1}


def test_export_records_count_endpoint_supports_exact_platform_match(tmp_path):
    storage_path = tmp_path / "analyses.jsonl"
    now = datetime.now(UTC)
    _write_jsonl_records(
        storage_path,
        [
            _stored_record("amazon", platform="Amazon", created_at=now),
            _stored_record("amazon-us", platform="Amazon US", created_at=now),
        ],
    )
    app = create_app(storage_path=storage_path)
    client = TestClient(app)

    response = client.get(
        "/api/records/export-count",
        params={"platform": "Amazon", "platform_match": "exact"},
    )

    assert response.status_code == 200
    assert response.json() == {"count": 1}


def test_export_records_csv_endpoint_supports_exact_platform_match(tmp_path):
    storage_path = tmp_path / "analyses.jsonl"
    now = datetime.now(UTC)
    _write_jsonl_records(
        storage_path,
        [
            _stored_record("amazon", platform="Amazon", created_at=now),
            _stored_record("amazon-us", platform="Amazon US", created_at=now),
        ],
    )
    app = create_app(storage_path=storage_path)
    client = TestClient(app)

    response = client.get(
        "/api/records/export.csv",
        params={"platform": "Amazon", "platform_match": "exact"},
    )

    assert response.status_code == 200
    text = response.content.decode("utf-8-sig")
    assert "amazon," in text
    assert "amazon-us" not in text


def test_export_records_count_endpoint_returns_zero_for_empty_filter_result(tmp_path):
    storage_path = tmp_path / "analyses.jsonl"
    _write_jsonl_records(
        storage_path,
        [
            _stored_record("amazon", platform="Amazon", created_at=datetime.now(UTC)),
        ],
    )
    app = create_app(storage_path=storage_path)
    client = TestClient(app)

    response = client.get("/api/records/export-count", params={"feedback_status": "archived"})

    assert response.status_code == 200
    assert response.json() == {"count": 0}


def test_index_contains_summary_range_selector(tmp_path):
    app = create_app(storage_path=tmp_path / "analyses.jsonl")
    client = TestClient(app)

    response = client.get("/")

    assert response.status_code == 200
    html = response.text
    assert 'id="summary-range"' in html
    assert 'value="7d"' in html
    assert 'value="30d"' in html
    assert "最近 7 天" in html


def test_static_app_js_contains_summary_range_hooks(tmp_path):
    app = create_app(storage_path=tmp_path / "analyses.jsonl")
    client = TestClient(app)

    response = client.get("/static/app.js")

    assert response.status_code == 200
    script = response.text
    assert "bindSummaryRange" in script
    assert "summary-range" in script
    assert 'params.set("range", range)' in script
    assert 'params.set("range", summaryRange)' in script
    assert "updateExportFilterSummary();" in script
    assert "updateExportCountPreview();" in script
    assert "refreshRecordFilterViews();" in script


def test_recent_records_include_expandable_detail_markup(tmp_path):
    app = create_app(storage_path=tmp_path / "analyses.jsonl")
    client = TestClient(app)
    response = client.post(
        "/api/analyze",
        data={"platform": "Amazon", "conversation_text": "Customer: not working"},
    )
    record_id = response.json()["record_id"]
    client.post(
        f"/api/records/{record_id}/feedback",
        data={"accepted": "false", "note": "需要复核安装步骤"},
    )

    html = client.get("/").text

    assert "查看详情" in html
    assert "data-record-detail-toggle" in html
    assert 'aria-expanded="false"' in html
    assert 'aria-controls="record-detail-' in html
    assert 'class="record-detail"' in html
    assert "复制详情" in html
    assert "data-record-copy" in html
    assert "data-record-copy-status" in html
    assert 'aria-live="polite"' in html
    assert "客户问题" in html
    assert "下一步建议" in html
    assert "人工备注" in html
    assert "需要复核安装步骤" in html


def test_static_app_js_contains_record_detail_hooks(tmp_path):
    app = create_app(storage_path=tmp_path / "analyses.jsonl")
    client = TestClient(app)

    response = client.get("/static/app.js")

    assert response.status_code == 200
    script = response.text
    assert "bindRecordDetails" in script
    assert "toggleRecordDetail" in script
    assert "recordDetailHtml" in script
    assert "data-record-detail-toggle" in script
    assert "data-record-copy" in script
    assert "data-record-copy-status" in script
    assert "aria-expanded" in script
    assert "收起详情" in script
    assert "bindRecordCopyActions" in script
    assert "copyRecordDetails" in script
    assert "buildRecordDetailCopyText" in script
    assert "navigator.clipboard.writeText" in script
    assert "已复制详情" in script
    assert "复制失败，请手动选择详情文本" in script
    assert "bindRecordCopyActions(article)" in script


def test_styles_cover_record_detail_components(tmp_path):
    app = create_app(storage_path=tmp_path / "analyses.jsonl")
    client = TestClient(app)

    response = client.get("/static/styles.css")

    assert response.status_code == 200
    css = response.text
    assert ".record-detail-toggle" in css
    assert ".record-detail" in css
    assert ".record-detail-grid" in css
    assert ".record-detail-grid dt" in css
    assert ".record-copy-action" in css
    assert ".record-copy-status" in css


def test_index_contains_platform_presets_for_all_platform_inputs(tmp_path):
    app = create_app(storage_path=tmp_path / "analyses.jsonl")
    client = TestClient(app)

    response = client.get("/")

    assert response.status_code == 200
    html = response.text
    assert 'id="platform-presets"' in html
    assert 'id="paste-platform" name="platform" list="platform-presets"' in html
    assert 'id="upload-platform" name="platform" list="platform-presets"' in html
    assert 'id="batch-platform" name="platform" list="platform-presets"' in html
    assert 'value="Amazon"' in html
    assert 'value="TikTok Shop"' in html
    assert 'value="Shopee"' in html
    assert 'value="Walmart Marketplace"' in html
    assert 'value="eBay"' in html
    assert 'value="Shopify"' in html
    assert 'value="AliExpress"' in html
    assert 'value="Lazada"' in html
    assert 'value="Temu"' in html
    assert 'value="Shein"' in html
    assert 'value="Other overseas platform"' in html


def test_records_trends_endpoint_compares_recent_periods(tmp_path):
    storage_path = tmp_path / "analyses.jsonl"
    now = datetime.now(UTC)
    _write_jsonl_records(
        storage_path,
        [
            _stored_record("current-1", platform="Amazon", created_at=now - timedelta(days=1)),
            _stored_record("current-2", platform="Amazon", created_at=now - timedelta(days=2)),
            _stored_record("previous", platform="Amazon", created_at=now - timedelta(days=8)),
        ],
    )
    app = create_app(storage_path=storage_path)
    client = TestClient(app)

    response = client.get("/api/records/trends", params={"period": "7d"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["period"] == "7d"
    assert payload["current_period"]["total_records"] == 2
    assert payload["previous_period"]["total_records"] == 1
    assert payload["total_delta"] == 1
    assert payload["clusters"][0]["platform"] == "Amazon"
    assert payload["clusters"][0]["delta"] == 1


def test_records_trends_endpoint_falls_back_to_seven_days(tmp_path):
    app = create_app(storage_path=tmp_path / "analyses.jsonl")
    client = TestClient(app)

    response = client.get("/api/records/trends", params={"period": "30d"})

    assert response.status_code == 200
    assert response.json()["period"] == "7d"


def test_index_contains_issue_trend_region(tmp_path):
    app = create_app(storage_path=tmp_path / "analyses.jsonl")
    client = TestClient(app)

    response = client.get("/")

    assert response.status_code == 200
    html = response.text
    assert 'id="issue-trends"' in html
    assert 'id="trend-content"' in html
    assert 'aria-label="近 7 天问题趋势"' in html
    assert "趋势加载中" in html


def test_styles_cover_issue_trend_components(tmp_path):
    app = create_app(storage_path=tmp_path / "analyses.jsonl")
    client = TestClient(app)

    response = client.get("/static/styles.css")

    assert response.status_code == 200
    css = response.text
    assert ".trend-dashboard" in css
    assert ".trend-metrics" in css
    assert ".trend-row" in css
    assert ".trend-change.is-up" in css
    assert ".trend-change.is-down" in css
    assert ".trend-alert" in css


def test_static_app_js_contains_issue_trend_hooks(tmp_path):
    app = create_app(storage_path=tmp_path / "analyses.jsonl")
    client = TestClient(app)

    response = client.get("/static/app.js")

    assert response.status_code == 200
    script = response.text
    assert "loadIssueTrends" in script
    assert "renderIssueTrends" in script
    assert "issueTrendRows" in script
    assert "issueTrendRow" in script
    assert "trendChangeLabel" in script
    assert "bindIssueTrendFilters" in script
    assert "applyIssueTrendFilter" in script
    assert "/api/records/trends?period=7d" in script
    assert "data-issue-trend-filter" in script
    assert "明显上升" in script


def test_task_api_creates_reuses_lists_and_completes_task(tmp_path):
    storage_path = tmp_path / "analyses.jsonl"
    task_path = tmp_path / "tasks.jsonl"
    _write_jsonl_records(
        storage_path,
        [_stored_record("record-1", platform="Amazon", created_at=datetime.now(UTC))],
    )
    client = TestClient(
        create_app(storage_path=storage_path, task_storage_path=task_path)
    )
    form = {
        "source": "summary",
        "source_range": "all",
        "platform": "Amazon",
        "issue_category": "function_use",
        "responsibility": "customer_service_training",
        "team": "customer_service_training",
        "priority": "medium",
        "due_date": "2030-01-01",
    }

    created = client.post("/api/tasks", data=form)
    duplicate = client.post(
        "/api/tasks", data={**form, "source": "trend", "source_range": "7d"}
    )
    listed = client.get(
        "/api/tasks", params={"status": "pending", "priority": "medium"}
    )
    task_id = created.json()["task"]["id"]
    skipped = client.patch(
        f"/api/tasks/{task_id}",
        json={"status": "completed", "result": "不能跳过处理中"},
    )
    started = client.patch(
        f"/api/tasks/{task_id}", json={"status": "in_progress"}
    )
    empty_result = client.patch(
        f"/api/tasks/{task_id}",
        json={"status": "completed", "result": "  "},
    )
    completed = client.patch(
        f"/api/tasks/{task_id}",
        json={"status": "completed", "result": "已更新帮助中心"},
    )

    assert created.status_code == 201
    assert created.json()["created"] is True
    assert duplicate.status_code == 200
    assert duplicate.json() == {"created": False, "task": created.json()["task"]}
    assert listed.status_code == 200
    assert listed.json()["counts"]["pending"] == 1
    assert listed.json()["tasks"][0]["record_ids"] == ["record-1"]
    assert skipped.status_code == 409
    assert started.status_code == 200
    assert started.json()["status"] == "in_progress"
    assert empty_result.status_code == 422
    assert completed.status_code == 200
    assert completed.json()["result"] == "已更新帮助中心"


def test_task_api_maps_validation_conflict_missing_and_storage_errors(tmp_path):
    storage_path = tmp_path / "analyses.jsonl"
    task_path = tmp_path / "tasks.jsonl"
    _write_jsonl_records(
        storage_path,
        [_stored_record("record-1", platform="Amazon", created_at=datetime.now(UTC))],
    )
    client = TestClient(
        create_app(storage_path=storage_path, task_storage_path=task_path)
    )

    invalid_create = client.post(
        "/api/tasks",
        data={
            "source": "summary",
            "source_range": "all",
            "platform": "unknown",
            "issue_category": "function_use",
            "responsibility": "customer_service_training",
        },
    )
    invalid_filter = client.get("/api/tasks", params={"status": "reopened"})
    invalid_priority = client.get("/api/tasks", params={"priority": "urgent"})
    missing = client.patch("/api/tasks/missing", json={"team": "product"})

    assert invalid_create.status_code == 422
    assert invalid_filter.status_code == 422
    assert invalid_priority.status_code == 422
    assert missing.status_code == 404

    task_path.write_text("{broken}\n", encoding="utf-8")
    damaged = client.get("/api/tasks")
    assert damaged.status_code == 500
    assert damaged.json()["detail"] == "任务数据读取失败"
    assert client.get("/api/records/summary").status_code == 200


def test_index_contains_task_region_and_accessible_filters(tmp_path):
    client = TestClient(create_app(storage_path=tmp_path / "analyses.jsonl"))

    html = client.get("/").text

    assert 'id="task-workflow"' in html
    assert 'id="task-content"' in html
    assert 'id="task-status-filter"' in html
    assert 'id="task-priority-filter"' in html
    assert 'id="task-create-form"' in html
    assert 'aria-label="问题簇处理任务"' in html
    assert html.index('id="task-workflow"') < html.index('id="recent-records"')


def test_styles_cover_task_cards_states_overdue_and_mobile(tmp_path):
    client = TestClient(create_app(storage_path=tmp_path / "analyses.jsonl"))

    css = client.get("/static/styles.css").text

    assert ".task-dashboard" in css
    assert ".task-card" in css
    assert ".task-status" in css
    assert ".task-overdue" in css
    assert ".task-card.is-highlighted" in css
    assert ".task-create-form" in css
    assert "@media (max-width: 720px)" in css


def test_static_app_js_contains_task_workflow_hooks(tmp_path):
    client = TestClient(create_app(storage_path=tmp_path / "analyses.jsonl"))

    script = client.get("/static/app.js").text

    assert "latestTaskRequestId" in script
    assert "loadTasks" in script
    assert "submitTaskCreate" in script
    assert "data-task-create" in script
