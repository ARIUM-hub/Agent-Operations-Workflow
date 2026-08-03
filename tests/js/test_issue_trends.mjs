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

function deferred() {
  let resolve;
  const promise = new Promise((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
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
  assert.equal(elements.get("platform-filter").dataset.matchMode, "exact");
  assert.equal(elements.get("issue-filter").value, "function_use");
  assert.equal(elements.get("responsibility-filter").value, "customer_service_training");
  assert.equal(elements.get("record-search").value, "保留关键词");
  assert.equal(elements.get("feedback-filter").value, "unreviewed");
  assert.equal(context.buildExportFilterParams().get("platform_match"), "exact");
  assert.deepEqual(calls, ["filters", "scroll", "summary"]);
});

test("趋势下钻的平台精确匹配而普通平台筛选仍支持关键词", () => {
  const { context } = loadApp();
  const amazon = new FakeElement({ dataset: { platform: "Amazon" } });
  const amazonUs = new FakeElement({ dataset: { platform: "Amazon US" } });
  const baseFilters = {
    query: "",
    platform: "amazon",
    issue: "",
    responsibility: "",
    feedback: "",
  };

  assert.equal(context.recordMatchesFilters(amazon, baseFilters), true);
  assert.equal(context.recordMatchesFilters(amazonUs, baseFilters), true);
  assert.equal(context.recordMatchesFilters(amazon, { ...baseFilters, platformMatch: "exact" }), true);
  assert.equal(context.recordMatchesFilters(amazonUs, { ...baseFilters, platformMatch: "exact" }), false);
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

test("较旧的趋势响应不会覆盖较新的分析后刷新结果", async () => {
  const { context } = loadApp();
  const firstResponse = deferred();
  const secondResponse = deferred();
  const rendered = [];
  let fetchCalls = 0;
  context.fetch = () => {
    fetchCalls += 1;
    return fetchCalls === 1 ? firstResponse.promise : secondResponse.promise;
  };
  context.renderIssueTrends = (payload) => rendered.push(payload.version);

  const firstLoad = context.loadIssueTrends();
  const secondLoad = context.loadIssueTrends();
  secondResponse.resolve({ ok: true, json: async () => ({ version: "new" }) });
  await secondLoad;
  firstResponse.resolve({ ok: true, json: async () => ({ version: "old" }) });
  await firstLoad;

  assert.deepEqual(rendered, ["new"]);
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
