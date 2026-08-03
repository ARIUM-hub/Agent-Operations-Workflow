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
