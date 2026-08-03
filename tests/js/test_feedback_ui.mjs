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
