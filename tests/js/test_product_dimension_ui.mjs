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
  appendChild(child) { this.children.push(child); return child; }
  prepend(child) { this.children.unshift(child); }
  querySelector() { return null; }
  querySelectorAll() { return []; }
  closest() { return this; }
  scrollIntoView() { this.scrolledIntoView = true; }
  setAttribute(name, value) { this.attributes.set(name, String(value)); }
  getAttribute(name) { return this.attributes.get(name) ?? null; }
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
