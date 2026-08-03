# 问题趋势对比与异常提示 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (recommended) or superpowers:subagent-driven-development when explicitly needed for independent tasks. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在本地工作台中对比最近 7 天与前 7 天的问题簇变化，展示 Top 5 趋势并突出达到固定阈值的明显上升项。

**Architecture:** 新增纯后端 `trends.py` 聚合模块和独立 `/api/records/trends` 路由，保持固定趋势与现有概览范围解耦。前端用原生 JavaScript 渲染趋势指标和可下钻列表，复用现有筛选、导出和滚动链路；不增加数据库、前端依赖、轮询或模型调用。

**Tech Stack:** Python 3.12、FastAPI、Jinja2、原生 JavaScript/CSS、pytest、Node.js 内置 `node:test`/`assert`/`vm`。

---

## 文件结构

- Create: `src/customer_issue_agent/trends.py`，负责周期划分、问题簇聚合、阈值和稳定排序。
- Modify: `src/customer_issue_agent/app.py`，暴露独立趋势 GET 接口。
- Modify: `src/customer_issue_agent/templates/index.html`，提供趋势区域和加载空壳。
- Modify: `src/customer_issue_agent/static/app.js`，加载、渲染、绑定趋势下钻，并在新分析后刷新洞察。
- Modify: `src/customer_issue_agent/static/styles.css`，增加趋势卡片、方向和异常标签样式。
- Create: `tests/test_trends.py`，覆盖所有后端周期与聚合边界。
- Modify: `tests/test_app.py`，锁定 API、模板、JavaScript 和 CSS 契约。
- Create: `tests/js/test_issue_trends.mjs`，加载真实 `app.js` 验证渲染、下钻和刷新编排。
- Modify: `README.md`，说明趋势口径、阈值和下钻方式。

### Task 1: 实现确定性双周期趋势聚合

**Files:**
- Create: `tests/test_trends.py`
- Create: `src/customer_issue_agent/trends.py`

- [ ] **Step 1: 写入趋势模块的失败测试**

创建 `tests/test_trends.py`：

```python
from datetime import UTC, datetime, timedelta

from customer_issue_agent.trends import build_issue_trends


NOW = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)


def _record(
    created_at: datetime | str | None,
    *,
    platform: object = "Amazon",
    issue_category: object = "function_use",
    responsibility: object = "customer_service_training",
) -> dict:
    value = created_at.isoformat() if isinstance(created_at, datetime) else created_at
    record = {
        "analysis": {
            "request": {"platform": platform},
            "attribution": {
                "issue_category": issue_category,
                "primary_responsibility": responsibility,
            },
        }
    }
    if value is not None:
        record["created_at"] = value
    return record


def test_build_issue_trends_uses_two_disjoint_seven_day_periods():
    records = [
        _record(NOW),
        _record(NOW - timedelta(days=7)),
        _record(NOW - timedelta(days=7, seconds=1)),
        _record(NOW - timedelta(days=14)),
        _record(NOW - timedelta(days=14, seconds=1)),
        _record(NOW + timedelta(seconds=1)),
        _record("not-a-date"),
        _record(None),
        _record("2026-07-30T12:00:00"),
    ]

    result = build_issue_trends(records, now=NOW)

    assert result["period"] == "7d"
    assert result["current_period"] == {
        "start": (NOW - timedelta(days=7)).isoformat(),
        "end": NOW.isoformat(),
        "total_records": 3,
    }
    assert result["previous_period"] == {
        "start": (NOW - timedelta(days=14)).isoformat(),
        "end": (NOW - timedelta(days=7)).isoformat(),
        "total_records": 2,
    }
    assert result["total_delta"] == 1


def test_build_issue_trends_returns_union_threshold_and_stable_order():
    records = []
    records.extend(
        _record(NOW - timedelta(days=1), platform="Amazon")
        for _ in range(3)
    )
    records.append(_record(NOW - timedelta(days=8), platform="Amazon"))
    records.extend(
        _record(
            NOW - timedelta(days=8),
            platform="TikTok Shop",
            issue_category="product_fault",
            responsibility="product",
        )
        for _ in range(3)
    )
    records.extend(
        _record(
            NOW - timedelta(days=1),
            platform="eBay",
            issue_category="installation",
            responsibility="operations",
        )
        for _ in range(2)
    )
    records.extend(
        _record(
            created_at,
            platform="Shopee",
            issue_category="accessory",
            responsibility="product",
        )
        for created_at in (NOW - timedelta(days=1), NOW - timedelta(days=8))
    )

    result = build_issue_trends(records, now=NOW)

    assert result["clusters"] == [
        {
            "platform": "TikTok Shop",
            "issue_category": "product_fault",
            "responsibility": "product",
            "current_count": 0,
            "previous_count": 3,
            "delta": -3,
            "significant_increase": False,
        },
        {
            "platform": "Amazon",
            "issue_category": "function_use",
            "responsibility": "customer_service_training",
            "current_count": 3,
            "previous_count": 1,
            "delta": 2,
            "significant_increase": True,
        },
        {
            "platform": "eBay",
            "issue_category": "installation",
            "responsibility": "operations",
            "current_count": 2,
            "previous_count": 0,
            "delta": 2,
            "significant_increase": False,
        },
    ]


def test_build_issue_trends_handles_empty_unknown_and_period_fallback():
    empty = build_issue_trends([], period="30d", now=NOW)

    assert empty == {
        "period": "7d",
        "current_period": {
            "start": (NOW - timedelta(days=7)).isoformat(),
            "end": NOW.isoformat(),
            "total_records": 0,
        },
        "previous_period": {
            "start": (NOW - timedelta(days=14)).isoformat(),
            "end": (NOW - timedelta(days=7)).isoformat(),
            "total_records": 0,
        },
        "total_delta": 0,
        "clusters": [],
    }

    unknown = build_issue_trends(
        [
            _record(
                NOW - timedelta(days=1),
                platform=" ",
                issue_category=None,
                responsibility=[],
            ),
            {
                "created_at": (NOW - timedelta(days=2)).isoformat(),
                "analysis": [],
            },
        ],
        now=NOW,
    )

    assert unknown["clusters"] == [
        {
            "platform": "unknown",
            "issue_category": "unknown",
            "responsibility": "unknown",
            "current_count": 2,
            "previous_count": 0,
            "delta": 2,
            "significant_increase": False,
        }
    ]
```

- [ ] **Step 2: 运行测试并确认模块不存在**

```powershell
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
python -m pytest tests/test_trends.py -q
```

Expected: collection fails with `ModuleNotFoundError: No module named 'customer_issue_agent.trends'`.

- [ ] **Step 3: 写入最小完整聚合实现**

创建 `src/customer_issue_agent/trends.py`：

```python
from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

IssueClusterKey = tuple[str, str, str]
PERIOD_DAYS = 7


def build_issue_trends(
    records: list[dict[str, Any]],
    *,
    period: str = "7d",
    now: datetime | None = None,
) -> dict[str, Any]:
    del period
    current_end = _as_utc(now or datetime.now(UTC))
    current_start = current_end - timedelta(days=PERIOD_DAYS)
    previous_start = current_start - timedelta(days=PERIOD_DAYS)
    current_clusters: Counter[IssueClusterKey] = Counter()
    previous_clusters: Counter[IssueClusterKey] = Counter()
    current_total = 0
    previous_total = 0

    for record in records:
        created_at = _parse_created_at(record.get("created_at"))
        if created_at is None or created_at < previous_start or created_at > current_end:
            continue
        key = _issue_cluster_key(record)
        if created_at >= current_start:
            current_clusters[key] += 1
            current_total += 1
        else:
            previous_clusters[key] += 1
            previous_total += 1

    clusters = []
    for platform, issue_category, responsibility in current_clusters.keys() | previous_clusters.keys():
        key = (platform, issue_category, responsibility)
        current_count = current_clusters[key]
        previous_count = previous_clusters[key]
        delta = current_count - previous_count
        if delta == 0:
            continue
        clusters.append(
            {
                "platform": platform,
                "issue_category": issue_category,
                "responsibility": responsibility,
                "current_count": current_count,
                "previous_count": previous_count,
                "delta": delta,
                "significant_increase": current_count >= 3 and delta >= 2,
            }
        )

    clusters.sort(key=_cluster_sort_key)
    return {
        "period": "7d",
        "current_period": {
            "start": current_start.isoformat(),
            "end": current_end.isoformat(),
            "total_records": current_total,
        },
        "previous_period": {
            "start": previous_start.isoformat(),
            "end": current_start.isoformat(),
            "total_records": previous_total,
        },
        "total_delta": current_total - previous_total,
        "clusters": clusters,
    }


def _issue_cluster_key(record: dict[str, Any]) -> IssueClusterKey:
    analysis = _mapping(record.get("analysis"))
    request = _mapping(analysis.get("request"))
    attribution = _mapping(analysis.get("attribution"))
    return (
        _value(request.get("platform")),
        _value(attribution.get("issue_category")),
        _value(attribution.get("primary_responsibility")),
    )


def _cluster_sort_key(item: dict[str, Any]) -> tuple[Any, ...]:
    return (
        -abs(item["delta"]),
        -item["current_count"],
        item["platform"].casefold(),
        item["platform"],
        item["issue_category"].casefold(),
        item["issue_category"],
        item["responsibility"].casefold(),
        item["responsibility"],
    )


def _parse_created_at(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return _as_utc(parsed)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _value(value: object) -> str:
    if not isinstance(value, str):
        return "unknown"
    stripped = str(value).strip()
    return stripped or "unknown"
```

- [ ] **Step 4: 运行聚合测试并提交**

```powershell
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
python -m pytest tests/test_trends.py -q
git diff --check
git add tests/test_trends.py src/customer_issue_agent/trends.py
git commit -m "feat: aggregate issue trend periods"
```

Expected: `3 passed`，差异检查无错误，提交成功。

### Task 2: 暴露趋势 API 和页面区域

**Files:**
- Modify: `tests/test_app.py`
- Modify: `src/customer_issue_agent/app.py:20`
- Modify: `src/customer_issue_agent/templates/index.html:109`
- Modify: `src/customer_issue_agent/static/styles.css:515`

- [ ] **Step 1: 写入 API、模板和样式失败契约测试**

在 `tests/test_app.py` 末尾加入：

```python
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
```

- [ ] **Step 2: 运行测试并确认路由与标记缺失**

```powershell
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
python -m pytest tests/test_app.py -k "records_trends or issue_trend" -q
```

Expected: 4 个测试失败；API 返回 404，模板和 CSS 断言指出趋势区域尚不存在。

- [ ] **Step 3: 新增趋势 API**

在 `src/customer_issue_agent/app.py` 导入：

```python
from customer_issue_agent.trends import build_issue_trends
```

在 summary 路由之后、`return app` 之前加入：

```python
    @app.get("/api/records/trends")
    async def records_trends(period: str = "7d") -> dict:
        return build_issue_trends(store.list_records(), period=period)
```

- [ ] **Step 4: 新增趋势模板空壳**

在 `src/customer_issue_agent/templates/index.html` 的 `records-summary` 结束标签之后、最近记录之前加入：

```html
        <section
          id="issue-trends"
          class="trend-dashboard panel"
          aria-label="近 7 天问题趋势"
          aria-live="polite"
        >
          <div class="section-heading">
            <div>
              <p class="eyebrow">周期对比</p>
              <h2>近 7 天趋势</h2>
            </div>
            <span class="trend-period">对比前 7 天</span>
          </div>
          <div id="trend-content" class="trend-loading">趋势加载中...</div>
        </section>
```

- [ ] **Step 5: 新增趋势视觉样式和移动端规则**

在 `src/customer_issue_agent/static/styles.css` 的 summary 样式之后加入：

```css
.trend-dashboard {
  margin-top: 24px;
}

.trend-period,
.trend-loading,
.trend-error,
.trend-empty {
  color: var(--muted);
}

.trend-metrics {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.trend-card {
  margin-top: 16px;
}

.trend-card h3 {
  margin: 0;
}

.trend-list {
  display: grid;
  gap: 10px;
  padding: 0;
  margin: 14px 0 0;
  list-style: none;
}

.trend-row,
.trend-row-button {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 14px;
}

.trend-row {
  padding-top: 10px;
  border-top: 1px solid var(--line);
}

.trend-row:first-child {
  padding-top: 0;
  border-top: 0;
}

.trend-row-button {
  width: 100%;
  border: 0;
  padding: 0;
  background: transparent;
  color: inherit;
  cursor: pointer;
  font: inherit;
  text-align: left;
}

.trend-row-button:hover .trend-cluster-label strong,
.trend-row-button:focus-visible .trend-cluster-label strong {
  color: var(--accent);
}

.trend-row-button:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 4px;
}

.trend-cluster-label {
  display: grid;
  gap: 4px;
}

.trend-cluster-label strong {
  margin-top: 0;
  font-size: 16px;
}

.trend-cluster-label small {
  color: var(--muted);
  font-weight: 600;
}

.trend-counts {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  white-space: nowrap;
}

.trend-change {
  min-width: 38px;
  font-weight: 800;
  text-align: right;
}

.trend-change.is-up {
  color: #b4472d;
}

.trend-change.is-down {
  color: #28705f;
}

.summary-card .trend-alert {
  border: 1px solid rgba(180, 71, 45, 0.35);
  border-radius: 999px;
  padding: 4px 8px;
  background: rgba(180, 71, 45, 0.1);
  color: #8f321f;
  font-size: 12px;
  font-weight: 800;
}
```

把 `@media (max-width: 900px)` 中的网格选择器改为：

```css
  .summary-metrics,
  .summary-grid,
  .trend-metrics {
    grid-template-columns: 1fr;
  }
```

在 `@media (max-width: 720px)` 中加入：

```css
  .trend-row,
  .trend-row-button {
    grid-template-columns: 1fr;
  }

  .trend-counts {
    justify-content: flex-start;
    flex-wrap: wrap;
  }
```

- [ ] **Step 6: 运行契约测试并提交**

```powershell
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
python -m pytest tests/test_app.py -k "records_trends or issue_trend" -q
node --check src/customer_issue_agent/static/app.js
git diff --check
git add tests/test_app.py src/customer_issue_agent/app.py src/customer_issue_agent/templates/index.html src/customer_issue_agent/static/styles.css
git commit -m "feat: expose issue trend dashboard"
```

Expected: 4 个 pytest 通过，语法与差异检查通过，提交成功。

### Task 3: 加载、渲染并下钻趋势问题簇

**Files:**
- Create: `tests/js/test_issue_trends.mjs`
- Modify: `tests/test_app.py`
- Modify: `src/customer_issue_agent/static/app.js:33`

- [ ] **Step 1: 创建真实 app.js 的趋势行为测试**

创建 `tests/js/test_issue_trends.mjs`：

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
}

class FakeElement {
  constructor({ dataset = {}, options = [], textContent = "", value = "" } = {}) {
    this.dataset = { ...dataset };
    this.options = options.map((optionValue) => ({ value: optionValue }));
    this.textContent = textContent;
    this.value = value;
    this.innerHTML = "";
    this.classList = new FakeClassList();
    this.disabled = false;
    this.listeners = new Map();
    this.selectors = new Map();
    this.resetCalls = 0;
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

  click() {
    this.listeners.get("click")?.({ preventDefault() {} });
  }

  reset() {
    this.resetCalls += 1;
  }
}

function loadApp() {
  const elements = new Map([
    ["trend-content", new FakeElement()],
    ["summary-range", new FakeElement({ value: "all" })],
    ["platform-filter", new FakeElement()],
    [
      "issue-filter",
      new FakeElement({ options: ["", "installation", "function_use", "product_fault", "accessory"] }),
    ],
    [
      "responsibility-filter",
      new FakeElement({ options: ["", "operations", "customer_service_training", "product"] }),
    ],
    ["record-search", new FakeElement({ value: "保留关键词" })],
    ["feedback-filter", new FakeElement({ value: "unreviewed" })],
  ]);
  const document = {
    domReady: null,
    addEventListener(event, callback) {
      if (event === "DOMContentLoaded") this.domReady = callback;
    },
    createElement: () => new FakeElement(),
    getElementById: (id) => elements.get(id) || null,
    querySelector: () => null,
    querySelectorAll: () => [],
  };
  const context = vm.createContext({
    URLSearchParams,
    clearTimeout,
    console,
    document,
    FormData: class FormData {},
    navigator: {},
    setTimeout,
    window: { location: {} },
  });
  vm.runInContext(appScript, context);
  return { context, document, elements };
}

function cluster(overrides = {}) {
  return {
    platform: "Amazon",
    issue_category: "function_use",
    responsibility: "customer_service_training",
    current_count: 3,
    previous_count: 1,
    delta: 2,
    significant_increase: true,
    ...overrides,
  };
}

test("趋势变化文案保留正负方向", () => {
  const { context } = loadApp();

  assert.equal(context.trendChangeLabel(2), "+2");
  assert.equal(context.trendChangeLabel(-3), "-3");
  assert.equal(context.trendChangeLabel(0), "0");
});

test("趋势列表只渲染前五项并标记明显上升", () => {
  const { context } = loadApp();
  const items = Array.from({ length: 6 }, (_, index) => cluster({
    platform: `Amazon ${index + 1}`,
    significant_increase: index === 0,
  }));

  const html = context.issueTrendRows(items);

  assert.equal((html.match(/data-issue-trend-filter/g) || []).length, 5);
  assert.equal((html.match(/明显上升/g) || []).length, 1);
  assert.match(html, /Amazon 5/);
  assert.doesNotMatch(html, /Amazon 6/);
  assert.match(html, /本期 3/);
  assert.match(html, /上期 1/);
  assert.match(html, /\+2/);
});

test("unknown 趋势只读且空趋势显示稳定状态", () => {
  const { context, elements } = loadApp();
  const unknownHtml = context.issueTrendRows([cluster({ platform: "unknown" })]);

  assert.doesNotMatch(unknownHtml, /data-issue-trend-filter/);

  context.renderIssueTrends({
    current_period: { total_records: 0 },
    previous_period: { total_records: 0 },
    total_delta: 0,
    clusters: [],
  });

  assert.match(elements.get("trend-content").innerHTML, /最近两个周期暂无明显变化/);
});

test("有效趋势下钻设置七天范围并保留关键词与复核状态", () => {
  const { context, elements } = loadApp();
  const calls = [];
  context.refreshRecordFilterViews = () => calls.push("filters");
  context.loadRecordsSummary = () => calls.push("summary");
  context.scrollToRecentRecords = () => calls.push("scroll");

  context.applyIssueTrendFilter({
    platform: "Amazon",
    issueCategory: "function_use",
    responsibility: "customer_service_training",
  });

  assert.equal(elements.get("summary-range").value, "7d");
  assert.equal(elements.get("platform-filter").value, "Amazon");
  assert.equal(elements.get("issue-filter").value, "function_use");
  assert.equal(elements.get("responsibility-filter").value, "customer_service_training");
  assert.equal(elements.get("record-search").value, "保留关键词");
  assert.equal(elements.get("feedback-filter").value, "unreviewed");
  assert.deepEqual(calls, ["filters", "scroll", "summary"]);
});

test("无效趋势下钻不改变时间和筛选", () => {
  const { context, elements } = loadApp();

  context.applyIssueTrendFilter({
    platform: "unknown",
    issueCategory: "function_use",
    responsibility: "customer_service_training",
  });

  assert.equal(elements.get("summary-range").value, "all");
  assert.equal(elements.get("platform-filter").value, "");
});

test("趋势加载成功渲染且失败只更新趋势区域", async () => {
  const success = loadApp();
  const payload = {
    current_period: { total_records: 3 },
    previous_period: { total_records: 1 },
    total_delta: 2,
    clusters: [cluster()],
  };
  success.context.fetch = async () => ({ ok: true, json: async () => payload });
  let rendered = null;
  success.context.renderIssueTrends = (value) => { rendered = value; };

  await success.context.loadIssueTrends();

  assert.equal(rendered, payload);

  const failure = loadApp();
  failure.context.fetch = async () => ({
    ok: false,
    json: async () => ({ detail: "趋势暂不可用" }),
  });

  await failure.context.loadIssueTrends();

  assert.match(failure.elements.get("trend-content").innerHTML, /趋势暂不可用/);
  assert.match(failure.elements.get("trend-content").innerHTML, /trend-error/);
});

test("页面初始化只调用一次趋势加载", () => {
  const { context, document } = loadApp();
  const noops = [
    "bindTabs",
    "bindAnalysisForm",
    "bindBatchForm",
    "bindFeedbackForms",
    "bindSummaryRange",
    "bindFilteredExport",
    "bindRecordFilters",
    "bindReviewQueueToggle",
    "bindRecordDetails",
    "bindRecordCopyActions",
  ];
  noops.forEach((name) => { context[name] = () => {}; });
  context.loadRecordsSummary = () => {};
  let trendLoads = 0;
  context.loadIssueTrends = () => { trendLoads += 1; };

  document.domReady();

  assert.equal(trendLoads, 1);
});
```

- [ ] **Step 2: 运行 Node 测试并确认趋势函数缺失**

```powershell
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
node --test tests/js/test_issue_trends.mjs
```

Expected: 7 个测试因 `trendChangeLabel`、`issueTrendRows`、`renderIssueTrends`、`applyIssueTrendFilter` 或 `loadIssueTrends` 不存在而失败。

- [ ] **Step 3: 实现趋势加载、渲染与下钻**

在 `DOMContentLoaded` 中的 `loadRecordsSummary();` 后加入：

```javascript
  loadIssueTrends();
```

在 `renderRecordsSummary()` 之前加入以下完整函数组：

```javascript
async function loadIssueTrends() {
  const container = document.getElementById("trend-content");
  if (!container) {
    return;
  }

  try {
    const response = await fetch("/api/records/trends?period=7d");
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(readError(payload));
    }
    renderIssueTrends(payload);
  } catch (error) {
    container.innerHTML = `<p class="trend-error">${escapeHtml(error.message || "趋势加载失败，请刷新页面重试。")}</p>`;
  }
}

function renderIssueTrends(trends) {
  const container = document.getElementById("trend-content");
  if (!container) {
    return;
  }

  container.innerHTML = `
    <div class="summary-metrics trend-metrics">
      ${summaryMetric("近 7 天记录", trends.current_period?.total_records ?? 0)}
      ${summaryMetric("前 7 天记录", trends.previous_period?.total_records ?? 0)}
      ${summaryMetric("净变化", trendChangeLabel(trends.total_delta ?? 0))}
    </div>
    <article class="summary-card trend-card">
      <h3>变化最大的 Top 5 问题簇</h3>
      ${issueTrendRows(trends.clusters || [])}
    </article>
  `;
  bindIssueTrendFilters(container);
}

function issueTrendRows(items = []) {
  const rows = items.slice(0, 5);
  if (!rows.length) {
    return `<p class="trend-empty">最近两个周期暂无明显变化。</p>`;
  }
  return `<ul class="trend-list">${rows.map(issueTrendRow).join("")}</ul>`;
}

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
  const alert = item.significant_increase
    ? `<span class="trend-alert">明显上升</span>`
    : "";
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
    <li class="trend-row">
      <button
        class="trend-row-button"
        type="button"
        data-issue-trend-filter
        data-trend-platform="${escapeHtml(platform)}"
        data-trend-issue-category="${escapeHtml(issueCategory)}"
        data-trend-responsibility="${escapeHtml(responsibility)}"
        aria-label="${escapeHtml(ariaLabel)}"
      >${content}</button>
    </li>
  `;
}

function trendChangeLabel(value) {
  const number = Number(value) || 0;
  return number > 0 ? `+${number}` : String(number);
}

function bindIssueTrendFilters(root = document) {
  root.querySelectorAll("[data-issue-trend-filter]").forEach((button) => {
    if (button.dataset.bound === "true") {
      return;
    }
    button.dataset.bound = "true";
    button.addEventListener("click", () => {
      applyIssueTrendFilter({
        platform: button.dataset.trendPlatform || "",
        issueCategory: button.dataset.trendIssueCategory || "",
        responsibility: button.dataset.trendResponsibility || "",
      });
    });
  });
}

function applyIssueTrendFilter({ platform, issueCategory, responsibility }) {
  const range = document.getElementById("summary-range");
  const platformFilter = document.getElementById("platform-filter");
  if (
    !range
    || !platformFilter
    || !isSummaryIssueClusterFilterable(platform, issueCategory, responsibility)
  ) {
    return;
  }

  range.value = "7d";
  applySummaryIssueClusterFilter({ platform, issueCategory, responsibility });
  loadRecordsSummary();
}
```

- [ ] **Step 4: 锁定 JavaScript 趋势函数契约**

在 `tests/test_app.py` 末尾加入：

```python
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
```

- [ ] **Step 5: 运行趋势行为和契约测试并提交**

```powershell
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
node --test tests/js/test_issue_trends.mjs
python -m pytest tests/test_app.py -k "issue_trend" -q
node --check src/customer_issue_agent/static/app.js
git diff --check
git add tests/js/test_issue_trends.mjs tests/test_app.py src/customer_issue_agent/static/app.js
git commit -m "feat: render and drill into issue trends"
```

Expected: Node `7 pass, 0 fail`，相关 pytest 全部通过，语法和差异检查通过。

### Task 4: 在分析成功后刷新概览与趋势一次

**Files:**
- Modify: `tests/js/test_issue_trends.mjs`
- Modify: `src/customer_issue_agent/static/app.js:117`

- [ ] **Step 1: 追加单条、批量和反馈刷新行为测试**

把以下 helper 和测试追加到 `tests/js/test_issue_trends.mjs`：

```javascript
function createSubmitForm(endpoint) {
  const button = new FakeElement({ textContent: "提交" });
  const form = new FakeElement({ dataset: { endpoint } });
  form.setSelector("button[type='submit']", button);
  const message = new FakeElement();
  form.setSelector(".form-message", message);
  return { button, form, message };
}

test("单条分析成功后概览和趋势各刷新一次", async () => {
  const { context } = loadApp();
  const { form } = createSubmitForm("/api/analyze");
  const errorBox = new FakeElement();
  const calls = [];
  context.fetch = async () => ({
    ok: true,
    json: async () => ({ record_id: "one", analysis: {} }),
  });
  context.renderAnalysisResult = () => calls.push("render");
  context.bindFeedbackForms = () => calls.push("bind-feedback");
  context.prependRecentRecord = () => calls.push("recent");
  context.loadRecordsSummary = () => calls.push("summary");
  context.loadIssueTrends = () => calls.push("trends");

  await context.submitAnalysisForm(form, errorBox);

  assert.equal(calls.filter((value) => value === "summary").length, 1);
  assert.equal(calls.filter((value) => value === "trends").length, 1);
  assert.equal(form.resetCalls, 1);
});

test("批量分析成功后按批次刷新概览和趋势而不是按记录刷新", async () => {
  const { context } = loadApp();
  const { form } = createSubmitForm("/api/analyze-batch-file");
  const errorBox = new FakeElement();
  const calls = [];
  context.fetch = async () => ({
    ok: true,
    json: async () => ({
      batch_id: "batch",
      count: 2,
      records: [{ record_id: "one" }, { record_id: "two" }],
    }),
  });
  context.renderBatchResults = () => calls.push("render");
  context.prependRecentRecord = () => calls.push("recent");
  context.loadRecordsSummary = () => calls.push("summary");
  context.loadIssueTrends = () => calls.push("trends");

  await context.submitBatchForm(form, errorBox);

  assert.equal(calls.filter((value) => value === "recent").length, 2);
  assert.equal(calls.filter((value) => value === "summary").length, 1);
  assert.equal(calls.filter((value) => value === "trends").length, 1);
  assert.equal(form.resetCalls, 1);
});

test("反馈保存成功不刷新固定问题趋势", async () => {
  const { context } = loadApp();
  const { form } = createSubmitForm("/api/records/one/feedback");
  let trendLoads = 0;
  context.fetch = async () => ({
    ok: true,
    json: async () => ({
      record_id: "one",
      feedback: { accepted: true, note: "" },
    }),
  });
  context.syncFeedbackUi = () => {};
  context.refreshRecordFilterViews = () => {};
  context.loadRecordsSummary = () => {};
  context.loadIssueTrends = () => { trendLoads += 1; };

  await context.submitFeedbackForm(form);

  assert.equal(trendLoads, 0);
});
```

- [ ] **Step 2: 运行 Node 测试并确认两个分析刷新用例失败**

```powershell
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
node --test tests/js/test_issue_trends.mjs
```

Expected: 原 7 个测试和反馈测试通过；单条与批量测试因 `summary`、`trends` 调用次数为 0 而失败。

- [ ] **Step 3: 在两个成功路径加入批次级刷新**

在 `submitAnalysisForm()` 的 `prependRecentRecord(payload);` 后加入：

```javascript
    loadRecordsSummary();
    loadIssueTrends();
```

在 `submitBatchForm()` 的 `payload.records.forEach(...)` 完成后、`form.reset();` 之前加入：

```javascript
    loadRecordsSummary();
    loadIssueTrends();
```

不要修改 `submitFeedbackForm()`，反馈不改变趋势问题簇。

- [ ] **Step 4: 运行刷新测试和完整前端行为测试并提交**

```powershell
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
node --test tests/js/test_feedback_ui.mjs tests/js/test_issue_trends.mjs
python -m pytest tests/test_app.py -k "analyze or feedback or issue_trend" -q
node --check src/customer_issue_agent/static/app.js
git diff --check
git add tests/js/test_issue_trends.mjs src/customer_issue_agent/static/app.js
git commit -m "feat: refresh insights after analysis"
```

Expected: Node `10` 个趋势测试加 `6` 个反馈测试全部通过；相关 pytest、语法和差异检查通过。

### Task 5: 文档、完整验证和目标 PR 迁移

**Files:**
- Modify: `README.md:108`

- [ ] **Step 1: 更新运营概览使用说明**

在 README 的运营概览段落加入：

```markdown
“近 7 天趋势”会固定对比最近 7 天和前 7 天，按平台、问题类型和责任方展示数量变化最大的 Top 5 问题簇。当前周期至少 3 条且比上一周期增加至少 2 条时标记为“明显上升”；少量 `0 → 1` 或 `1 → 2` 只展示普通变化，不触发异常提示。

点击有效趋势问题簇会填入平台、问题类型和责任方筛选，并把运营概览及筛选导出范围切换到最近 7 天，同时保留已有关键词和复核状态。趋势统计完全基于本地 JSONL，不会后台轮询，也不会调用模型。
```

- [ ] **Step 2: 运行完整验证**

每条命令独立初始化 UTF-8 输出编码：

```powershell
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
python -m pytest -q
```

```powershell
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
node --test tests/js/test_feedback_ui.mjs tests/js/test_issue_trends.mjs
```

```powershell
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
node --check src/customer_issue_agent/static/app.js
```

```powershell
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
git diff --check
```

Expected: pytest 全绿；Node 16 个测试通过；JavaScript 语法和差异检查无错误。

- [ ] **Step 3: 检查 UTF-8、范围并提交文档**

```powershell
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$StrictUtf8 = [System.Text.UTF8Encoding]::new($false, $true)
$Files = @(
  "README.md",
  "src/customer_issue_agent/trends.py",
  "src/customer_issue_agent/app.py",
  "src/customer_issue_agent/templates/index.html",
  "src/customer_issue_agent/static/app.js",
  "src/customer_issue_agent/static/styles.css",
  "tests/test_trends.py",
  "tests/test_app.py",
  "tests/js/test_issue_trends.mjs"
)
foreach ($File in $Files) {
  $null = $StrictUtf8.GetString([System.IO.File]::ReadAllBytes((Resolve-Path $File)))
}
git status --short
git diff --stat HEAD
git add README.md
git commit -m "docs: describe issue trend alerts"
```

Expected: 严格 UTF-8 解码无异常；范围只包含本计划文件；文档提交成功。

- [ ] **Step 4: 在目标仓库干净临时 worktree 中复验并快进推送**

使用 HTTP/1.1 临时参数读取目标分支，避免当前环境 Git/libcurl 的默认协议连接重置；不修改全局 Git 配置：

```powershell
$TargetRemote = "https://github.com/ARIUM-hub/Agent-Operations-Workflow.git"
git -c http.version=HTTP/1.1 ls-remote $TargetRemote refs/heads/codex/customer-issue-agent-mvp
```

从读取到的目标 head 创建一次性干净 worktree，只 cherry-pick 本功能的设计、计划和实施提交。再次运行 Task 5 Step 2 的四项完整验证，并检查相对目标 head 只包含本计划列出的文件。

最后使用普通快进推送：

```powershell
$TargetRemote = "https://github.com/ARIUM-hub/Agent-Operations-Workflow.git"
git -c http.version=HTTP/1.1 push $TargetRemote HEAD:codex/customer-issue-agent-mvp
```

推送后读取 `refs/heads/codex/customer-issue-agent-mvp` 和 `refs/pull/2/head`，两者必须等于临时 worktree 的完整 head SHA。确认后只删除本次临时 worktree 和临时分支；不修改旧 `origin`，不删除开发 worktree。

## 自检结果

- Spec coverage：周期边界、未来与非法日期、嵌套结构异常、问题簇并集、阈值、排序、Top 5、独立 API、加载降级、点击下钻、分析刷新、反馈不刷新、移动端和无模型调用均有对应任务与测试。
- Placeholder scan：所有代码步骤都给出完整新增文件、完整函数组或精确插入块，没有省略式实现指令。
- Naming consistency：后端统一使用 `build_issue_trends`、`current_period`、`previous_period`、`total_delta`、`significant_increase`；前端统一使用 `loadIssueTrends`、`renderIssueTrends`、`issueTrendRows`、`applyIssueTrendFilter`。
- Scope control：不修改存储、领域模型、反馈语义、CSV 字段、依赖或供应商逻辑。
- Refresh consistency：页面一次、单条一次、批次一次；概览范围和普通筛选不刷新固定趋势，反馈保存不刷新趋势。
- Visual consistency：可点击与只读趋势行共用双列网格，移动端同步折为单列，并覆盖概览卡片对趋势标签的继承样式。
- PowerShell isolation：验证命令各自初始化 UTF-8，目标 Git 操作使用单次命令级 HTTP/1.1 参数。
