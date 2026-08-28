# 商品维度分析实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (recommended) or superpowers:subagent-driven-development when explicitly needed for independent tasks. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为海外电商客户问题分析记录增加店铺、SKU 和平台商品 ID，并把 SKU 维度贯通到输入、筛选、导出、概览、趋势、处理任务和效果复盘。

**Architecture:** 扩展现有 `AnalysisRequest` 和 `analyses.jsonl` 记录，不建立旁路索引。文件解析层输出携带行级商品元数据的结构化会话，应用层合并表单默认值并在写入前完成整批校验；现有筛选、汇总、趋势和任务服务从同一请求结构读取商品字段。历史记录和历史任务通过空字符串默认值保持兼容。

**Tech Stack:** Python 3.13、FastAPI、Pydantic v2、openpyxl、JSONL、Jinja2、原生 JavaScript、CSS、pytest、Node.js test runner。

---

## 文件结构与职责

**新增文件：**

- `tests/js/test_product_dimension_ui.mjs`：商品输入、筛选、导出、概览、趋势和 SKU 任务前端行为。

**修改文件：**

- `src/customer_issue_agent/domain.py`：三个可选商品字段及统一校验。
- `src/customer_issue_agent/ingestion.py`：结构化文件会话、表头别名、行级商品元数据、单文件冲突检测和 Excel 标识转换。
- `src/customer_issue_agent/app.py`：表单默认值合并、整批预校验、筛选参数和 SKU 任务参数。
- `src/customer_issue_agent/record_filters.py`：店铺包含匹配、SKU 与平台商品 ID 精确匹配及搜索文本。
- `src/customer_issue_agent/export.py`：CSV 商品列。
- `src/customer_issue_agent/summary.py`：SKU 覆盖、Top SKU 和 SKU 高频问题簇。
- `src/customer_issue_agent/trends.py`：SKU 近 7 天趋势。
- `src/customer_issue_agent/tasks.py`：SKU 任务去重、快照、显著上升和效果窗口。
- `src/customer_issue_agent/templates/index.html`：三个输入表单、商品筛选、记录元数据、商品详情和任务 SKU 隐藏字段。
- `src/customer_issue_agent/static/app.js`：商品筛选、导出、概览、趋势、下钻和 SKU 任务交互。
- `src/customer_issue_agent/static/styles.css`：商品输入和洞察的桌面、移动布局。
- `README.md`：商品字段、列别名、筛选、洞察和 SKU 任务说明。
- `tests/test_domain.py`：商品字段模型校验。
- `tests/test_ingestion.py`：TXT、CSV、XLSX 商品元数据提取。
- `tests/test_app.py`：三个分析端点、筛选端点、模板和样式契约。
- `tests/test_record_filters.py`：商品筛选组合与历史数据兼容。
- `tests/test_export.py`：CSV 商品列和空值。
- `tests/test_summary.py`：SKU 聚合、覆盖与稳定排序。
- `tests/test_trends.py`：SKU 周期趋势和时间边界。
- `tests/test_tasks.py`：SKU 任务生命周期和效果复盘。
- `tests/js/test_task_workflow.mjs`：SKU 任务卡和记录下钻。
- `tests/js/test_issue_trends.mjs`：SKU 趋势与旧响应保护兼容。

## 实施约束

- 每个生产改动前先运行对应失败测试，确认失败原因是缺少该行为。
- 所有文本文件保持严格 UTF-8，中文直接保存，不使用 `\uXXXX`。
- 不新增生产依赖，不调用模型或海外平台 API。
- 不增加后台轮询、自动重试、并发任务或供应商请求。
- 每项任务单独提交，提交前运行该任务涉及的完整测试文件。

---

### Task 1：扩展商品字段领域模型

**Files:**
- Modify: `src/customer_issue_agent/domain.py:64-82`
- Test: `tests/test_domain.py`

- [ ] **Step 1：写商品字段默认值、去空格和长度失败测试**

在 `tests/test_domain.py` 增加：

```python
import pytest
from pydantic import ValidationError

from customer_issue_agent.domain import AnalysisRequest


def test_analysis_request_product_fields_are_optional_and_trimmed():
    empty = AnalysisRequest(platform="Amazon", conversation_text="Customer: broken")
    populated = AnalysisRequest(
        platform="Amazon",
        conversation_text="Customer: broken",
        store_name="  US Store  ",
        sku="  SKU-01  ",
        platform_product_id="  B0ABC123  ",
    )

    assert empty.store_name == ""
    assert empty.sku == ""
    assert empty.platform_product_id == ""
    assert populated.store_name == "US Store"
    assert populated.sku == "SKU-01"
    assert populated.platform_product_id == "B0ABC123"


@pytest.mark.parametrize("field", ["store_name", "sku", "platform_product_id"])
def test_analysis_request_rejects_overlong_product_field(field):
    payload = {
        "platform": "Amazon",
        "conversation_text": "Customer: broken",
        field: "x" * 201,
    }

    with pytest.raises(ValidationError):
        AnalysisRequest(**payload)


@pytest.mark.parametrize("value", [True, [], {}])
def test_analysis_request_rejects_non_string_sku(value):
    with pytest.raises(ValidationError):
        AnalysisRequest(
            platform="Amazon",
            conversation_text="Customer: broken",
            sku=value,
        )
```

- [ ] **Step 2：运行领域模型测试并确认失败**

Run:

```powershell
python -m pytest -q tests/test_domain.py
```

Expected: 新测试因 `AnalysisRequest` 不接受商品字段或缺少属性而失败。

- [ ] **Step 3：实现可选商品字段和严格校验**

在 `AnalysisRequest` 中加入字段并使用独立校验器，保留现有必填字段行为：

```python
class AnalysisRequest(BaseModel):
    platform: str = Field(default="Unknown")
    conversation_text: str
    store_name: str = Field(default="", max_length=200)
    sku: str = Field(default="", max_length=200)
    platform_product_id: str = Field(default="", max_length=200)

    @field_validator("platform", "conversation_text")
    @classmethod
    def trim_required_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("字段不能为空")
        return stripped

    @field_validator("store_name", "sku", "platform_product_id", mode="before")
    @classmethod
    def trim_optional_product_text(cls, value: object) -> str:
        if value is None:
            return ""
        if not isinstance(value, str):
            raise ValueError("商品字段必须是字符串")
        return value.strip()
```

- [ ] **Step 4：运行领域模型测试并确认通过**

Run:

```powershell
python -m pytest -q tests/test_domain.py
```

Expected: `tests/test_domain.py` 全部通过。

- [ ] **Step 5：提交领域模型**

```powershell
git add src/customer_issue_agent/domain.py tests/test_domain.py
git commit -m "feat: add product metadata fields"
```

---

### Task 2：结构化提取文件商品元数据

**Files:**
- Modify: `src/customer_issue_agent/ingestion.py`
- Test: `tests/test_ingestion.py`

- [ ] **Step 1：写 TXT 默认空元数据和批量 CSV 行级提取失败测试**

在 `tests/test_ingestion.py` 增加：

```python
from customer_issue_agent.ingestion import (
    ExtractedConversation,
    extract_batch_conversations,
    extract_conversation,
)


def test_txt_conversation_has_empty_file_product_metadata():
    extracted = extract_conversation("conversation.txt", b"Customer: broken")

    assert extracted == ExtractedConversation(conversation_text="Customer: broken")


def test_batch_csv_extracts_fixed_priority_product_aliases():
    content = (
        "conversation,store,shop,sku,seller_sku,product_id,asin\n"
        "Customer: broken,Store A,Ignored Shop,SKU-01,Ignored SKU,P-01,B0IGNORED\n"
    ).encode("utf-8")

    extracted = extract_batch_conversations("batch.csv", content)

    assert extracted == [
        ExtractedConversation(
            conversation_text="Customer: broken",
            store_name="Store A",
            sku="SKU-01",
            platform_product_id="P-01",
        )
    ]
```

- [ ] **Step 2：写普通表格一致元数据和冲突元数据失败测试**

继续增加：

```python
import pytest


def test_single_csv_accepts_repeated_product_metadata():
    content = (
        "speaker,message,sku,asin\n"
        "Customer,It is broken,SKU-01,B0ABC\n"
        "Agent,Please restart,sku-01,b0abc\n"
    ).encode("utf-8")

    extracted = extract_conversation("conversation.csv", content)

    assert extracted.conversation_text == "Customer: It is broken\nAgent: Please restart"
    assert extracted.sku == "SKU-01"
    assert extracted.platform_product_id == "B0ABC"


def test_single_csv_rejects_conflicting_skus():
    content = (
        "speaker,message,sku\n"
        "Customer,First issue,SKU-01\n"
        "Agent,Second row,SKU-02\n"
    ).encode("utf-8")

    with pytest.raises(ValueError, match="多个 SKU"):
        extract_conversation("conversation.csv", content)
```

- [ ] **Step 3：写 Excel 标识转换失败测试**

使用现有 workbook 测试辅助方式增加：

```python
from datetime import date
from io import BytesIO

from openpyxl import Workbook


def _workbook_bytes(rows):
    workbook = Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(row)
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def test_batch_xlsx_converts_numeric_product_ids_without_dot_zero():
    content = _workbook_bytes([
        ["conversation", "sku", "product_id"],
        ["Customer: broken", 1001, 12345.0],
    ])

    extracted = extract_batch_conversations("batch.xlsx", content)

    assert extracted[0].sku == "1001"
    assert extracted[0].platform_product_id == "12345"


@pytest.mark.parametrize("invalid", [True, date(2026, 8, 4)])
def test_batch_xlsx_rejects_boolean_and_date_product_ids(invalid):
    content = _workbook_bytes([
        ["conversation", "sku"],
        ["Customer: broken", invalid],
    ])

    with pytest.raises(ValueError, match="商品标识"):
        extract_batch_conversations("batch.xlsx", content)
```

- [ ] **Step 4：运行 ingestion 测试并确认失败**

Run:

```powershell
python -m pytest -q tests/test_ingestion.py
```

Expected: 因结构化提取类型和新函数尚不存在而失败。

- [ ] **Step 5：实现结构化会话和固定别名**

在 `ingestion.py` 顶部增加：

```python
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal


STORE_KEYS = ("store_name", "store", "shop_name", "shop", "店铺名称", "店铺")
SKU_KEYS = ("sku", "seller_sku", "merchant_sku", "product_sku", "商品sku", "商品 sku")
PRODUCT_ID_KEYS = (
    "platform_product_id",
    "product_id",
    "asin",
    "item_id",
    "listing_id",
    "商品id",
    "商品 id",
)


@dataclass(frozen=True)
class ExtractedConversation:
    conversation_text: str
    store_name: str = ""
    sku: str = ""
    platform_product_id: str = ""
```

实现固定优先级读取和 Excel 单元格转换：

```python
def _metadata_from_mapping(row: dict[str, object]) -> dict[str, str]:
    normalized = {
        str(key).strip().casefold(): value
        for key, value in row.items()
        if key is not None
    }
    return {
        "store_name": _first_identifier(normalized, STORE_KEYS),
        "sku": _first_identifier(normalized, SKU_KEYS),
        "platform_product_id": _first_identifier(normalized, PRODUCT_ID_KEYS),
    }


def _first_identifier(row: dict[str, object], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = row.get(key.casefold())
        if value is None or value == "":
            continue
        return _identifier_text(value)
    return ""


def _identifier_text(value: object) -> str:
    if isinstance(value, bool) or isinstance(value, (date, datetime)):
        raise ValueError("商品标识必须是文本或数字")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("商品标识必须是有限数字")
        if value.is_integer():
            return str(int(value))
        return format(Decimal(str(value)), "f").rstrip("0").rstrip(".")
    if not isinstance(value, str):
        raise ValueError("商品标识必须是文本或数字")
    return value.strip()
```

同时增加 `import math`。

- [ ] **Step 6：实现单文件和批量文件结构化返回**

保留现有解码和会话文本逻辑，把公开入口改成：

```python
def extract_conversation(filename: str, content: bytes) -> ExtractedConversation:
    suffix = Path(filename).suffix.lower()
    if suffix in {".txt", ".log"}:
        extracted = ExtractedConversation(conversation_text=_decode_text(content))
    elif suffix == ".csv":
        extracted = _extract_single_csv(content)
    elif suffix in {".xlsx", ".xlsm"}:
        extracted = _extract_single_xlsx(content)
    else:
        raise ValueError("仅支持 txt、log、csv、xlsx 或 xlsm 文件")
    return _clean_extracted(extracted, "没有可分析内容")


def extract_batch_conversations(
    filename: str,
    content: bytes,
    limit: int = BATCH_LIMIT,
) -> list[ExtractedConversation]:
    suffix = Path(filename).suffix.lower()
    if suffix in {".txt", ".log"}:
        items = [ExtractedConversation(conversation_text=value) for value in _split_batch_text(_decode_text(content))]
    elif suffix == ".csv":
        items = _extract_batch_csv_rows(content)
    elif suffix in {".xlsx", ".xlsm"}:
        items = _extract_batch_xlsx_rows(content)
    else:
        raise ValueError("仅支持 txt、log、csv、xlsx 或 xlsm 文件")
    cleaned = [
        _clean_extracted(item, "文件中没有可分析会话，请检查导出内容")
        for item in items
        if item.conversation_text and item.conversation_text.strip()
    ]
    if not cleaned:
        raise ValueError("文件中没有可分析会话，请检查导出内容")
    if len(cleaned) > limit:
        raise ValueError(f"单次最多分析 {limit} 条，请拆分文件后重试")
    return cleaned
```

单文件元数据合并使用完整函数：

```python
def _consistent_metadata(rows: list[dict[str, object]]) -> dict[str, str]:
    metadata_rows = [_metadata_from_mapping(row) for row in rows]
    result = {"store_name": "", "sku": "", "platform_product_id": ""}
    labels = {"store_name": "店铺", "sku": "SKU", "platform_product_id": "平台商品 ID"}
    for field, label in labels.items():
        values = [row[field] for row in metadata_rows if row[field]]
        normalized = {value.casefold() for value in values}
        if len(normalized) > 1:
            raise ValueError(f"单条文件包含多个 {label}，请改用批量上传")
        if values:
            result[field] = values[0]
    return result
```

补齐公开入口引用的内部函数：

```python
def _clean_extracted(item: ExtractedConversation, empty_message: str) -> ExtractedConversation:
    conversation_text = item.conversation_text.strip()
    if not conversation_text:
        raise ValueError(empty_message)
    return ExtractedConversation(
        conversation_text=conversation_text,
        store_name=item.store_name.strip(),
        sku=item.sku.strip(),
        platform_product_id=item.platform_product_id.strip(),
    )


def _csv_mapping_rows(content: bytes) -> tuple[str, list[dict[str, object]]]:
    decoded = _decode_text(content)
    rows = [dict(row) for row in csv.DictReader(StringIO(decoded))]
    return decoded, rows


def _xlsx_mapping_rows(content: bytes) -> list[dict[str, object]]:
    workbook = load_workbook(BytesIO(content), read_only=True, data_only=True)
    sheet = workbook.active
    values = list(sheet.iter_rows(values_only=True))
    if not values:
        return []
    headers = ["" if value is None else str(value).strip() for value in values[0]]
    return [
        {
            headers[index]: value
            for index, value in enumerate(row)
            if index < len(headers) and headers[index]
        }
        for row in values[1:]
    ]


def _conversation_value(row: dict[str, object]) -> str:
    normalized = {
        str(key).strip().casefold(): value
        for key, value in row.items()
        if key is not None
    }
    for key in BATCH_TEXT_KEYS:
        value = normalized.get(key.casefold())
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _extract_single_csv(content: bytes) -> ExtractedConversation:
    _, rows = _csv_mapping_rows(content)
    metadata = _consistent_metadata(rows)
    return ExtractedConversation(
        conversation_text=_extract_csv(content),
        **metadata,
    )


def _extract_single_xlsx(content: bytes) -> ExtractedConversation:
    rows = _xlsx_mapping_rows(content)
    metadata = _consistent_metadata(rows)
    return ExtractedConversation(
        conversation_text=_extract_xlsx(content),
        **metadata,
    )


def _extract_batch_csv_rows(content: bytes) -> list[ExtractedConversation]:
    decoded, rows = _csv_mapping_rows(content)
    extracted = [
        ExtractedConversation(
            conversation_text=_conversation_value(row),
            **_metadata_from_mapping(row),
        )
        for row in rows
        if _conversation_value(row)
    ]
    if extracted:
        return extracted
    return [ExtractedConversation(conversation_text=value) for value in _split_batch_text(decoded)]


def _extract_batch_xlsx_rows(content: bytes) -> list[ExtractedConversation]:
    rows = _xlsx_mapping_rows(content)
    return [
        ExtractedConversation(
            conversation_text=_conversation_value(row),
            **_metadata_from_mapping(row),
        )
        for row in rows
        if _conversation_value(row)
    ]
```

更新 `tests/test_ingestion.py` 的现有测试入口：

```python
single = extract_conversation(filename="chat.txt", content=content)
assert single.conversation_text == expected_text

batch = extract_batch_conversations(filename="batch.txt", content=content)
assert [item.conversation_text for item in batch] == expected_texts
```

删除旧的 `extract_conversation_text`、`extract_batch_conversation_texts` 导入和调用，避免同时维护两套公开入口。

- [ ] **Step 7：运行 ingestion 测试并确认通过**

Run:

```powershell
python -m pytest -q tests/test_ingestion.py
```

Expected: `tests/test_ingestion.py` 全部通过。

- [ ] **Step 8：提交文件提取层**

```powershell
git add src/customer_issue_agent/ingestion.py tests/test_ingestion.py
git commit -m "feat: extract product metadata from uploads"
```

---

### Task 3：贯通分析 API 和整批预校验

**Files:**
- Modify: `src/customer_issue_agent/app.py:10-88,273-291`
- Test: `tests/test_app.py`

- [ ] **Step 1：写单条表单与文件覆盖失败测试**

在 `tests/test_app.py` 增加：

```python
def test_analyze_endpoint_saves_trimmed_product_metadata(tmp_path):
    client = TestClient(create_app(storage_path=tmp_path / "analyses.jsonl"))

    response = client.post(
        "/api/analyze",
        data={
            "platform": "Amazon",
            "conversation_text": "Customer: it is broken",
            "store_name": "  US Store  ",
            "sku": "  SKU-01  ",
            "platform_product_id": "  B0ABC  ",
        },
    )

    assert response.status_code == 200
    request = response.json()["analysis"]["request"]
    assert request["store_name"] == "US Store"
    assert request["sku"] == "SKU-01"
    assert request["platform_product_id"] == "B0ABC"


def test_analyze_file_uses_file_metadata_before_form_defaults(tmp_path):
    client = TestClient(create_app(storage_path=tmp_path / "analyses.jsonl"))
    content = b"speaker,message,sku,asin\nCustomer,it is broken,FILE-SKU,B0FILE\n"

    response = client.post(
        "/api/analyze-file",
        data={"platform": "Amazon", "sku": "FORM-SKU", "platform_product_id": "FORM-ID"},
        files={"file": ("conversation.csv", content, "text/csv")},
    )

    assert response.status_code == 200
    request = response.json()["analysis"]["request"]
    assert request["sku"] == "FILE-SKU"
    assert request["platform_product_id"] == "B0FILE"
```

- [ ] **Step 2：写批量行级覆盖和预校验无部分写入失败测试**

继续增加：

```python
def test_batch_endpoint_uses_row_product_metadata_and_form_fallback(tmp_path):
    storage_path = tmp_path / "analyses.jsonl"
    client = TestClient(create_app(storage_path=storage_path))
    content = (
        "conversation,sku,store\n"
        "Customer: first broken,ROW-SKU,Row Store\n"
        "Customer: second broken,,\n"
    ).encode("utf-8")

    response = client.post(
        "/api/analyze-batch-file",
        data={"platform": "Amazon", "sku": "DEFAULT-SKU", "store_name": "Default Store"},
        files={"file": ("batch.csv", content, "text/csv")},
    )

    assert response.status_code == 200
    requests = [item["analysis"]["request"] for item in response.json()["records"]]
    assert requests[0]["sku"] == "ROW-SKU"
    assert requests[0]["store_name"] == "Row Store"
    assert requests[1]["sku"] == "DEFAULT-SKU"
    assert requests[1]["store_name"] == "Default Store"


def test_batch_endpoint_validates_all_product_fields_before_writing(tmp_path):
    storage_path = tmp_path / "analyses.jsonl"
    client = TestClient(create_app(storage_path=storage_path))
    content = (
        "conversation,sku\n"
        "Customer: valid,SKU-01\n"
        f"Customer: invalid,{'x' * 201}\n"
    ).encode("utf-8")

    response = client.post(
        "/api/analyze-batch-file",
        data={"platform": "Amazon"},
        files={"file": ("batch.csv", content, "text/csv")},
    )

    assert response.status_code == 422
    assert not storage_path.exists()
```

- [ ] **Step 3：运行 API 定向测试并确认失败**

Run:

```powershell
python -m pytest -q tests/test_app.py -k "product_metadata or validates_all_product"
```

Expected: 新商品参数未传递、旧 ingestion 入口已变化或批量出现部分写入，测试失败。

- [ ] **Step 4：实现默认值合并与请求预构造**

在 `app.py` 导入 `ExtractedConversation`、`extract_conversation`、`extract_batch_conversations`，增加：

```python
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
```

- [ ] **Step 5：更新三个端点和分析执行函数**

三个端点都声明相同可选 Form 参数。批量端点先构建全部 `AnalysisRequest`，再保存：

```python
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
```

把 `_run_analysis` 改为：

```python
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
```

- [ ] **Step 6：运行 API 和现有分析测试**

Run:

```powershell
python -m pytest -q tests/test_app.py tests/test_ingestion.py
```

Expected: 两个测试文件全部通过，批量非法元数据不产生文件。

- [ ] **Step 7：提交 API 贯通**

```powershell
git add src/customer_issue_agent/app.py tests/test_app.py
git commit -m "feat: carry product metadata through analysis APIs"
```

---

### Task 4：增加商品筛选、搜索和 CSV 导出

**Files:**
- Modify: `src/customer_issue_agent/record_filters.py`
- Modify: `src/customer_issue_agent/export.py`
- Modify: `src/customer_issue_agent/app.py:113-159`
- Test: `tests/test_record_filters.py`
- Test: `tests/test_export.py`
- Test: `tests/test_app.py`

- [ ] **Step 1：写店铺包含、SKU 精确和平台商品 ID 精确失败测试**

先扩展 `tests/test_record_filters.py` 的记录辅助函数：

```python
def _record(
    record_id: str,
    *,
    platform: str = "Amazon",
    store_name: str = "",
    sku: str = "",
    platform_product_id: str = "",
    issue_category: str = "function_use",
    responsibility: str = "customer_service_training",
    evidence_strength: str = "likely",
    report: str = "客户反馈无法连接，客服需要补问设备型号。",
    feedback: dict | None = None,
) -> dict:
    return {
        "id": record_id,
        "analysis": {
            "request": {
                "platform": platform,
                "store_name": store_name,
                "sku": sku,
                "platform_product_id": platform_product_id,
            },
            "attribution": {
                "customer_problem": report,
                "issue_category": issue_category,
                "primary_responsibility": responsibility,
                "evidence_strength": evidence_strength,
                "recommended_actions": ["补问设备型号"],
                "missing_information": ["错误提示截图"],
            },
            "report": report,
        },
        "feedback": feedback,
    }
```

再增加：

```python
def test_product_filters_use_store_contains_and_exact_identifiers():
    records = [
        _record("one", platform="Amazon", store_name="US Flagship", sku="SKU-1", platform_product_id="B001"),
        _record("two", platform="Amazon", store_name="EU Outlet", sku="SKU-10", platform_product_id="B0010"),
        _record("legacy", platform="Amazon"),
    ]

    assert [item["id"] for item in filter_records(records, store_name="flag")] == ["one"]
    assert [item["id"] for item in filter_records(records, sku="sku-1")] == ["one"]
    assert [item["id"] for item in filter_records(records, platform_product_id="b001")] == ["one"]
    assert filter_records(records, sku="SKU") == []


def test_product_metadata_is_in_keyword_search():
    record = _record(
        "one",
        platform="Amazon",
        store_name="US Flagship",
        sku="SKU-1",
        platform_product_id="B001",
    )

    assert filter_records([record], q="flagship") == [record]
    assert filter_records([record], q="sku-1") == [record]
    assert filter_records([record], q="b001") == [record]
```

- [ ] **Step 2：写 CSV 商品列失败测试**

在 `tests/test_export.py` 增加完整记录辅助函数：

```python
def _product_record(
    *,
    store_name: str = "",
    sku: str = "",
    platform_product_id: str = "",
) -> dict:
    return {
        "id": "record-product",
        "created_at": "2026-08-04T00:00:00+00:00",
        "analysis": {
            "request": {
                "platform": "Amazon",
                "store_name": store_name,
                "sku": sku,
                "platform_product_id": platform_product_id,
            },
            "attribution": {
                "customer_problem": "连接失败",
                "issue_category": "function_use",
                "root_causes": ["unclear_instructions"],
                "primary_responsibility": "customer_service_training",
                "evidence_strength": "likely",
                "recommended_actions": ["补问设备型号"],
                "missing_information": ["设备型号"],
            },
        },
        "feedback": None,
    }
```

再增加：

```python
def test_records_csv_exports_product_metadata_after_platform():
    record = _product_record(
        store_name="美国旗舰店",
        sku="SKU-01",
        platform_product_id="B0ABC",
    )

    decoded = build_records_csv([record]).decode("utf-8-sig")
    rows = list(csv.DictReader(StringIO(decoded)))

    platform_index = list(rows[0]).index("平台")
    assert list(rows[0])[platform_index:platform_index + 4] == ["平台", "店铺", "SKU", "平台商品 ID"]
    assert rows[0]["店铺"] == "美国旗舰店"
    assert rows[0]["SKU"] == "SKU-01"
    assert rows[0]["平台商品 ID"] == "B0ABC"


def test_records_csv_leaves_legacy_product_fields_empty():
    rows = list(csv.DictReader(StringIO(build_records_csv([_product_record()]).decode("utf-8-sig"))))

    assert rows[0]["店铺"] == ""
    assert rows[0]["SKU"] == ""
    assert rows[0]["平台商品 ID"] == ""
```

- [ ] **Step 3：运行筛选和导出测试并确认失败**

Run:

```powershell
python -m pytest -q tests/test_record_filters.py tests/test_export.py
```

Expected: 新参数或 CSV 列不存在，测试失败。

- [ ] **Step 4：实现后端商品筛选**

扩展 `filter_records()` 参数和内部 filters 字典，并在 `_matches()` 中读取 `analysis.request`：

```python
record_store = _clean(request.get("store_name"))
record_sku = _clean(request.get("sku"))
record_product_id = _clean(request.get("platform_product_id"))
if filters["store_name"] and filters["store_name"] not in record_store:
    return False
if filters["sku"] and filters["sku"] != record_sku:
    return False
if filters["platform_product_id"] and filters["platform_product_id"] != record_product_id:
    return False
```

把三个字段加入 `_search_text()` 的扁平文本来源：

```python
request.get("store_name"),
request.get("sku"),
request.get("platform_product_id"),
```

- [ ] **Step 5：实现 CSV 列和 API 查询参数**

在 `export.py` 的 `CSV_HEADERS` 中把以下列放在平台后：

```python
"店铺",
"SKU",
"平台商品 ID",
```

在 `_record_to_row()` 返回：

```python
"店铺": _text(request.get("store_name")),
"SKU": _text(request.get("sku")),
"平台商品 ID": _text(request.get("platform_product_id")),
```

`export_records_csv()` 和 `export_records_count()` 声明并传递三个新查询参数。

- [ ] **Step 6：写端点筛选口径一致测试**

先扩展 `tests/test_app.py` 的 `_stored_record()` 参数：

```python
def _stored_record(
    record_id: str,
    *,
    platform: str,
    created_at: datetime,
    issue_category: str = "function_use",
    store_name: str = "",
    sku: str = "",
    platform_product_id: str = "",
) -> dict:
```

把 request 改为：

```python
"request": {
    "platform": platform,
    "conversation_text": "Customer: not working",
    "store_name": store_name,
    "sku": sku,
    "platform_product_id": platform_product_id,
},
```

再增加完整端点测试：

```python
def test_product_filters_match_export_and_count_endpoints(tmp_path):
    storage_path = tmp_path / "analyses.jsonl"
    now = datetime.now(UTC)
    _write_jsonl_records(storage_path, [
        _stored_record(
            "one",
            platform="Amazon",
            created_at=now,
            store_name="US Flagship",
            sku="SKU-1",
            platform_product_id="B001",
        ),
        _stored_record(
            "ten",
            platform="Amazon",
            created_at=now,
            store_name="US Flagship",
            sku="SKU-10",
            platform_product_id="B0010",
        ),
    ])
    client = TestClient(create_app(storage_path=storage_path))
    params = {"store_name": "flag", "sku": "sku-1", "platform_product_id": "b001"}

    csv_response = client.get("/api/records/export.csv", params=params)
    count_response = client.get("/api/records/export-count", params=params)

    assert csv_response.status_code == 200
    assert count_response.json() == {"count": 1}
    assert "SKU-1" in csv_response.content.decode("utf-8-sig")
    assert "SKU-10" not in csv_response.content.decode("utf-8-sig")
```

- [ ] **Step 7：运行筛选、导出和端点测试**

Run:

```powershell
python -m pytest -q tests/test_record_filters.py tests/test_export.py tests/test_app.py
```

Expected: 三个测试文件全部通过。

- [ ] **Step 8：提交筛选和导出**

```powershell
git add src/customer_issue_agent/record_filters.py src/customer_issue_agent/export.py src/customer_issue_agent/app.py tests/test_record_filters.py tests/test_export.py tests/test_app.py
git commit -m "feat: filter and export product dimensions"
```

---

### Task 5：构建 SKU 覆盖、Top SKU 和高频问题簇

**Files:**
- Modify: `src/customer_issue_agent/summary.py`
- Test: `tests/test_summary.py`

- [ ] **Step 1：写覆盖率、跨平台 Top SKU 和历史空值失败测试**

先扩展 `tests/test_summary.py` 的记录辅助函数，在 `platform` 后增加 `sku: object = ""`，并把 request 改为：

```python
"request": {"platform": platform, "sku": sku},
```

再增加：

```python
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
```

- [ ] **Step 2：写 SKU 高频问题 Top 5 和稳定排序失败测试**

继续增加：

```python
def test_summary_ranks_sku_issue_clusters_by_platform_and_sku():
    records = [
        _record(
            platform="Amazon",
            sku="SKU-01",
            issue_category="function_use",
            responsibility="customer_service_training",
        )
        for index in range(3)
    ]
    records.extend([
        _record(
            platform="TikTok Shop",
            sku="sku-01",
            issue_category="product_fault",
            responsibility="supply_chain_quality",
        ),
        _record(platform="Amazon"),
    ])

    clusters = build_records_summary(records)["top_sku_issue_clusters"]

    assert clusters[0] == {
        "platform": "Amazon",
        "sku": "SKU-01",
        "issue_category": "function_use",
        "responsibility": "customer_service_training",
        "count": 3,
    }
    assert all(item["sku"] != "unknown" for item in clusters)
```

- [ ] **Step 3：运行 summary 测试并确认失败**

Run:

```powershell
python -m pytest -q tests/test_summary.py
```

Expected: 新响应键不存在，测试失败。

- [ ] **Step 4：实现 SKU 聚合结构**

在 `summary.py` 增加类型和聚合容器：

```python
SkuIssueClusterKey = tuple[str, str, str, str]

sku_display: dict[str, str] = {}
sku_counts: Counter[str] = Counter()
sku_platforms: dict[str, dict[str, str]] = {}
sku_issue_clusters: Counter[SkuIssueClusterKey] = Counter()
sku_issue_display: dict[SkuIssueClusterKey, str] = {}
sku_issue_platform_display: dict[SkuIssueClusterKey, str] = {}
missing_sku = 0
```

在记录循环中使用完整逻辑：

```python
sku = _optional_value(request.get("sku"))
if not sku:
    missing_sku += 1
else:
    sku_key = sku.casefold()
    sku_display.setdefault(sku_key, sku)
    sku_counts[sku_key] += 1
    sku_platforms.setdefault(sku_key, {}).setdefault(platform.casefold(), platform)
    cluster_key = (platform.casefold(), sku_key, issue_category, responsibility)
    sku_issue_clusters[cluster_key] += 1
    sku_issue_display.setdefault(cluster_key, sku)
    sku_issue_platform_display.setdefault(cluster_key, platform)
```

增加：

```python
def _optional_value(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()
```

- [ ] **Step 5：实现确定性响应构造**

增加完整 helper：

```python
def _rank_skus(
    counts: Counter[str],
    display: dict[str, str],
    platforms: dict[str, dict[str, str]],
) -> list[dict[str, object]]:
    return [
        {
            "sku": display[key],
            "count": count,
            "platform_count": len(platforms[key]),
            "platforms": [
                value
                for _, value in sorted(platforms[key].items(), key=lambda item: (item[0], item[1]))
            ],
        }
        for key, count in sorted(counts.items(), key=lambda item: (-item[1], item[0], display[item[0]]))
    ]
```

`build_records_summary()` 返回新增字段：

```python
"product_coverage": {
    "with_sku": sum(sku_counts.values()),
    "missing_sku": missing_sku,
},
"top_skus": _rank_skus(sku_counts, sku_display, sku_platforms),
"top_sku_issue_clusters": _rank_sku_issue_clusters(
    sku_issue_clusters,
    sku_issue_display,
    sku_issue_platform_display,
),
```

实现完整 SKU 问题簇排序函数：

```python
def _rank_sku_issue_clusters(
    counter: Counter[SkuIssueClusterKey],
    sku_display: dict[SkuIssueClusterKey, str],
    platform_display: dict[SkuIssueClusterKey, str],
    limit: int = 5,
) -> list[dict[str, int | str]]:
    ranked = sorted(
        counter.items(),
        key=lambda item: (
            -item[1],
            item[0][0],
            item[0][1],
            item[0][2].casefold(),
            item[0][2],
            item[0][3].casefold(),
            item[0][3],
        ),
    )[:limit]
    return [
        {
            "platform": platform_display[key],
            "sku": sku_display[key],
            "issue_category": key[2],
            "responsibility": key[3],
            "count": count,
        }
        for key, count in ranked
    ]
```

- [ ] **Step 6：运行 summary 与 API summary 测试**

Run:

```powershell
python -m pytest -q tests/test_summary.py tests/test_app.py -k "summary"
```

Expected: summary 相关测试全部通过，原响应字段不变。

- [ ] **Step 7：提交商品概览后端**

```powershell
git add src/customer_issue_agent/summary.py tests/test_summary.py
git commit -m "feat: summarize sku dimensions"
```

---

### Task 6：计算 SKU 近 7 天趋势

**Files:**
- Modify: `src/customer_issue_agent/trends.py`
- Test: `tests/test_trends.py`

- [ ] **Step 1：写 SKU 趋势周期、阈值和无 SKU 排除失败测试**

先扩展 `tests/test_trends.py` 的 `_record()`，增加 `sku: object = ""` 参数，并把 request 改为：

```python
"request": {"platform": platform, "sku": sku},
```

再增加：

```python
def test_issue_trends_include_sku_clusters_with_existing_thresholds():
    now = datetime(2026, 8, 4, 12, tzinfo=UTC)
    records = [
        _record(
            now - timedelta(days=index + 1),
            platform="Amazon",
            sku="SKU-01" if index != 1 else "sku-01",
            issue_category="function_use",
            responsibility="customer_service_training",
        )
        for index in range(3)
    ]
    records.extend([
        _record(
            now - timedelta(days=8),
            platform="Amazon",
            sku="SKU-01",
            issue_category="function_use",
            responsibility="customer_service_training",
        ),
        _record(
            now - timedelta(days=1),
            platform="Amazon",
            sku="",
            issue_category="function_use",
            responsibility="customer_service_training",
        ),
    ])

    trends = build_issue_trends(records, now=now)

    assert trends["sku_clusters"] == [{
        "platform": "Amazon",
        "sku": "SKU-01",
        "issue_category": "function_use",
        "responsibility": "customer_service_training",
        "current_count": 3,
        "previous_count": 1,
        "delta": 2,
        "significant_increase": True,
    }]
    assert trends["current_period"]["total_records"] == 4
```

- [ ] **Step 2：写未来、非法日期与稳定排序失败测试**

增加完整稳定排序测试：

```python
def test_sku_trends_skip_future_invalid_dates_and_sort_stably():
    now = datetime(2026, 8, 4, 12, tzinfo=UTC)
    records = [
        _record(
            now - timedelta(days=1),
            platform="Amazon",
            sku=sku,
            issue_category="function_use",
            responsibility="customer_service_training",
        )
        for sku in ("SKU-06", "SKU-02", "SKU-05", "SKU-01", "SKU-04", "SKU-03")
    ]
    records.extend([
        _record(now + timedelta(seconds=1), platform="Amazon", sku="FUTURE"),
        _record("not-a-date", platform="Amazon", sku="INVALID"),
    ])

    sku_clusters = build_issue_trends(records, now=now)["sku_clusters"]

    assert all(item["sku"] not in {"FUTURE", "INVALID"} for item in sku_clusters)
    assert [item["sku"] for item in sku_clusters] == [
        "SKU-01",
        "SKU-02",
        "SKU-03",
        "SKU-04",
        "SKU-05",
        "SKU-06",
    ]
```

测试数据必须让 `SKU-01` 与 `SKU-02` 的绝对增量和当前数量相同，以验证平台、SKU 字典序打破平局。

- [ ] **Step 3：运行趋势测试并确认失败**

Run:

```powershell
python -m pytest -q tests/test_trends.py
```

Expected: `sku_clusters` 不存在，测试失败。

- [ ] **Step 4：实现普通与 SKU 计数共用周期边界**

在 `build_issue_trends()` 的普通计数器后初始化 SKU 容器：

```python
current_sku_clusters: Counter[tuple[str, str, str, str]] = Counter()
previous_sku_clusters: Counter[tuple[str, str, str, str]] = Counter()
sku_display: dict[tuple[str, str, str, str], str] = {}
```

在现有记录循环中，普通计数保持不变；SKU 非空时记录首次显示文本并额外计数：

```python
sku_key = _sku_cluster_key(record)
if sku_key is not None:
    analysis = _mapping(record.get("analysis"))
    request = _mapping(analysis.get("request"))
    sku_display.setdefault(sku_key, _optional_value(request.get("sku")))
if created_at >= current_start:
    current_clusters[key] += 1
    current_total += 1
    if sku_key is not None:
        current_sku_clusters[sku_key] += 1
else:
    previous_clusters[key] += 1
    previous_total += 1
    if sku_key is not None:
        previous_sku_clusters[sku_key] += 1
```

增加完整 key helper：

```python
def _sku_cluster_key(record: dict[str, Any]) -> tuple[str, str, str, str] | None:
    analysis = _mapping(record.get("analysis"))
    request = _mapping(analysis.get("request"))
    attribution = _mapping(analysis.get("attribution"))
    sku = _optional_value(request.get("sku"))
    if not sku:
        return None
    return (
        _value(request.get("platform")),
        sku.casefold(),
        _value(attribution.get("issue_category")),
        _value(attribution.get("primary_responsibility")),
    )


def _optional_value(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()
```

- [ ] **Step 5：构造并排序 SKU 趋势响应**

增加 helper：

```python
def _build_sku_clusters(
    current: Counter[tuple[str, str, str, str]],
    previous: Counter[tuple[str, str, str, str]],
    display: dict[tuple[str, str, str, str], str],
) -> list[dict[str, Any]]:
    result = []
    for key in current.keys() | previous.keys():
        platform, _, issue_category, responsibility = key
        current_count = current[key]
        previous_count = previous[key]
        delta = current_count - previous_count
        if delta == 0:
            continue
        result.append({
            "platform": platform,
            "sku": display[key],
            "issue_category": issue_category,
            "responsibility": responsibility,
            "current_count": current_count,
            "previous_count": previous_count,
            "delta": delta,
            "significant_increase": current_count >= 3 and delta >= 2,
        })
    result.sort(key=_sku_cluster_sort_key)
    return result
```

把以下字段加入响应：

```python
"sku_clusters": _build_sku_clusters(
    current_sku_clusters,
    previous_sku_clusters,
    sku_display,
),
```

`_sku_cluster_sort_key()` 使用绝对增量降序、当前数量降序、平台、SKU、问题类型和责任方升序：

```python
def _sku_cluster_sort_key(item: dict[str, Any]) -> tuple[Any, ...]:
    return (
        -abs(item["delta"]),
        -item["current_count"],
        item["platform"].casefold(),
        item["platform"],
        item["sku"].casefold(),
        item["sku"],
        item["issue_category"].casefold(),
        item["issue_category"],
        item["responsibility"].casefold(),
        item["responsibility"],
    )
```

- [ ] **Step 6：运行趋势测试**

Run:

```powershell
python -m pytest -q tests/test_trends.py tests/test_app.py -k "trend"
```

Expected: 普通趋势和 SKU 趋势测试全部通过。

- [ ] **Step 7：提交 SKU 趋势后端**

```powershell
git add src/customer_issue_agent/trends.py tests/test_trends.py
git commit -m "feat: calculate sku issue trends"
```

---

### Task 7：实现 SKU 范围任务和效果复盘

**Files:**
- Modify: `src/customer_issue_agent/tasks.py`
- Modify: `src/customer_issue_agent/app.py:184-218`
- Test: `tests/test_tasks.py`
- Test: `tests/test_app.py`

- [ ] **Step 1：写 SKU 快照、去重和无 SKU 任务并存失败测试**

先扩展 `tests/test_tasks.py` 的 `_record()`，增加 `sku: str = ""` 参数，并把 request 改为：

```python
"request": {
    "platform": platform,
    "conversation_text": "Customer: help",
    "sku": sku,
},
```

再增加：

```python
def test_sku_task_snapshot_is_exact_and_deduplicates_case_insensitively(tmp_path):
    service, task_store = _service(tmp_path, [
        _record("sku-one", sku="SKU-01"),
        _record("sku-case", sku="sku-01"),
        _record("sku-ten", sku="SKU-010"),
        _record("legacy", sku=""),
    ])

    sku_task, created = service.create_task(_payload(sku="SKU-01"), now=NOW, today=TODAY)
    duplicate, duplicate_created = service.create_task(_payload(sku="sku-01"), now=NOW, today=TODAY)
    general_task, general_created = service.create_task(_payload(sku=""), now=NOW, today=TODAY)

    assert created is True
    assert duplicate_created is False
    assert duplicate["id"] == sku_task["id"]
    assert sku_task["record_ids"] == ["sku-one", "sku-case"]
    assert general_created is True
    assert general_task["id"] != sku_task["id"]
    assert len(task_store.list_tasks()) == 2
```

- [ ] **Step 2：写 SKU 趋势重算和复盘窗口隔离失败测试**

继续增加：

```python
def test_sku_trend_task_recomputes_significant_increase_for_same_sku(tmp_path):
    records = [
        _record(f"current-{index}", created_at=NOW - timedelta(days=index + 1), sku="SKU-01")
        for index in range(3)
    ]
    records.extend([
        _record("previous", created_at=NOW - timedelta(days=8), sku="sku-01"),
        _record("other-current-1", created_at=NOW - timedelta(days=1), sku="SKU-02"),
        _record("other-current-2", created_at=NOW - timedelta(days=2), sku="SKU-02"),
    ])
    service, _ = _service(tmp_path, records)

    task, _ = service.create_task(
        _payload(source="trend", source_range="30d", sku="SKU-01"),
        now=NOW,
        today=TODAY,
    )

    assert task["source_range"] == "7d"
    assert task["record_ids"] == ["current-0", "current-1", "current-2"]
    assert task["significant_increase"] is True
    assert task["priority"] == "high"


def test_sku_task_recomputes_trend_and_effect_windows_for_same_sku(tmp_path):
    completed_at = NOW + timedelta(days=1)
    records = [
        _record("baseline-sku", created_at=NOW - timedelta(days=1), sku="SKU-01"),
        _record("baseline-other", created_at=NOW - timedelta(days=1), sku="SKU-02"),
        _record("effect-sku", created_at=completed_at + timedelta(days=1), sku="sku-01"),
        _record("effect-other", created_at=completed_at + timedelta(days=1), sku="SKU-02"),
    ]
    service, _ = _service(tmp_path, records)
    task, _ = service.create_task(_payload(sku="SKU-01"), now=NOW, today=TODAY)
    service.update_task(task["id"], {"status": "in_progress"}, now=NOW)
    service.update_task(
        task["id"],
        {"status": "completed", "result": "已修复 SKU 页面"},
        now=completed_at,
    )

    review = service.get_effect_review(
        task["id"],
        now=completed_at + timedelta(days=7),
    )

    assert review["evidence"]["baseline"]["record_ids"] == ["baseline-sku"]
    assert review["evidence"]["effect"]["record_ids"] == ["effect-sku"]
```

- [ ] **Step 3：运行任务测试并确认失败**

Run:

```powershell
python -m pytest -q tests/test_tasks.py -k "sku_task"
```

Expected: SKU 不参与去重或记录匹配，测试失败。

- [ ] **Step 4：实现可选 SKU 校验和任务键**

在 `create_task()` 中：

```python
sku = _optional_bounded_text(payload.get("sku"), "SKU", max_length=200)
key = _cluster_key(platform, issue_category, responsibility, sku)
```

增加：

```python
def _optional_bounded_text(value: object, field: str, *, max_length: int) -> str:
    if value in (None, ""):
        return ""
    if not isinstance(value, str):
        raise TaskValidationError(f"{field}必须是字符串")
    cleaned = value.strip()
    if len(cleaned) > max_length:
        raise TaskValidationError(f"{field}不能超过 {max_length} 个字符")
    return cleaned


def _cluster_key(
    platform: str,
    issue_category: str,
    responsibility: str,
    sku: str = "",
) -> tuple[str, str, str, str]:
    return (
        platform.casefold(),
        sku.casefold(),
        issue_category,
        responsibility,
    )


def _task_key(task: Mapping[str, object]) -> tuple[str, str, str, str]:
    return _cluster_key(
        _text(task.get("platform")),
        _text(task.get("issue_category")),
        _text(task.get("responsibility")),
        _text(task.get("sku")),
    )
```

任务字典始终写入 `"sku": sku`，历史任务读取时 `_text(None)` 返回空字符串。

- [ ] **Step 5：把 SKU 贯通到记录匹配和显著上升**

在 `create_task()` 中把 SKU 明确传给快照和趋势重算：

```python
record_ids = _matching_record_ids(
    records,
    platform=platform,
    issue_category=issue_category,
    responsibility=responsibility,
    source_range=source_range,
    now=current,
    sku=sku,
)
significant_increase = source == "trend" and _significant_increase(
    records,
    platform,
    issue_category,
    responsibility,
    current,
    sku=sku,
)
```

把 `_matching_record_ids()` 签名末尾增加 `sku`，并在它调用 `_record_matches_cluster()` 时传入：

```python
def _matching_record_ids(
    records: list[dict],
    *,
    platform: str,
    issue_category: str,
    responsibility: str,
    source_range: str,
    now: datetime,
    sku: str = "",
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
        if (
            _record_matches_cluster(
                record,
                platform=platform,
                issue_category=issue_category,
                responsibility=responsibility,
                sku=sku,
            )
            and isinstance(record.get("id"), str)
        ):
            matched.append(record["id"])
    return matched
```

在 `_window_evidence()` 中把匹配调用改为：

```python
_record_matches_cluster(
    record,
    platform=_text(task.get("platform")),
    issue_category=_text(task.get("issue_category")),
    responsibility=_text(task.get("responsibility")),
    sku=_text(task.get("sku")),
)
```

把 `_significant_increase()` 改为：

```python
def _significant_increase(
    records: list[dict],
    platform: str,
    issue_category: str,
    responsibility: str,
    now: datetime,
    sku: str = "",
) -> bool:
    current_start = now - timedelta(days=7)
    previous_start = current_start - timedelta(days=7)
    current_count = 0
    previous_count = 0
    for record in records:
        created_at = _record_time(record.get("created_at"))
        if (
            created_at is None
            or created_at < previous_start
            or created_at > now
            or not _record_matches_cluster(
                record,
                platform=platform,
                issue_category=issue_category,
                responsibility=responsibility,
                sku=sku,
            )
        ):
            continue
        if created_at >= current_start:
            current_count += 1
        else:
            previous_count += 1
    return current_count >= 3 and current_count - previous_count >= 2
```

最后把 `_record_matches_cluster()` 改为：

```python
def _record_matches_cluster(
    record: Mapping[str, object],
    *,
    platform: str,
    issue_category: str,
    responsibility: str,
    sku: str = "",
) -> bool:
    analysis = _mapping(record.get("analysis"))
    request = _mapping(analysis.get("request"))
    attribution = _mapping(analysis.get("attribution"))
    record_sku = _text(request.get("sku"))
    return (
        _text(request.get("platform")).casefold() == platform.casefold()
        and (not sku or record_sku.casefold() == sku.casefold())
        and _text(attribution.get("issue_category")) == issue_category
        and _text(attribution.get("primary_responsibility")) == responsibility
    )
```

- [ ] **Step 6：更新标题、API 和错误测试**

SKU 任务标题使用：

```python
title_parts = [platform]
if sku:
    title_parts.append(sku)
title_parts.extend([
    IssueCategory(issue_category).label,
    Responsibility(responsibility).label,
])
title = " · ".join(title_parts)
```

`POST /api/tasks` 增加 `sku: str = Form(default="")` 并传入 payload。复用 Task 4 已扩展的 `_stored_record()`，在 `tests/test_app.py` 增加：

```python
def test_task_api_creates_sku_scoped_task_and_rejects_overlong_sku(tmp_path):
    storage_path = tmp_path / "analyses.jsonl"
    task_path = tmp_path / "tasks.jsonl"
    now = datetime.now(UTC)
    _write_jsonl_records(storage_path, [
        _stored_record("sku-one", platform="Amazon", created_at=now, sku="SKU-01"),
        _stored_record("sku-ten", platform="Amazon", created_at=now, sku="SKU-010"),
    ])
    client = TestClient(create_app(storage_path=storage_path, task_storage_path=task_path))
    form = {
        "source": "summary",
        "source_range": "all",
        "platform": "Amazon",
        "sku": "SKU-01",
        "issue_category": "function_use",
        "responsibility": "customer_service_training",
    }

    created = client.post("/api/tasks", data=form)
    invalid = client.post("/api/tasks", data={**form, "sku": "x" * 201})

    assert created.status_code == 201
    assert created.json()["task"]["sku"] == "SKU-01"
    assert created.json()["task"]["record_ids"] == ["sku-one"]
    assert invalid.status_code == 422
```

- [ ] **Step 7：运行任务和 API 测试**

Run:

```powershell
python -m pytest -q tests/test_tasks.py tests/test_app.py -k "task"
```

Expected: SKU 与历史无 SKU 任务测试全部通过。

- [ ] **Step 8：提交 SKU 任务后端**

```powershell
git add src/customer_issue_agent/tasks.py src/customer_issue_agent/app.py tests/test_tasks.py tests/test_app.py
git commit -m "feat: scope tasks and reviews by sku"
```

---

### Task 8：增加商品输入、记录筛选和前端导出参数

**Files:**
- Create: `tests/js/test_product_dimension_ui.mjs`
- Modify: `src/customer_issue_agent/templates/index.html`
- Modify: `src/customer_issue_agent/static/app.js`
- Test: `tests/test_app.py`

- [ ] **Step 1：写模板商品输入和记录数据属性失败测试**

在 `tests/test_app.py` 增加：

```python
def test_index_contains_product_inputs_filters_and_task_sku_field(tmp_path):
    client = TestClient(create_app(storage_path=tmp_path / "analyses.jsonl"))

    html = client.get("/").text

    for form_prefix in ("paste", "upload", "batch"):
        assert f'id="{form_prefix}-store-name"' in html
        assert f'id="{form_prefix}-sku"' in html
        assert f'id="{form_prefix}-platform-product-id"' in html
    assert 'id="store-filter"' in html
    assert 'id="sku-filter"' in html
    assert 'id="platform-product-id-filter"' in html
    assert '<input type="hidden" name="sku">' in html
```

- [ ] **Step 2：创建完整前端商品测试文件并写失败测试**

创建 `tests/js/test_product_dimension_ui.mjs`。这个 harness 不触发 `DOMContentLoaded`，只为被测纯函数提供确定的 DOM；`issue-filter` 和 `responsibility-filter` 的 options 也预置好，供 Task 9 的下钻测试继续复用：

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

  toggle(name, force) {
    const enabled = force === undefined ? !this.values.has(name) : Boolean(force);
    enabled ? this.values.add(name) : this.values.delete(name);
    return enabled;
  }

  contains(name) {
    return this.values.has(name);
  }
}

class FakeElement {
  constructor({ dataset = {}, options = [], value = "" } = {}) {
    this.dataset = { ...dataset };
    this.options = options.map((optionValue) => ({ value: optionValue }));
    this.value = value;
    this.textContent = "";
    this.innerHTML = "";
    this.hidden = false;
    this.disabled = false;
    this.children = [];
    this.attributes = new Map();
    this.classList = new FakeClassList();
  }

  addEventListener() {}

  appendChild(child) {
    this.children.push(child);
    return child;
  }

  prepend(child) {
    this.children.unshift(child);
  }

  querySelector() {
    return null;
  }

  querySelectorAll() {
    return [];
  }

  closest() {
    return this;
  }

  scrollIntoView() {
    this.scrolledIntoView = true;
  }

  setAttribute(name, value) {
    this.attributes.set(name, String(value));
  }

  getAttribute(name) {
    return this.attributes.get(name) ?? null;
  }
}

function createRecord(dataset) {
  return new FakeElement({
    dataset: {
      searchText: "",
      platform: "",
      storeName: "",
      sku: "",
      platformProductId: "",
      issueCategory: "",
      responsibility: "",
      feedbackStatus: "unreviewed",
      ...dataset,
    },
  });
}

function loadApp() {
  const elements = new Map([
    ["record-filter", new FakeElement()],
    ["record-search", new FakeElement()],
    ["platform-filter", new FakeElement()],
    ["store-filter", new FakeElement()],
    ["sku-filter", new FakeElement()],
    ["platform-product-id-filter", new FakeElement()],
    ["issue-filter", new FakeElement({ options: ["", "function_use"] })],
    ["responsibility-filter", new FakeElement({ options: ["", "customer_service_training"] })],
    ["feedback-filter", new FakeElement()],
    ["summary-range", new FakeElement({ value: "all" })],
    ["summary-content", new FakeElement()],
    ["trend-content", new FakeElement()],
    ["recent-records", new FakeElement()],
    ["export-filter-summary", new FakeElement()],
    ["export-count-preview", new FakeElement()],
    ["filter-count", new FakeElement()],
    ["filter-empty", new FakeElement()],
  ]);
  const records = [
    createRecord({
      searchText: "record-1 Amazon Flagship US Store SKU-1 B001 broken",
      platform: "Amazon",
      storeName: "Flagship US Store",
      sku: "SKU-1",
      platformProductId: "B001",
      issueCategory: "function_use",
      responsibility: "customer_service_training",
    }),
    createRecord({
      searchText: "record-2 TikTok Outlet SKU-10 B010 setup",
      platform: "TikTok Shop",
      storeName: "Outlet",
      sku: "SKU-10",
      platformProductId: "B010",
      issueCategory: "function_use",
      responsibility: "customer_service_training",
    }),
  ];
  const document = {
    addEventListener() {},
    createElement: () => new FakeElement(),
    getElementById: (id) => elements.get(id) || null,
    querySelector: () => null,
    querySelectorAll(selector) {
      if (selector === "#recent-records .record") return records;
      return [];
    },
  };
  const context = vm.createContext({
    URLSearchParams,
    clearTimeout,
    console,
    document,
    fetch: async () => ({
      ok: false,
      json: async () => ({ detail: "测试环境不发起网络请求" }),
    }),
    FormData: class FormData {},
    navigator: {},
    setTimeout,
    window: { location: {} },
  });
  vm.runInContext(appScript, context);
  return { context, elements, records };
}

test("商品筛选使用店铺包含和 SKU 商品 ID 精确匹配", () => {
  const { context, elements, records } = loadApp();
  elements.get("store-filter").value = "flag";
  elements.get("sku-filter").value = "sku-1";
  elements.get("platform-product-id-filter").value = "b001";

  context.applyRecordFilters();

  assert.equal(records[0].hidden, false);
  assert.equal(records[1].hidden, true);
});

test("商品筛选进入导出和数量预览参数", () => {
  const { context, elements } = loadApp();
  elements.get("store-filter").value = "US Store";
  elements.get("sku-filter").value = "SKU-1";
  elements.get("platform-product-id-filter").value = "B001";

  const params = context.buildExportFilterParams();

  assert.equal(params.get("store_name"), "US Store");
  assert.equal(params.get("sku"), "SKU-1");
  assert.equal(params.get("platform_product_id"), "B001");
});
```

- [ ] **Step 3：运行模板和 Node 测试并确认失败**

Run:

```powershell
python -m pytest -q tests/test_app.py -k "product_inputs"
node --test tests/js/test_product_dimension_ui.mjs
```

Expected: 模板字段和前端商品筛选尚不存在，测试失败。

- [ ] **Step 4：增加三个表单商品输入和记录筛选控件**

每个分析表单在平台字段之后增加同一结构，ID 按表单前缀变化：

```html
<div class="product-fields" aria-label="商品信息（可选）">
  <label class="field" for="paste-store-name">
    <span>店铺</span>
    <input id="paste-store-name" name="store_name" maxlength="200">
  </label>
  <label class="field" for="paste-sku">
    <span>SKU</span>
    <input id="paste-sku" name="sku" maxlength="200">
  </label>
  <label class="field" for="paste-platform-product-id">
    <span>平台商品 ID</span>
    <input id="paste-platform-product-id" name="platform_product_id" maxlength="200">
  </label>
</div>
```

最近记录筛选增加对应三个 `filter-field`。任务创建表单增加：

```html
<input type="hidden" name="sku">
```

- [ ] **Step 5：把商品字段写入服务端和动态记录卡**

服务端模板记录 article 增加：

```html
data-store-name="{{ record.analysis.request.store_name|default('', true) }}"
data-sku="{{ record.analysis.request.sku|default('', true) }}"
data-platform-product-id="{{ record.analysis.request.platform_product_id|default('', true) }}"
```

`data-search-base-text` 和 `data-search-text` 加入三个字段。记录 meta 和详情只在字段非空时显示商品信息。

`buildRecordCard()` 和 `recordDetailHtml()` 从 `analysis.request` 读取相同字段，动态新增记录与初始模板口径一致。

- [ ] **Step 6：实现本地商品筛选和导出参数**

把 `applyRecordFilters()` 和 `recordMatchesFilters()` 改为：

```javascript
function applyRecordFilters() {
  const records = Array.from(document.querySelectorAll("#recent-records .record"));
  const query = document.getElementById("record-search")?.value.trim().toLowerCase() || "";
  const platformFilter = document.getElementById("platform-filter");
  const platform = platformFilter?.value.trim().toLowerCase() || "";
  const platformMatch = platformFilter?.dataset.matchMode || "";
  const storeName = document.getElementById("store-filter")?.value.trim().toLowerCase() || "";
  const sku = document.getElementById("sku-filter")?.value.trim().toLowerCase() || "";
  const platformProductId = document.getElementById("platform-product-id-filter")?.value.trim().toLowerCase() || "";
  const issue = document.getElementById("issue-filter")?.value || "";
  const responsibility = document.getElementById("responsibility-filter")?.value || "";
  const feedback = document.getElementById("feedback-filter")?.value || "";
  let visible = 0;

  records.forEach((record) => {
    const matches = recordMatchesFilters(record, {
      query,
      platform,
      platformMatch,
      storeName,
      sku,
      platformProductId,
      issue,
      responsibility,
      feedback,
    });
    record.hidden = !matches;
    if (matches) visible += 1;
  });
  updateFilterState(visible, records.length);
}


function recordMatchesFilters(record, filters) {
  const searchText = (record.dataset.searchText || "").toLowerCase();
  const platform = (record.dataset.platform || "").toLowerCase();
  const storeName = (record.dataset.storeName || "").toLowerCase();
  const sku = (record.dataset.sku || "").toLowerCase();
  const platformProductId = (record.dataset.platformProductId || "").toLowerCase();
  const matchesQuery = !filters.query || searchText.includes(filters.query);
  const matchesPlatform = !filters.platform || (
    filters.platformMatch === "exact"
      ? platform === filters.platform
      : platform.includes(filters.platform)
  );
  const matchesStore = !filters.storeName || storeName.includes(filters.storeName);
  const matchesSku = !filters.sku || sku === filters.sku;
  const matchesProductId = !filters.platformProductId || platformProductId === filters.platformProductId;
  const matchesIssue = !filters.issue || record.dataset.issueCategory === filters.issue;
  const matchesResponsibility = !filters.responsibility || record.dataset.responsibility === filters.responsibility;
  const matchesFeedback = !filters.feedback || record.dataset.feedbackStatus === filters.feedback;
  return matchesQuery
    && matchesPlatform
    && matchesStore
    && matchesSku
    && matchesProductId
    && matchesIssue
    && matchesResponsibility
    && matchesFeedback;
}
```

`buildExportFilterParams()` 读取原始 trimmed 值，并在现有 platform 条件后加入：

```javascript
const storeName = document.getElementById("store-filter")?.value.trim() || "";
const sku = document.getElementById("sku-filter")?.value.trim() || "";
const platformProductId = document.getElementById("platform-product-id-filter")?.value.trim() || "";

if (storeName) params.set("store_name", storeName);
if (sku) params.set("sku", sku);
if (platformProductId) params.set("platform_product_id", platformProductId);
```

`updateExportFilterSummary()` 读取同样三个值，并在现有 platform 条件后加入：

```javascript
if (storeName) conditions.push(`店铺：${storeName}`);
if (sku) conditions.push(`SKU：${sku}`);
if (platformProductId) conditions.push(`平台商品 ID：${platformProductId}`);
```

- [ ] **Step 7：运行前端商品筛选、模板和现有前端测试**

Run:

```powershell
node --test tests/js/test_product_dimension_ui.mjs tests/js/test_feedback_ui.mjs
python -m pytest -q tests/test_app.py
```

Expected: 商品筛选和现有反馈同步测试全部通过。

- [ ] **Step 8：提交商品输入与筛选 UI**

```powershell
git add src/customer_issue_agent/templates/index.html src/customer_issue_agent/static/app.js tests/js/test_product_dimension_ui.mjs tests/test_app.py
git commit -m "feat: add product inputs and filters"
```

---

### Task 9：渲染商品概览、SKU 趋势和 SKU 任务交互

**Files:**
- Modify: `src/customer_issue_agent/static/app.js`
- Modify: `src/customer_issue_agent/templates/index.html`
- Modify: `tests/js/test_product_dimension_ui.mjs`
- Modify: `tests/js/test_task_workflow.mjs`
- Modify: `tests/js/test_issue_trends.mjs`

- [ ] **Step 1：写商品概览和 SKU 趋势渲染失败测试**

在 `tests/js/test_product_dimension_ui.mjs` 增加：

```javascript
test("商品概览展示覆盖率 Top SKU 和前五个 SKU 问题簇", () => {
  const { context, elements } = loadApp();
  context.renderRecordsSummary({
    total_records: 5,
    reviewed_records: 0,
    corrected_records: 0,
    product_coverage: { with_sku: 4, missing_sku: 1 },
    top_skus: [{ sku: "SKU-01", count: 3, platform_count: 2, platforms: ["Amazon", "TikTok Shop"] }],
    top_sku_issue_clusters: Array.from({ length: 6 }, (_, index) => ({
      platform: "Amazon",
      sku: `SKU-0${index + 1}`,
      issue_category: "function_use",
      responsibility: "customer_service_training",
      count: 6 - index,
    })),
  });

  const html = elements.get("summary-content").innerHTML;
  assert.match(html, /未填写 SKU/);
  assert.match(html, /SKU-01/);
  assert.equal((html.match(/data-sku-cluster-filter/g) || []).length, 5);
});


test("SKU 趋势展示变化并限制前五项", () => {
  const { context, elements } = loadApp();
  context.renderIssueTrends({
    period: "7d",
    current_period: { total_records: 6 },
    previous_period: { total_records: 2 },
    total_delta: 4,
    clusters: [],
    sku_clusters: Array.from({ length: 6 }, (_, index) => ({
      platform: "Amazon",
      sku: `SKU-0${index + 1}`,
      issue_category: "function_use",
      responsibility: "customer_service_training",
      current_count: 3,
      previous_count: 1,
      delta: 2,
      significant_increase: index === 0,
    })),
  });

  const html = elements.get("trend-content").innerHTML;
  assert.match(html, /SKU-01/);
  assert.match(html, /明显上升/);
  assert.equal((html.match(/data-sku-trend-filter/g) || []).length, 5);
});
```

- [ ] **Step 2：写 SKU 下钻和任务草稿失败测试**

增加：

```javascript
test("SKU 问题簇下钻应用精确筛选并保留关键词复核", () => {
  const { context, elements } = loadApp();
  elements.get("record-search").value = "broken";
  elements.get("feedback-filter").value = "unreviewed";

  context.applySkuClusterFilter({
    platform: "Amazon",
    sku: "SKU-01",
    issueCategory: "function_use",
    responsibility: "customer_service_training",
    range: "7d",
  });

  assert.equal(elements.get("platform-filter").value, "Amazon");
  assert.equal(elements.get("sku-filter").value, "SKU-01");
  assert.equal(elements.get("summary-range").value, "7d");
  assert.equal(elements.get("record-search").value, "broken");
  assert.equal(elements.get("feedback-filter").value, "unreviewed");
});


test("SKU 趋势任务草稿携带 SKU 和高优先级", () => {
  const { context } = loadApp();
  const draft = context.createTaskDraft({
    source: "trend",
    platform: "Amazon",
    sku: "SKU-01",
    issueCategory: "function_use",
    responsibility: "customer_service_training",
    significantIncrease: true,
  });

  assert.equal(draft.sku, "SKU-01");
  assert.equal(draft.priority, "high");
});
```

- [ ] **Step 3：运行商品 UI 和任务 UI 测试并确认失败**

Run:

```powershell
node --test tests/js/test_product_dimension_ui.mjs tests/js/test_task_workflow.mjs tests/js/test_issue_trends.mjs
```

Expected: 商品概览、SKU 趋势和 SKU 草稿函数尚不存在，测试失败。

- [ ] **Step 4：实现商品概览 HTML**

在 `renderRecordsSummary()` 的现有指标和分布后加入：

```javascript
<section class="product-insights" aria-label="商品维度">
  <h3>商品维度</h3>
  <div class="summary-metrics product-coverage">
    ${summaryMetric("有 SKU", summary.product_coverage?.with_sku ?? 0)}
    ${summaryMetric("未填写 SKU", summary.product_coverage?.missing_sku ?? 0)}
  </div>
  ${skuDistribution(summary.top_skus || [])}
  ${skuIssueClusters(summary.top_sku_issue_clusters || [])}
</section>
```

实现 `skuDistribution()` 和 `skuIssueClusters()`，所有动态字段使用 `escapeHtml()`，只渲染前五项。有效行包含：

```html
data-sku-cluster-filter
data-platform="Amazon"
data-sku="SKU-01"
data-issue-category="function_use"
data-responsibility="customer_service_training"
```

并为 SKU 高频问题行添加现有 `data-task-create` 属性和 `data-task-sku`。

- [ ] **Step 5：实现 SKU 趋势 HTML 和事件绑定**

`renderIssueTrends()` 同时渲染普通趋势和：

```javascript
function skuTrendRows(items = []) {
  const visible = items.slice(0, 5);
  if (!visible.length) {
    return '<p class="trend-empty">当前周期暂无 SKU 变化。</p>';
  }
  return `<div class="trend-list sku-trend-list">${visible.map(skuTrendRow).join("")}</div>`;
}
```

`skuTrendRow()` 输出平台、SKU、问题类型、责任方、当前/上一周期、变化方向和明显上升标签；有效行同时包含 `data-sku-trend-filter` 与 `data-task-create`。

在 `renderRecordsSummary()` 和 `renderIssueTrends()` 结束时分别绑定商品下钻和任务创建按钮。

- [ ] **Step 6：实现统一 SKU 下钻**

增加完整函数：

```javascript
function applySkuClusterFilter({
  platform,
  sku,
  issueCategory,
  responsibility,
  range = "",
}) {
  const platformFilter = document.getElementById("platform-filter");
  const skuFilter = document.getElementById("sku-filter");
  const issueFilter = document.getElementById("issue-filter");
  const responsibilityFilter = document.getElementById("responsibility-filter");
  if (!platformFilter || !skuFilter || !issueFilter || !responsibilityFilter || !sku) {
    return;
  }
  platformFilter.value = platform;
  platformFilter.dataset.matchMode = "exact";
  skuFilter.value = sku;
  issueFilter.value = issueCategory;
  responsibilityFilter.value = responsibility;
  if (range) {
    const summaryRange = document.getElementById("summary-range");
    if (summaryRange) summaryRange.value = range;
  }
  refreshRecordFilterViews();
  if (range) loadRecordsSummary();
  scrollToRecentRecords();
}
```

绑定函数从按钮 dataset 传入字段，Top SKU 点击只设置 SKU，不清空平台和其他筛选。

- [ ] **Step 7：把 SKU 贯通到任务表单、卡片和记录下钻**

扩展 `bindTaskCreateButtons()` 和 `createTaskDraft()` 的 `sku = ""` 参数。`openTaskCreateForm()` 设置：

```javascript
form.elements.sku.value = draft.sku;
```

标题在 SKU 非空时插入 SKU。任务卡增加：

```html
data-task-sku="${escapeHtml(task.sku || "")}"
```

并在 meta 中显示 SKU pill。`drilldownTaskRecords()` 恢复 `sku-filter` 精确值；无 SKU 任务清空 SKU 筛选，避免旧筛选隐藏任务记录。

- [ ] **Step 8：运行全部前端测试**

Run:

```powershell
node --test tests/js/test_feedback_ui.mjs tests/js/test_issue_trends.mjs tests/js/test_task_workflow.mjs tests/js/test_task_effect_review.mjs tests/js/test_product_dimension_ui.mjs
node --check src/customer_issue_agent/static/app.js
```

Expected: 所有 Node 测试通过，JavaScript 语法检查退出码为 0。

- [ ] **Step 9：提交商品洞察与任务前端**

```powershell
git add src/customer_issue_agent/static/app.js src/customer_issue_agent/templates/index.html tests/js/test_product_dimension_ui.mjs tests/js/test_task_workflow.mjs tests/js/test_issue_trends.mjs
git commit -m "feat: show sku insights and task actions"
```

---

### Task 10：完成布局、文档和端到端验收

**Files:**
- Modify: `src/customer_issue_agent/static/styles.css`
- Modify: `README.md`
- Modify: `tests/test_app.py`

- [ ] **Step 1：写商品布局和 README 契约失败测试**

在 `tests/test_app.py` 增加：

```python
def test_styles_cover_product_fields_insights_and_mobile(tmp_path):
    client = TestClient(create_app(storage_path=tmp_path / "analyses.jsonl"))
    css = client.get("/static/styles.css").text

    assert ".product-fields" in css
    assert ".product-insights" in css
    assert ".product-coverage" in css
    assert ".sku-trend-list" in css
    assert ".task-sku" in css
    mobile = css.split("@media (max-width: 720px)", 1)[1]
    assert ".product-fields" in mobile


def test_readme_documents_product_dimensions():
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "SKU/ASIN/店铺维度" in readme
    assert "seller_sku" in readme
    assert "平台商品 ID" in readme
    assert "SKU 范围任务" in readme
```

- [ ] **Step 2：运行布局和文档测试并确认失败**

Run:

```powershell
python -m pytest -q tests/test_app.py -k "product_fields_insights or readme_documents"
```

Expected: CSS 类和 README 章节不存在，测试失败。

- [ ] **Step 3：实现桌面和移动布局**

在 `styles.css` 增加：

```css
.product-fields {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.product-insights {
  display: grid;
  gap: 14px;
  border-top: 1px solid var(--line);
  padding-top: 18px;
}

.product-insights h3 {
  margin: 0;
}

.product-coverage {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.task-sku {
  background: #e6f1ec;
  color: #275849;
}
```

在现有 `@media (max-width: 720px)` 中加入：

```css
.product-fields,
.product-coverage {
  grid-template-columns: 1fr;
}
```

商品洞察继续使用现有 summary/trend 卡片视觉，不引入新的颜色体系或动画依赖。

- [ ] **Step 4：更新 README 商品维度章节**

在任务效果复盘之后增加 `## SKU/ASIN/店铺维度`，完整说明：

- 三个可选字段及单条表单输入。
- CSV/Excel 的店铺、SKU、平台商品 ID 常见别名。
- 行级值覆盖表单默认值。
- 缺 SKU 记录保留但不进入 SKU 排名。
- 商品筛选、Top SKU、SKU 高频问题和 SKU 趋势。
- SKU 范围任务及 SKU 限定效果复盘。
- 不自动猜测商品标识、不接平台 API、不调用模型。

- [ ] **Step 5：运行 Python、Node、语法和 UTF-8 全量验证**

Run:

```powershell
python -m pytest -q
node --test tests/js/test_feedback_ui.mjs tests/js/test_issue_trends.mjs tests/js/test_task_workflow.mjs tests/js/test_task_effect_review.mjs tests/js/test_product_dimension_ui.mjs
node --check src/customer_issue_agent/static/app.js
git diff --check target/master...HEAD
```

Expected: 所有测试通过，Node 无失败，语法和差异检查退出码为 0。

严格 UTF-8 检查：

```powershell
$utf8 = [System.Text.UTF8Encoding]::new($false, $true)
git diff --name-only --diff-filter=ACM target/master...HEAD | ForEach-Object {
  $path = Join-Path (Get-Location) $_
  $null = $utf8.GetString([System.IO.File]::ReadAllBytes($path))
}
```

Expected: 无解码异常。

- [ ] **Step 6：运行真实浏览器验收**

启动本地服务：

```powershell
python -m uvicorn customer_issue_agent.app:create_app --factory --app-dir src --host 127.0.0.1 --port 58623
```

在桌面视口和 `390×844` 移动视口依次确认：

1. 粘贴表单填写中文店铺、`SKU-01`、`B0ABC` 后成功分析。
2. 最近记录展示商品信息，商品详情和复制文本不出现 `undefined`。
3. 店铺包含筛选可命中，SKU `SKU-1` 不匹配 `SKU-10`。
4. 导出摘要和预计数量包含商品条件。
5. SKU 覆盖、Top SKU、SKU 高频问题和 SKU 趋势布局无横向溢出。
6. 点击 SKU 高频问题正确下钻并可创建 SKU 任务。
7. SKU 任务卡展示 SKU，关联记录下钻恢复精确 SKU。
8. 浏览器控制台无错误，不产生截图、日志或 `data/` 仓库残留。

- [ ] **Step 7：提交布局和文档**

```powershell
git add src/customer_issue_agent/static/styles.css README.md tests/test_app.py
git commit -m "docs: explain product dimension workflow"
```

- [ ] **Step 8：检查工作树和提交边界**

Run:

```powershell
git status --short
git log --oneline target/master..HEAD
git diff --stat target/master...HEAD
```

Expected: 工作树为空；提交只包含商品维度设计、计划和实现；没有 `data/`、截图、日志或其他智能体文件。

---

## 最终验证清单

- [ ] 商品字段模型严格校验字符串、空格和 200 字符上限。
- [ ] TXT/LOG 使用表单默认值，CSV/XLSX 使用固定别名优先级。
- [ ] 单文件冲突商品值返回 `422`，批量非法元数据不产生部分写入。
- [ ] 历史无商品字段记录正常读取、筛选和导出。
- [ ] 店铺包含匹配，SKU 和平台商品 ID 精确匹配。
- [ ] CSV 与数量预览使用完全相同的商品筛选口径。
- [ ] SKU 覆盖、Top SKU 和 SKU 高频问题排序确定。
- [ ] SKU 趋势复用现有时间边界和显著上升阈值。
- [ ] SKU 任务与无 SKU 任务可并存，SKU 大小写差异仍正确去重。
- [ ] SKU 快照、显著上升和两个复盘窗口不混入其他 SKU。
- [ ] 前端动态记录和服务端模板使用相同商品数据属性。
- [ ] 下钻保留关键词和复核状态，趋势下钻切换最近 7 天。
- [ ] Python、Node、JavaScript 语法、严格 UTF-8 和差异检查全部通过。
- [ ] 桌面、移动视口和浏览器控制台验收通过。
- [ ] 无模型调用、海外平台 API、后台轮询、自动重试或新增依赖。
