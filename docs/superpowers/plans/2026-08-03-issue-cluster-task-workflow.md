# Issue Cluster Task Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (recommended) or superpowers:subagent-driven-development when explicitly needed for independent tasks. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在客户使用问题归因工作台中增加按“平台 + 问题类型 + 责任方”创建、处理和完成本地任务的闭环，并保留创建时的分析记录快照。

**Architecture:** 使用独立 `tasks.jsonl` 追加事件流保存任务，`TaskStore` 只重建状态，`TaskService` 负责快照、默认值、去重、排序和单向状态机。FastAPI 仅映射请求与错误，原生 JavaScript 负责创建表单、任务卡片、筛选、更新和记录下钻；任务区域的失败与现有分析、复核、概览、趋势和导出隔离。

**Tech Stack:** Python 3.12、FastAPI、Pydantic 枚举、UTF-8 JSONL、Jinja2、原生 JavaScript、CSS、pytest、Node `node:test`/`vm`

---

## File Map

- Create: `src/customer_issue_agent/task_storage.py`：追加任务事件并按文件顺序重建最新任务。
- Create: `src/customer_issue_agent/tasks.py`：校验问题簇、生成快照和默认值、去重、排序、更新状态。
- Modify: `src/customer_issue_agent/app.py`：注入任务文件并提供三个任务 API。
- Modify: `src/customer_issue_agent/templates/index.html`：在趋势与最近记录之间加入任务区域和创建表单。
- Modify: `src/customer_issue_agent/static/app.js`：创建入口、任务加载、筛选、编辑、完成和记录下钻。
- Modify: `src/customer_issue_agent/static/styles.css`：任务卡片、表单、状态、逾期、高亮和移动端布局。
- Create: `tests/test_task_storage.py`：任务事件流单元测试。
- Create: `tests/test_tasks.py`：任务领域服务单元测试。
- Modify: `tests/test_app.py`：API、模板和静态资源契约测试。
- Create: `tests/js/test_task_workflow.mjs`：真实 `app.js` 的任务交互行为测试。
- Modify: `README.md`：任务闭环使用说明与本地存储边界。

### Task 1: Task Event Storage

**Files:**
- Create: `tests/test_task_storage.py`
- Create: `src/customer_issue_agent/task_storage.py`

- [ ] **Step 1: Write failing storage tests**

Create `tests/test_task_storage.py` with the complete test module below:

```python
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
        {"status": "completed", "result": "已更新帮助中心", "completed_at": "2026-08-05T08:00:00+00:00"},
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
        {"type": "task_updated", "task_id": "missing", "updated_at": "2026-08-03T08:00:00+00:00", "changes": {}},
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
```

- [ ] **Step 2: Run the tests and verify the import fails**

Run:

```powershell
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
python -m pytest tests/test_task_storage.py -q
```

Expected: FAIL during collection with `ModuleNotFoundError: No module named 'customer_issue_agent.task_storage'`.

- [ ] **Step 3: Implement the UTF-8 append-only store**

Create `src/customer_issue_agent/task_storage.py`:

```python
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path


class TaskStorageError(ValueError):
    pass


class TaskStore:
    def __init__(self, path: Path):
        self.path = path

    def append_created(self, task: dict) -> None:
        self._append({"type": "task_created", "task": deepcopy(task)})

    def append_updated(self, task_id: str, updated_at: str, changes: dict) -> None:
        self._append(
            {
                "type": "task_updated",
                "task_id": task_id,
                "updated_at": updated_at,
                "changes": deepcopy(changes),
            }
        )

    def list_tasks(self) -> list[dict]:
        if not self.path.exists():
            return []
        tasks: dict[str, dict] = {}
        order: list[str] = []
        with self.path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    event = json.loads(stripped)
                except json.JSONDecodeError as exc:
                    raise TaskStorageError(f"任务事件第 {line_number} 行不是合法 JSON") from exc
                self._apply_event(tasks, order, event, line_number)
        return [deepcopy(tasks[task_id]) for task_id in order]

    def _append(self, event: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")

    @staticmethod
    def _apply_event(tasks: dict[str, dict], order: list[str], event: object, line_number: int) -> None:
        if not isinstance(event, dict):
            raise TaskStorageError(f"任务事件第 {line_number} 行必须是对象")
        event_type = event.get("type")
        if event_type == "task_created":
            task = event.get("task")
            task_id = task.get("id") if isinstance(task, dict) else None
            if not isinstance(task_id, str) or not task_id.strip():
                raise TaskStorageError(f"任务事件第 {line_number} 行缺少任务 ID")
            if task_id in tasks:
                raise TaskStorageError(f"任务事件第 {line_number} 行重复创建任务 {task_id}")
            tasks[task_id] = deepcopy(task)
            order.append(task_id)
            return
        if event_type == "task_updated":
            task_id = event.get("task_id")
            changes = event.get("changes")
            updated_at = event.get("updated_at")
            if not isinstance(task_id, str) or not task_id.strip():
                raise TaskStorageError(f"任务事件第 {line_number} 行缺少任务 ID")
            if task_id not in tasks:
                raise TaskStorageError(f"任务事件第 {line_number} 行引用不存在任务 {task_id}")
            if not isinstance(changes, dict) or not isinstance(updated_at, str) or not updated_at:
                raise TaskStorageError(f"任务事件第 {line_number} 行更新内容不完整")
            tasks[task_id].update(deepcopy(changes))
            tasks[task_id]["updated_at"] = updated_at
            return
        raise TaskStorageError(f"任务事件第 {line_number} 行类型未知")
```

- [ ] **Step 4: Run the storage tests and verify they pass**

Run: `python -m pytest tests/test_task_storage.py -q`

Expected: `8 passed`.

- [ ] **Step 5: Commit the storage slice**

```powershell
git add src/customer_issue_agent/task_storage.py tests/test_task_storage.py
git commit -m "feat: add task event storage"
```

### Task 2: Task Service, Snapshot, Defaults, Dedupe, and State Machine

**Files:**
- Create: `tests/test_tasks.py`
- Create: `src/customer_issue_agent/tasks.py`

- [ ] **Step 1: Write failing service tests**

Create `tests/test_tasks.py`. The helpers and tests below are the complete module; they deliberately use fixed UTC datetimes so range boundaries and suggested dates are deterministic:

```python
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
    timestamp = created_at if isinstance(created_at, str) else (created_at or NOW).isoformat()
    return {
        "id": record_id,
        "created_at": timestamp,
        "analysis": {
            "request": {"platform": platform, "conversation_text": "Customer: help"},
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


@pytest.mark.parametrize(
    ("source_range", "expected_ids"),
    [
        ("7d", ["match", "case-match"]),
        ("30d", ["match", "case-match", "old"]),
        ("all", ["match", "case-match", "old", "very-old"]),
    ],
)
def test_summary_snapshot_uses_exact_cluster_and_range(tmp_path, source_range, expected_ids):
    records = [
        _record("match", created_at=NOW - timedelta(days=2)),
        _record("case-match", platform="amazon", created_at=NOW - timedelta(days=6)),
        _record("old", created_at=NOW - timedelta(days=8)),
        _record("very-old", created_at=NOW - timedelta(days=31)),
        _record("other-platform", platform="Amazon US", created_at=NOW - timedelta(days=1)),
        _record("other-issue", issue_category="installation", created_at=NOW - timedelta(days=1)),
        _record("future", created_at=NOW + timedelta(days=1)),
        _record("invalid-time", created_at="not-a-time"),
    ]
    service, _ = _service(tmp_path, records)

    task, created = service.create_task(_payload(source_range=source_range), now=NOW, today=TODAY)

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


@pytest.mark.parametrize(
    ("priority", "expected_due_date"),
    [("high", "2026-08-06"), ("medium", "2026-08-10"), ("low", "2026-08-17")],
)
def test_custom_priority_team_and_due_date_defaults(tmp_path, priority, expected_due_date):
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
    # API 将第二个返回值映射为 {"created": false, "task": existing_task}。


def test_task_moves_forward_requires_result_and_allows_new_round(tmp_path):
    service, _ = _service(tmp_path, [_record("record-1")])
    first, _ = service.create_task(_payload(), now=NOW, today=TODAY)

    started = service.update_task(first["id"], {"status": "in_progress"}, now=NOW + timedelta(hours=1))
    with pytest.raises(TaskValidationError, match="处理结果"):
        service.update_task(started["id"], {"status": "completed", "result": "  "}, now=NOW)
    completed = service.update_task(
        started["id"],
        {"status": "completed", "result": "  已更新操作说明  "},
        now=NOW + timedelta(hours=2),
    )
    second, created = service.create_task(_payload(), now=NOW + timedelta(hours=3), today=TODAY)

    assert completed["result"] == "已更新操作说明"
    assert completed["completed_at"] == "2026-08-03T10:00:00+00:00"
    assert created is True
    assert second["id"] != first["id"]


def test_invalid_transitions_completed_edits_and_unknown_fields_are_rejected(tmp_path):
    service, _ = _service(tmp_path, [_record("record-1")])
    task, _ = service.create_task(_payload(), now=NOW, today=TODAY)

    with pytest.raises(TaskConflictError, match="状态"):
        service.update_task(task["id"], {"status": "completed", "result": "跳过处理中"}, now=NOW)
    with pytest.raises(TaskValidationError, match="未知字段"):
        service.update_task(task["id"], {"title": "不能改标题"}, now=NOW)
    with pytest.raises(TaskValidationError, match="不能为空"):
        service.update_task(task["id"], {}, now=NOW)

    service.update_task(task["id"], {"status": "in_progress"}, now=NOW)
    with pytest.raises(TaskConflictError, match="状态"):
        service.update_task(task["id"], {"status": "pending"}, now=NOW)
    with pytest.raises(TaskValidationError, match="只有完成任务"):
        service.update_task(task["id"], {"result": "提前填写"}, now=NOW)
    service.update_task(task["id"], {"status": "completed", "result": "已处理"}, now=NOW)
    with pytest.raises(TaskConflictError, match="已完成"):
        service.update_task(task["id"], {"team": "product"}, now=NOW)


def test_metadata_update_changes_only_explicit_fields(tmp_path):
    service, _ = _service(tmp_path, [_record("record-1")])
    task, _ = service.create_task(_payload(due_date="2026-08-20"), now=NOW, today=TODAY)

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
    store.append_updated(base["id"], NOW.isoformat(), {"priority": "low", "due_date": "2026-08-10"})
    second = {**base, "id": "task-overdue", "priority": "high", "due_date": "2026-08-02"}
    store.append_created(second)
    third = {**base, "id": "task-completed", "status": "completed", "completed_at": NOW.isoformat()}
    store.append_created(third)

    payload = service.list_tasks(today=TODAY)

    assert payload["counts"] == {"pending": 2, "in_progress": 0, "completed": 1}
    assert [task["id"] for task in payload["tasks"]] == ["task-overdue", base["id"], "task-completed"]
    assert service.list_tasks(status="completed", priority="medium", today=TODAY)["tasks"][0]["id"] == "task-completed"
    with pytest.raises(TaskValidationError):
        service.list_tasks(status="reopened", today=TODAY)
```

- [ ] **Step 2: Run the service tests and verify the module is missing**

Run: `python -m pytest tests/test_tasks.py -q`

Expected: FAIL during collection with `ModuleNotFoundError: No module named 'customer_issue_agent.tasks'`.

- [ ] **Step 3: Implement the task service**

Create `src/customer_issue_agent/tasks.py`:

```python
from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

from customer_issue_agent.domain import IssueCategory, Responsibility
from customer_issue_agent.storage import AnalysisStore
from customer_issue_agent.task_storage import TaskStore
from customer_issue_agent.trends import build_issue_trends

SOURCES = {"summary", "trend"}
SOURCE_RANGES = {"all", "7d", "30d"}
PRIORITIES = {"low", "medium", "high"}
STATUSES = {"pending", "in_progress", "completed"}
OPEN_STATUSES = {"pending", "in_progress"}
UPDATE_FIELDS = {"team", "priority", "due_date", "status", "result"}
PRIORITY_DAYS = {"high": 3, "medium": 7, "low": 14}
PRIORITY_RANK = {"high": 3, "medium": 2, "low": 1}


class TaskValidationError(ValueError):
    pass


class TaskConflictError(ValueError):
    pass


class TaskNotFoundError(KeyError):
    pass


class TaskService:
    def __init__(self, analysis_store: AnalysisStore, task_store: TaskStore):
        self.analysis_store = analysis_store
        self.task_store = task_store

    def create_task(
        self,
        payload: Mapping[str, object],
        *,
        now: datetime | None = None,
        today: date | None = None,
    ) -> tuple[dict, bool]:
        current = _as_utc(now or datetime.now(UTC))
        local_today = today or current.astimezone().date()
        source = _enum_value(payload.get("source"), SOURCES, "来源")
        platform = _required_text(payload.get("platform"), "平台")
        if platform.casefold() == "unknown":
            raise TaskValidationError("unknown 平台不能创建任务")
        issue_category = _issue_category(payload.get("issue_category"))
        responsibility = _responsibility(payload.get("responsibility"), "责任方")
        source_range = "7d" if source == "trend" else _enum_value(
            payload.get("source_range"), SOURCE_RANGES, "统计范围"
        )

        tasks = self.task_store.list_tasks()
        key = _cluster_key(platform, issue_category, responsibility)
        for task in tasks:
            if task.get("status") in OPEN_STATUSES and _task_key(task) == key:
                return task, False

        records = self.analysis_store.list_records()
        record_ids = _matching_record_ids(
            records,
            platform=platform,
            issue_category=issue_category,
            responsibility=responsibility,
            source_range=source_range,
            now=current,
        )
        if not record_ids:
            raise TaskValidationError("当前范围没有匹配记录，无法创建任务")

        significant_increase = source == "trend" and _significant_increase(
            records, platform, issue_category, responsibility, current
        )
        team = _optional_enum(payload.get("team"), Responsibility, "责任团队") or responsibility
        suggested_priority = "high" if significant_increase else "medium"
        priority = _optional_choice(payload.get("priority"), PRIORITIES, "优先级") or suggested_priority
        due_date = _optional_due_date(payload.get("due_date")) or (
            local_today + timedelta(days=PRIORITY_DAYS[priority])
        ).isoformat()
        timestamp = current.isoformat()
        task = {
            "id": f"task-{uuid4()}",
            "title": f"{platform} · {IssueCategory(issue_category).label} · {Responsibility(responsibility).label}",
            "created_at": timestamp,
            "updated_at": timestamp,
            "source": source,
            "source_range": source_range,
            "platform": platform,
            "issue_category": issue_category,
            "responsibility": responsibility,
            "record_ids": record_ids,
            "record_count": len(record_ids),
            "significant_increase": significant_increase,
            "team": team,
            "priority": priority,
            "due_date": due_date,
            "status": "pending",
            "result": None,
            "completed_at": None,
        }
        self.task_store.append_created(task)
        return task, True

    def list_tasks(
        self,
        *,
        status: str = "",
        priority: str = "",
        today: date | None = None,
    ) -> dict:
        status_filter = _optional_choice(status, STATUSES, "状态")
        priority_filter = _optional_choice(priority, PRIORITIES, "优先级")
        tasks = self.task_store.list_tasks()
        counts = {value: sum(task.get("status") == value for task in tasks) for value in STATUSES}
        filtered = [
            task
            for task in tasks
            if (not status_filter or task.get("status") == status_filter)
            and (not priority_filter or task.get("priority") == priority_filter)
        ]
        local_today = today or datetime.now().astimezone().date()
        filtered.sort(key=lambda task: _task_sort_key(task, local_today))
        return {
            "counts": {
                "pending": counts["pending"],
                "in_progress": counts["in_progress"],
                "completed": counts["completed"],
            },
            "tasks": filtered,
        }

    def update_task(self, task_id: str, payload: Mapping[str, object], *, now: datetime | None = None) -> dict:
        current = _as_utc(now or datetime.now(UTC))
        tasks = self.task_store.list_tasks()
        task = next((item for item in tasks if item.get("id") == task_id), None)
        if task is None:
            raise TaskNotFoundError(task_id)
        if task.get("status") == "completed":
            raise TaskConflictError("已完成任务不可编辑或重新打开")
        unknown_fields = set(payload) - UPDATE_FIELDS
        if unknown_fields:
            raise TaskValidationError(f"包含未知字段：{', '.join(sorted(unknown_fields))}")
        if not payload:
            raise TaskValidationError("更新内容不能为空")

        changes: dict[str, object] = {}
        if "team" in payload:
            changes["team"] = _responsibility(payload.get("team"), "责任团队")
        if "priority" in payload:
            changes["priority"] = _enum_value(payload.get("priority"), PRIORITIES, "优先级")
        if "due_date" in payload:
            changes["due_date"] = _due_date(payload.get("due_date"))

        target_status = payload.get("status")
        if target_status is not None:
            target_status = _enum_value(target_status, STATUSES, "状态")
            expected = "in_progress" if task["status"] == "pending" else "completed"
            if target_status != expected:
                raise TaskConflictError(f"状态只能从 {task['status']} 进入 {expected}")
            changes["status"] = target_status

        if target_status == "completed":
            result = _required_text(payload.get("result"), "处理结果")
            changes.update({"result": result, "completed_at": current.isoformat()})
        elif "result" in payload:
            raise TaskValidationError("只有完成任务时才能填写处理结果")

        timestamp = current.isoformat()
        self.task_store.append_updated(task_id, timestamp, changes)
        return {**task, **changes, "updated_at": timestamp}


def _matching_record_ids(
    records: list[dict],
    *,
    platform: str,
    issue_category: str,
    responsibility: str,
    source_range: str,
    now: datetime,
) -> list[str]:
    cutoff = None if source_range == "all" else now - timedelta(days=7 if source_range == "7d" else 30)
    matched: list[str] = []
    for record in records:
        created_at = _record_time(record.get("created_at"))
        if created_at is None or created_at > now or (cutoff is not None and created_at < cutoff):
            continue
        analysis = _mapping(record.get("analysis"))
        request = _mapping(analysis.get("request"))
        attribution = _mapping(analysis.get("attribution"))
        if (
            _text(request.get("platform")).casefold() == platform.casefold()
            and _text(attribution.get("issue_category")) == issue_category
            and _text(attribution.get("primary_responsibility")) == responsibility
            and isinstance(record.get("id"), str)
        ):
            matched.append(record["id"])
    return matched


def _significant_increase(
    records: list[dict], platform: str, issue_category: str, responsibility: str, now: datetime
) -> bool:
    trends = build_issue_trends(records, now=now)
    return any(
        _text(item.get("platform")).casefold() == platform.casefold()
        and item.get("issue_category") == issue_category
        and item.get("responsibility") == responsibility
        and item.get("significant_increase") is True
        for item in trends["clusters"]
    )


def _task_sort_key(task: dict, today: date) -> tuple:
    if task.get("status") == "completed":
        return (1, 1, 0, date.max.toordinal(), -_timestamp(task.get("completed_at")), str(task.get("id")))
    due = date.fromisoformat(str(task["due_date"]))
    return (
        0,
        0 if due < today else 1,
        -PRIORITY_RANK[str(task["priority"])],
        due.toordinal(),
        -_timestamp(task.get("created_at")),
        str(task.get("id")),
    )


def _task_key(task: Mapping[str, object]) -> tuple[str, str, str]:
    return _cluster_key(
        _text(task.get("platform")),
        _text(task.get("issue_category")),
        _text(task.get("responsibility")),
    )


def _cluster_key(platform: str, issue_category: str, responsibility: str) -> tuple[str, str, str]:
    return platform.strip().casefold(), issue_category.strip(), responsibility.strip()


def _issue_category(value: object) -> str:
    return _optional_enum(value, IssueCategory, "问题类型") or _raise_required("问题类型")


def _responsibility(value: object, field: str) -> str:
    return _optional_enum(value, Responsibility, field) or _raise_required(field)


def _optional_enum(value: object, enum_type: type, field: str) -> str:
    cleaned = _text(value)
    if not cleaned:
        return ""
    try:
        return enum_type(cleaned).value
    except ValueError as exc:
        raise TaskValidationError(f"{field}不合法") from exc


def _enum_value(value: object, allowed: set[str], field: str) -> str:
    cleaned = _required_text(value, field)
    if cleaned not in allowed:
        raise TaskValidationError(f"{field}不合法")
    return cleaned


def _optional_choice(value: object, allowed: set[str], field: str) -> str:
    cleaned = _text(value)
    if not cleaned:
        return ""
    if cleaned not in allowed:
        raise TaskValidationError(f"{field}不合法")
    return cleaned


def _optional_due_date(value: object) -> str:
    cleaned = _text(value)
    return _due_date(cleaned) if cleaned else ""


def _due_date(value: object) -> str:
    cleaned = _required_text(value, "截止日期")
    try:
        return date.fromisoformat(cleaned).isoformat()
    except ValueError as exc:
        raise TaskValidationError("截止日期必须是 YYYY-MM-DD") from exc


def _required_text(value: object, field: str) -> str:
    cleaned = _text(value)
    if not cleaned:
        raise TaskValidationError(f"{field}不能为空")
    return cleaned


def _raise_required(field: str) -> str:
    raise TaskValidationError(f"{field}不能为空")


def _record_time(value: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return _as_utc(parsed)


def _timestamp(value: object) -> float:
    parsed = _record_time(value)
    return parsed.timestamp() if parsed else 0.0


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _text(value: object) -> str:
    return str(value).strip() if value is not None else ""
```

- [ ] **Step 4: Run service tests and fix only failures in this slice**

Run: `python -m pytest tests/test_tasks.py -q`

Expected: `22 passed` (the parametrized cases are counted separately by pytest).

- [ ] **Step 5: Run storage and service tests together**

Run: `python -m pytest tests/test_task_storage.py tests/test_tasks.py -q`

Expected: all tests PASS and no warning about task data encoding.

- [ ] **Step 6: Commit the service slice**

```powershell
git add src/customer_issue_agent/tasks.py tests/test_tasks.py
git commit -m "feat: add issue cluster task service"
```

### Task 3: Task API, Template Region, and Visual Contract

**Files:**
- Modify: `tests/test_app.py`
- Modify: `src/customer_issue_agent/app.py`
- Modify: `src/customer_issue_agent/templates/index.html`
- Modify: `src/customer_issue_agent/static/styles.css`

- [ ] **Step 1: Add failing API and page contract tests**

Append these tests to `tests/test_app.py`; they reuse that module's existing `_write_jsonl_records` and `_stored_record` helpers:

```python
def test_task_api_creates_reuses_lists_and_completes_task(tmp_path):
    storage_path = tmp_path / "analyses.jsonl"
    task_path = tmp_path / "tasks.jsonl"
    _write_jsonl_records(
        storage_path,
        [_stored_record("record-1", platform="Amazon", created_at=datetime.now(UTC))],
    )
    client = TestClient(create_app(storage_path=storage_path, task_storage_path=task_path))
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
    duplicate = client.post("/api/tasks", data={**form, "source": "trend", "source_range": "7d"})
    listed = client.get("/api/tasks", params={"status": "pending", "priority": "medium"})
    task_id = created.json()["task"]["id"]
    skipped = client.patch(
        f"/api/tasks/{task_id}",
        json={"status": "completed", "result": "不能跳过处理中"},
    )
    started = client.patch(f"/api/tasks/{task_id}", json={"status": "in_progress"})
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
    client = TestClient(create_app(storage_path=storage_path, task_storage_path=task_path))

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
```

- [ ] **Step 2: Run the contract tests and verify the missing signature/routes/markup fail**

Run:

```powershell
python -m pytest tests/test_app.py -q
```

Expected: FAIL because `create_app` has no `task_storage_path`, `/api/tasks` does not exist, and the task region selectors are absent.

- [ ] **Step 3: Wire task storage and API into FastAPI**

Apply these exact import changes in `src/customer_issue_agent/app.py`:

```python
from fastapi.responses import HTMLResponse, JSONResponse, Response

from customer_issue_agent.task_storage import TaskStorageError, TaskStore
from customer_issue_agent.tasks import (
    TaskConflictError,
    TaskNotFoundError,
    TaskService,
    TaskValidationError,
)
```

Replace the `create_app` signature and store initialization with:

```python
def create_app(storage_path: Path | None = None, task_storage_path: Path | None = None) -> FastAPI:
    app = FastAPI(title="客户使用问题归因智能体")
    templates = Jinja2Templates(directory=str(PACKAGE_DIR / "templates"))
    static_dir = PACKAGE_DIR / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    analysis_path = storage_path or DEFAULT_STORAGE
    store = AnalysisStore(analysis_path)
    task_store = TaskStore(task_storage_path or analysis_path.with_name("tasks.jsonl"))
    task_service = TaskService(store, task_store)
```

Insert these routes immediately after `records_trends` and before `return app`:

```python
    @app.get("/api/tasks")
    async def list_tasks(status: str = "", priority: str = "") -> dict:
        try:
            return task_service.list_tasks(status=status, priority=priority)
        except (TaskValidationError, TaskStorageError) as exc:
            _raise_task_http_error(exc)

    @app.post("/api/tasks")
    async def create_task(
        source: str = Form(...),
        source_range: str = Form(...),
        platform: str = Form(...),
        issue_category: str = Form(...),
        responsibility: str = Form(...),
        team: str = Form(default=""),
        priority: str = Form(default=""),
        due_date: str = Form(default=""),
    ) -> JSONResponse:
        try:
            task, created = task_service.create_task(
                {
                    "source": source,
                    "source_range": source_range,
                    "platform": platform,
                    "issue_category": issue_category,
                    "responsibility": responsibility,
                    "team": team,
                    "priority": priority,
                    "due_date": due_date,
                }
            )
        except (TaskValidationError, TaskConflictError, TaskNotFoundError, TaskStorageError) as exc:
            _raise_task_http_error(exc)
        return JSONResponse(status_code=201 if created else 200, content={"created": created, "task": task})

    @app.patch("/api/tasks/{task_id}")
    async def update_task(task_id: str, payload: dict) -> dict:
        try:
            return task_service.update_task(task_id, payload)
        except (TaskValidationError, TaskConflictError, TaskNotFoundError, TaskStorageError) as exc:
            _raise_task_http_error(exc)
```

Add this module-level helper before `_run_analysis`:

```python
def _raise_task_http_error(exc: Exception) -> None:
    if isinstance(exc, TaskStorageError):
        raise HTTPException(status_code=500, detail="任务数据读取失败") from exc
    if isinstance(exc, TaskNotFoundError):
        raise HTTPException(status_code=404, detail="任务不存在") from exc
    if isinstance(exc, TaskConflictError):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    raise HTTPException(status_code=422, detail=str(exc)) from exc
```

- [ ] **Step 4: Add the task region and create form**

In `src/customer_issue_agent/templates/index.html`, insert this complete section after the `issue-trends` section and before the section containing “最近记录”:

```html
        <section id="task-workflow" class="task-dashboard" aria-label="问题簇处理任务">
          <div class="section-heading task-heading">
            <div>
              <p class="eyebrow">处理任务</p>
              <h2>问题簇处理闭环</h2>
            </div>
            <div class="task-filters" aria-label="筛选处理任务">
              <label for="task-status-filter">状态</label>
              <select id="task-status-filter">
                <option value="">全部状态</option>
                <option value="pending">待处理</option>
                <option value="in_progress">处理中</option>
                <option value="completed">已完成</option>
              </select>
              <label for="task-priority-filter">优先级</label>
              <select id="task-priority-filter">
                <option value="">全部优先级</option>
                <option value="high">高</option>
                <option value="medium">中</option>
                <option value="low">低</option>
              </select>
            </div>
          </div>
          <form id="task-create-form" class="task-create-form" hidden>
            <input type="hidden" name="source">
            <input type="hidden" name="source_range">
            <input type="hidden" name="platform">
            <input type="hidden" name="issue_category">
            <input type="hidden" name="responsibility">
            <div>
              <p class="eyebrow">创建处理任务</p>
              <h3 data-task-create-title></h3>
              <p data-task-create-source></p>
            </div>
            <label>责任团队
              <select name="team" required>
                <option value="operations">运营</option>
                <option value="customer_service_training">客服培训</option>
                <option value="product">产品</option>
                <option value="supply_chain_quality">供应链或质量</option>
                <option value="need_more_information">需要补充信息</option>
              </select>
            </label>
            <label>优先级
              <select name="priority" required>
                <option value="high">高</option>
                <option value="medium">中</option>
                <option value="low">低</option>
              </select>
            </label>
            <label>截止日期<input type="date" name="due_date" required></label>
            <div class="task-form-actions">
              <button class="primary-action" type="submit" data-loading-label="创建中...">创建任务</button>
              <button class="secondary-action" type="button" data-task-create-cancel>取消</button>
            </div>
            <p class="form-message" role="alert" aria-live="polite"></p>
          </form>
          <div id="task-content">
            <p class="task-loading">任务加载中...</p>
          </div>
        </section>
```

- [ ] **Step 5: Add focused task styling**

Append this block before the existing `@media` rules in `src/customer_issue_agent/static/styles.css`:

```css
.task-dashboard { display: grid; gap: 1rem; }
.task-heading { align-items: end; gap: 1rem; }
.task-filters { display: flex; flex-wrap: wrap; align-items: center; gap: .55rem; }
.task-filters label { color: var(--muted); font-size: .82rem; font-weight: 700; }
.task-metrics, .task-grid { display: grid; gap: .85rem; }
.task-metrics { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.task-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.task-card, .task-create-form { border: 1px solid var(--line); border-radius: 18px; background: rgba(255, 255, 255, .78); padding: 1rem; }
.task-card { display: grid; gap: .8rem; transition: border-color .2s ease, box-shadow .2s ease; }
.task-card.is-highlighted { border-color: var(--accent); box-shadow: 0 0 0 4px rgba(173, 71, 38, .14); }
.task-card-header, .task-card-meta, .task-actions, .task-form-actions { display: flex; flex-wrap: wrap; align-items: center; gap: .6rem; }
.task-card-header { justify-content: space-between; align-items: flex-start; }
.task-card h3 { margin: 0; font-size: 1rem; }
.task-status, .task-priority, .task-source, .task-overdue { border-radius: 999px; padding: .25rem .55rem; font-size: .75rem; font-weight: 800; }
.task-status { background: #e9efe8; color: #34513a; }
.task-priority { background: #f3e7d4; color: #70451e; }
.task-source { background: #e7edf2; color: #314b5c; }
.task-overdue { background: #f7ded8; color: #922f1f; }
.task-record-link { border: 0; background: transparent; color: var(--accent); padding: 0; text-decoration: underline; cursor: pointer; }
.task-result { border-left: 3px solid var(--accent); margin: 0; padding-left: .75rem; }
.task-create-form { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: .85rem; }
.task-create-form[hidden] { display: none; }
.task-create-form > div:first-child, .task-create-form .form-message { grid-column: 1 / -1; }
.task-create-form label, .task-edit-form label, .task-complete-form label { display: grid; gap: .35rem; }
.task-loading, .task-error, .task-empty { color: var(--muted); }
.task-error { color: var(--danger); }
.issue-cluster-actions { gap: .55rem; }
.task-create-trigger { flex: 0 0 auto; }
```

Inside the existing `@media (max-width: 720px)` rule, add:

```css
  .task-metrics, .task-grid, .task-create-form { grid-template-columns: 1fr; }
  .task-create-form > div:first-child, .task-create-form .form-message { grid-column: auto; }
  .task-heading, .task-filters { align-items: stretch; }
  .task-filters select { flex: 1 1 9rem; }
```

- [ ] **Step 6: Run API/page tests and all backend tests**

Run:

```powershell
python -m pytest tests/test_app.py tests/test_task_storage.py tests/test_tasks.py -q
python -m pytest -q
```

Expected: both commands PASS; the second command includes the existing 94 tests plus the new task tests.

- [ ] **Step 7: Commit the API and page shell**

```powershell
git add src/customer_issue_agent/app.py src/customer_issue_agent/templates/index.html src/customer_issue_agent/static/styles.css tests/test_app.py
git commit -m "feat: expose task workflow API and region"
```

### Task 4: Task List, Filters, and Manual Creation UI

**Files:**
- Create: `tests/js/test_task_workflow.mjs`
- Modify: `tests/test_app.py`
- Modify: `src/customer_issue_agent/static/app.js`

- [ ] **Step 1: Create failing JavaScript behavior tests for loading and creation**

Append this static asset contract test to `tests/test_app.py`:

```python
def test_static_app_js_contains_task_workflow_hooks(tmp_path):
    client = TestClient(create_app(storage_path=tmp_path / "analyses.jsonl"))

    script = client.get("/static/app.js").text

    assert "latestTaskRequestId" in script
    assert "loadTasks" in script
    assert "submitTaskCreate" in script
    assert "data-task-create" in script
```

Create `tests/js/test_task_workflow.mjs` with a DOM stub following the existing `tests/js/test_issue_trends.mjs` pattern. The initial complete test cases are:

```javascript
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const appScript = readFileSync("src/customer_issue_agent/static/app.js", "utf8");

class FakeClassList {
  constructor() { this.values = new Set(); }
  add(...names) { names.forEach((name) => this.values.add(name)); }
  remove(...names) { names.forEach((name) => this.values.delete(name)); }
  contains(name) { return this.values.has(name); }
  toggle(name, force) {
    const enabled = force === undefined ? !this.values.has(name) : Boolean(force);
    enabled ? this.values.add(name) : this.values.delete(name);
    return enabled;
  }
}

class FakeElement {
  constructor({ dataset = {}, value = "", textContent = "" } = {}) {
    this.dataset = { ...dataset };
    this.value = value;
    this.textContent = textContent;
    this.innerHTML = "";
    this.hidden = false;
    this.disabled = false;
    this.classList = new FakeClassList();
    this.listeners = new Map();
    this.selectors = new Map();
  }
  setSelector(selector, value) { this.selectors.set(selector, value); return this; }
  querySelector(selector) { return this.selectors.get(selector) || null; }
  querySelectorAll(selector) { return this.selectors.get(selector) || []; }
  addEventListener(event, callback) { this.listeners.set(event, callback); }
  scrollIntoView() {}
  reset() {}
}

function loadApp({ includeTasks = true } = {}) {
  const elements = new Map();
  if (includeTasks) {
    elements.set("task-content", new FakeElement());
    elements.set("task-status-filter", new FakeElement());
    elements.set("task-priority-filter", new FakeElement());
  }
  elements.set("summary-range", new FakeElement({ value: "30d" }));
  const document = {
    domReady: null,
    addEventListener(event, callback) { if (event === "DOMContentLoaded") this.domReady = callback; },
    getElementById(id) { return elements.get(id) || null; },
    querySelector() { return null; },
    querySelectorAll() { return []; },
    createElement() { return new FakeElement(); },
  };
  const context = vm.createContext({
    URLSearchParams,
    clearTimeout,
    console,
    Date,
    document,
    FormData: class FormData {},
    navigator: {},
    setTimeout,
    window: { location: {} },
  });
  vm.runInContext(appScript, context);
  return { context, document, elements };
}

function task(overrides = {}) {
  return {
    id: "task-one",
    title: "Amazon · 功能不会用或设置失败 · 客服培训",
    source: "summary",
    source_range: "all",
    platform: "Amazon",
    issue_category: "function_use",
    responsibility: "customer_service_training",
    record_count: 3,
    team: "customer_service_training",
    priority: "medium",
    due_date: "2030-01-01",
    status: "pending",
    result: null,
    completed_at: null,
    ...overrides,
  };
}

function deferred() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
}

test("任务查询包含当前状态和优先级筛选", () => {
  const { context, elements } = loadApp();
  elements.get("task-status-filter").value = "in_progress";
  elements.get("task-priority-filter").value = "high";

  assert.equal(context.buildTaskListUrl(), "/api/tasks?status=in_progress&priority=high");
});

test("任务卡显示来源、状态、优先级、记录数和逾期文字", () => {
  const { context } = loadApp();
  const html = context.taskCardHtml(task({ due_date: "2020-01-01" }), new Date("2026-08-03T08:00:00Z"));
  const completedHtml = context.taskCardHtml(task({
    status: "completed", result: "已更新说明", completed_at: "2026-08-03T10:00:00+00:00",
  }));

  assert.match(html, /高频问题/);
  assert.match(html, /待处理/);
  assert.match(html, /中优先级/);
  assert.match(html, /3 条关联记录/);
  assert.match(html, /已逾期/);
  assert.match(completedHtml, /已更新说明/);
  assert.match(completedHtml, /2026-08-03T10:00:00\+00:00/);
  assert.doesNotMatch(completedHtml, /已逾期/);
});

test("高频和趋势问题簇的筛选与创建按钮互为兄弟", () => {
  const { context } = loadApp();
  context.isSummaryIssueClusterFilterable = () => true;

  const summaryHtml = context.summaryIssueClusterRow({
    platform: "Amazon", issue_category: "function_use",
    responsibility: "customer_service_training", count: 3,
  });
  const trendHtml = context.issueTrendRow({
    platform: "Amazon", issue_category: "function_use", responsibility: "customer_service_training",
    current_count: 3, previous_count: 1, delta: 2, significant_increase: true,
  });

  assert.equal((summaryHtml.match(/<button/g) || []).length, 2);
  assert.equal((trendHtml.match(/<button/g) || []).length, 2);
  assert.doesNotMatch(summaryHtml, /<button[^>]*>[\s\S]*<button[^>]*>[\s\S]*<\/button>[\s\S]*<\/button>/);
  assert.doesNotMatch(trendHtml, /<button[^>]*>[\s\S]*<button[^>]*>[\s\S]*<\/button>[\s\S]*<\/button>/);
});

test("高频和趋势创建草稿使用正确范围和建议优先级", () => {
  const { context } = loadApp();
  const summary = context.createTaskDraft({
    source: "summary", platform: "Amazon", issueCategory: "function_use",
    responsibility: "customer_service_training", significantIncrease: false,
  });
  const trend = context.createTaskDraft({
    source: "trend", platform: "TikTok Shop", issueCategory: "product_fault",
    responsibility: "supply_chain_quality", significantIncrease: true,
  });

  assert.equal(summary.sourceRange, "30d");
  assert.equal(summary.priority, "medium");
  assert.equal(trend.sourceRange, "7d");
  assert.equal(trend.priority, "high");
  assert.equal(trend.team, "supply_chain_quality");
});

test("新建和重复任务各刷新一次，重复任务清空筛选并定位已有 ID", async () => {
  const { context, elements } = loadApp();
  const calls = [];
  let responseCount = 0;
  context.loadTasks = (options) => { calls.push(options); };
  context.fetch = async () => ({
    ok: true,
    status: 200,
    json: async () => ({ created: responseCount++ === 0, task: task() }),
  });
  const form = new FakeElement();
  form.setSelector("button[type='submit']", new FakeElement({ textContent: "创建任务" }));
  form.setSelector(".form-message", new FakeElement());

  await context.submitTaskCreate(form);
  elements.get("task-status-filter").value = "completed";
  elements.get("task-priority-filter").value = "high";
  await context.submitTaskCreate(form);

  assert.deepEqual(calls, [{}, { highlightTaskId: "task-one" }]);
  assert.equal(elements.get("task-status-filter").value, "");
  assert.equal(elements.get("task-priority-filter").value, "");
});

test("创建失败保留表单并显示局部错误且不刷新任务", async () => {
  const { context } = loadApp();
  let refreshes = 0;
  context.loadTasks = () => { refreshes += 1; };
  context.fetch = async () => ({ ok: false, json: async () => ({ detail: "没有匹配记录" }) });
  const form = new FakeElement();
  const message = new FakeElement();
  form.setSelector("button[type='submit']", new FakeElement({ textContent: "创建任务" }));
  form.setSelector(".form-message", message);

  await context.submitTaskCreate(form);

  assert.equal(form.hidden, false);
  assert.equal(refreshes, 0);
  assert.equal(message.textContent, "没有匹配记录");
});

test("较旧任务列表响应不覆盖新的筛选结果", async () => {
  const { context } = loadApp();
  const first = deferred();
  const second = deferred();
  const rendered = [];
  let count = 0;
  context.fetch = () => (++count === 1 ? first.promise : second.promise);
  context.renderTasks = (payload) => rendered.push(payload.version);

  const oldLoad = context.loadTasks();
  const newLoad = context.loadTasks();
  second.resolve({ ok: true, json: async () => ({ version: "new" }) });
  await newLoad;
  first.resolve({ ok: true, json: async () => ({ version: "old" }) });
  await oldLoad;

  assert.deepEqual(rendered, ["new"]);
});

test("缺少任务容器时不发送请求", async () => {
  const { context } = loadApp({ includeTasks: false });
  let fetches = 0;
  context.fetch = async () => { fetches += 1; };

  await context.loadTasks();

  assert.equal(fetches, 0);
});

test("页面初始化只加载一次任务且分析相关流程不额外触发", () => {
  const { context, document } = loadApp();
  [
    "bindTabs", "bindAnalysisForm", "bindBatchForm", "bindFeedbackForms", "bindSummaryRange",
    "loadRecordsSummary", "loadIssueTrends", "bindFilteredExport", "bindRecordFilters",
    "bindReviewQueueToggle", "bindRecordDetails", "bindRecordCopyActions", "bindTaskFilters",
    "bindTaskCreateForm",
  ].forEach((name) => { context[name] = () => {}; });
  let taskLoads = 0;
  context.loadTasks = () => { taskLoads += 1; };

  document.domReady();

  assert.equal(taskLoads, 1);
});

test("分析、批量分析和反馈保存不刷新任务区域", async () => {
  const { context } = loadApp();
  let taskLoads = 0;
  context.loadTasks = () => { taskLoads += 1; };
  [
    "renderAnalysisResult", "bindFeedbackForms", "prependRecentRecord", "loadRecordsSummary",
    "loadIssueTrends", "renderBatchResults", "syncFeedbackUi", "refreshRecordFilterViews",
  ].forEach((name) => { context[name] = () => {}; });
  context.fetch = async (url) => {
    if (url === "/api/analyze") {
      return { ok: true, json: async () => ({ record_id: "one", analysis: {} }) };
    }
    if (url === "/api/analyze-batch-file") {
      return { ok: true, json: async () => ({ batch_id: "batch", count: 1, records: [{ record_id: "two" }] }) };
    }
    return { ok: true, json: async () => ({ record_id: "one", feedback: { accepted: true } }) };
  };
  const analysisForm = new FakeElement({ dataset: { endpoint: "/api/analyze" } });
  analysisForm.setSelector("button[type='submit']", new FakeElement({ textContent: "分析" }));
  const batchForm = new FakeElement({ dataset: { endpoint: "/api/analyze-batch-file" } });
  batchForm.setSelector("button[type='submit']", new FakeElement({ textContent: "批量分析" }));
  const feedbackForm = new FakeElement({ dataset: { endpoint: "/api/records/one/feedback" } });
  feedbackForm.setSelector("button[type='submit']", new FakeElement({ textContent: "保存反馈" }));
  feedbackForm.setSelector(".form-message", new FakeElement());

  await context.submitAnalysisForm(analysisForm, new FakeElement());
  await context.submitBatchForm(batchForm, new FakeElement());
  await context.submitFeedbackForm(feedbackForm);

  assert.equal(taskLoads, 0);
});
```

- [ ] **Step 2: Run the new Node suite and verify the functions are undefined**

Run:

```powershell
node --test tests/js/test_task_workflow.mjs
python -m pytest tests/test_app.py::test_static_app_js_contains_task_workflow_hooks -q
```

Expected: Node FAILS with errors such as `context.buildTaskListUrl is not a function`, and pytest FAILS because `latestTaskRequestId` is absent.

- [ ] **Step 3: Add task labels, request sequencing, initialization, list rendering, and creation**

In `src/customer_issue_agent/static/app.js`, extend `labels` with:

```javascript
  task_status: { pending: "待处理", in_progress: "处理中", completed: "已完成" },
  task_priority: { high: "高", medium: "中", low: "低" },
```

Add `let latestTaskRequestId = 0;` beside the existing request counters. In `DOMContentLoaded`, add exactly these calls after `loadIssueTrends()`:

```javascript
  bindTaskFilters();
  bindTaskCreateForm();
  loadTasks();
```

Replace `summaryIssueClusterRow` with this complete function so the filter and create controls are siblings:

```javascript
function summaryIssueClusterRow(item) {
  const platform = String(item.platform ?? "").trim();
  const issueCategory = String(item.issue_category ?? "").trim();
  const responsibility = String(item.responsibility ?? "").trim();
  const count = item.count ?? 0;
  const issueLabel = labelFor("issue_category", issueCategory);
  const responsibilityLabel = labelFor("responsibility", responsibility);
  const content = `
    <span class="issue-cluster-label">
      <strong>${escapeHtml(platform || "unknown")}</strong>
      <small>${escapeHtml(issueLabel)} / ${escapeHtml(responsibilityLabel)}</small>
    </span>
    <strong>${escapeHtml(count)}</strong>
  `;
  if (!isSummaryIssueClusterFilterable(platform, issueCategory, responsibility)) {
    return `<li>${content}</li>`;
  }
  const ariaLabel = `筛选高频问题：${platform}，${issueLabel}，责任方${responsibilityLabel}，共${count}条`;
  return `
    <li class="issue-cluster-actions">
      <button
        class="issue-cluster-filter"
        type="button"
        data-summary-issue-cluster-filter
        data-summary-cluster-platform="${escapeHtml(platform)}"
        data-summary-cluster-issue-category="${escapeHtml(issueCategory)}"
        data-summary-cluster-responsibility="${escapeHtml(responsibility)}"
        aria-label="${escapeHtml(ariaLabel)}"
      >${content}</button>
      <button
        class="secondary-action task-create-trigger"
        type="button"
        data-task-create
        data-task-source="summary"
        data-task-platform="${escapeHtml(platform)}"
        data-task-issue-category="${escapeHtml(issueCategory)}"
        data-task-responsibility="${escapeHtml(responsibility)}"
        data-task-significant-increase="false"
      >创建任务</button>
    </li>
  `;
}
```

Replace `issueTrendRow` with this complete sibling-button version:

```javascript
function issueTrendRow(item) {
  const platform = String(item.platform ?? "").trim();
  const issueCategory = String(item.issue_category ?? "").trim();
  const responsibility = String(item.responsibility ?? "").trim();
  const currentCount = Number(item.current_count) || 0;
  const previousCount = Number(item.previous_count) || 0;
  const delta = Number(item.delta) || 0;
  const directionClass = delta >= 0 ? "is-up" : "is-down";
  const issueLabel = labelFor("issue_category", issueCategory);
  const responsibilityLabel = labelFor("responsibility", responsibility);
  const alert = item.significant_increase ? `<span class="trend-alert">明显上升</span>` : "";
  const content = `
    <span class="trend-cluster-label">
      <strong>${escapeHtml(platform || "unknown")}</strong>
      <small>${escapeHtml(issueLabel)} / ${escapeHtml(responsibilityLabel)}</small>
    </span>
    <span class="trend-counts">
      <span>本期 ${escapeHtml(currentCount)}</span>
      <span>上期 ${escapeHtml(previousCount)}</span>
      <span class="trend-change ${directionClass}">${escapeHtml(trendChangeLabel(delta))}</span>
      ${alert}
    </span>
  `;
  if (!isSummaryIssueClusterFilterable(platform, issueCategory, responsibility)) {
    return `<li class="trend-row">${content}</li>`;
  }
  const ariaLabel = `筛选趋势问题：${platform}，${issueLabel}，责任方${responsibilityLabel}，本期${currentCount}条，上期${previousCount}条`;
  return `
    <li class="trend-row issue-cluster-actions">
      <button
        class="trend-row-button"
        type="button"
        data-issue-trend-filter
        data-trend-platform="${escapeHtml(platform)}"
        data-trend-issue-category="${escapeHtml(issueCategory)}"
        data-trend-responsibility="${escapeHtml(responsibility)}"
        aria-label="${escapeHtml(ariaLabel)}"
      >${content}</button>
      <button
        class="secondary-action task-create-trigger"
        type="button"
        data-task-create
        data-task-source="trend"
        data-task-platform="${escapeHtml(platform)}"
        data-task-issue-category="${escapeHtml(issueCategory)}"
        data-task-responsibility="${escapeHtml(responsibility)}"
        data-task-significant-increase="${item.significant_increase === true}"
      >创建任务</button>
    </li>
  `;
}
```

At the end of `renderRecordsSummary`, use these three calls:

```javascript
  bindSummaryPlatformFilters(container);
  bindSummaryIssueClusterFilters(container);
  bindTaskCreateButtons(container);
```

At the end of `renderIssueTrends`, use:

```javascript
  bindIssueTrendFilters(container);
  bindTaskCreateButtons(container);
```

Append these complete functions before `readError`:

```javascript
function bindTaskFilters() {
  ["task-status-filter", "task-priority-filter"].forEach((id) => {
    document.getElementById(id)?.addEventListener("change", () => loadTasks());
  });
}

function buildTaskListUrl() {
  const params = new URLSearchParams();
  const status = document.getElementById("task-status-filter")?.value || "";
  const priority = document.getElementById("task-priority-filter")?.value || "";
  if (status) params.set("status", status);
  if (priority) params.set("priority", priority);
  const query = params.toString();
  return `/api/tasks${query ? `?${query}` : ""}`;
}

async function loadTasks({ highlightTaskId = "" } = {}) {
  const container = document.getElementById("task-content");
  if (!container) return;
  const requestId = ++latestTaskRequestId;
  try {
    const response = await fetch(buildTaskListUrl());
    const payload = await response.json();
    if (requestId !== latestTaskRequestId) return;
    if (!response.ok) throw new Error(readError(payload));
    renderTasks(payload, highlightTaskId);
  } catch (error) {
    if (requestId !== latestTaskRequestId) return;
    container.innerHTML = `<p class="task-error">${escapeHtml(error.message || "任务数据读取失败")}</p>`;
  }
}

function renderTasks(payload, highlightTaskId = "") {
  const container = document.getElementById("task-content");
  if (!container) return;
  const tasks = payload.tasks || [];
  container.innerHTML = `
    <div class="task-metrics">
      ${summaryMetric("待处理", payload.counts?.pending ?? 0)}
      ${summaryMetric("处理中", payload.counts?.in_progress ?? 0)}
      ${summaryMetric("已完成", payload.counts?.completed ?? 0)}
    </div>
    ${tasks.length
      ? `<div class="task-grid">${tasks.map((task) => taskCardHtml(task)).join("")}</div>`
      : `<p class="task-empty">当前筛选下暂无处理任务。</p>`}
  `;
  bindTaskActions(container);
  if (highlightTaskId) highlightTask(highlightTaskId);
}

function taskCardHtml(task, now = new Date()) {
  const overdue = task.status !== "completed" && new Date(`${task.due_date}T23:59:59`) < now;
  const source = task.source === "trend" ? "趋势问题" : "高频问题";
  const result = task.status === "completed"
    ? `
      <p class="task-result"><strong>处理结果：</strong>${escapeHtml(task.result || "暂无信息")}</p>
      <p>完成时间：${escapeHtml(task.completed_at || "暂无信息")}</p>
    `
    : "";
  return `
    <article class="task-card" data-task-id="${escapeHtml(task.id)}">
      <div class="task-card-header">
        <h3>${escapeHtml(task.title)}</h3>
        <span class="task-status">${escapeHtml(labelFor("task_status", task.status))}</span>
      </div>
      <div class="task-card-meta">
        <span class="task-source">${source}</span>
        <span class="task-priority">${escapeHtml(labelFor("task_priority", task.priority))}优先级</span>
        ${overdue ? `<span class="task-overdue">已逾期</span>` : ""}
      </div>
      <p>责任团队：${escapeHtml(labelFor("responsibility", task.team))}</p>
      <p>截止日期：${escapeHtml(task.due_date)}</p>
      <button class="task-record-link" type="button" data-task-records>${escapeHtml(task.record_count)} 条关联记录</button>
      ${result}
      <div class="task-actions"></div>
    </article>
  `;
}

function bindTaskCreateButtons(root = document) {
  root.querySelectorAll("[data-task-create]").forEach((button) => {
    if (button.dataset.bound === "true") return;
    button.dataset.bound = "true";
    button.addEventListener("click", () => openTaskCreateForm(createTaskDraft({
      source: button.dataset.taskSource || "summary",
      platform: button.dataset.taskPlatform || "",
      issueCategory: button.dataset.taskIssueCategory || "",
      responsibility: button.dataset.taskResponsibility || "",
      significantIncrease: button.dataset.taskSignificantIncrease === "true",
    })));
  });
}

function createTaskDraft({ source, platform, issueCategory, responsibility, significantIncrease }) {
  const sourceRange = source === "trend"
    ? "7d"
    : document.getElementById("summary-range")?.value || "all";
  const priority = source === "trend" && significantIncrease ? "high" : "medium";
  return {
    source,
    sourceRange,
    platform,
    issueCategory,
    responsibility,
    significantIncrease,
    team: responsibility,
    priority,
    dueDate: suggestedDueDate(priority),
  };
}

function suggestedDueDate(priority, now = new Date()) {
  const days = { high: 3, medium: 7, low: 14 }[priority] || 7;
  const value = new Date(now.getFullYear(), now.getMonth(), now.getDate() + days);
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function openTaskCreateForm(draft) {
  const form = document.getElementById("task-create-form");
  if (!form) return;
  form.hidden = false;
  form.elements.source.value = draft.source;
  form.elements.source_range.value = draft.sourceRange;
  form.elements.platform.value = draft.platform;
  form.elements.issue_category.value = draft.issueCategory;
  form.elements.responsibility.value = draft.responsibility;
  form.elements.team.value = draft.team;
  form.elements.priority.value = draft.priority;
  form.elements.due_date.value = draft.dueDate;
  form.querySelector("[data-task-create-title]").textContent = `${draft.platform} · ${labelFor("issue_category", draft.issueCategory)} · ${labelFor("responsibility", draft.responsibility)}`;
  form.querySelector("[data-task-create-source]").textContent = draft.source === "trend" ? "来源：近 7 天趋势" : `来源：高频问题（${draft.sourceRange}）`;
  clearError(form.querySelector(".form-message"));
  form.scrollIntoView({ behavior: "smooth", block: "center" });
}

function bindTaskCreateForm() {
  const form = document.getElementById("task-create-form");
  if (!form) return;
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    submitTaskCreate(form);
  });
  form.querySelector("[data-task-create-cancel]")?.addEventListener("click", () => { form.hidden = true; });
  form.elements.priority.addEventListener("change", () => {
    form.elements.due_date.value = suggestedDueDate(form.elements.priority.value);
  });
}

async function submitTaskCreate(form) {
  const button = form.querySelector("button[type='submit']");
  const message = form.querySelector(".form-message");
  const originalLabel = button.textContent;
  setLoading(button, true);
  clearError(message);
  try {
    const response = await fetch("/api/tasks", { method: "POST", body: new FormData(form) });
    const payload = await response.json();
    if (!response.ok) throw new Error(readError(payload));
    form.hidden = true;
    if (!payload.created) {
      const status = document.getElementById("task-status-filter");
      const priority = document.getElementById("task-priority-filter");
      if (status) status.value = "";
      if (priority) priority.value = "";
    }
    await loadTasks(payload.created ? {} : { highlightTaskId: payload.task.id });
  } catch (error) {
    showError(message, error.message || "任务创建失败，请重试。");
  } finally {
    setLoading(button, false);
    button.textContent = originalLabel;
  }
}

function highlightTask(taskId) {
  const cards = Array.from(document.querySelectorAll("[data-task-id]"));
  const card = cards.find((item) => item.dataset.taskId === taskId);
  if (!card) return;
  card.classList.add("is-highlighted");
  card.scrollIntoView({ behavior: "smooth", block: "center" });
  setTimeout(() => card.classList.remove("is-highlighted"), 1800);
}

function bindTaskActions() {}
```

- [ ] **Step 4: Run Node tests and static syntax checks**

Run:

```powershell
node --test tests/js/test_task_workflow.mjs
node --check src/customer_issue_agent/static/app.js
python -m pytest tests/test_app.py::test_static_app_js_contains_task_workflow_hooks -q
```

Expected: the new Node and static asset contract tests PASS and `node --check` exits `0` without output.

- [ ] **Step 5: Run existing JavaScript suites to catch regressions in sibling buttons and initialization**

Run:

```powershell
node --test tests/js/test_feedback_ui.mjs tests/js/test_issue_trends.mjs tests/js/test_task_workflow.mjs
```

Expected: all three suites PASS. `DOMContentLoaded` must call `loadTasks` exactly once, while the existing single analysis, batch analysis, feedback, summary-range and trend flows must not call it.

- [ ] **Step 6: Commit list and creation UI**

```powershell
git add src/customer_issue_agent/static/app.js tests/test_app.py tests/js/test_task_workflow.mjs
git commit -m "feat: add task list and creation UI"
```

### Task 5: Edit, Start, Complete, Failure Isolation, and Record Drilldown

**Files:**
- Modify: `tests/js/test_task_workflow.mjs`
- Modify: `tests/test_app.py`
- Modify: `src/customer_issue_agent/static/app.js`
- Modify: `src/customer_issue_agent/static/styles.css`

- [ ] **Step 1: Add failing interaction tests**

Append this lifecycle asset contract to `tests/test_app.py`:

```python
def test_static_app_js_contains_task_lifecycle_hooks(tmp_path):
    client = TestClient(create_app(storage_path=tmp_path / "analyses.jsonl"))

    script = client.get("/static/app.js").text

    assert "taskActionsHtml" in script
    assert "updateTask" in script
    assert "completeTask" in script
    assert "drilldownTaskRecords" in script
    assert "data-task-records" in script
```

Append these tests to `tests/js/test_task_workflow.mjs`:

```javascript
test("待处理、处理中和已完成任务只显示合法操作", () => {
  const { context } = loadApp();

  assert.match(context.taskActionsHtml(task()), /开始处理/);
  assert.match(context.taskActionsHtml(task()), /编辑/);
  assert.doesNotMatch(context.taskActionsHtml(task()), /完成任务/);
  assert.match(context.taskActionsHtml(task({ status: "in_progress" })), /完成任务/);
  assert.doesNotMatch(context.taskActionsHtml(task({ status: "completed" })), /data-task-edit/);
});

test("开始处理成功只刷新一次任务区域", async () => {
  const { context } = loadApp();
  const calls = [];
  context.fetch = async (url, options) => {
    calls.push([url, JSON.parse(options.body)]);
    return { ok: true, json: async () => task({ status: "in_progress" }) };
  };
  context.loadTasks = () => { calls.push(["refresh"]); };

  await context.updateTask("task-one", { status: "in_progress" }, new FakeElement());

  assert.deepEqual(calls, [
    ["/api/tasks/task-one", { status: "in_progress" }],
    ["refresh"],
  ]);
});

test("空处理结果不提交，合法结果去除空白后完成", async () => {
  const { context } = loadApp();
  let fetches = 0;
  context.fetch = async () => {
    fetches += 1;
    return { ok: true, json: async () => task({ status: "completed" }) };
  };
  context.loadTasks = () => {};
  const message = new FakeElement();

  await context.completeTask("task-one", "   ", message);
  assert.equal(fetches, 0);
  assert.match(message.textContent, /处理结果/);

  await context.completeTask("task-one", "  已更新说明  ", message);
  assert.equal(fetches, 1);
});

test("更新失败保留展开表单和值且不刷新任务", async () => {
  const { context } = loadApp();
  let refreshes = 0;
  context.fetch = async () => ({ ok: false, json: async () => ({ detail: "状态冲突" }) });
  context.loadTasks = () => { refreshes += 1; };
  const message = new FakeElement();

  const succeeded = await context.updateTask("task-one", { team: "product" }, message);

  assert.equal(succeeded, false);
  assert.equal(refreshes, 0);
  assert.equal(message.textContent, "状态冲突");
});

test("任务记录下钻设置保存范围和精确问题簇并保留关键词复核", () => {
  const { context, elements } = loadApp();
  elements.set("platform-filter", new FakeElement());
  elements.set("issue-filter", new FakeElement());
  elements.set("responsibility-filter", new FakeElement());
  elements.set("record-search", new FakeElement({ value: "保留关键词" }));
  elements.set("feedback-filter", new FakeElement({ value: "unreviewed" }));
  const calls = [];
  context.refreshRecordFilterViews = () => calls.push("filters");
  context.loadRecordsSummary = () => calls.push("summary");
  context.scrollToRecentRecords = () => calls.push("scroll");

  context.drilldownTaskRecords(task({ source_range: "7d" }));

  assert.equal(elements.get("summary-range").value, "7d");
  assert.equal(elements.get("platform-filter").value, "Amazon");
  assert.equal(elements.get("platform-filter").dataset.matchMode, "exact");
  assert.equal(elements.get("record-search").value, "保留关键词");
  assert.equal(elements.get("feedback-filter").value, "unreviewed");
  assert.deepEqual(calls, ["filters", "summary", "scroll"]);
});
```

- [ ] **Step 2: Run the interaction tests and verify missing functions fail**

Run:

```powershell
node --test tests/js/test_task_workflow.mjs
python -m pytest tests/test_app.py::test_static_app_js_contains_task_lifecycle_hooks -q
```

Expected: Node FAILS for undefined `taskActionsHtml`, `updateTask`, `completeTask`, and `drilldownTaskRecords`; pytest FAILS because those lifecycle hooks are absent.

- [ ] **Step 3: Render legal actions and bind local forms**

Replace `<div class="task-actions"></div>` in `taskCardHtml` with `${taskActionsHtml(task)}` and replace its opening `<article>` tag with:

```html
    <article
      class="task-card"
      data-task-id="${escapeHtml(task.id)}"
      data-task-source-range="${escapeHtml(task.source_range)}"
      data-task-platform="${escapeHtml(task.platform)}"
      data-task-issue-category="${escapeHtml(task.issue_category)}"
      data-task-responsibility="${escapeHtml(task.responsibility)}"
    >
```

Replace the empty `bindTaskActions` and append the following functions:

```javascript
function taskActionsHtml(task) {
  if (task.status === "completed") return "";
  const primary = task.status === "pending"
    ? `<button class="primary-action" type="button" data-task-start>开始处理</button>`
    : `<button class="primary-action" type="button" data-task-complete-toggle>完成任务</button>`;
  return `
    <div class="task-actions">
      ${primary}
      <button class="secondary-action" type="button" data-task-edit>编辑</button>
    </div>
    <p class="form-message" data-task-action-message role="alert"></p>
    <form class="task-edit-form" hidden>
      <label>责任团队<select name="team">${taskTeamOptions(task.team)}</select></label>
      <label>优先级<select name="priority">${taskPriorityOptions(task.priority)}</select></label>
      <label>截止日期<input name="due_date" type="date" value="${escapeHtml(task.due_date)}"></label>
      <button class="primary-action" type="submit">保存</button>
      <p class="form-message" role="alert"></p>
    </form>
    <form class="task-complete-form" hidden>
      <label>处理结果<textarea name="result" rows="3" required></textarea></label>
      <button class="primary-action" type="submit">确认完成</button>
      <p class="form-message" role="alert"></p>
    </form>
  `;
}

function taskTeamOptions(selected) {
  return Object.entries(labels.responsibility)
    .map(([value, label]) => `<option value="${value}"${value === selected ? " selected" : ""}>${escapeHtml(label)}</option>`)
    .join("");
}

function taskPriorityOptions(selected) {
  return Object.entries(labels.task_priority)
    .map(([value, label]) => `<option value="${value}"${value === selected ? " selected" : ""}>${escapeHtml(label)}</option>`)
    .join("");
}

function bindTaskActions(root) {
  root.querySelectorAll("[data-task-id]").forEach((card) => {
    const taskId = card.dataset.taskId;
    card.querySelector("[data-task-start]")?.addEventListener("click", (event) => {
      updateTask(
        taskId,
        { status: "in_progress" },
        card.querySelector("[data-task-action-message]"),
        event.currentTarget,
      );
    });
    card.querySelector("[data-task-edit]")?.addEventListener("click", () => {
      card.querySelector(".task-edit-form").hidden = false;
    });
    card.querySelector("[data-task-complete-toggle]")?.addEventListener("click", () => {
      card.querySelector(".task-complete-form").hidden = false;
    });
    const editForm = card.querySelector(".task-edit-form");
    editForm?.addEventListener("submit", async (event) => {
      event.preventDefault();
      const data = new FormData(editForm);
      await updateTask(
        taskId,
        Object.fromEntries(data.entries()),
        editForm.querySelector(".form-message"),
        editForm.querySelector("button[type='submit']"),
      );
    });
    const completeForm = card.querySelector(".task-complete-form");
    completeForm?.addEventListener("submit", async (event) => {
      event.preventDefault();
      await completeTask(
        taskId,
        completeForm.elements.result.value,
        completeForm.querySelector(".form-message"),
        completeForm.querySelector("button[type='submit']"),
      );
    });
    card.querySelector("[data-task-records]")?.addEventListener("click", () => drilldownTaskRecords({
      source_range: card.dataset.taskSourceRange,
      platform: card.dataset.taskPlatform,
      issue_category: card.dataset.taskIssueCategory,
      responsibility: card.dataset.taskResponsibility,
    }));
  });
}
```

- [ ] **Step 4: Implement PATCH behavior and exact record drilldown**

Append these functions next to the task action functions:

```javascript
async function updateTask(taskId, changes, messageTarget, button = null) {
  const originalLabel = button?.textContent || "";
  if (messageTarget?.classList) clearError(messageTarget);
  if (button) setLoading(button, true);
  try {
    const response = await fetch(`/api/tasks/${encodeURIComponent(taskId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(changes),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(readError(payload));
    await loadTasks();
    return true;
  } catch (error) {
    if (messageTarget?.classList) showError(messageTarget, error.message || "任务更新失败，请重试。");
    return false;
  } finally {
    if (button) {
      setLoading(button, false);
      button.textContent = originalLabel;
    }
  }
}

async function completeTask(taskId, result, messageTarget, button = null) {
  const cleaned = String(result || "").trim();
  if (!cleaned) {
    showError(messageTarget, "请填写处理结果后再完成任务。");
    return false;
  }
  return updateTask(taskId, { status: "completed", result: cleaned }, messageTarget, button);
}

function drilldownTaskRecords(task) {
  const range = document.getElementById("summary-range");
  const platform = document.getElementById("platform-filter");
  const issue = document.getElementById("issue-filter");
  const responsibility = document.getElementById("responsibility-filter");
  if (!range || !platform || !issue || !responsibility) return;
  range.value = task.source_range || "all";
  platform.value = task.platform || "";
  platform.dataset.matchMode = "exact";
  issue.value = task.issue_category || "";
  responsibility.value = task.responsibility || "";
  refreshRecordFilterViews();
  loadRecordsSummary();
  scrollToRecentRecords();
}
```

- [ ] **Step 5: Add expanded-form layout without changing the visual system**

Append to the task CSS block:

```css
.task-edit-form, .task-complete-form { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: .65rem; border-top: 1px solid var(--line); padding-top: .8rem; }
.task-complete-form { grid-template-columns: 1fr auto; align-items: end; }
.task-edit-form[hidden], .task-complete-form[hidden] { display: none; }
.task-edit-form .form-message, .task-complete-form .form-message { grid-column: 1 / -1; }
```

Inside `@media (max-width: 720px)`, add:

```css
  .task-edit-form, .task-complete-form { grid-template-columns: 1fr; }
  .task-edit-form .form-message, .task-complete-form .form-message { grid-column: auto; }
```

- [ ] **Step 6: Verify all frontend refresh and failure-isolation behavior**

Run:

```powershell
node --test tests/js/test_feedback_ui.mjs tests/js/test_issue_trends.mjs tests/js/test_task_workflow.mjs
node --check src/customer_issue_agent/static/app.js
python -m pytest tests/test_app.py::test_static_app_js_contains_task_lifecycle_hooks -q
```

Expected: all Node and lifecycle asset contract tests PASS. In particular, existing analysis and feedback tests must show no extra task refresh; task list requests use the latest-request guard; failed writes do not call `loadTasks`.

- [ ] **Step 7: Commit the task lifecycle UI**

```powershell
git add src/customer_issue_agent/static/app.js src/customer_issue_agent/static/styles.css tests/test_app.py tests/js/test_task_workflow.mjs
git commit -m "feat: complete task workflow interactions"
```

### Task 6: Documentation, Full Verification, Review, and PR Migration

**Files:**
- Modify: `README.md`
- Verify: all files changed by Tasks 1-5

- [ ] **Step 1: Document the operator workflow and storage boundary**

Append this section to `README.md`:

```markdown
## 问题簇处理任务

“高频问题”和“近 7 天趋势”中的有效问题簇可以人工创建处理任务。任务按平台、问题类型和责任方去重，同一问题簇同时只保留一个待处理或处理中的任务；旧任务完成后可以创建新一轮。

创建任务时，后端会重新读取本地分析记录并保存匹配记录 ID 快照。趋势任务固定使用最近 7 天，明显上升问题默认高优先级；其他任务默认中优先级。高、中、低优先级分别建议 3、7、14 天截止日期，责任团队、优先级和截止日期均可人工调整。

任务只能按“待处理 → 处理中 → 已完成”推进，完成时必须填写处理结果。点击任务的关联记录数量，会恢复任务保存的范围和精确问题簇筛选，同时保留当前关键词与复核状态。

任务事件以 UTF-8 追加写入分析文件同目录的 `tasks.jsonl`，不会修改 `analyses.jsonl`、人工反馈或 CSV 字段。任务区域不会自动轮询、自动建任务、调用模型或连接海外电商平台 API；任务读取失败时，现有分析、复核、概览、趋势、筛选和导出仍可继续使用。
```

- [ ] **Step 2: Run focused tests with verbose failure names**

```powershell
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
python -m pytest tests/test_task_storage.py tests/test_tasks.py tests/test_app.py -q
node --test tests/js/test_task_workflow.mjs
```

Expected: all focused Python and Node tests PASS.

- [ ] **Step 3: Run the full acceptance suite**

```powershell
python -m pytest -q
node --test tests/js/test_feedback_ui.mjs tests/js/test_issue_trends.mjs tests/js/test_task_workflow.mjs
node --check src/customer_issue_agent/static/app.js
git diff --check
```

Expected: pytest reports the previous `94 passed` plus all newly added tests; Node reports the previous `18/18` plus all task workflow tests; JavaScript syntax and `git diff --check` exit `0`.

- [ ] **Step 4: Verify UTF-8 and forbidden implementation drift**

```powershell
$utf8 = [System.Text.UTF8Encoding]::new($false, $true)
$changed = git diff --name-only 959d058b503c0111ef6f93ec98d5c4d1b3ad3cd9 -- '*.py' '*.js' '*.css' '*.html' '*.md'
foreach ($file in $changed) { [void]$utf8.GetString([System.IO.File]::ReadAllBytes((Join-Path (Get-Location) $file))) }
rg -n "\\\\u[0-9a-fA-F]{4}|setInterval|WebSocket|celery|redis|sqlalchemy|openai" src tests README.md
```

Expected: UTF-8 decoding completes without exception. The `rg` command returns no newly added Unicode escapes, polling, background queue, database, or model-provider integration; any pre-existing match must be inspected against `git diff` rather than removed blindly.

- [ ] **Step 5: Review the implementation against the specification**

Use the `requesting-code-review` skill. Review specifically for snapshot immutability, platform case-insensitive exact matching, valid timestamp exclusion, duplicate open-task prevention, one-way transitions, required completion result, immutable completed tasks, counts-before-filtering, overdue ordering, stale GET suppression, one-refresh-per-write, local error isolation, sibling buttons, and mobile accessibility. Resolve every confirmed P1/P2 finding with a new failing regression test before changing implementation.

- [ ] **Step 6: Commit documentation and any review fixes**

```powershell
git add README.md
git commit -m "docs: explain issue cluster task workflow"
git status --short
```

Expected: documentation commit succeeds. If review fixes were needed, commit each tested fix separately before this documentation commit. `git status --short` is empty.

- [ ] **Step 7: Build a clean push worktree from the target PR head**

Do not modify the long-lived worktree's `origin`. Use the explicit target repository and the known pre-feature PR head:

```powershell
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$RepoRoot = (git rev-parse --show-toplevel).Trim()
$WorktreeParent = Split-Path -Parent $RepoRoot
$PushRoot = Join-Path $WorktreeParent "customer-issue-agent-task-workflow-push"
if (Test-Path -LiteralPath $PushRoot) { throw "临时推送目录已存在，请先人工确认：$PushRoot" }
git -c http.version=HTTP/1.1 fetch https://github.com/ARIUM-hub/Agent-Operations-Workflow.git codex/customer-issue-agent-mvp
git worktree add --detach $PushRoot FETCH_HEAD
$Commits = @(git rev-list --reverse "959d058b503c0111ef6f93ec98d5c4d1b3ad3cd9..codex/customer-issue-agent-mvp")
if ($Commits.Count -eq 0) { throw "没有找到本功能提交" }
git -C $PushRoot cherry-pick $Commits
```

Expected: fetch succeeds, the temporary worktree starts from PR #2's current head, and only commits after `959d058b503c0111ef6f93ec98d5c4d1b3ad3cd9` are replayed. Inspect `git -C $PushRoot log --oneline 959d058b..HEAD` and confirm it contains this feature's design, plan, implementation, tests, and documentation only.

- [ ] **Step 8: Re-run full verification in the clean push worktree and fast-forward the PR branch**

```powershell
Push-Location $PushRoot
python -m pytest -q
node --test tests/js/test_feedback_ui.mjs tests/js/test_issue_trends.mjs tests/js/test_task_workflow.mjs
node --check src/customer_issue_agent/static/app.js
git diff --check 959d058b503c0111ef6f93ec98d5c4d1b3ad3cd9 HEAD
git status --short
git -c http.version=HTTP/1.1 push https://github.com/ARIUM-hub/Agent-Operations-Workflow.git HEAD:codex/customer-issue-agent-mvp
Pop-Location
```

Expected: all verification passes, status is clean, and the normal push fast-forwards PR #2 without `--force`.

- [ ] **Step 9: Confirm remote parity, then safely remove only the temporary worktree**

```powershell
$RemoteHead = (git -c http.version=HTTP/1.1 ls-remote https://github.com/ARIUM-hub/Agent-Operations-Workflow.git refs/heads/codex/customer-issue-agent-mvp).Split("`t")[0]
$LocalPushHead = (git -C $PushRoot rev-parse HEAD).Trim()
if ($RemoteHead -ne $LocalPushHead) { throw "远端与临时 worktree 提交不一致，停止清理" }
$ResolvedPushRoot = [System.IO.Path]::GetFullPath($PushRoot)
$ResolvedParent = [System.IO.Path]::GetFullPath($WorktreeParent) + [System.IO.Path]::DirectorySeparatorChar
if (-not $ResolvedPushRoot.StartsWith($ResolvedParent, [System.StringComparison]::OrdinalIgnoreCase)) { throw "临时目录不在预期父目录内" }
git worktree remove $ResolvedPushRoot
git worktree prune
git status --short --branch
```

Expected: remote and local push hashes match, only `customer-issue-agent-task-workflow-push` is removed, the long-lived development worktree remains, and its `origin` is unchanged.

---

## Acceptance Checklist

- [ ] 高频问题和趋势问题簇都有独立“创建任务”按钮，且不嵌套在筛选按钮中。
- [ ] 后端而非客户端决定快照、趋势范围和明显上升标记。
- [ ] 快照排除缺失、非法、未来或范围外时间，并保持文件顺序与不可变性。
- [ ] 同一问题簇只有一个未完成任务，完成后能创建新一轮。
- [ ] 责任团队、优先级和截止日期默认值及人工修改均通过后端校验。
- [ ] 状态严格按 `pending -> in_progress -> completed`，完成结果必填，已完成任务只读。
- [ ] 任务数量基于全部任务，筛选只作用于任务列表，排序和逾期文字符合规格。
- [ ] 创建、重复定位、编辑、开始、完成都只在成功后刷新任务区域一次。
- [ ] 失败写请求保留表单和值，旧 GET 响应不能覆盖新结果。
- [ ] 任务记录下钻恢复保存范围和精确问题簇，同时保留关键词和复核状态。
- [ ] 任务数据损坏只让任务区域降级，不影响其他工作台能力。
- [ ] 没有数据库、模型调用、平台 API、后台任务、轮询、通知或第三方前端依赖。
- [ ] 所有新增文本为 UTF-8，中文直接保存，JSONL 使用 `ensure_ascii=False`。
- [ ] pytest、Node 行为测试、JavaScript 语法和差异检查全部通过。
