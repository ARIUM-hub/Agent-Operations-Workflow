import json

import pytest

from customer_issue_agent.task_storage import TaskStorageError, TaskStore


def _task(task_id: str = "task-one") -> dict:
    return {
        "id": task_id,
        "title": "Amazon · 功能不会用或设置失败 · 客服培训",
        "created_at": "2026-08-03T08:00:00+00:00",
        "updated_at": "2026-08-03T08:00:00+00:00",
        "source": "summary",
        "source_range": "all",
        "platform": "Amazon",
        "issue_category": "function_use",
        "responsibility": "customer_service_training",
        "record_ids": ["record-1"],
        "record_count": 1,
        "significant_increase": False,
        "team": "customer_service_training",
        "priority": "medium",
        "due_date": "2026-08-10",
        "status": "pending",
        "result": None,
        "completed_at": None,
    }


def test_missing_task_file_returns_empty_list(tmp_path):
    assert TaskStore(tmp_path / "tasks.jsonl").list_tasks() == []


def test_created_and_updated_events_rebuild_latest_state(tmp_path):
    store = TaskStore(tmp_path / "tasks.jsonl")
    store.append_created(_task())
    store.append_updated(
        "task-one",
        "2026-08-04T08:00:00+00:00",
        {"status": "in_progress", "team": "product"},
    )

    assert store.list_tasks() == [
        {
            **_task(),
            "updated_at": "2026-08-04T08:00:00+00:00",
            "status": "in_progress",
            "team": "product",
        }
    ]


def test_multiple_tasks_and_completed_rounds_remain_independent(tmp_path):
    store = TaskStore(tmp_path / "tasks.jsonl")
    store.append_created(_task("round-one"))
    store.append_updated(
        "round-one",
        "2026-08-05T08:00:00+00:00",
        {
            "status": "completed",
            "result": "已更新帮助中心",
            "completed_at": "2026-08-05T08:00:00+00:00",
        },
    )
    store.append_created(_task("round-two"))

    tasks = store.list_tasks()

    assert [task["id"] for task in tasks] == ["round-one", "round-two"]
    assert tasks[0]["result"] == "已更新帮助中心"
    assert tasks[1]["status"] == "pending"


def test_utf8_result_is_written_without_ascii_escaping(tmp_path):
    path = tmp_path / "tasks.jsonl"
    store = TaskStore(path)
    store.append_created(_task())
    store.append_updated(
        "task-one",
        "2026-08-05T08:00:00+00:00",
        {"status": "completed", "result": "已补充中文操作说明"},
    )

    raw = path.read_text(encoding="utf-8")

    assert "已补充中文操作说明" in raw
    assert "\\u" not in raw
    assert raw.endswith("\n")


@pytest.mark.parametrize(
    "event",
    [
        {"type": "unknown"},
        {"type": "task_created", "task": {"title": "缺少 ID"}},
        {
            "type": "task_updated",
            "task_id": "missing",
            "updated_at": "2026-08-03T08:00:00+00:00",
            "changes": {},
        },
    ],
)
def test_invalid_events_raise_explicit_storage_error(tmp_path, event):
    path = tmp_path / "tasks.jsonl"
    path.write_text(json.dumps(event, ensure_ascii=False) + "\n", encoding="utf-8")

    with pytest.raises(TaskStorageError, match="任务事件"):
        TaskStore(path).list_tasks()


def test_invalid_json_reports_line_number(tmp_path):
    path = tmp_path / "tasks.jsonl"
    path.write_text("{broken}\n", encoding="utf-8")

    with pytest.raises(TaskStorageError, match="第 1 行"):
        TaskStore(path).list_tasks()
