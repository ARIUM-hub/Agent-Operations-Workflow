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

  contains(name) {
    return this.values.has(name);
  }

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

  reset() {}
}

function loadApp({ includeTasks = true } = {}) {
  const elements = new Map();
  if (includeTasks) {
    elements.set("task-content", new FakeElement());
    elements.set("task-status-filter", new FakeElement());
    elements.set("task-priority-filter", new FakeElement());
    elements.set("task-effect-review-filter", new FakeElement());
  }
  elements.set("summary-range", new FakeElement({ value: "30d" }));
  const document = {
    domReady: null,
    addEventListener(event, callback) {
      if (event === "DOMContentLoaded") this.domReady = callback;
    },
    getElementById(id) {
      return elements.get(id) || null;
    },
    querySelector() {
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
  const promise = new Promise((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

test("任务查询包含当前状态和优先级筛选", () => {
  const { context, elements } = loadApp();
  elements.get("task-status-filter").value = "in_progress";
  elements.get("task-priority-filter").value = "high";

  assert.equal(
    context.buildTaskListUrl(),
    "/api/tasks?status=in_progress&priority=high",
  );
});

test("任务卡显示来源、状态、优先级、记录数和逾期文字", () => {
  const { context } = loadApp();
  const html = context.taskCardHtml(
    task({ due_date: "2020-01-01" }),
    new Date("2026-08-03T08:00:00Z"),
  );
  const completedHtml = context.taskCardHtml(task({
    status: "completed",
    result: "已更新说明",
    completed_at: "2026-08-03T10:00:00+00:00",
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

test("任务在截止日结束前不显示逾期", () => {
  const { context } = loadApp();
  const html = context.taskCardHtml(
    task({ due_date: "2026-08-03" }),
    new Date("2026-08-03T23:59:59.500"),
  );

  assert.doesNotMatch(html, /已逾期/);
});

test("高频和趋势问题簇的筛选与创建按钮互为兄弟", () => {
  const { context } = loadApp();
  context.isSummaryIssueClusterFilterable = () => true;

  const summaryHtml = context.summaryIssueClusterRow({
    platform: "Amazon",
    issue_category: "function_use",
    responsibility: "customer_service_training",
    count: 3,
  });
  const trendHtml = context.issueTrendRow({
    platform: "Amazon",
    issue_category: "function_use",
    responsibility: "customer_service_training",
    current_count: 3,
    previous_count: 1,
    delta: 2,
    significant_increase: true,
  });

  assert.equal((summaryHtml.match(/<button/g) || []).length, 2);
  assert.equal((trendHtml.match(/<button/g) || []).length, 2);
  assert.doesNotMatch(
    summaryHtml,
    /<button[^>]*>[\s\S]*<button[^>]*>[\s\S]*<\/button>[\s\S]*<\/button>/,
  );
  assert.doesNotMatch(
    trendHtml,
    /<button[^>]*>[\s\S]*<button[^>]*>[\s\S]*<\/button>[\s\S]*<\/button>/,
  );
});

test("高频和趋势创建草稿使用正确范围和建议优先级", () => {
  const { context } = loadApp();
  const summary = context.createTaskDraft({
    source: "summary",
    platform: "Amazon",
    issueCategory: "function_use",
    responsibility: "customer_service_training",
    significantIncrease: false,
  });
  const trend = context.createTaskDraft({
    source: "trend",
    platform: "TikTok Shop",
    issueCategory: "product_fault",
    responsibility: "supply_chain_quality",
    significantIncrease: true,
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
  context.loadTasks = (options) => {
    calls.push(options);
  };
  context.fetch = async () => ({
    ok: true,
    status: 200,
    json: async () => ({ created: responseCount++ === 0, task: task() }),
  });
  const form = new FakeElement();
  form.setSelector(
    "button[type='submit']",
    new FakeElement({ textContent: "创建任务" }),
  );
  form.setSelector(".form-message", new FakeElement());

  await context.submitTaskCreate(form);
  elements.get("task-status-filter").value = "completed";
  elements.get("task-priority-filter").value = "high";
  elements.get("task-effect-review-filter").value = "ready";
  await context.submitTaskCreate(form);

  assert.equal(calls.length, 2);
  assert.equal(Object.keys(calls[0]).length, 0);
  assert.equal(calls[1].highlightTaskId, "task-one");
  assert.equal(elements.get("task-status-filter").value, "");
  assert.equal(elements.get("task-priority-filter").value, "");
  assert.equal(elements.get("task-effect-review-filter").value, "");
});

test("创建失败保留表单并显示局部错误且不刷新任务", async () => {
  const { context } = loadApp();
  let refreshes = 0;
  context.loadTasks = () => {
    refreshes += 1;
  };
  context.fetch = async () => ({
    ok: false,
    json: async () => ({ detail: "没有匹配记录" }),
  });
  const form = new FakeElement();
  const message = new FakeElement();
  form.setSelector(
    "button[type='submit']",
    new FakeElement({ textContent: "创建任务" }),
  );
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
  context.fetch = async () => {
    fetches += 1;
  };

  await context.loadTasks();

  assert.equal(fetches, 0);
});

test("页面初始化只加载一次任务", () => {
  const { context, document } = loadApp();
  [
    "bindTabs",
    "bindAnalysisForm",
    "bindBatchForm",
    "bindFeedbackForms",
    "bindSummaryRange",
    "loadRecordsSummary",
    "loadIssueTrends",
    "bindFilteredExport",
    "bindRecordFilters",
    "bindReviewQueueToggle",
    "bindRecordDetails",
    "bindRecordCopyActions",
    "bindTaskFilters",
    "bindTaskCreateForm",
  ].forEach((name) => {
    context[name] = () => {};
  });
  let taskLoads = 0;
  context.loadTasks = () => {
    taskLoads += 1;
  };

  document.domReady();

  assert.equal(taskLoads, 1);
});

test("分析、批量分析和反馈保存不刷新任务区域", async () => {
  const { context } = loadApp();
  let taskLoads = 0;
  context.loadTasks = () => {
    taskLoads += 1;
  };
  [
    "renderAnalysisResult",
    "bindFeedbackForms",
    "prependRecentRecord",
    "loadRecordsSummary",
    "loadIssueTrends",
    "renderBatchResults",
    "syncFeedbackUi",
    "refreshRecordFilterViews",
  ].forEach((name) => {
    context[name] = () => {};
  });
  context.fetch = async (url) => {
    if (url === "/api/analyze") {
      return { ok: true, json: async () => ({ record_id: "one", analysis: {} }) };
    }
    if (url === "/api/analyze-batch-file") {
      return {
        ok: true,
        json: async () => ({
          batch_id: "batch",
          count: 1,
          records: [{ record_id: "two" }],
        }),
      };
    }
    return {
      ok: true,
      json: async () => ({
        record_id: "one",
        feedback: { accepted: true },
      }),
    };
  };
  const analysisForm = new FakeElement({
    dataset: { endpoint: "/api/analyze" },
  });
  analysisForm.setSelector(
    "button[type='submit']",
    new FakeElement({ textContent: "分析" }),
  );
  const batchForm = new FakeElement({
    dataset: { endpoint: "/api/analyze-batch-file" },
  });
  batchForm.setSelector(
    "button[type='submit']",
    new FakeElement({ textContent: "批量分析" }),
  );
  const feedbackForm = new FakeElement({
    dataset: { endpoint: "/api/records/one/feedback" },
  });
  feedbackForm.setSelector(
    "button[type='submit']",
    new FakeElement({ textContent: "保存反馈" }),
  );
  feedbackForm.setSelector(".form-message", new FakeElement());

  await context.submitAnalysisForm(analysisForm, new FakeElement());
  await context.submitBatchForm(batchForm, new FakeElement());
  await context.submitFeedbackForm(feedbackForm);

  assert.equal(taskLoads, 0);
});

test("待处理、处理中和已完成任务只显示合法操作", () => {
  const { context } = loadApp();

  assert.match(context.taskActionsHtml(task()), /开始处理/);
  assert.match(context.taskActionsHtml(task()), /编辑/);
  assert.doesNotMatch(context.taskActionsHtml(task()), /完成任务/);
  assert.match(
    context.taskActionsHtml(task({ status: "in_progress" })),
    /完成任务/,
  );
  assert.doesNotMatch(
    context.taskActionsHtml(task({ status: "completed" })),
    /data-task-edit/,
  );
});

test("开始处理成功只刷新一次任务区域", async () => {
  const { context } = loadApp();
  const calls = [];
  context.fetch = async (url, options) => {
    calls.push([url, JSON.parse(options.body)]);
    return {
      ok: true,
      json: async () => task({ status: "in_progress" }),
    };
  };
  context.loadTasks = () => {
    calls.push(["refresh"]);
  };

  await context.updateTask(
    "task-one",
    { status: "in_progress" },
    new FakeElement(),
  );

  assert.equal(calls.length, 2);
  assert.equal(calls[0][0], "/api/tasks/task-one");
  assert.equal(calls[0][1].status, "in_progress");
  assert.equal(calls[1][0], "refresh");
});

test("空处理结果不提交，合法结果去除空白后完成", async () => {
  const { context } = loadApp();
  const requestBodies = [];
  context.fetch = async (_url, options) => {
    requestBodies.push(JSON.parse(options.body));
    return {
      ok: true,
      json: async () => task({ status: "completed" }),
    };
  };
  context.loadTasks = () => {};
  const message = new FakeElement();

  await context.completeTask("task-one", "   ", message);
  assert.equal(requestBodies.length, 0);
  assert.match(message.textContent, /处理结果/);

  await context.completeTask("task-one", "  已更新说明  ", message);
  assert.equal(requestBodies.length, 1);
  assert.equal(requestBodies[0].result, "已更新说明");
});

test("更新失败保留展开表单和值且不刷新任务", async () => {
  const { context } = loadApp();
  let refreshes = 0;
  context.fetch = async () => ({
    ok: false,
    json: async () => ({ detail: "状态冲突" }),
  });
  context.loadTasks = () => {
    refreshes += 1;
  };
  const message = new FakeElement();

  const succeeded = await context.updateTask(
    "task-one",
    { team: "product" },
    message,
  );

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
  assert.equal(elements.get("issue-filter").value, "function_use");
  assert.equal(
    elements.get("responsibility-filter").value,
    "customer_service_training",
  );
  assert.equal(elements.get("record-search").value, "保留关键词");
  assert.equal(elements.get("feedback-filter").value, "unreviewed");
  assert.deepEqual(calls, ["filters", "summary", "scroll"]);
});

test("任务卡关联记录点击把 SKU 传给下钻", () => {
  const { context } = loadApp();
  const recordsButton = new FakeElement();
  const card = new FakeElement({
    dataset: {
      taskId: "task-one",
      taskSourceRange: "all",
      taskPlatform: "Amazon",
      taskSku: "SKU-01",
      taskIssueCategory: "function_use",
      taskResponsibility: "customer_service_training",
    },
  });
  card.setSelector("[data-task-records]", recordsButton);
  const root = new FakeElement();
  root.setSelector("[data-task-id]", [card]);
  let received = null;
  context.drilldownTaskRecords = (taskData) => {
    received = taskData;
  };

  context.bindTaskActions(root);
  recordsButton.listeners.get("click")();

  assert.equal(received.sku, "SKU-01");
});
