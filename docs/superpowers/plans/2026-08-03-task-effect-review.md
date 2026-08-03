# Task Effect Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (recommended) or superpowers:subagent-driven-development when explicitly needed for independent tasks. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为已完成的问题簇处理任务增加固定 7 天前后数据对比、人工效果复盘、可修正审计记录和待复盘队列。

**Architecture:** 在现有 `tasks.jsonl` 中追加专用 `task_effect_reviewed` 事件，由 `TaskStore` 投影最新复盘，由 `TaskService` 计算成熟状态、时间窗口和证据快照。FastAPI 暴露列表过滤、证据预览和复盘提交接口；原生 JavaScript 在任务卡内完成待复盘提示、证据展示、提交与修正，不增加轮询、数据库、模型调用或平台 API。

**Tech Stack:** Python 3.12、FastAPI、UTF-8 JSONL、Jinja2、原生 JavaScript/CSS、pytest、Node `node:test`/`vm`

---

## File Structure

- `src/customer_issue_agent/task_storage.py`：追加和投影 `task_effect_reviewed` 事件，保留最新复盘与修订次数。
- `src/customer_issue_agent/tasks.py`：计算复盘状态、7 天证据窗口、服务端重算、人工结论校验和组合筛选。
- `src/customer_issue_agent/app.py`：扩展任务列表参数，新增证据 GET 和复盘 POST。
- `src/customer_issue_agent/templates/index.html`：增加待复盘筛选和人工刷新入口。
- `src/customer_issue_agent/static/app.js`：渲染复盘状态、加载证据、提交或修正复盘并处理旧响应。
- `src/customer_issue_agent/static/styles.css`：复盘状态、证据对比、记录 ID 和移动端布局。
- `tests/test_task_storage.py`：复盘事件投影、修订、UTF-8 和损坏事件测试。
- `tests/test_tasks.py`：成熟状态、窗口边界、证据匹配、提交重算和筛选测试。
- `tests/test_app.py`：复盘 API、错误映射、模板和静态契约测试。
- `tests/js/test_task_effect_review.mjs`：复盘状态、证据、提交、修正和旧响应行为测试。
- `README.md`：说明固定窗口、人工判断、修正和无轮询边界。

---

### Task 1: Persist Effect Review Events

**Files:**
- Modify: `tests/test_task_storage.py`
- Modify: `src/customer_issue_agent/task_storage.py`

- [ ] **Step 1: Write failing storage projection tests**

在 `tests/test_task_storage.py` 增加复盘构造器，并让 `_task()` 默认包含未复盘投影字段：

```python
def _review(revision: int = 1, note: str = "已更新中文说明") -> dict:
    return {
        "revision": revision,
        "verdict": "effective",
        "note": note,
        "baseline": {
            "start": "2026-07-27T08:00:00+00:00",
            "end": "2026-08-03T08:00:00+00:00",
            "record_ids": ["before-1", "before-2"],
            "count": 2,
        },
        "effect": {
            "start": "2026-08-10T08:00:00+00:00",
            "end": "2026-08-17T08:00:00+00:00",
            "record_ids": ["after-1"],
            "count": 1,
        },
        "delta": -1,
        "change_rate": -0.5,
    }
```

在 `_task()` 返回值中增加：

```python
"effect_review": None,
"effect_review_revision_count": 0,
```

新增测试：

```python
def test_effect_review_events_project_latest_revision(tmp_path):
    store = TaskStore(tmp_path / "tasks.jsonl")
    store.append_created(_task())
    store.append_effect_review(
        "task-one", "2026-08-17T08:00:00+00:00", _review()
    )
    store.append_effect_review(
        "task-one",
        "2026-08-18T08:00:00+00:00",
        _review(2, "修正后的复盘结论"),
    )

    task = store.list_tasks()[0]

    assert task["effect_review"] == {
        **_review(2, "修正后的复盘结论"),
        "reviewed_at": "2026-08-18T08:00:00+00:00",
    }
    assert task["effect_review_revision_count"] == 2


def test_effect_review_note_is_written_as_utf8(tmp_path):
    path = tmp_path / "tasks.jsonl"
    store = TaskStore(path)
    store.append_created(_task())
    store.append_effect_review(
        "task-one", "2026-08-17T08:00:00+00:00", _review()
    )

    raw = path.read_text(encoding="utf-8")

    assert "已更新中文说明" in raw
    assert "\\u" not in raw
```

把以下复盘损坏事件加入现有参数化错误测试：

```python
{
    "type": "task_effect_reviewed",
    "task_id": "missing",
    "reviewed_at": "2026-08-17T08:00:00+00:00",
    "review": _review(),
},
{
    "type": "task_effect_reviewed",
    "task_id": "task-one",
    "reviewed_at": "",
    "review": {},
},
```

- [ ] **Step 2: Run the storage tests and verify RED**

Run:

```powershell
python -m pytest -q tests/test_task_storage.py
```

Expected: FAIL because `TaskStore.append_effect_review` does not exist and created tasks do not expose review projection fields.

- [ ] **Step 3: Implement append-only review projection**

在 `TaskStore` 增加：

```python
def append_effect_review(
    self, task_id: str, reviewed_at: str, review: dict
) -> None:
    self._append(
        {
            "type": "task_effect_reviewed",
            "task_id": task_id,
            "reviewed_at": reviewed_at,
            "review": deepcopy(review),
        }
    )
```

在 `task_created` 分支复制任务后补齐旧任务默认值：

```python
projected = deepcopy(task)
projected.setdefault("effect_review", None)
projected.setdefault("effect_review_revision_count", 0)
tasks[task_id] = projected
```

在 `task_updated` 分支之后增加：

```python
if event_type == "task_effect_reviewed":
    task_id = event.get("task_id")
    review = event.get("review")
    reviewed_at = event.get("reviewed_at")
    if not isinstance(task_id, str) or not task_id.strip():
        raise TaskStorageError(f"任务事件第 {line_number} 行缺少任务 ID")
    if task_id not in tasks:
        raise TaskStorageError(
            f"任务事件第 {line_number} 行引用不存在任务 {task_id}"
        )
    expected_revision = tasks[task_id]["effect_review_revision_count"] + 1
    if (
        not isinstance(review, dict)
        or not isinstance(reviewed_at, str)
        or not reviewed_at
        or review.get("revision") != expected_revision
    ):
        raise TaskStorageError(f"任务事件第 {line_number} 行复盘内容不完整")
    tasks[task_id]["effect_review"] = {
        **deepcopy(review),
        "reviewed_at": reviewed_at,
    }
    tasks[task_id]["effect_review_revision_count"] = expected_revision
    return
```

- [ ] **Step 4: Run storage tests and verify GREEN**

Run:

```powershell
python -m pytest -q tests/test_task_storage.py
```

Expected: PASS.

- [ ] **Step 5: Commit storage support**

```powershell
git add src/customer_issue_agent/task_storage.py tests/test_task_storage.py
git commit -m "feat: store task effect reviews"
```

---

### Task 2: Add Review Readiness and List Filtering

**Files:**
- Modify: `tests/test_tasks.py`
- Modify: `src/customer_issue_agent/tasks.py`

- [ ] **Step 1: Write failing readiness and filter tests**

在 `tests/test_tasks.py` 增加辅助函数：

```python
def _completed_task(service: TaskService, *, completed_at: datetime) -> dict:
    task = service.create_task(_payload(), now=NOW, today=TODAY)[0]
    service.update_task(task["id"], {"status": "in_progress"}, now=NOW)
    return service.update_task(
        task["id"],
        {"status": "completed", "result": "已更新帮助中心"},
        now=completed_at,
    )
```

新增测试：

```python
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
```

- [ ] **Step 2: Run readiness tests and verify RED**

Run:

```powershell
python -m pytest -q tests/test_tasks.py -k "effect_review_readiness or unfinished_tasks or invalid_effect_review_filter"
```

Expected: FAIL because `list_tasks` has no `now` or `effect_review_state` arguments.

- [ ] **Step 3: Implement readiness projection and filtering**

在常量区增加：

```python
EFFECT_REVIEW_STATES = {"not_applicable", "accumulating", "ready", "reviewed"}
EFFECT_REVIEW_PERIOD = timedelta(days=7)
```

在新任务对象中增加：

```python
"effect_review": None,
"effect_review_revision_count": 0,
```

把 `list_tasks` 签名扩展为：

```python
def list_tasks(
    self,
    *,
    status: str = "",
    priority: str = "",
    effect_review_state: str = "",
    now: datetime | None = None,
    today: date | None = None,
) -> dict:
```

方法主体先计算当前时间和复盘状态，再筛选：

```python
current = _as_utc(now or datetime.now(UTC))
status_filter = _optional_choice(status, STATUSES, "状态")
priority_filter = _optional_choice(priority, PRIORITIES, "优先级")
review_filter = _optional_choice(
    effect_review_state, EFFECT_REVIEW_STATES, "复盘状态"
)
tasks = [_with_effect_review_state(task, current) for task in self.task_store.list_tasks()]
counts = {
    value: sum(task.get("status") == value for task in tasks)
    for value in STATUSES
}
effect_review_counts = {
    value: sum(task["effect_review_state"] == value for task in tasks)
    for value in ("accumulating", "ready", "reviewed")
}
filtered = [
    task
    for task in tasks
    if (not status_filter or task.get("status") == status_filter)
    and (not priority_filter or task.get("priority") == priority_filter)
    and (not review_filter or task["effect_review_state"] == review_filter)
]
local_today = today or current.astimezone().date()
filtered.sort(key=lambda task: _task_sort_key(task, local_today))
return {
    "counts": {
        "pending": counts["pending"],
        "in_progress": counts["in_progress"],
        "completed": counts["completed"],
    },
    "effect_review_counts": effect_review_counts,
    "tasks": filtered,
}
```

增加状态辅助函数：

```python
def _with_effect_review_state(task: dict, now: datetime) -> dict:
    if task.get("status") != "completed":
        return {
            **task,
            "effect_review_state": "not_applicable",
            "effect_review_ready_at": None,
        }
    completed_at = _record_time(task.get("completed_at"))
    if completed_at is None:
        raise TaskValidationError("任务完成时间不合法")
    ready_at = completed_at + EFFECT_REVIEW_PERIOD
    if task.get("effect_review") is not None:
        state = "reviewed"
    else:
        state = "ready" if now >= ready_at else "accumulating"
    return {
        **task,
        "effect_review_state": state,
        "effect_review_ready_at": ready_at.isoformat(),
    }
```

- [ ] **Step 4: Run task service tests and verify GREEN**

Run:

```powershell
python -m pytest -q tests/test_tasks.py
```

Expected: PASS.

- [ ] **Step 5: Commit readiness support**

```powershell
git add src/customer_issue_agent/tasks.py tests/test_tasks.py
git commit -m "feat: expose task review readiness"
```

---

### Task 3: Compute and Submit Review Evidence

**Files:**
- Modify: `tests/test_tasks.py`
- Modify: `src/customer_issue_agent/tasks.py`

- [ ] **Step 1: Write failing evidence window tests**

新增固定时间：

```python
CREATED_AT = datetime(2026, 8, 3, 8, 0, tzinfo=UTC)
COMPLETED_AT = datetime(2026, 8, 5, 8, 0, tzinfo=UTC)
REVIEW_READY_AT = datetime(2026, 8, 12, 8, 0, tzinfo=UTC)
```

新增辅助函数，使任务创建时间和完成时间可控：

```python
def _ready_review_service(tmp_path, records: list[dict]):
    service, store = _service(
        tmp_path,
        [_record("task-seed", created_at=CREATED_AT), *records],
    )
    task = service.create_task(_payload(), now=CREATED_AT, today=TODAY)[0]
    service.update_task(task["id"], {"status": "in_progress"}, now=CREATED_AT)
    completed = service.update_task(
        task["id"],
        {"status": "completed", "result": "已更新操作说明"},
        now=COMPLETED_AT,
    )
    return service, store, completed
```

新增窗口和匹配测试：

```python
def test_effect_review_evidence_uses_half_open_windows_and_exact_cluster(tmp_path):
    records = [
        _record("baseline-start", created_at=CREATED_AT - timedelta(days=7)),
        _record("baseline-middle", platform="amazon", created_at=CREATED_AT - timedelta(days=1)),
        _record("baseline-end", created_at=CREATED_AT),
        _record("effect-start", created_at=COMPLETED_AT),
        _record("effect-middle", created_at=COMPLETED_AT + timedelta(days=1)),
        _record("effect-end", created_at=COMPLETED_AT + timedelta(days=7)),
        _record("other-platform", platform="Amazon US", created_at=COMPLETED_AT),
        _record("invalid-time", created_at="bad-time"),
    ]
    service, _, completed = _ready_review_service(tmp_path, records)

    payload = service.get_effect_review(completed["id"], now=REVIEW_READY_AT)

    assert payload["evidence"]["baseline"]["record_ids"] == [
        "baseline-start",
        "baseline-middle",
    ]
    assert payload["evidence"]["effect"]["record_ids"] == [
        "effect-start",
        "effect-middle",
    ]
    assert payload["evidence"]["delta"] == 0
    assert payload["evidence"]["change_rate"] == 0.0


def test_zero_baseline_has_null_change_rate(tmp_path):
    records = [_record("effect", created_at=COMPLETED_AT + timedelta(days=1))]
    service, _, completed = _ready_review_service(tmp_path, records)

    evidence = service.get_effect_review(
        completed["id"], now=REVIEW_READY_AT
    )["evidence"]

    assert evidence["baseline"]["count"] == 0
    assert evidence["effect"]["count"] == 1
    assert evidence["change_rate"] is None
```

- [ ] **Step 2: Write failing review submission and revision tests**

```python
def test_effect_review_submission_recomputes_and_appends_revision(tmp_path):
    records = [
        _record("baseline", created_at=CREATED_AT - timedelta(days=1)),
        _record("effect", created_at=COMPLETED_AT + timedelta(days=1)),
    ]
    service, store, completed = _ready_review_service(tmp_path, records)
    preview = service.get_effect_review(completed["id"], now=REVIEW_READY_AT)
    with service.analysis_store.path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(
            json.dumps(
                _record(
                    "effect-late-import",
                    created_at=COMPLETED_AT + timedelta(days=2),
                ),
                ensure_ascii=False,
            )
            + "\n"
        )

    first = service.review_task_effect(
        completed["id"],
        {"verdict": "effective", "note": "  已更新说明  "},
        now=REVIEW_READY_AT,
    )
    second = service.review_task_effect(
        completed["id"],
        {"verdict": "no_clear_change", "note": "修正结论"},
        now=REVIEW_READY_AT + timedelta(hours=1),
    )

    assert preview["evidence"]["effect"]["count"] == 1
    assert first["review"]["effect"]["count"] == 2
    assert first["review"]["note"] == "已更新说明"
    assert first["review"]["revision"] == 1
    assert second["review"]["revision"] == 2
    assert second["task"]["effect_review_state"] == "reviewed"
    assert store.list_tasks()[0]["effect_review_revision_count"] == 2


def test_zero_effect_window_still_accepts_human_verdict(tmp_path):
    service, _, completed = _ready_review_service(
        tmp_path,
        [_record("baseline", created_at=CREATED_AT - timedelta(days=1))],
    )

    payload = service.review_task_effect(
        completed["id"],
        {"verdict": "worsened", "note": "运营根据其他证据判断"},
        now=REVIEW_READY_AT,
    )

    assert payload["review"]["effect"]["count"] == 0
    assert payload["review"]["verdict"] == "worsened"


@pytest.mark.parametrize(
    "payload",
    [
        {"verdict": "automatic", "note": "说明"},
        {"verdict": "effective", "note": "  "},
        {"verdict": "effective", "note": "说明", "record_ids": []},
    ],
)
def test_invalid_effect_review_payload_is_rejected(tmp_path, payload):
    service, _, completed = _ready_review_service(
        tmp_path,
        [_record("baseline", created_at=CREATED_AT - timedelta(days=1))],
    )

    with pytest.raises(TaskValidationError):
        service.review_task_effect(completed["id"], payload, now=REVIEW_READY_AT)


def test_effect_review_requires_completed_and_mature_task(tmp_path):
    service, _, completed = _ready_review_service(
        tmp_path,
        [_record("baseline", created_at=CREATED_AT - timedelta(days=1))],
    )

    with pytest.raises(TaskConflictError, match="数据积累"):
        service.get_effect_review(
            completed["id"], now=REVIEW_READY_AT - timedelta(seconds=1)
        )
    with pytest.raises(TaskNotFoundError):
        service.get_effect_review("missing", now=REVIEW_READY_AT)

    pending_path = tmp_path / "pending"
    pending_path.mkdir()
    pending_service, _ = _service(
        pending_path,
        [_record("pending-record", created_at=CREATED_AT)],
    )
    pending = pending_service.create_task(
        _payload(), now=CREATED_AT, today=TODAY
    )[0]
    with pytest.raises(TaskConflictError, match="任务完成后"):
        pending_service.get_effect_review(pending["id"], now=REVIEW_READY_AT)
```

- [ ] **Step 3: Run evidence tests and verify RED**

Run:

```powershell
python -m pytest -q tests/test_tasks.py -k "effect_review"
```

Expected: FAIL because `get_effect_review` and `review_task_effect` do not exist.

- [ ] **Step 4: Implement evidence preview and submission**

增加常量：

```python
EFFECT_REVIEW_VERDICTS = {"effective", "no_clear_change", "worsened"}
EFFECT_REVIEW_FIELDS = {"verdict", "note"}
```

在 `TaskService` 增加：

```python
def get_effect_review(
    self, task_id: str, *, now: datetime | None = None
) -> dict:
    current = _as_utc(now or datetime.now(UTC))
    task = self._reviewable_task(task_id, current)
    evidence = _effect_review_evidence(
        self.analysis_store.list_records(), task
    )
    return {
        "task_id": task_id,
        "state": task["effect_review_state"],
        "ready_at": task["effect_review_ready_at"],
        "evidence": evidence,
        "latest_review": task.get("effect_review"),
        "revision_count": task.get("effect_review_revision_count", 0),
    }

def review_task_effect(
    self,
    task_id: str,
    payload: Mapping[str, object],
    *,
    now: datetime | None = None,
) -> dict:
    current = _as_utc(now or datetime.now(UTC))
    task = self._reviewable_task(task_id, current)
    unknown_fields = set(payload) - EFFECT_REVIEW_FIELDS
    if unknown_fields:
        raise TaskValidationError(
            f"包含未知字段：{', '.join(sorted(unknown_fields))}"
        )
    verdict = _enum_value(
        payload.get("verdict"), EFFECT_REVIEW_VERDICTS, "复盘结论"
    )
    note = _required_text(payload.get("note"), "复盘说明")
    evidence = _effect_review_evidence(
        self.analysis_store.list_records(), task
    )
    revision = int(task.get("effect_review_revision_count", 0)) + 1
    review = {
        "revision": revision,
        "verdict": verdict,
        "note": note,
        **evidence,
    }
    reviewed_at = current.isoformat()
    self.task_store.append_effect_review(task_id, reviewed_at, review)
    projected_review = {**review, "reviewed_at": reviewed_at}
    reviewed_task = _with_effect_review_state(
        {
            **task,
            "effect_review": projected_review,
            "effect_review_revision_count": revision,
        },
        current,
    )
    return {
        "task": reviewed_task,
        "review": projected_review,
        "revision_count": revision,
    }

def _reviewable_task(self, task_id: str, now: datetime) -> dict:
    task = next(
        (item for item in self.task_store.list_tasks() if item.get("id") == task_id),
        None,
    )
    if task is None:
        raise TaskNotFoundError(task_id)
    projected = _with_effect_review_state(task, now)
    if task.get("status") != "completed":
        raise TaskConflictError("任务完成后才能进行效果复盘")
    ready_at = _record_time(projected.get("effect_review_ready_at"))
    if ready_at is None or now < ready_at:
        raise TaskConflictError("效果数据积累中，满 7 天后再复盘")
    return projected
```

在模块级增加证据函数：

```python
def _effect_review_evidence(records: list[dict], task: Mapping[str, object]) -> dict:
    created_at = _record_time(task.get("created_at"))
    completed_at = _record_time(task.get("completed_at"))
    if created_at is None or completed_at is None:
        raise TaskValidationError("任务时间不合法")
    baseline = _window_evidence(
        records,
        task,
        start=created_at - EFFECT_REVIEW_PERIOD,
        end=created_at,
    )
    effect = _window_evidence(
        records,
        task,
        start=completed_at,
        end=completed_at + EFFECT_REVIEW_PERIOD,
    )
    delta = effect["count"] - baseline["count"]
    change_rate = (
        round(delta / baseline["count"], 4) if baseline["count"] else None
    )
    return {
        "baseline": baseline,
        "effect": effect,
        "delta": delta,
        "change_rate": change_rate,
    }


def _window_evidence(
    records: list[dict],
    task: Mapping[str, object],
    *,
    start: datetime,
    end: datetime,
) -> dict:
    record_ids = []
    for record in records:
        created_at = _record_time(record.get("created_at"))
        record_id = record.get("id")
        if (
            created_at is not None
            and start <= created_at < end
            and isinstance(record_id, str)
            and record_id.strip()
            and _record_matches_cluster(
                record,
                platform=_text(task.get("platform")),
                issue_category=_text(task.get("issue_category")),
                responsibility=_text(task.get("responsibility")),
            )
        ):
            record_ids.append(record_id)
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "record_ids": record_ids,
        "count": len(record_ids),
    }
```

- [ ] **Step 5: Run all service and storage tests**

Run:

```powershell
python -m pytest -q tests/test_tasks.py tests/test_task_storage.py
```

Expected: PASS.

- [ ] **Step 6: Commit effect review service**

```powershell
git add src/customer_issue_agent/tasks.py tests/test_tasks.py
git commit -m "feat: calculate task effect evidence"
```

---

### Task 4: Expose Effect Review APIs

**Files:**
- Modify: `tests/test_app.py`
- Modify: `src/customer_issue_agent/app.py`

- [ ] **Step 1: Write failing API tests**

在 `tests/test_app.py` 导入 `TaskStore`，并增加已完成任务构造器：

```python
from customer_issue_agent.task_storage import TaskStore


def _completed_task_event(now: datetime) -> dict:
    return {
        "id": "task-review",
        "title": "Amazon · 功能不会用或设置失败 · 客服培训",
        "created_at": (now - timedelta(days=20)).isoformat(),
        "updated_at": (now - timedelta(days=8)).isoformat(),
        "source": "summary",
        "source_range": "all",
        "platform": "Amazon",
        "issue_category": "function_use",
        "responsibility": "customer_service_training",
        "record_ids": ["baseline"],
        "record_count": 1,
        "significant_increase": False,
        "team": "customer_service_training",
        "priority": "medium",
        "due_date": (now - timedelta(days=10)).date().isoformat(),
        "status": "completed",
        "result": "已更新帮助中心",
        "completed_at": (now - timedelta(days=8)).isoformat(),
        "effect_review": None,
        "effect_review_revision_count": 0,
    }
```

新增成功测试：

```python
def test_effect_review_api_previews_submits_revises_and_filters(tmp_path):
    now = datetime.now(UTC)
    storage_path = tmp_path / "analyses.jsonl"
    task_path = tmp_path / "tasks.jsonl"
    task = _completed_task_event(now)
    _write_jsonl_records(
        storage_path,
        [
            _stored_record(
                "baseline",
                platform="Amazon",
                created_at=now - timedelta(days=21),
            ),
            _stored_record(
                "effect",
                platform="amazon",
                created_at=now - timedelta(days=2),
            ),
        ],
    )
    TaskStore(task_path).append_created(task)
    client = TestClient(
        create_app(storage_path=storage_path, task_storage_path=task_path)
    )

    preview = client.get("/api/tasks/task-review/effect-review")
    submitted = client.post(
        "/api/tasks/task-review/effect-reviews",
        json={"verdict": "effective", "note": "同类问题下降"},
    )
    revised = client.post(
        "/api/tasks/task-review/effect-reviews",
        json={"verdict": "no_clear_change", "note": "补录后修正"},
    )
    listed = client.get(
        "/api/tasks", params={"effect_review_state": "reviewed"}
    )

    assert preview.status_code == 200
    assert preview.json()["evidence"]["baseline"]["record_ids"] == ["baseline"]
    assert preview.json()["evidence"]["effect"]["record_ids"] == ["effect"]
    assert submitted.status_code == 200
    assert submitted.json()["review"]["revision"] == 1
    assert revised.json()["review"]["revision"] == 2
    assert listed.json()["effect_review_counts"]["reviewed"] == 1
    assert listed.json()["tasks"][0]["effect_review_state"] == "reviewed"
```

新增错误测试：

```python
def test_effect_review_api_maps_missing_conflict_and_validation(tmp_path):
    storage_path = tmp_path / "analyses.jsonl"
    task_path = tmp_path / "tasks.jsonl"
    now = datetime.now(UTC)
    task_store = TaskStore(task_path)
    task_store.append_created(_completed_task_event(now))
    task_store.append_created(
        {
            **_completed_task_event(now),
            "id": "task-accumulating",
            "completed_at": now.isoformat(),
        }
    )
    client = TestClient(
        create_app(storage_path=storage_path, task_storage_path=task_path)
    )

    missing = client.get("/api/tasks/missing/effect-review")
    accumulating = client.get("/api/tasks/task-accumulating/effect-review")
    invalid = client.post(
        "/api/tasks/task-review/effect-reviews",
        json={"verdict": "automatic", "note": "说明"},
    )
    invalid_filter = client.get(
        "/api/tasks", params={"effect_review_state": "late"}
    )

    assert missing.status_code == 404
    assert accumulating.status_code == 409
    assert invalid.status_code == 422
    assert invalid_filter.status_code == 422
```

- [ ] **Step 2: Run API tests and verify RED**

Run:

```powershell
python -m pytest -q tests/test_app.py -k "effect_review_api"
```

Expected: FAIL with `404` for missing endpoints or unexpected query argument handling.

- [ ] **Step 3: Implement list parameter and review endpoints**

扩展列表端点：

```python
@app.get("/api/tasks")
async def list_tasks(
    status: str = "",
    priority: str = "",
    effect_review_state: str = "",
) -> dict:
    try:
        return task_service.list_tasks(
            status=status,
            priority=priority,
            effect_review_state=effect_review_state,
        )
    except (TaskValidationError, TaskStorageError) as exc:
        _raise_task_http_error(exc)
```

在任务 PATCH 端点后增加：

```python
@app.get("/api/tasks/{task_id}/effect-review")
async def get_task_effect_review(task_id: str) -> dict:
    try:
        return task_service.get_effect_review(task_id)
    except (
        TaskValidationError,
        TaskConflictError,
        TaskNotFoundError,
        TaskStorageError,
    ) as exc:
        _raise_task_http_error(exc)

@app.post("/api/tasks/{task_id}/effect-reviews")
async def review_task_effect(task_id: str, payload: dict) -> dict:
    try:
        return task_service.review_task_effect(task_id, payload)
    except (
        TaskValidationError,
        TaskConflictError,
        TaskNotFoundError,
        TaskStorageError,
    ) as exc:
        _raise_task_http_error(exc)
```

- [ ] **Step 4: Run all API and service tests**

Run:

```powershell
python -m pytest -q tests/test_app.py tests/test_tasks.py tests/test_task_storage.py
```

Expected: PASS.

- [ ] **Step 5: Commit API support**

```powershell
git add src/customer_issue_agent/app.py tests/test_app.py
git commit -m "feat: expose task effect review api"
```

---

### Task 5: Add Review Queue Controls and Card States

**Files:**
- Modify: `src/customer_issue_agent/templates/index.html`
- Modify: `src/customer_issue_agent/static/app.js`
- Modify: `tests/test_app.py`
- Create: `tests/js/test_task_effect_review.mjs`

- [ ] **Step 1: Write failing template and URL tests**

在 `test_index_contains_task_region_and_accessible_filters` 增加：

```python
assert 'id="task-effect-review-filter"' in html
assert 'data-task-refresh' in html
assert "待复盘" in html
```

创建 `tests/js/test_task_effect_review.mjs`，写入独立、可直接运行的最小 DOM 测试夹具：

```javascript
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const appScript = readFileSync("src/customer_issue_agent/static/app.js", "utf8");

class FakeClassList {
  constructor() {
    this.values = new Set();
  }

  add(...names) {
    names.forEach((name) => this.values.add(name));
  }

  remove(...names) {
    names.forEach((name) => this.values.delete(name));
  }
}

class FakeElement {
  constructor({ value = "", textContent = "" } = {}) {
    this.value = value;
    this.textContent = textContent;
    this.innerHTML = "";
    this.hidden = false;
    this.disabled = false;
    this.dataset = {};
    this.elements = {};
    this.classList = new FakeClassList();
    this.listeners = new Map();
    this.selectors = new Map();
  }

  setSelector(selector, value) {
    this.selectors.set(selector, value);
    return this;
  }

  querySelector(selector) {
    return this.selectors.get(selector) || null;
  }

  querySelectorAll(selector) {
    return this.selectors.get(selector) || [];
  }

  addEventListener(event, callback) {
    this.listeners.set(event, callback);
  }

  scrollIntoView() {}
}

function loadApp() {
  const elements = new Map([
    ["task-content", new FakeElement()],
    ["task-status-filter", new FakeElement()],
    ["task-priority-filter", new FakeElement()],
    ["task-effect-review-filter", new FakeElement()],
    ["task-refresh", new FakeElement()],
  ]);
  const document = {
    addEventListener() {},
    getElementById(id) {
      return elements.get(id) || null;
    },
    querySelector(selector) {
      if (selector === "[data-task-refresh]") {
        return elements.get("task-refresh");
      }
      return null;
    },
    querySelectorAll() {
      return [];
    },
    createElement() {
      return new FakeElement();
    },
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
  return { context, elements };
}

function deferred() {
  let resolve;
  const promise = new Promise((done) => {
    resolve = done;
  });
  return { promise, resolve };
}
```

增加基础任务构造器：

```javascript
function completedTask(overrides = {}) {
  return {
    id: "task-review",
    title: "Amazon · 功能不会用或设置失败 · 客服培训",
    source: "summary",
    source_range: "all",
    platform: "Amazon",
    issue_category: "function_use",
    responsibility: "customer_service_training",
    record_count: 3,
    team: "customer_service_training",
    priority: "medium",
    due_date: "2026-08-10",
    status: "completed",
    result: "已更新说明",
    completed_at: "2026-08-10T08:00:00+00:00",
    effect_review: null,
    effect_review_revision_count: 0,
    effect_review_state: "ready",
    effect_review_ready_at: "2026-08-17T08:00:00+00:00",
    ...overrides,
  };
}
```

新增测试：

```javascript
test("任务查询包含复盘状态筛选", () => {
  const { context, elements } = loadApp();
  elements.get("task-status-filter").value = "completed";
  elements.get("task-effect-review-filter").value = "ready";

  assert.equal(
    context.buildTaskListUrl(),
    "/api/tasks?status=completed&effect_review_state=ready",
  );
});

test("任务列表展示待复盘数量和三种复盘状态", () => {
  const { context, elements } = loadApp();
  context.renderTasks({
    counts: { pending: 0, in_progress: 0, completed: 3 },
    effect_review_counts: { accumulating: 1, ready: 2, reviewed: 0 },
    tasks: [],
  });
  const accumulating = context.taskEffectReviewStatusHtml(completedTask({
    effect_review_state: "accumulating",
  }));
  const ready = context.taskEffectReviewStatusHtml(completedTask());
  const reviewed = context.taskEffectReviewStatusHtml(completedTask({
    effect_review_state: "reviewed",
    effect_review_revision_count: 2,
    effect_review: {
      verdict: "effective",
      note: "问题下降",
      reviewed_at: "2026-08-18T08:00:00+00:00",
    },
  }));

  assert.match(elements.get("task-content").innerHTML, /待复盘/);
  assert.match(elements.get("task-content").innerHTML, />2</);
  assert.match(accumulating, /效果数据积累中/);
  assert.match(ready, /待效果复盘/);
  assert.match(reviewed, /有效/);
  assert.match(reviewed, /修订 2 次/);
});

test("人工刷新只触发一次任务加载", () => {
  const { context, elements } = loadApp();
  let loads = 0;
  context.loadTasks = () => {
    loads += 1;
  };

  context.bindTaskFilters();
  elements.get("task-refresh").listeners.get("click")();

  assert.equal(loads, 1);
});
```

- [ ] **Step 2: Run template and Node tests and verify RED**

Run:

```powershell
python -m pytest -q tests/test_app.py::test_index_contains_task_region_and_accessible_filters
node --test tests/js/test_task_effect_review.mjs
```

Expected: FAIL because the filter, refresh control and review rendering functions do not exist.

- [ ] **Step 3: Add template controls**

在任务筛选区增加：

```html
<label for="task-effect-review-filter">复盘状态</label>
<select id="task-effect-review-filter">
  <option value="">全部复盘状态</option>
  <option value="accumulating">数据积累中</option>
  <option value="ready">待复盘</option>
  <option value="reviewed">已复盘</option>
</select>
<button
  id="task-refresh"
  class="secondary-action"
  type="button"
  data-task-refresh
>刷新任务</button>
```

- [ ] **Step 4: Extend labels, filters, metrics and card state rendering**

在 `labels` 增加：

```javascript
task_effect_review_state: {
  not_applicable: "不适用",
  accumulating: "数据积累中",
  ready: "待复盘",
  reviewed: "已复盘",
},
task_effect_verdict: {
  effective: "有效",
  no_clear_change: "无明显变化",
  worsened: "恶化",
},
```

把 `bindTaskFilters` 改为：

```javascript
function bindTaskFilters() {
  [
    "task-status-filter",
    "task-priority-filter",
    "task-effect-review-filter",
  ].forEach((id) => {
    document.getElementById(id)?.addEventListener("change", () => loadTasks());
  });
  document.querySelector("[data-task-refresh]")?.addEventListener(
    "click",
    () => loadTasks(),
  );
}
```

在 `buildTaskListUrl` 增加：

```javascript
const effectReviewState = document.getElementById(
  "task-effect-review-filter",
)?.value || "";
if (effectReviewState) {
  params.set("effect_review_state", effectReviewState);
}
```

在 `renderTasks` 的指标中增加：

```javascript
${summaryMetric("待复盘", payload.effect_review_counts?.ready ?? 0)}
```

在 `taskCardHtml` 的处理结果之后插入：

```javascript
${taskEffectReviewStatusHtml(task)}
```

增加纯渲染函数：

```javascript
function formatTaskDateTime(value) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return String(value || "暂无信息");
  }
  return parsed.toLocaleString("zh-CN", { hour12: false });
}

function taskEffectReviewStatusHtml(task) {
  if (task.status !== "completed") {
    return "";
  }
  if (task.effect_review_state === "accumulating") {
    return `
      <p class="task-review-state is-accumulating">
        <strong>效果数据积累中</strong>
        <span>${escapeHtml(formatTaskDateTime(task.effect_review_ready_at))} 后可复盘</span>
      </p>
    `;
  }
  if (task.effect_review_state === "ready") {
    return `<p class="task-review-state is-ready"><strong>待效果复盘</strong></p>`;
  }
  if (task.effect_review_state === "reviewed") {
    const review = task.effect_review || {};
    return `
      <div class="task-review-state is-reviewed">
        <strong>${escapeHtml(labelFor("task_effect_verdict", review.verdict))}</strong>
        <span>${escapeHtml(review.note || "暂无说明")}</span>
        <small>复盘时间：${escapeHtml(formatTaskDateTime(review.reviewed_at))}</small>
        <small>修订 ${escapeHtml(task.effect_review_revision_count || 1)} 次</small>
      </div>
    `;
  }
  return "";
}
```

- [ ] **Step 5: Run focused tests and verify GREEN**

Run:

```powershell
python -m pytest -q tests/test_app.py -k "task_region"
node --test tests/js/test_task_effect_review.mjs
node --test tests/js/test_task_workflow.mjs
```

Expected: PASS.

- [ ] **Step 6: Commit queue controls**

```powershell
git add src/customer_issue_agent/templates/index.html src/customer_issue_agent/static/app.js tests/test_app.py tests/js/test_task_effect_review.mjs
git commit -m "feat: show task review queue"
```

---

### Task 6: Implement Review Evidence and Submission Interaction

**Files:**
- Modify: `src/customer_issue_agent/static/app.js`
- Modify: `tests/js/test_task_effect_review.mjs`
- Modify: `tests/test_app.py`

- [ ] **Step 1: Write failing evidence rendering tests**

在 Node 测试中增加证据构造器：

```javascript
function reviewPayload(overrides = {}) {
  return {
    task_id: "task-review",
    state: "ready",
    ready_at: "2026-08-17T08:00:00+00:00",
    evidence: {
      baseline: {
        start: "2026-07-27T08:00:00+00:00",
        end: "2026-08-03T08:00:00+00:00",
        record_ids: ["before-1", "before-2"],
        count: 2,
      },
      effect: {
        start: "2026-08-10T08:00:00+00:00",
        end: "2026-08-17T08:00:00+00:00",
        record_ids: ["after-1"],
        count: 1,
      },
      delta: -1,
      change_rate: -0.5,
    },
    latest_review: null,
    revision_count: 0,
    ...overrides,
  };
}
```

新增测试：

```javascript
test("复盘面板展示两个窗口、变化方向和记录 ID", () => {
  const { context } = loadApp();
  const html = context.taskEffectReviewPanelHtml(reviewPayload());

  assert.match(html, /创建前 7 天/);
  assert.match(html, /完成后 7 天/);
  assert.match(html, /减少 1 条/);
  assert.match(html, /下降 50%/);
  assert.match(html, /before-1/);
  assert.match(html, /after-1/);
});

test("基准期为零时不显示虚假变化比例", () => {
  const { context } = loadApp();
  const payload = reviewPayload();
  payload.evidence.baseline = {
    ...payload.evidence.baseline,
    record_ids: [],
    count: 0,
  };
  payload.evidence.change_rate = null;

  const html = context.taskEffectReviewPanelHtml(payload);

  assert.match(html, /基准期 0 条/);
  assert.doesNotMatch(html, /Infinity|NaN/);
});
```

- [ ] **Step 2: Write failing request, revision and stale-response tests**

```javascript
test("提交复盘去除空白并只刷新一次任务", async () => {
  const { context } = loadApp();
  const calls = [];
  context.fetch = async (url, options) => {
    calls.push([url, JSON.parse(options.body)]);
    return {
      ok: true,
      json: async () => ({ review: { revision: 1 } }),
    };
  };
  context.loadTasks = () => calls.push(["refresh"]);
  const form = new FakeElement();
  form.elements = {
    verdict: { value: "effective" },
    note: { value: "  同类问题下降  " },
  };
  form.setSelector("button[type='submit']", new FakeElement({ textContent: "提交复盘" }));
  form.setSelector(".form-message", new FakeElement());

  const succeeded = await context.submitTaskEffectReview("task-review", form);

  assert.equal(succeeded, true);
  assert.deepEqual(calls[0], [
    "/api/tasks/task-review/effect-reviews",
    { verdict: "effective", note: "同类问题下降" },
  ]);
  assert.deepEqual(calls[1], ["refresh"]);
});

test("空复盘说明不提交且失败时保留表单", async () => {
  const { context } = loadApp();
  let fetches = 0;
  context.fetch = async () => {
    fetches += 1;
    return { ok: false, json: async () => ({ detail: "复盘冲突" }) };
  };
  context.loadTasks = () => {};
  const form = new FakeElement();
  const message = new FakeElement();
  form.elements = {
    verdict: { value: "effective" },
    note: { value: "   " },
  };
  form.setSelector("button[type='submit']", new FakeElement({ textContent: "提交复盘" }));
  form.setSelector(".form-message", message);

  await context.submitTaskEffectReview("task-review", form);
  assert.equal(fetches, 0);
  assert.match(message.textContent, /复盘说明/);

  form.elements.note.value = "保留这段输入";
  await context.submitTaskEffectReview("task-review", form);
  assert.equal(form.elements.note.value, "保留这段输入");
  assert.equal(message.textContent, "复盘冲突");
});

test("较旧证据响应不覆盖较新的复盘面板", async () => {
  const { context } = loadApp();
  const first = deferred();
  const second = deferred();
  const panel = new FakeElement();
  let count = 0;
  context.fetch = () => (++count === 1 ? first.promise : second.promise);

  const oldLoad = context.loadTaskEffectReview("old", panel);
  const newLoad = context.loadTaskEffectReview("new", panel);
  second.resolve({ ok: true, json: async () => reviewPayload({ task_id: "new" }) });
  await newLoad;
  first.resolve({ ok: true, json: async () => reviewPayload({ task_id: "old" }) });
  await oldLoad;

  assert.match(panel.innerHTML, /task-review-form/);
  assert.equal(panel.dataset.taskId, "new");
});
```

- [ ] **Step 3: Run Node tests and verify RED**

Run:

```powershell
node --test tests/js/test_task_effect_review.mjs
```

Expected: FAIL because panel, load and submit functions do not exist.

- [ ] **Step 4: Add completed-task actions and evidence rendering**

增加全局请求序号：

```javascript
let latestTaskEffectReviewRequestId = 0;
```

把 `taskActionsHtml` 的已完成分支改为：

```javascript
if (task.status === "completed") {
  if (task.effect_review_state === "accumulating") {
    return "";
  }
  const label = task.effect_review_state === "reviewed"
    ? "查看或修正复盘"
    : "开始复盘";
  return `
    <div class="task-actions">
      <button class="primary-action" type="button" data-task-effect-review>
        ${label}
      </button>
    </div>
    <p class="form-message" data-task-action-message role="alert"></p>
    <div class="task-effect-review-panel" data-task-effect-review-panel hidden></div>
  `;
}
```

增加格式和渲染函数：

```javascript
function effectWindowHtml(title, window) {
  const ids = window.record_ids || [];
  return `
    <article class="task-effect-window">
      <h4>${title}</h4>
      <p>${escapeHtml(formatTaskDateTime(window.start))} 至 ${escapeHtml(formatTaskDateTime(window.end))}</p>
      <strong>${escapeHtml(window.count)} 条</strong>
      <details>
        <summary>查看 ${escapeHtml(ids.length)} 个记录 ID</summary>
        <ul>${ids.map((id) => `<li>${escapeHtml(id)}</li>`).join("")}</ul>
      </details>
    </article>
  `;
}

function effectChangeText(evidence) {
  const delta = Number(evidence.delta || 0);
  const direction = delta < 0
    ? `减少 ${Math.abs(delta)} 条`
    : delta > 0
      ? `增加 ${delta} 条`
      : "数量持平";
  if (evidence.change_rate === null) {
    return `${direction}；基准期 0 条，无法计算变化比例`;
  }
  const percent = Math.abs(Number(evidence.change_rate) * 100);
  const rate = evidence.change_rate < 0
    ? `下降 ${percent}%`
    : evidence.change_rate > 0
      ? `上升 ${percent}%`
      : "变化 0%";
  return `${direction}；${rate}`;
}

function taskEffectReviewPanelHtml(payload) {
  const latest = payload.latest_review || {};
  return `
    <div class="task-effect-evidence">
      ${effectWindowHtml("创建前 7 天", payload.evidence.baseline)}
      ${effectWindowHtml("完成后 7 天", payload.evidence.effect)}
    </div>
    <p class="task-effect-change">${escapeHtml(effectChangeText(payload.evidence))}</p>
    <form class="task-review-form">
      <label>
        复盘结论
        <select name="verdict" required>
          ${effectVerdictOptions(latest.verdict || "effective")}
        </select>
      </label>
      <label>
        复盘说明
        <textarea name="note" rows="3" required>${escapeHtml(latest.note || "")}</textarea>
      </label>
      <button class="primary-action" type="submit">提交复盘</button>
      <p class="form-message" role="alert"></p>
    </form>
  `;
}

function effectVerdictOptions(selected) {
  return Object.entries(labels.task_effect_verdict)
    .map(([value, label]) => (
      `<option value="${value}"${value === selected ? " selected" : ""}>${escapeHtml(label)}</option>`
    ))
    .join("");
}
```

- [ ] **Step 5: Implement evidence loading, binding and submission**

在 `bindTaskActions` 的卡片循环中增加：

```javascript
card.querySelector("[data-task-effect-review]")?.addEventListener(
  "click",
  () => {
    const panel = card.querySelector("[data-task-effect-review-panel]");
    if (panel) {
      panel.hidden = false;
      loadTaskEffectReview(taskId, panel);
    }
  },
);
```

增加：

```javascript
async function loadTaskEffectReview(taskId, panel) {
  const requestId = ++latestTaskEffectReviewRequestId;
  panel.dataset.taskId = taskId;
  panel.innerHTML = '<p class="task-loading">复盘证据加载中...</p>';
  try {
    const response = await fetch(
      `/api/tasks/${encodeURIComponent(taskId)}/effect-review`,
    );
    const payload = await response.json();
    if (requestId !== latestTaskEffectReviewRequestId) {
      return;
    }
    if (!response.ok) {
      throw new Error(readError(payload));
    }
    panel.dataset.taskId = payload.task_id;
    panel.innerHTML = taskEffectReviewPanelHtml(payload);
    const form = panel.querySelector(".task-review-form");
    form?.addEventListener("submit", (event) => {
      event.preventDefault();
      submitTaskEffectReview(taskId, form);
    });
  } catch (error) {
    if (requestId === latestTaskEffectReviewRequestId) {
      panel.innerHTML = `<p class="task-error">${escapeHtml(error.message || "复盘证据读取失败")}</p>`;
    }
  }
}

async function submitTaskEffectReview(taskId, form) {
  const verdict = form.elements.verdict.value;
  const note = String(form.elements.note.value || "").trim();
  const button = form.querySelector("button[type='submit']");
  const message = form.querySelector(".form-message");
  if (!note) {
    showError(message, "请填写复盘说明后再提交。")
    return false;
  }
  const originalLabel = button?.textContent || "";
  clearError(message);
  if (button) {
    setLoading(button, true);
  }
  try {
    const response = await fetch(
      `/api/tasks/${encodeURIComponent(taskId)}/effect-reviews`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ verdict, note }),
      },
    );
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(readError(payload));
    }
    await loadTasks();
    return true;
  } catch (error) {
    showError(message, error.message || "效果复盘提交失败，请重试。")
    return false;
  } finally {
    if (button) {
      setLoading(button, false);
      button.textContent = originalLabel;
    }
  }
}
```

- [ ] **Step 6: Add static contract assertions**

在 `tests/test_app.py` 新增：

```python
def test_static_app_js_contains_task_effect_review_hooks(tmp_path):
    client = TestClient(create_app(storage_path=tmp_path / "analyses.jsonl"))

    script = client.get("/static/app.js").text

    assert "latestTaskEffectReviewRequestId" in script
    assert "loadTaskEffectReview" in script
    assert "taskEffectReviewPanelHtml" in script
    assert "submitTaskEffectReview" in script
    assert "data-task-effect-review" in script
```

- [ ] **Step 7: Run all frontend behavior tests**

Run:

```powershell
node --test tests/js/test_feedback_ui.mjs tests/js/test_issue_trends.mjs tests/js/test_task_workflow.mjs tests/js/test_task_effect_review.mjs
python -m pytest -q tests/test_app.py
node --check src/customer_issue_agent/static/app.js
```

Expected: PASS.

- [ ] **Step 8: Commit review interaction**

```powershell
git add src/customer_issue_agent/static/app.js tests/js/test_task_effect_review.mjs tests/test_app.py
git commit -m "feat: complete task effect review interaction"
```

---

### Task 7: Style Desktop and Mobile Review Layouts

**Files:**
- Modify: `tests/test_app.py`
- Modify: `src/customer_issue_agent/static/styles.css`

- [ ] **Step 1: Write failing CSS contract test**

扩展任务样式测试：

```python
assert ".task-review-state" in css
assert ".task-effect-review-panel" in css
assert ".task-effect-evidence" in css
assert ".task-effect-window" in css
assert ".task-effect-change" in css
assert ".task-review-form" in css
```

- [ ] **Step 2: Run CSS contract test and verify RED**

Run:

```powershell
python -m pytest -q tests/test_app.py::test_styles_cover_task_cards_states_overdue_and_mobile
```

Expected: FAIL because review selectors are absent.

- [ ] **Step 3: Add intentional review styling**

在现有任务样式后增加：

```css
.task-metrics {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.task-review-state {
  display: grid;
  gap: 4px;
  margin: 14px 0 0;
  padding: 12px 14px;
  border: 1px solid var(--line);
  border-radius: 14px;
  background: color-mix(in srgb, var(--paper) 88%, var(--accent) 12%);
}

.task-review-state.is-ready {
  border-color: color-mix(in srgb, var(--signal) 45%, var(--line));
}

.task-review-state.is-reviewed {
  border-color: color-mix(in srgb, var(--accent) 45%, var(--line));
}

.task-effect-review-panel {
  display: grid;
  gap: 14px;
  margin-top: 14px;
  padding-top: 14px;
  border-top: 1px solid var(--line);
}

.task-effect-review-panel[hidden] {
  display: none;
}

.task-effect-evidence {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.task-effect-window {
  padding: 14px;
  border-radius: 14px;
  background: var(--paper);
  box-shadow: inset 0 0 0 1px var(--line);
}

.task-effect-window h4,
.task-effect-window p {
  margin: 0 0 8px;
}

.task-effect-window ul {
  margin: 8px 0 0;
  padding-left: 20px;
  overflow-wrap: anywhere;
}

.task-effect-change {
  margin: 0;
  font-weight: 800;
}

.task-review-form {
  display: grid;
  grid-template-columns: minmax(150px, 0.35fr) minmax(240px, 1fr) auto;
  align-items: end;
  gap: 12px;
}

.task-review-form label {
  display: grid;
  gap: 7px;
  color: var(--muted);
  font-size: 13px;
  font-weight: 700;
}

.task-review-form .form-message {
  grid-column: 1 / -1;
}
```

在 `@media (max-width: 720px)` 中增加：

```css
.task-effect-evidence,
.task-review-form {
  grid-template-columns: 1fr;
}

.task-review-form .form-message {
  grid-column: auto;
}
```

- [ ] **Step 4: Run CSS and frontend tests**

Run:

```powershell
python -m pytest -q tests/test_app.py
node --test tests/js/test_task_effect_review.mjs tests/js/test_task_workflow.mjs
```

Expected: PASS.

- [ ] **Step 5: Commit responsive styles**

```powershell
git add src/customer_issue_agent/static/styles.css tests/test_app.py
git commit -m "style: add task effect review layout"
```

---

### Task 8: Document, Review and Verify the Complete Feature

**Files:**
- Modify: `README.md`
- Review: all files changed since `4b80e43`

- [ ] **Step 1: Write the README contract test first**

在 `tests/test_app.py` 顶部增加：

```python
from pathlib import Path
```

再增加：

```python
def test_readme_describes_task_effect_review_without_polling():
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "任务效果复盘" in readme
    assert "创建前 7 天" in readme
    assert "完成后 7 天" in readme
    assert "有效、无明显变化、恶化" in readme
    assert "不会自动轮询" in readme
```

- [ ] **Step 2: Run the README test and verify RED**

Run:

```powershell
python -m pytest -q tests/test_app.py::test_readme_describes_task_effect_review_without_polling
```

Expected: FAIL because the README does not yet describe effect review.

- [ ] **Step 3: Add the user-facing README section**

在“问题簇处理任务”后增加：

```markdown
## 任务效果复盘

已完成任务会在完成后积累 7 天效果数据。系统固定比较任务创建前 7 天与任务完成后 7 天的同一平台、问题类型和责任方记录；完成未满 7 天时显示“数据积累中”，满 7 天后进入“待复盘”。

复盘面板展示两个窗口的记录数量、记录 ID、增减条数和变化比例。运营必须结合证据人工选择“有效、无明显变化、恶化”并填写复盘说明；系统不会自动替代人工结论。复盘可以修正，每次修正都追加到 UTF-8 `tasks.jsonl` 并保留历史。

任务区提供复盘状态筛选和人工刷新按钮，不会自动轮询、自动提交复盘、调用模型或连接海外电商平台 API。
```

- [ ] **Step 4: Run the full automated verification suite**

Run:

```powershell
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
python -m pytest -q
node --test tests/js/test_feedback_ui.mjs tests/js/test_issue_trends.mjs tests/js/test_task_workflow.mjs tests/js/test_task_effect_review.mjs
node --check src/customer_issue_agent/static/app.js
git diff --check 4b80e43...HEAD
```

Expected: all pytest tests PASS, all Node tests PASS, JavaScript syntax check exits 0, and diff check exits 0.

- [ ] **Step 5: Run strict UTF-8 verification**

Run:

```powershell
$ErrorActionPreference = "Stop"
$utf8 = New-Object System.Text.UTF8Encoding($false, $true)
$files = @(git diff --name-only 4b80e43...HEAD) |
  Where-Object { $_ -match '\.(py|js|mjs|css|html|md)$' }
foreach ($file in $files) {
  $path = (Resolve-Path -LiteralPath $file).Path
  [void]$utf8.GetString([System.IO.File]::ReadAllBytes($path))
}
"UTF-8 strict decode passed: $($files.Count) files"
```

Expected: command exits 0 and reports every changed text file.

- [ ] **Step 6: Inspect desktop and mobile behavior in the real local app**

启动本地服务：

```powershell
python -m uvicorn customer_issue_agent.app:create_app --factory --app-dir src --host 127.0.0.1 --port 58627 --log-level warning
```

验收以下真实页面状态：

1. 桌面任务筛选保持单行或自然换行，不出现大片空白。
2. “待复盘”指标、复盘状态筛选和人工刷新可见。
3. 数据积累中、待复盘、已复盘都有中文文字，不只依赖颜色。
4. 复盘证据两个窗口、记录 ID、结论和备注清晰可读。
5. `390×844` 视口没有横向溢出，证据和表单改为单列。
6. 页面没有定时任务请求；只有加载、筛选、人工刷新、打开面板和提交触发请求。

验收结束后恢复视口、关闭浏览器测试标签并停止本地 uvicorn 进程。

- [ ] **Step 7: Perform a focused code review**

检查：

```powershell
git diff --stat 4b80e43...HEAD
git diff 4b80e43...HEAD -- src/customer_issue_agent/task_storage.py src/customer_issue_agent/tasks.py src/customer_issue_agent/app.py
git diff 4b80e43...HEAD -- src/customer_issue_agent/static/app.js src/customer_issue_agent/static/styles.css
git status --short
```

确认：

- 客户端不能提交证据字段。
- 窗口严格为 `[start, end)`。
- 复盘提交重新读取分析记录。
- 修订号连续递增。
- 0 条基准不会除零。
- 没有自动轮询、失败循环、模型请求或平台 API。
- 工作区没有 `data/`、临时截图或其他任务文件。

- [ ] **Step 8: Commit documentation**

```powershell
git add README.md tests/test_app.py
git commit -m "docs: explain task effect review"
```

- [ ] **Step 9: Re-run final verification after the documentation commit**

Run:

```powershell
python -m pytest -q
node --test tests/js/test_feedback_ui.mjs tests/js/test_issue_trends.mjs tests/js/test_task_workflow.mjs tests/js/test_task_effect_review.mjs
node --check src/customer_issue_agent/static/app.js
git diff --check 4b80e43...HEAD
git status --short
```

Expected: every command exits 0 and `git status --short` prints nothing.

---

## Completion Boundary

完成本计划后，分支应包含可审计的任务效果复盘闭环，但仍保持本地、单进程、人工触发。不要在同一批次加入多周期复盘、通知、登录权限、平台同步、后台队列、数据库或模型供应商逻辑。
