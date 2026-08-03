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
        source_range = (
            "7d"
            if source == "trend"
            else _enum_value(payload.get("source_range"), SOURCE_RANGES, "统计范围")
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
        team = (
            _optional_enum(payload.get("team"), Responsibility, "责任团队")
            or responsibility
        )
        suggested_priority = "high" if significant_increase else "medium"
        priority = (
            _optional_choice(payload.get("priority"), PRIORITIES, "优先级")
            or suggested_priority
        )
        due_date = _optional_due_date(payload.get("due_date")) or (
            local_today + timedelta(days=PRIORITY_DAYS[priority])
        ).isoformat()
        timestamp = current.isoformat()
        task = {
            "id": f"task-{uuid4()}",
            "title": (
                f"{platform} · {IssueCategory(issue_category).label} · "
                f"{Responsibility(responsibility).label}"
            ),
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
        counts = {
            value: sum(task.get("status") == value for task in tasks)
            for value in STATUSES
        }
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

    def update_task(
        self,
        task_id: str,
        payload: Mapping[str, object],
        *,
        now: datetime | None = None,
    ) -> dict:
        current = _as_utc(now or datetime.now(UTC))
        tasks = self.task_store.list_tasks()
        task = next((item for item in tasks if item.get("id") == task_id), None)
        if task is None:
            raise TaskNotFoundError(task_id)
        if task.get("status") == "completed":
            raise TaskConflictError("已完成任务不可编辑或重新打开")
        unknown_fields = set(payload) - UPDATE_FIELDS
        if unknown_fields:
            raise TaskValidationError(
                f"包含未知字段：{', '.join(sorted(unknown_fields))}"
            )
        if not payload:
            raise TaskValidationError("更新内容不能为空")

        changes: dict[str, object] = {}
        if "team" in payload:
            changes["team"] = _responsibility(payload.get("team"), "责任团队")
        if "priority" in payload:
            changes["priority"] = _enum_value(
                payload.get("priority"), PRIORITIES, "优先级"
            )
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
    cutoff = (
        None
        if source_range == "all"
        else now - timedelta(days=7 if source_range == "7d" else 30)
    )
    matched: list[str] = []
    for record in records:
        created_at = _record_time(record.get("created_at"))
        if (
            created_at is None
            or created_at > now
            or (cutoff is not None and created_at < cutoff)
        ):
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
    records: list[dict],
    platform: str,
    issue_category: str,
    responsibility: str,
    now: datetime,
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
        return (
            1,
            1,
            0,
            date.max.toordinal(),
            -_timestamp(task.get("completed_at")),
            str(task.get("id")),
        )
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


def _cluster_key(
    platform: str, issue_category: str, responsibility: str
) -> tuple[str, str, str]:
    return platform.strip().casefold(), issue_category.strip(), responsibility.strip()


def _issue_category(value: object) -> str:
    return _optional_enum(value, IssueCategory, "问题类型") or _raise_required(
        "问题类型"
    )


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
    except (OverflowError, TypeError, ValueError):
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
