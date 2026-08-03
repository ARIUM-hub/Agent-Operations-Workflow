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
  form.setSelector(
    "button[type='submit']",
    new FakeElement({ textContent: "提交复盘" }),
  );
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
  form.setSelector(
    "button[type='submit']",
    new FakeElement({ textContent: "提交复盘" }),
  );
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
  second.resolve({
    ok: true,
    json: async () => reviewPayload({ task_id: "new" }),
  });
  await newLoad;
  first.resolve({
    ok: true,
    json: async () => reviewPayload({ task_id: "old" }),
  });
  await oldLoad;

  assert.match(panel.innerHTML, /task-review-form/);
  assert.equal(panel.dataset.taskId, "new");
});

test("不同任务的复盘面板可以各自完成加载", async () => {
  const { context } = loadApp();
  const first = deferred();
  const second = deferred();
  const firstPanel = new FakeElement();
  const secondPanel = new FakeElement();
  let count = 0;
  context.fetch = () => (++count === 1 ? first.promise : second.promise);

  const firstLoad = context.loadTaskEffectReview("first", firstPanel);
  const secondLoad = context.loadTaskEffectReview("second", secondPanel);
  second.resolve({
    ok: true,
    json: async () => reviewPayload({ task_id: "second" }),
  });
  await secondLoad;
  first.resolve({
    ok: true,
    json: async () => reviewPayload({ task_id: "first" }),
  });
  await firstLoad;

  assert.match(firstPanel.innerHTML, /task-review-form/);
  assert.match(secondPanel.innerHTML, /task-review-form/);
  assert.equal(firstPanel.dataset.taskId, "first");
  assert.equal(secondPanel.dataset.taskId, "second");
});
