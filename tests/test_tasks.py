import json
from datetime import UTC, date, datetime, timedelta

import pytest

from customer_issue_agent.storage import AnalysisStore
from customer_issue_agent.task_storage import TaskStore
from customer_issue_agent.tasks import (
    TaskConflictError,
    TaskNotFoundError,
    TaskService,
    TaskValidationError,
)

NOW = datetime(2026, 8, 3, 8, 0, tzinfo=UTC)
TODAY = date(2026, 8, 3)


def _record(
    record_id: str,
    *,
    platform: str = "Amazon",
    issue_category: str = "function_use",
    responsibility: str = "customer_service_training",
    created_at: datetime | str | None = None,
) -> dict:
    timestamp = (
        created_at
        if isinstance(created_at, str)
        else (created_at or NOW).isoformat()
    )
    return {
        "id": record_id,
        "created_at": timestamp,
        "analysis": {
            "request": {
                "platform": platform,
                "conversation_text": "Customer: help",
            },
            "attribution": {
                "issue_category": issue_category,
                "primary_responsibility": responsibility,
            },
        },
        "feedback": None,
    }


def _service(tmp_path, records: list[dict]) -> tuple[TaskService, TaskStore]:
    analysis_path = tmp_path / "analyses.jsonl"
    analysis_path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )
    task_store = TaskStore(tmp_path / "tasks.jsonl")
    return TaskService(AnalysisStore(analysis_path), task_store), task_store


def _payload(**overrides) -> dict:
    return {
        "source": "summary",
        "source_range": "all",
        "platform": "Amazon",
        "issue_category": "function_use",
        "responsibility": "customer_service_training",
        **overrides,
    }


def _completed_task(service: TaskService, *, completed_at: datetime) -> dict:
    task = service.create_task(_payload(), now=NOW, today=TODAY)[0]
    service.update_task(task["id"], {"status": "in_progress"}, now=NOW)
    return service.update_task(
        task["id"],
        {"status": "completed", "result": "已更新帮助中心"},
        now=completed_at,
    )


@pytest.mark.parametrize(
    ("source_range", "expected_ids"),
    [
        ("7d", ["match", "case-match"]),
        ("30d", ["match", "case-match", "old"]),
        ("all", ["match", "case-match", "old", "very-old"]),
    ],
)
def test_summary_snapshot_uses_exact_cluster_and_range(
    tmp_path, source_range, expected_ids
):
    records = [
        _record("match", created_at=NOW - timedelta(days=2)),
        _record("case-match", platform="amazon", created_at=NOW - timedelta(days=6)),
        _record("old", created_at=NOW - timedelta(days=8)),
        _record("very-old", created_at=NOW - timedelta(days=31)),
        _record(
            "other-platform",
            platform="Amazon US",
            created_at=NOW - timedelta(days=1),
        ),
        _record(
            "other-issue",
            issue_category="installation",
            created_at=NOW - timedelta(days=1),
        ),
        _record("future", created_at=NOW + timedelta(days=1)),
        _record("invalid-time", created_at="not-a-time"),
    ]
    service, _ = _service(tmp_path, records)

    task, created = service.create_task(
        _payload(source_range=source_range), now=NOW, today=TODAY
    )

    assert created is True
    assert task["record_ids"] == expected_ids
    assert task["record_count"] == len(expected_ids)
    assert task["source_range"] == source_range


def test_trend_snapshot_is_fixed_to_seven_days_and_recomputes_increase(tmp_path):
    records = [
        _record("current-1", created_at=NOW - timedelta(days=1)),
        _record("current-2", created_at=NOW - timedelta(days=2)),
        _record("current-3", created_at=NOW - timedelta(days=3)),
        _record("previous", created_at=NOW - timedelta(days=8)),
    ]
    service, _ = _service(tmp_path, records)

    task, _ = service.create_task(
        _payload(source="trend", source_range="30d"),
        now=NOW,
        today=TODAY,
    )

    assert task["source_range"] == "7d"
    assert task["record_ids"] == ["current-1", "current-2", "current-3"]
    assert task["significant_increase"] is True
    assert task["priority"] == "high"
    assert task["due_date"] == "2026-08-06"


def test_trend_increase_merges_platform_case_variants(tmp_path):
    records = [
        _record("current-1", platform="Amazon", created_at=NOW - timedelta(days=1)),
        _record("current-2", platform="amazon", created_at=NOW - timedelta(days=2)),
        _record("current-3", platform="Amazon", created_at=NOW - timedelta(days=3)),
        _record("previous", platform="Amazon", created_at=NOW - timedelta(days=8)),
    ]
    service, _ = _service(tmp_path, records)

    task, _ = service.create_task(
        _payload(source="trend"),
        now=NOW,
        today=TODAY,
    )

    assert task["record_count"] == 3
    assert task["significant_increase"] is True
    assert task["priority"] == "high"


@pytest.mark.parametrize(
    ("priority", "expected_due_date"),
    [("high", "2026-08-06"), ("medium", "2026-08-10"), ("low", "2026-08-17")],
)
def test_custom_priority_team_and_due_date_defaults(
    tmp_path, priority, expected_due_date
):
    service, _ = _service(tmp_path, [_record("record-1")])

    task, _ = service.create_task(
        _payload(team="product", priority=priority),
        now=NOW,
        today=TODAY,
    )

    assert task["team"] == "product"
    assert task["priority"] == priority
    assert task["due_date"] == expected_due_date


def test_explicit_due_date_and_generated_title_are_preserved(tmp_path):
    service, _ = _service(tmp_path, [_record("record-1")])

    task, _ = service.create_task(
        _payload(due_date="2026-08-20"),
        now=NOW,
        today=TODAY,
    )

    assert task["title"] == "Amazon · 功能不会用或设置失败 · 客服培训"
    assert task["due_date"] == "2026-08-20"


def test_open_task_is_reused_without_appending_duplicate_event(tmp_path):
    service, task_store = _service(tmp_path, [_record("record-1")])
    first, first_created = service.create_task(_payload(), now=NOW, today=TODAY)
    second, second_created = service.create_task(
        _payload(source="trend", source_range="7d"),
        now=NOW + timedelta(hours=1),
        today=TODAY,
    )

    assert first_created is True
    assert second_created is False
    assert second["id"] == first["id"]
    assert len(task_store.list_tasks()) == 1


@pytest.mark.parametrize(
    "override",
    [
        {"team": "not-valid"},
        {"priority": "urgent"},
        {"due_date": "2026/08/10"},
    ],
)
def test_duplicate_task_request_still_validates_override_fields(tmp_path, override):
    service, task_store = _service(tmp_path, [_record("record-1")])
    service.create_task(_payload(), now=NOW, today=TODAY)

    with pytest.raises(TaskValidationError):
        service.create_task(_payload(**override), now=NOW, today=TODAY)

    assert len(task_store.list_tasks()) == 1


def test_task_moves_forward_requires_result_and_allows_new_round(tmp_path):
    service, _ = _service(tmp_path, [_record("record-1")])
    first, _ = service.create_task(_payload(), now=NOW, today=TODAY)

    started = service.update_task(
        first["id"], {"status": "in_progress"}, now=NOW + timedelta(hours=1)
    )
    with pytest.raises(TaskValidationError, match="处理结果"):
        service.update_task(
            started["id"], {"status": "completed", "result": "  "}, now=NOW
        )
    completed = service.update_task(
        started["id"],
        {"status": "completed", "result": "  已更新操作说明  "},
        now=NOW + timedelta(hours=2),
    )
    second, created = service.create_task(
        _payload(), now=NOW + timedelta(hours=3), today=TODAY
    )

    assert completed["result"] == "已更新操作说明"
    assert completed["completed_at"] == "2026-08-03T10:00:00+00:00"
    assert created is True
    assert second["id"] != first["id"]


def test_invalid_transitions_completed_edits_and_unknown_fields_are_rejected(tmp_path):
    service, _ = _service(tmp_path, [_record("record-1")])
    task, _ = service.create_task(_payload(), now=NOW, today=TODAY)

    with pytest.raises(TaskConflictError, match="状态"):
        service.update_task(
            task["id"],
            {"status": "completed", "result": "跳过处理中"},
            now=NOW,
        )
    with pytest.raises(TaskValidationError, match="未知字段"):
        service.update_task(task["id"], {"title": "不能改标题"}, now=NOW)
    with pytest.raises(TaskValidationError, match="不能为空"):
        service.update_task(task["id"], {}, now=NOW)
    with pytest.raises(TaskValidationError, match="状态"):
        service.update_task(task["id"], {"status": None}, now=NOW)

    service.update_task(task["id"], {"status": "in_progress"}, now=NOW)
    with pytest.raises(TaskConflictError, match="状态"):
        service.update_task(task["id"], {"status": "pending"}, now=NOW)
    with pytest.raises(TaskValidationError, match="只有完成任务"):
        service.update_task(task["id"], {"result": "提前填写"}, now=NOW)
    service.update_task(
        task["id"], {"status": "completed", "result": "已处理"}, now=NOW
    )
    with pytest.raises(TaskConflictError, match="已完成"):
        service.update_task(task["id"], {"team": "product"}, now=NOW)


def test_metadata_update_changes_only_explicit_fields(tmp_path):
    service, _ = _service(tmp_path, [_record("record-1")])
    task, _ = service.create_task(
        _payload(due_date="2026-08-20"), now=NOW, today=TODAY
    )

    updated = service.update_task(
        task["id"],
        {"team": "product", "priority": "high"},
        now=NOW + timedelta(hours=1),
    )

    assert updated["team"] == "product"
    assert updated["priority"] == "high"
    assert updated["due_date"] == "2026-08-20"


@pytest.mark.parametrize(
    "payload",
    [
        _payload(platform="unknown"),
        _payload(issue_category="not-valid"),
        _payload(responsibility="not-valid"),
        _payload(source="automatic"),
        _payload(source_range="90d"),
        _payload(team="not-valid"),
        _payload(priority="urgent"),
        _payload(due_date="2026/08/10"),
    ],
)
def test_invalid_cluster_or_source_is_rejected(tmp_path, payload):
    service, _ = _service(tmp_path, [_record("record-1")])

    with pytest.raises(TaskValidationError):
        service.create_task(payload, now=NOW, today=TODAY)


def test_empty_snapshot_and_missing_task_are_rejected(tmp_path):
    service, _ = _service(tmp_path, [_record("other", platform="TikTok Shop")])

    with pytest.raises(TaskValidationError, match="没有匹配记录"):
        service.create_task(_payload(), now=NOW, today=TODAY)
    with pytest.raises(TaskNotFoundError):
        service.update_task("missing", {"team": "product"}, now=NOW)


def test_list_counts_filters_and_orders_overdue_high_priority_first(tmp_path):
    service, store = _service(tmp_path, [_record("record-1")])
    base = service.create_task(_payload(), now=NOW, today=TODAY)[0]
    store.append_updated(
        base["id"], NOW.isoformat(), {"priority": "low", "due_date": "2026-08-10"}
    )
    second = {
        **base,
        "id": "task-overdue",
        "priority": "high",
        "due_date": "2026-08-02",
    }
    store.append_created(second)
    third = {
        **base,
        "id": "task-completed",
        "status": "completed",
        "completed_at": NOW.isoformat(),
    }
    store.append_created(third)

    payload = service.list_tasks(today=TODAY)

    assert payload["counts"] == {"pending": 2, "in_progress": 0, "completed": 1}
    assert [task["id"] for task in payload["tasks"]] == [
        "task-overdue",
        base["id"],
        "task-completed",
    ]
    assert (
        service.list_tasks(
            status="completed", priority="medium", today=TODAY
        )["tasks"][0]["id"]
        == "task-completed"
    )
    with pytest.raises(TaskValidationError):
        service.list_tasks(status="reopened", today=TODAY)


def test_task_list_exposes_effect_review_readiness_and_counts(tmp_path):
    service, _ = _service(tmp_path, [_record("record-1")])
    completed = _completed_task(service, completed_at=NOW + timedelta(days=1))

    accumulating = service.list_tasks(now=NOW + timedelta(days=7))
    ready = service.list_tasks(now=NOW + timedelta(days=8))

    assert accumulating["tasks"][0]["effect_review_state"] == "accumulating"
    assert accumulating["tasks"][0]["effect_review_ready_at"] == (
        "2026-08-11T08:00:00+00:00"
    )
    assert accumulating["effect_review_counts"] == {
        "accumulating": 1,
        "ready": 0,
        "reviewed": 0,
    }
    assert ready["tasks"][0]["effect_review_state"] == "ready"
    assert ready["effect_review_counts"]["ready"] == 1
    assert service.list_tasks(
        effect_review_state="ready", now=NOW + timedelta(days=8)
    )["tasks"][0]["id"] == completed["id"]


def test_unfinished_tasks_are_not_applicable_for_effect_review(tmp_path):
    service, _ = _service(tmp_path, [_record("record-1")])
    service.create_task(_payload(), now=NOW, today=TODAY)

    payload = service.list_tasks(now=NOW + timedelta(days=30))

    assert payload["tasks"][0]["effect_review_state"] == "not_applicable"
    assert payload["tasks"][0]["effect_review_ready_at"] is None
    assert payload["effect_review_counts"] == {
        "accumulating": 0,
        "ready": 0,
        "reviewed": 0,
    }


def test_invalid_effect_review_filter_is_rejected(tmp_path):
    service, _ = _service(tmp_path, [_record("record-1")])

    with pytest.raises(TaskValidationError, match="复盘状态"):
        service.list_tasks(effect_review_state="late", now=NOW)
