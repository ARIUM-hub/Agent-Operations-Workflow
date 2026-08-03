# 反馈保存后 UI 即时同步 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (recommended) or superpowers:subagent-driven-development when explicitly needed for independent tasks. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在人工反馈 POST 成功后，同步页面中同一记录的所有状态、详情、搜索、待复核数量和运营概览，无需刷新页面。

**Architecture:** 继续由 `submitFeedbackForm()` 负责网络请求与表单消息，在成功分支调用一个纯本地同步入口。单条结果、批次结果和最近记录通过统一的 `data-record-*` 契约被同一组 helper 更新；现有筛选刷新和概览加载函数保持唯一数据刷新入口。

**Tech Stack:** FastAPI/Jinja2、原生 JavaScript、pytest、Node.js 内置 `node:test`/`assert`/`vm`，不增加 npm 包或模型调用。

---

## 文件结构

- Modify: `src/customer_issue_agent/templates/index.html`，为服务端渲染的最近记录提供同步所需 DOM 钩子。
- Modify: `src/customer_issue_agent/static/app.js`，统一动态卡片 DOM 契约，实现反馈状态同步并接入提交成功流程。
- Modify: `tests/test_app.py`，锁定服务端模板和动态 JavaScript 生成器必须暴露的钩子。
- Create: `tests/js/test_feedback_ui.mjs`，用轻量 DOM stub 加载真实 `app.js`，验证同步行为和提交编排。
- Modify: `README.md`，说明保存反馈后页面即时同步的用户可见行为。

### Task 1: 统一三类记录视图的 DOM 状态契约

**Files:**
- Modify: `tests/test_app.py`
- Modify: `src/customer_issue_agent/templates/index.html:173`
- Modify: `src/customer_issue_agent/static/app.js:129`

- [ ] **Step 1: 写入服务端模板和动态生成器的失败契约测试**

在 `tests/test_app.py` 中加入以下测试：

```python
def test_recent_records_expose_feedback_sync_dom_contract(tmp_path):
    storage_path = tmp_path / "analyses.jsonl"
    app = create_app(storage_path=storage_path)
    client = TestClient(app)
    analysis_response = client.post(
        "/api/analyze",
        data={"platform": "Amazon", "conversation_text": "Customer: not working"},
    )
    record_id = analysis_response.json()["record_id"]
    client.post(
        f"/api/records/{record_id}/feedback",
        data={"accepted": "false", "note": "旧备注"},
    )

    response = client.get("/")

    assert response.status_code == 200
    html = response.text
    assert 'data-record-meta' in html
    assert 'data-record-feedback-status' in html
    assert 'data-record-feedback-note' in html
    assert 'data-search-base-text=' in html
    assert f'data-record-id="{record_id}"' in html
    assert 'data-feedback-status="corrected"' in html


def test_dynamic_record_renderers_expose_feedback_sync_dom_contract(tmp_path):
    app = create_app(storage_path=tmp_path / "analyses.jsonl")
    client = TestClient(app)

    response = client.get("/static/app.js")

    assert response.status_code == 200
    script = response.text
    assert 'result.dataset.recordId = payload.record_id' in script
    assert 'result.dataset.feedbackStatus = "unreviewed"' in script
    assert 'article.dataset.feedbackStatus = "unreviewed"' in script
    assert 'article.dataset.searchBaseText = searchBaseText' in script
    assert 'data-record-meta' in script
    assert 'data-batch-pending-count' in script
    assert 'data-record-feedback-status' in script
    assert 'data-record-feedback-note' in script
```

- [ ] **Step 2: 运行测试并确认因钩子缺失而失败**

```powershell
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
python -m pytest tests/test_app.py -k "feedback_sync_dom_contract" -q
```

Expected: `2 failed`，断言指出 `data-record-meta`、`data-search-base-text` 或动态记录状态赋值尚不存在，而不是导入或编码错误。

- [ ] **Step 3: 为服务端最近记录补齐钩子**

将 `src/customer_issue_agent/templates/index.html` 中最近记录 `<article>` 的搜索属性和元信息容器改为：

```html
data-feedback-status="{{ 'accepted' if record.feedback and record.feedback.accepted else 'corrected' if record.feedback else 'unreviewed' }}"
data-search-base-text="{{ record.id }} {{ record.analysis.request.platform }} {{ record.analysis.report }}"
data-search-text="{{ record.id }} {{ record.analysis.request.platform }} {{ record.analysis.report }} {{ record.feedback.note if record.feedback and record.feedback.note else '' }}"
>
  <div class="record-meta" data-record-meta>
```

将详情中的人工字段改为：

```html
<div>
  <dt>人工复核</dt>
  <dd data-record-feedback-status>{{ "已认可" if record.feedback and record.feedback.accepted else "已修正" if record.feedback else "未复核" }}</dd>
</div>
<div>
  <dt>人工备注</dt>
  <dd data-record-feedback-note>{{ record.feedback.note if record.feedback and record.feedback.note else "暂无信息" }}</dd>
</div>
```

- [ ] **Step 4: 为动态单条、批次和最近记录补齐同一契约**

用以下完整函数替换 `renderAnalysisResult(payload)`，设置初始状态并给 `.summary-strip` 加元信息钩子：

```javascript
function renderAnalysisResult(payload) {
  const result = document.getElementById("analysis-result");
  const analysis = payload.analysis;
  const attribution = analysis.attribution;
  result.dataset.recordId = payload.record_id;
  result.dataset.feedbackStatus = "unreviewed";
  result.innerHTML = `
    <div class="result-header">
      <div>
        <p class="eyebrow">分析完成</p>
        <h2>${escapeHtml(analysis.request.platform)}</h2>
      </div>
      <span class="record-id">#${escapeHtml(payload.record_id.slice(0, 8))}</span>
    </div>
    <div class="summary-strip" data-record-meta>
      <span>${labelFor("issue_category", attribution.issue_category)}</span>
      <span>${labelFor("responsibility", attribution.primary_responsibility)}</span>
      <span>${labelFor("evidence", attribution.evidence_strength)}</span>
    </div>
    <div class="result-grid">
      ${resultCard("客户问题", attribution.customer_problem)}
      ${resultCard("业务原因", attribution.root_causes.map((item) => labelFor("rootCause", item)).join(" + ") || analysis.report)}
      ${resultCard("优先责任方", labelFor("responsibility", attribution.primary_responsibility))}
      ${resultCard("下一步建议", attribution.recommended_actions.join("；"))}
      ${resultCard("需要补充", attribution.missing_information.join("；") || "暂无必须补充的信息。")}
    </div>
  `;
  result.appendChild(createFeedbackForm(payload.record_id));
}
```

把批次摘要的待复核指标调用改为：

```javascript
${summaryMetric("本批次记录", payload.count ?? summary.total_records)}
${summaryMetric("待复核", summary.unreviewed_records, "data-batch-pending-count")}
```

扩展 `summaryMetric()`，第三个参数只允许内部传入的静态属性名：

```javascript
function summaryMetric(label, value, valueAttribute = "") {
  const attribute = valueAttribute ? ` ${valueAttribute}` : "";
  return `
    <article class="summary-card">
      <span>${escapeHtml(label)}</span>
      <strong${attribute}>${escapeHtml(value)}</strong>
    </article>
  `;
}
```

在 `buildRecordCard(payload)` 创建 `article` 后增加状态，并修改元信息容器：

```javascript
article.className = "record result-record";
article.dataset.recordId = payload.record_id;
article.dataset.feedbackStatus = "unreviewed";
article.innerHTML = `
  <div class="record-meta" data-record-meta>
```

在 `prependRecentRecord(payload)` 中用稳定的基础文本初始化两个搜索字段，并修改元信息容器：

```javascript
const searchBaseText = `${payload.record_id} ${analysis.request.platform} ${analysis.report}`;
article.dataset.feedbackStatus = "unreviewed";
article.dataset.searchBaseText = searchBaseText;
article.dataset.searchText = searchBaseText;
article.innerHTML = `
  <div class="record-meta" data-record-meta>
```

修改 `recordDetailHtml()` 的最后两行字段调用：

```javascript
${recordDetailRow("人工复核", feedbackStatus, "data-record-feedback-status")}
${recordDetailRow("人工备注", feedbackNote, "data-record-feedback-note")}
```

并扩展 `recordDetailRow()`：

```javascript
function recordDetailRow(label, value, valueAttribute = "") {
  const attribute = valueAttribute ? ` ${valueAttribute}` : "";
  return `
    <div>
      <dt>${escapeHtml(label)}</dt>
      <dd${attribute}>${escapeHtml(value || "暂无信息")}</dd>
    </div>
  `;
}
```

- [ ] **Step 5: 运行契约测试并提交**

```powershell
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
python -m pytest tests/test_app.py -k "feedback_sync_dom_contract" -q
git diff --check
git add tests/test_app.py src/customer_issue_agent/templates/index.html src/customer_issue_agent/static/app.js
git commit -m "feat: expose feedback sync dom hooks"
```

Expected: `2 passed`，`git diff --check` 无输出，提交成功。

### Task 2: 集中同步同记录视图、详情、搜索和批次计数

**Files:**
- Create: `tests/js/test_feedback_ui.mjs`
- Modify: `src/customer_issue_agent/static/app.js:314`
- Modify: `tests/test_app.py:238`

- [ ] **Step 1: 创建加载真实 app.js 的轻量 DOM 行为测试**

创建 `tests/js/test_feedback_ui.mjs`，写入以下完整内容：

```javascript
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const appScript = readFileSync("src/customer_issue_agent/static/app.js", "utf8");

class FakeClassList {
  constructor(initial = []) {
    this.values = new Set(initial);
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
  constructor({ dataset = {}, textContent = "", classes = [] } = {}) {
    this.dataset = { ...dataset };
    this.textContent = textContent;
    this.classList = new FakeClassList(classes);
    this.children = [];
    this.selectors = new Map();
    this.attributes = new Map();
    this.hidden = false;
    this.disabled = false;
  }

  setSelector(selector, value) {
    this.selectors.set(selector, value);
    return this;
  }

  querySelector(selector) {
    if (selector === ".feedback-pill") {
      return this.children.find((child) => child.classList.contains("feedback-pill")) || null;
    }
    return this.selectors.get(selector) || null;
  }

  querySelectorAll(selector) {
    return this.selectors.get(selector) || [];
  }

  appendChild(child) {
    this.children.push(child);
    return child;
  }

  setAttribute(name, value) {
    this.attributes.set(name, String(value));
  }

  getAttribute(name) {
    return this.attributes.get(name) ?? null;
  }
}

function createRecord(recordId, { baseText, pillText, includeHooks = true } = {}) {
  const record = new FakeElement({
    dataset: {
      recordId,
      feedbackStatus: "unreviewed",
      ...(baseText === undefined ? {} : { searchBaseText: baseText, searchText: `${baseText} 旧备注` }),
    },
  });
  if (!includeHooks) {
    return record;
  }

  const meta = new FakeElement();
  if (pillText) {
    meta.appendChild(new FakeElement({ textContent: pillText, classes: ["feedback-pill"] }));
  }
  record.setSelector("[data-record-meta]", meta);
  record.setSelector("[data-record-feedback-status]", new FakeElement({ textContent: "未复核" }));
  record.setSelector("[data-record-feedback-note]", new FakeElement({ textContent: "旧备注" }));
  return record;
}

function loadApp({ records = [], batchRecords = [] } = {}) {
  const pending = new FakeElement({ textContent: "0" });
  const batchList = new FakeElement();
  batchList.querySelectorAll = (selector) => (
    selector === '[data-feedback-status="unreviewed"]'
      ? batchRecords.filter((record) => record.dataset.feedbackStatus === "unreviewed")
      : []
  );
  const document = {
    addEventListener() {},
    createElement: () => new FakeElement(),
    getElementById: () => null,
    querySelector(selector) {
      if (selector === "#batch-results .batch-list") return batchList;
      if (selector === "[data-batch-pending-count]") return pending;
      return null;
    },
    querySelectorAll(selector) {
      if (selector === "[data-record-id]") return records;
      return [];
    },
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
  return { context, pending };
}

test("认可反馈同步所有同 ID 视图并用新备注重建搜索文本", () => {
  const single = createRecord("record-1");
  const recent = createRecord("record-1", { baseText: "record-1 Amazon 原报告" });
  const untouched = createRecord("record-2", { baseText: "record-2 TikTok 另一报告" });
  const { context, pending } = loadApp({
    records: [single, recent, untouched],
    batchRecords: [single, untouched],
  });

  context.syncFeedbackUi("record-1", { accepted: true, note: "新备注 <b>仅文本</b>" });

  for (const record of [single, recent]) {
    assert.equal(record.dataset.feedbackStatus, "accepted");
    assert.equal(record.querySelector("[data-record-meta]").children.length, 1);
    assert.equal(record.querySelector("[data-record-meta]").children[0].textContent, "已认可");
    assert.equal(record.querySelector("[data-record-feedback-status]").textContent, "已认可");
    assert.equal(record.querySelector("[data-record-feedback-note]").textContent, "新备注 <b>仅文本</b>");
  }
  assert.equal(recent.dataset.searchText, "record-1 Amazon 原报告 新备注 <b>仅文本</b>");
  assert.equal(untouched.dataset.feedbackStatus, "unreviewed");
  assert.equal(untouched.dataset.searchText, "record-2 TikTok 另一报告 旧备注");
  assert.equal(pending.textContent, "1");
});

test("修正反馈原位更新标签且空备注显示暂无信息", () => {
  const record = createRecord("record-1", { baseText: "record-1 Amazon 原报告", pillText: "已认可" });
  record.dataset.feedbackStatus = "accepted";
  const { context } = loadApp({ records: [record], batchRecords: [record] });

  context.syncFeedbackUi("record-1", { accepted: false, note: "" });

  const meta = record.querySelector("[data-record-meta]");
  assert.equal(record.dataset.feedbackStatus, "corrected");
  assert.equal(meta.children.length, 1);
  assert.equal(meta.children[0].textContent, "已修正");
  assert.equal(record.querySelector("[data-record-feedback-note]").textContent, "暂无信息");
  assert.equal(record.dataset.searchText, "record-1 Amazon 原报告");
});

test("缺少可选钩子或匹配记录时同步不抛错", () => {
  const partial = createRecord("record-1", { includeHooks: false });
  const { context } = loadApp({ records: [partial] });

  assert.doesNotThrow(() => context.syncFeedbackUi("record-1", { accepted: true }));
  assert.doesNotThrow(() => context.syncFeedbackUi("missing", { accepted: false, note: "备注" }));
  assert.equal(partial.dataset.feedbackStatus, "accepted");
});

test("记录 ID 使用精确比较而不依赖动态 CSS 选择器", () => {
  const exact = createRecord('record"] special');
  const similar = createRecord('record"] special-extra');
  const { context } = loadApp({ records: [exact, similar] });

  context.syncFeedbackUi('record"] special', { accepted: true, note: "安全" });

  assert.equal(exact.dataset.feedbackStatus, "accepted");
  assert.equal(similar.dataset.feedbackStatus, "unreviewed");
});
```

- [ ] **Step 2: 运行 Node 测试并确认 helper 尚不存在**

```powershell
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
node --test tests/js/test_feedback_ui.mjs
```

Expected: 4 个测试因 `context.syncFeedbackUi is not a function` 失败，证明测试加载了真实脚本且失败原因是功能缺失。

- [ ] **Step 3: 实现最小反馈 UI 同步 helper**

在 `submitFeedbackForm()` 之前加入：

```javascript
function feedbackUiState(feedback) {
  const accepted = feedback?.accepted === true;
  return {
    value: accepted ? "accepted" : "corrected",
    label: accepted ? "已认可" : "已修正",
    note: String(feedback?.note || "").trim(),
  };
}

function syncFeedbackUi(recordId, feedback) {
  const state = feedbackUiState(feedback);
  document.querySelectorAll("[data-record-id]").forEach((record) => {
    if (record.dataset.recordId === String(recordId)) {
      updateRecordFeedbackView(record, state);
    }
  });
  updateBatchPendingCount();
}

function updateRecordFeedbackView(record, state) {
  record.dataset.feedbackStatus = state.value;
  updateFeedbackPill(record, state);

  const status = record.querySelector("[data-record-feedback-status]");
  const note = record.querySelector("[data-record-feedback-note]");
  if (status) {
    status.textContent = state.label;
  }
  if (note) {
    note.textContent = state.note || "暂无信息";
  }
  if (record.dataset.searchBaseText !== undefined) {
    record.dataset.searchText = [record.dataset.searchBaseText, state.note].filter(Boolean).join(" ");
  }
}

function updateFeedbackPill(record, state) {
  const meta = record.querySelector("[data-record-meta]");
  if (!meta) {
    return;
  }

  let pill = meta.querySelector(".feedback-pill");
  if (!pill) {
    pill = document.createElement("span");
    pill.classList.add("feedback-pill");
    meta.appendChild(pill);
  }
  pill.textContent = state.label;
}

function updateBatchPendingCount() {
  const batchList = document.querySelector("#batch-results .batch-list");
  const pending = document.querySelector("[data-batch-pending-count]");
  if (!batchList || !pending) {
    return;
  }

  pending.textContent = String(
    batchList.querySelectorAll('[data-feedback-status="unreviewed"]').length,
  );
}
```

- [ ] **Step 4: 将 helper 名称加入静态资源契约测试**

在 `test_static_app_js_contains_batch_and_feedback_hooks` 的末尾追加：

```python
assert "feedbackUiState" in script
assert "syncFeedbackUi" in script
assert "updateRecordFeedbackView" in script
assert "updateFeedbackPill" in script
assert "updateBatchPendingCount" in script
```

- [ ] **Step 5: 运行行为测试与契约测试并提交**

```powershell
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
node --test tests/js/test_feedback_ui.mjs
python -m pytest tests/test_app.py -k "batch_and_feedback_hooks or feedback_sync_dom_contract" -q
git diff --check
git add tests/js/test_feedback_ui.mjs tests/test_app.py src/customer_issue_agent/static/app.js
git commit -m "feat: sync saved feedback across record views"
```

Expected: Node 输出 `4 pass, 0 fail`；pytest 输出 `3 passed`；差异检查无输出。

### Task 3: 在反馈成功后刷新筛选与运营概览

**Files:**
- Modify: `tests/js/test_feedback_ui.mjs`
- Modify: `tests/test_app.py`
- Modify: `src/customer_issue_agent/static/app.js:314`

- [ ] **Step 1: 追加提交成功与失败路径的行为测试**

把以下 helper 和测试追加到 `tests/js/test_feedback_ui.mjs`：

```javascript
function createFeedbackForm() {
  const button = new FakeElement({ textContent: "保存反馈" });
  const message = new FakeElement();
  const form = new FakeElement({ dataset: { endpoint: "/api/records/record-1/feedback" } });
  form.setSelector("button[type='submit']", button);
  form.setSelector(".form-message", message);
  return { button, form, message };
}

test("提交成功后依次同步 UI、刷新筛选并刷新一次概览", async () => {
  const { context } = loadApp();
  const { button, form, message } = createFeedbackForm();
  const calls = [];
  context.fetch = async () => ({
    ok: true,
    json: async () => ({
      record_id: "record-1",
      feedback: { accepted: true, note: "已确认" },
    }),
  });
  context.syncFeedbackUi = (recordId, feedback) => calls.push(["sync", recordId, feedback.note]);
  context.refreshRecordFilterViews = () => calls.push(["filters"]);
  context.loadRecordsSummary = () => calls.push(["summary"]);

  await context.submitFeedbackForm(form);

  assert.deepEqual(calls, [
    ["sync", "record-1", "已确认"],
    ["filters"],
    ["summary"],
  ]);
  assert.equal(message.textContent, "已保存：认可系统判断。");
  assert.equal(message.classList.contains("is-success"), true);
  assert.equal(button.disabled, false);
  assert.equal(button.textContent, "保存反馈");
});

test("提交失败不改变本地反馈状态也不刷新概览", async () => {
  const { context } = loadApp();
  const { form, message } = createFeedbackForm();
  const calls = [];
  context.fetch = async () => ({
    ok: false,
    json: async () => ({ detail: "保存失败" }),
  });
  context.syncFeedbackUi = () => calls.push("sync");
  context.refreshRecordFilterViews = () => calls.push("filters");
  context.loadRecordsSummary = () => calls.push("summary");

  await context.submitFeedbackForm(form);

  assert.deepEqual(calls, []);
  assert.equal(message.textContent, "保存失败");
  assert.equal(message.classList.contains("is-visible"), true);
  assert.equal(message.classList.contains("is-success"), false);
});
```

- [ ] **Step 2: 运行 Node 测试并确认成功路径调用序列为空**

```powershell
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
node --test tests/js/test_feedback_ui.mjs
```

Expected: 前 4 个测试通过；“提交成功后依次同步”测试失败，实际 `calls` 为 `[]`；失败路径测试通过。

- [ ] **Step 3: 将同步和刷新接入 POST 成功分支**

在 `submitFeedbackForm(form)` 的 `response.ok` 检查之后、成功消息之前加入：

```javascript
syncFeedbackUi(payload.record_id, payload.feedback);
refreshRecordFilterViews();
loadRecordsSummary();
message.textContent = payload.feedback.accepted ? "已保存：认可系统判断。" : "已保存：人工修正已记录。";
message.classList.add("is-visible", "is-success");
```

不要 `await loadRecordsSummary()`：该函数内部自行捕获概览错误，反馈成功提示不应等待概览请求或因概览失败被改成失败。

- [ ] **Step 4: 锁定提交成功编排的静态契约**

在 `tests/test_app.py` 加入：

```python
def test_feedback_success_path_refreshes_local_views_and_summary(tmp_path):
    app = create_app(storage_path=tmp_path / "analyses.jsonl")
    client = TestClient(app)

    response = client.get("/static/app.js")

    assert response.status_code == 200
    script = response.text
    assert "syncFeedbackUi(payload.record_id, payload.feedback);" in script
    assert "refreshRecordFilterViews();" in script
    assert "loadRecordsSummary();" in script
```

- [ ] **Step 5: 运行行为测试、前端契约回归并提交**

```powershell
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
node --test tests/js/test_feedback_ui.mjs
python -m pytest tests/test_app.py -k "feedback or batch" -q
node --check src/customer_issue_agent/static/app.js
git diff --check
git add tests/js/test_feedback_ui.mjs tests/test_app.py src/customer_issue_agent/static/app.js
git commit -m "feat: refresh views after feedback save"
```

Expected: Node 输出 `6 pass, 0 fail`；所选 pytest 全部通过；语法和差异检查无输出。

### Task 4: 文档、完整验证和提交整理

**Files:**
- Modify: `README.md:75`

- [ ] **Step 1: 更新人工复核说明**

在 `README.md` 的“批量分析与人工复核”段落加入：

```markdown
人工反馈保存成功后，页面会即时同步同一记录在单条结果、批次结果和最近记录中的复核状态，并更新详情、备注搜索、“只看待复核”数量、当前批次待复核数量和运营概览，无需刷新页面。反馈表单仍保持可编辑，可以再次提交最新结论；如果保存失败，页面不会提前改变记录状态。
```

- [ ] **Step 2: 运行完整验证**

每条命令使用独立 PowerShell 变量初始化，避免跨命令依赖：

```powershell
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
python -m pytest -q
```

```powershell
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
node --test tests/js/test_feedback_ui.mjs
```

```powershell
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
node --check src/customer_issue_agent/static/app.js
```

```powershell
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
git diff --check
```

Expected: pytest 全绿；Node 输出 `6 pass, 0 fail`；JavaScript 语法检查和差异检查无输出。

- [ ] **Step 3: 检查范围并提交文档**

```powershell
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
git status --short
git diff --stat HEAD
git add README.md
git commit -m "docs: describe feedback ui sync"
```

Expected: 只包含本计划列出的 5 个文件；不包含后端路由、存储、模型供应商或依赖文件的意外修改。

- [ ] **Step 4: 在目标仓库干净临时 worktree 中复验并推送**

从目标仓库当前 PR 头创建临时分支，仅 cherry-pick 本功能的设计、计划和实施提交；不要修改本地 `origin`，也不要携带旧仓库或其他任务提交。使用目标 URL 显式推送：

```powershell
$TargetRemote = "https://github.com/ARIUM-hub/Agent-Operations-Workflow.git"
git push $TargetRemote HEAD:codex/customer-issue-agent-mvp
```

推送前在临时 worktree 再运行本 Task Step 2 的四项完整验证。推送后确认 PR `https://github.com/ARIUM-hub/Agent-Operations-Workflow/pull/2` 的 head 等于刚推送的提交，只删除本次创建的临时 worktree 和临时分支。

## 自检结果

- Spec coverage：成功后同步所有同 ID 视图、标签去重、详情与复制来源、备注搜索替换、筛选与待复核隐藏、批次重算、概览刷新一次、失败不更新和重复提交均有对应任务或行为测试。
- Placeholder scan：所有代码步骤都包含可执行的完整新增块或精确替换块，没有未完成指令或跨任务省略引用。
- Naming consistency：统一使用 `feedbackUiState`、`syncFeedbackUi`、`updateRecordFeedbackView`、`updateFeedbackPill`、`updateBatchPendingCount`；DOM 名统一为设计中的 `data-record-*` 与 `data-batch-pending-count`。
- Scope control：不增加后端 API、字段、npm 依赖、CSS 或模型调用；推送时只迁移本任务提交。
- PowerShell isolation：完整验证命令各自初始化 UTF-8 输出编码，不依赖前一条命令留下的变量状态。
