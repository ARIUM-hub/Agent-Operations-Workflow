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
        raise TaskStorageError(f"任务事件第 {line_number} 行类型未知")
