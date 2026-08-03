from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from math import isfinite
from pathlib import Path

EFFECT_REVIEW_VERDICTS = {"effective", "no_clear_change", "worsened"}
EFFECT_REVIEW_PERIOD = timedelta(days=7)


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
                    raise TaskStorageError(
                        f"任务事件第 {line_number} 行不是合法 JSON"
                    ) from exc
                self._apply_event(tasks, order, event, line_number)
        return [deepcopy(tasks[task_id]) for task_id in order]

    def _append(self, event: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")

    @staticmethod
    def _apply_event(
        tasks: dict[str, dict], order: list[str], event: object, line_number: int
    ) -> None:
        if not isinstance(event, dict):
            raise TaskStorageError(f"任务事件第 {line_number} 行必须是对象")
        event_type = event.get("type")
        if event_type == "task_created":
            task = event.get("task")
            task_id = task.get("id") if isinstance(task, dict) else None
            if not isinstance(task_id, str) or not task_id.strip():
                raise TaskStorageError(f"任务事件第 {line_number} 行缺少任务 ID")
            if task_id in tasks:
                raise TaskStorageError(
                    f"任务事件第 {line_number} 行重复创建任务 {task_id}"
                )
            projected = deepcopy(task)
            projected.setdefault("effect_review", None)
            projected.setdefault("effect_review_revision_count", 0)
            tasks[task_id] = projected
            order.append(task_id)
            return
        if event_type == "task_updated":
            task_id = event.get("task_id")
            changes = event.get("changes")
            updated_at = event.get("updated_at")
            if not isinstance(task_id, str) or not task_id.strip():
                raise TaskStorageError(f"任务事件第 {line_number} 行缺少任务 ID")
            if task_id not in tasks:
                raise TaskStorageError(
                    f"任务事件第 {line_number} 行引用不存在任务 {task_id}"
                )
            if (
                not isinstance(changes, dict)
                or not isinstance(updated_at, str)
                or not updated_at
            ):
                raise TaskStorageError(f"任务事件第 {line_number} 行更新内容不完整")
            tasks[task_id].update(deepcopy(changes))
            tasks[task_id]["updated_at"] = updated_at
            return
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
            expected_revision = (
                tasks[task_id]["effect_review_revision_count"] + 1
            )
            revision = review.get("revision") if isinstance(review, dict) else None
            if (
                not isinstance(review, dict)
                or not isinstance(reviewed_at, str)
                or not reviewed_at
                or not isinstance(revision, int)
                or isinstance(revision, bool)
                or revision != expected_revision
                or not _valid_effect_review(review, reviewed_at)
            ):
                raise TaskStorageError(
                    f"任务事件第 {line_number} 行复盘内容不完整"
                )
            tasks[task_id]["effect_review"] = {
                **deepcopy(review),
                "reviewed_at": reviewed_at,
            }
            tasks[task_id]["effect_review_revision_count"] = expected_revision
            return
        raise TaskStorageError(f"任务事件第 {line_number} 行类型未知")


def _valid_effect_review(review: dict, reviewed_at: object) -> bool:
    if (
        review.get("verdict") not in EFFECT_REVIEW_VERDICTS
        or not isinstance(review.get("note"), str)
        or not review["note"].strip()
        or _iso_datetime(reviewed_at) is None
    ):
        return False
    baseline_count = _valid_window_count(review.get("baseline"))
    effect_count = _valid_window_count(review.get("effect"))
    if baseline_count is None or effect_count is None:
        return False
    delta = review.get("delta")
    if (
        not isinstance(delta, int)
        or isinstance(delta, bool)
        or delta != effect_count - baseline_count
    ):
        return False
    change_rate = review.get("change_rate")
    if baseline_count == 0:
        return change_rate is None
    if (
        not isinstance(change_rate, (int, float))
        or isinstance(change_rate, bool)
        or not isfinite(change_rate)
    ):
        return False
    return Decimal(str(change_rate)) == _rounded_rate(delta, baseline_count)


def _valid_window_count(value: object) -> int | None:
    if not isinstance(value, dict):
        return None
    start = _iso_datetime(value.get("start"))
    end = _iso_datetime(value.get("end"))
    record_ids = value.get("record_ids")
    count = value.get("count")
    if (
        start is None
        or end is None
        or end - start != EFFECT_REVIEW_PERIOD
        or not isinstance(record_ids, list)
        or any(
            not isinstance(record_id, str) or not record_id.strip()
            for record_id in record_ids
        )
        or not isinstance(count, int)
        or isinstance(count, bool)
        or count != len(record_ids)
    ):
        return None
    return count


def _iso_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _rounded_rate(delta: int, baseline_count: int) -> Decimal:
    return (Decimal(delta) / Decimal(baseline_count)).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )
