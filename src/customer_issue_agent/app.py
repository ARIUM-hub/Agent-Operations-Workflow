from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from customer_issue_agent.attribution import analyze_attribution
from customer_issue_agent.domain import AnalysisRequest, AnalysisResult
from customer_issue_agent.export import build_records_csv
from customer_issue_agent.ingestion import (
    ExtractedConversation,
    extract_batch_conversations,
    extract_conversation,
)
from customer_issue_agent.parser import parse_conversation
from customer_issue_agent.record_filters import filter_records
from customer_issue_agent.report import build_report
from customer_issue_agent.storage import AnalysisStorageError, AnalysisStore
from customer_issue_agent.summary import build_records_summary
from customer_issue_agent.task_storage import TaskStorageError, TaskStore
from customer_issue_agent.tasks import (
    TaskConflictError,
    TaskNotFoundError,
    TaskService,
    TaskValidationError,
)
from customer_issue_agent.trends import build_issue_trends

PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_STORAGE = Path("data") / "analyses.jsonl"


def create_app(
    storage_path: Path | None = None, task_storage_path: Path | None = None
) -> FastAPI:
    app = FastAPI(title="客户使用问题归因智能体")
    templates = Jinja2Templates(directory=str(PACKAGE_DIR / "templates"))
    static_dir = PACKAGE_DIR / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    analysis_path = storage_path or DEFAULT_STORAGE
    store = AnalysisStore(analysis_path)
    task_store = TaskStore(task_storage_path or analysis_path.with_name("tasks.jsonl"))
    task_service = TaskService(store, task_store)

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request, "index.html", {"records": store.list_records()[-10:]})

    @app.post("/api/analyze")
    async def analyze_text(
        platform: str = Form(default="Other overseas platform"),
        conversation_text: str = Form(default=""),
        store_name: str = Form(default=""),
        sku: str = Form(default=""),
        platform_product_id: str = Form(default=""),
    ) -> dict:
        request = _analysis_request(
            platform=platform,
            conversation_text=conversation_text,
            store_name=store_name,
            sku=sku,
            platform_product_id=platform_product_id,
        )
        return _run_analysis(store, request)

    @app.post("/api/analyze-file")
    async def analyze_file(
        platform: str = Form(default="Other overseas platform"),
        store_name: str = Form(default=""),
        sku: str = Form(default=""),
        platform_product_id: str = Form(default=""),
        file: UploadFile | None = None,
    ) -> dict:
        if file is None:
            raise HTTPException(status_code=422, detail="请上传客服会话文件")
        content = await file.read()
        try:
            extracted = extract_conversation(file.filename or "conversation.txt", content)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        analysis_request = _request_from_extracted(
            extracted,
            platform=platform,
            store_name=store_name,
            sku=sku,
            platform_product_id=platform_product_id,
        )
        return _run_analysis(store, analysis_request)

    @app.post("/api/analyze-batch-file")
    async def analyze_batch_file(
        platform: str = Form(default="Other overseas platform"),
        store_name: str = Form(default=""),
        sku: str = Form(default=""),
        platform_product_id: str = Form(default=""),
        file: UploadFile | None = None,
    ) -> dict:
        if file is None:
            raise HTTPException(status_code=422, detail="请上传批量客服会话文件")
        content = await file.read()
        try:
            extracted_items = extract_batch_conversations(
                file.filename or "batch.txt",
                content,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        requests = [
            _request_from_extracted(
                item,
                platform=platform,
                store_name=store_name,
                sku=sku,
                platform_product_id=platform_product_id,
            )
            for item in extracted_items
        ]
        records = [_run_analysis(store, request) for request in requests]
        return {"batch_id": str(uuid4()), "count": len(records), "records": records}

    @app.post("/api/records/{record_id}/feedback")
    async def save_feedback(
        record_id: str,
        accepted: bool = Form(default=True),
        corrected_issue_category: str = Form(default=""),
        corrected_responsibility: str = Form(default=""),
        note: str = Form(default=""),
    ) -> dict:
        try:
            feedback = store.save_feedback(
                record_id,
                {
                    "accepted": accepted,
                    "corrected_issue_category": corrected_issue_category,
                    "corrected_responsibility": corrected_responsibility,
                    "note": note,
                },
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="记录不存在或已被清理，请刷新页面后重试") from exc
        return {"record_id": record_id, "feedback": feedback}

    @app.get("/api/records/export.csv")
    async def export_records_csv(
        platform: str = "",
        platform_match: str = "",
        store_name: str = "",
        sku: str = "",
        platform_product_id: str = "",
        issue_category: str = "",
        responsibility: str = "",
        feedback_status: str = "",
        q: str = "",
        range: str = "all",
    ) -> Response:
        records = filter_records(
            store.list_records(),
            platform=platform,
            platform_match=platform_match,
            store_name=store_name,
            sku=sku,
            platform_product_id=platform_product_id,
            issue_category=issue_category,
            responsibility=responsibility,
            feedback_status=feedback_status,
            q=q,
            range=range,
        )
        return Response(
            content=build_records_csv(records),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": "attachment; filename=customer-issue-records.csv"},
        )

    @app.get("/api/records/export-count")
    async def export_records_count(
        platform: str = "",
        platform_match: str = "",
        store_name: str = "",
        sku: str = "",
        platform_product_id: str = "",
        issue_category: str = "",
        responsibility: str = "",
        feedback_status: str = "",
        q: str = "",
        range: str = "all",
    ) -> dict:
        records = filter_records(
            store.list_records(),
            platform=platform,
            platform_match=platform_match,
            store_name=store_name,
            sku=sku,
            platform_product_id=platform_product_id,
            issue_category=issue_category,
            responsibility=responsibility,
            feedback_status=feedback_status,
            q=q,
            range=range,
        )
        return {"count": len(records)}

    @app.get("/api/records/summary")
    async def records_summary(range: str = "all") -> dict:
        return build_records_summary(filter_records(store.list_records(), range=range))

    @app.get("/api/records/trends")
    async def records_trends(period: str = "7d") -> dict:
        return build_issue_trends(store.list_records(), period=period)

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
        except (
            TaskValidationError,
            TaskConflictError,
            TaskNotFoundError,
            TaskStorageError,
        ) as exc:
            _raise_task_http_error(exc)
        return JSONResponse(
            status_code=201 if created else 200,
            content={"created": created, "task": task},
        )

    @app.patch("/api/tasks/{task_id}")
    async def update_task(task_id: str, payload: dict) -> dict:
        try:
            return task_service.update_task(task_id, payload)
        except (
            TaskValidationError,
            TaskConflictError,
            TaskNotFoundError,
            TaskStorageError,
        ) as exc:
            _raise_task_http_error(exc)

    @app.get("/api/tasks/{task_id}/effect-review")
    async def get_task_effect_review(task_id: str) -> dict:
        try:
            return task_service.get_effect_review(task_id)
        except (
            TaskValidationError,
            TaskConflictError,
            TaskNotFoundError,
            AnalysisStorageError,
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
            AnalysisStorageError,
            TaskStorageError,
        ) as exc:
            _raise_task_http_error(exc)

    return app


def _raise_task_http_error(exc: Exception) -> None:
    if isinstance(exc, TaskStorageError):
        raise HTTPException(status_code=500, detail="任务数据读取失败") from exc
    if isinstance(exc, AnalysisStorageError):
        raise HTTPException(status_code=500, detail="分析记录读取失败") from exc
    if isinstance(exc, TaskNotFoundError):
        raise HTTPException(status_code=404, detail="任务不存在") from exc
    if isinstance(exc, TaskConflictError):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    raise HTTPException(status_code=422, detail=str(exc)) from exc


def _analysis_request(
    *,
    platform: str,
    conversation_text: str,
    store_name: str = "",
    sku: str = "",
    platform_product_id: str = "",
) -> AnalysisRequest:
    try:
        return AnalysisRequest(
            platform=platform,
            conversation_text=conversation_text,
            store_name=store_name,
            sku=sku,
            platform_product_id=platform_product_id,
        )
    except ValidationError as exc:
        detail = [{"loc": error["loc"], "msg": error["msg"]} for error in exc.errors()]
        raise HTTPException(status_code=422, detail=detail) from exc


def _request_from_extracted(
    extracted: ExtractedConversation,
    *,
    platform: str,
    store_name: str,
    sku: str,
    platform_product_id: str,
) -> AnalysisRequest:
    return _analysis_request(
        platform=platform,
        conversation_text=extracted.conversation_text,
        store_name=extracted.store_name or store_name,
        sku=extracted.sku or sku,
        platform_product_id=extracted.platform_product_id or platform_product_id,
    )


def _run_analysis(store: AnalysisStore, request: AnalysisRequest) -> dict:
    parsed = parse_conversation(request.platform, request.conversation_text)
    attribution = analyze_attribution(parsed)
    result = AnalysisResult(
        request=request,
        parsed=parsed,
        attribution=attribution,
        report=build_report(parsed, attribution),
    )
    record_id = store.save(result)
    return {"record_id": record_id, "analysis": result.model_dump(mode="json")}


app = create_app()
