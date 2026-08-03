const labels = {
  issue_category: {
    installation: "安装、开箱或组装问题",
    function_use: "功能不会用或设置失败",
    expectation_gap: "功能表现未达到预期",
    product_fault: "产品异常、失灵或疑似质量问题",
    compatibility: "兼容性问题",
    accessory: "配件缺失或条件不满足",
    non_usage: "非产品使用问题",
    unclear: "信息不足",
  },
  responsibility: {
    operations: "运营",
    customer_service_training: "客服培训",
    product: "产品",
    supply_chain_quality: "供应链或质量",
    need_more_information: "需要补充信息",
  },
  evidence: {
    clear: "较明确",
    likely: "倾向于",
    insufficient: "信息不足",
  },
  feedback: {
    unreviewed: "未复核",
    accepted: "已认可",
    corrected: "已修正",
  },
  task_status: {
    pending: "待处理",
    in_progress: "处理中",
    completed: "已完成",
  },
  task_priority: {
    high: "高",
    medium: "中",
    low: "低",
  },
};

let latestExportCountRequestId = 0;
let latestIssueTrendRequestId = 0;
let latestTaskRequestId = 0;

document.addEventListener("DOMContentLoaded", () => {
  bindTabs();
  bindAnalysisForm("paste-form", "paste-error");
  bindAnalysisForm("upload-form", "upload-error");
  bindBatchForm();
  bindFeedbackForms(document);
  bindSummaryRange();
  loadRecordsSummary();
  loadIssueTrends();
  bindTaskFilters();
  bindTaskCreateForm();
  loadTasks();
  bindFilteredExport();
  bindRecordFilters();
  bindReviewQueueToggle();
  bindRecordDetails(document);
  bindRecordCopyActions(document);
});

function bindTabs() {
  const tabs = Array.from(document.querySelectorAll("[data-tab-target]"));
  const forms = {
    "paste-panel": document.getElementById("paste-form"),
    "upload-panel": document.getElementById("upload-form"),
    "batch-panel": document.getElementById("batch-form"),
  };

  tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      const target = tab.dataset.tabTarget;
      tabs.forEach((item) => {
        const selected = item === tab;
        item.classList.toggle("is-active", selected);
        item.setAttribute("aria-selected", String(selected));
      });

      Object.entries(forms).forEach(([panelId, form]) => {
        const panel = document.getElementById(panelId);
        const active = panelId === target;
        if (!form || !panel) {
          return;
        }
        form.classList.toggle("is-hidden", !active);
        panel.hidden = !active;
      });
    });
  });
}

function bindAnalysisForm(formId, errorId) {
  const form = document.getElementById(formId);
  if (!form) {
    return;
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    submitAnalysisForm(form, document.getElementById(errorId));
  });
}

function bindBatchForm() {
  const form = document.getElementById("batch-form");
  if (!form) {
    return;
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    submitBatchForm(form, document.getElementById("batch-error"));
  });
}

async function submitAnalysisForm(form, errorBox) {
  const button = form.querySelector("button[type='submit']");
  const originalLabel = button.textContent;
  clearError(errorBox);
  setLoading(button, true);

  try {
    const response = await fetch(form.dataset.endpoint, {
      method: "POST",
      body: new FormData(form),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(readError(payload));
    }
    renderAnalysisResult(payload);
    bindFeedbackForms(document.getElementById("analysis-result"));
    prependRecentRecord(payload);
    loadRecordsSummary();
    loadIssueTrends();
    form.reset();
  } catch (error) {
    showError(errorBox, error.message || "分析失败，请检查输入后重试。");
  } finally {
    button.textContent = originalLabel;
    setLoading(button, false);
  }
}

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

async function submitBatchForm(form, errorBox) {
  const button = form.querySelector("button[type='submit']");
  const originalLabel = button.textContent;
  clearError(errorBox);
  setLoading(button, true);

  try {
    const response = await fetch(form.dataset.endpoint, {
      method: "POST",
      body: new FormData(form),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(readError(payload));
    }
    renderBatchResults(payload);
    payload.records.forEach((record) => prependRecentRecord(record));
    loadRecordsSummary();
    loadIssueTrends();
    form.reset();
  } catch (error) {
    showError(errorBox, error.message || "批量分析失败，请检查文件后重试。");
  } finally {
    button.textContent = originalLabel;
    setLoading(button, false);
  }
}

function renderBatchResults(payload) {
  const container = document.getElementById("batch-results");
  container.innerHTML = `
    <div class="result-header">
      <div>
        <p class="eyebrow">批量分析完成</p>
        <h2>${payload.count} 条会话已生成分析</h2>
      </div>
      <span class="record-id">批次 #${escapeHtml(payload.batch_id.slice(0, 8))}</span>
    </div>
    ${batchSummaryHtml(payload)}
    <div class="batch-list"></div>
  `;
  const list = container.querySelector(".batch-list");
  payload.records.forEach((record) => {
    list.appendChild(buildRecordCard(record));
  });
  bindFeedbackForms(container);
}

function batchSummaryHtml(payload) {
  const summary = buildBatchSummary(payload.records || []);
  return `
    <section class="batch-summary" aria-label="本批次摘要">
      <div class="batch-summary-header">
        <p class="eyebrow">本批次摘要</p>
        <h3>先看整体，再逐条复核</h3>
      </div>
      <div class="summary-metrics batch-summary-metrics">
        ${summaryMetric("本批次记录", payload.count ?? summary.total_records)}
        ${summaryMetric("待复核", summary.unreviewed_records, "data-batch-pending-count")}
      </div>
      <div class="summary-grid batch-summary-grid">
        ${batchSummaryDistribution("问题类型", "issue_category", summary.issue_categories)}
        ${batchSummaryDistribution("责任方", "responsibility", summary.responsibilities)}
        ${batchSummaryDistribution("证据强度", "evidence", summary.evidence_strengths)}
      </div>
    </section>
  `;
}

function buildBatchSummary(records) {
  const issueCategories = {};
  const responsibilities = {};
  const evidenceStrengths = {};

  records.forEach((record) => {
    const attribution = record.analysis?.attribution || {};
    incrementBatchCounter(issueCategories, attribution.issue_category);
    incrementBatchCounter(responsibilities, attribution.primary_responsibility);
    incrementBatchCounter(evidenceStrengths, attribution.evidence_strength);
  });

  return {
    total_records: records.length,
    unreviewed_records: records.length,
    issue_categories: rankBatchSummary(issueCategories),
    responsibilities: rankBatchSummary(responsibilities),
    evidence_strengths: rankBatchSummary(evidenceStrengths),
  };
}

function incrementBatchCounter(counter, value) {
  const key = String(value || "unknown").trim() || "unknown";
  counter[key] = (counter[key] || 0) + 1;
}

function rankBatchSummary(counter) {
  return Object.entries(counter)
    .map(([value, count]) => ({ value, count }))
    .sort((left, right) => right.count - left.count || left.value.localeCompare(right.value));
}

function batchSummaryDistribution(title, labelGroup, items = []) {
  const rows = items.length
    ? items.map((item) => `
        <li>
          <span>${escapeHtml(labelFor(labelGroup, item.value))}</span>
          <strong>${escapeHtml(item.count)}</strong>
        </li>
      `).join("")
    : `<li><span>暂无数据</span><strong>0</strong></li>`;

  return `
    <article class="summary-card distribution-card batch-summary-card">
      <h4>${escapeHtml(title)}</h4>
      <ul class="distribution-list">${rows}</ul>
    </article>
  `;
}

function buildRecordCard(payload) {
  const analysis = payload.analysis;
  const attribution = analysis.attribution;
  const article = document.createElement("article");
  article.className = "record result-record";
  article.dataset.recordId = payload.record_id;
  article.dataset.feedbackStatus = "unreviewed";
  article.innerHTML = `
    <div class="record-meta" data-record-meta>
      <strong>${escapeHtml(analysis.request.platform)}</strong>
      <span>${labelFor("issue_category", attribution.issue_category)}</span>
      <span>${labelFor("responsibility", attribution.primary_responsibility)}</span>
      <span>${labelFor("evidence", attribution.evidence_strength)}</span>
    </div>
    <p>${escapeHtml(analysis.report)}</p>
  `;
  article.appendChild(createFeedbackForm(payload.record_id));
  return article;
}

function createFeedbackForm(recordId) {
  const template = document.querySelector("[data-feedback-template]");
  const fragment = template.content.cloneNode(true);
  const form = fragment.querySelector("form");
  form.dataset.endpoint = `/api/records/${recordId}/feedback`;
  return fragment;
}

function bindFeedbackForms(root) {
  root.querySelectorAll(".feedback-form").forEach((form) => {
    if (form.dataset.bound === "true") {
      return;
    }
    form.dataset.bound = "true";
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      submitFeedbackForm(form);
    });
  });
}

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

async function submitFeedbackForm(form) {
  const button = form.querySelector("button[type='submit']");
  const message = form.querySelector(".form-message");
  const originalLabel = button.textContent;
  clearError(message);
  setLoading(button, true);

  try {
    const response = await fetch(form.dataset.endpoint, {
      method: "POST",
      body: new FormData(form),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(readError(payload));
    }
    syncFeedbackUi(payload.record_id, payload.feedback);
    refreshRecordFilterViews();
    loadRecordsSummary();
    message.textContent = payload.feedback.accepted ? "已保存：认可系统判断。" : "已保存：人工修正已记录。";
    message.classList.add("is-visible", "is-success");
  } catch (error) {
    showError(message, error.message || "反馈保存失败，请稍后重试。");
  } finally {
    button.textContent = originalLabel;
    setLoading(button, false);
  }
}

function prependRecentRecord(payload) {
  const list = document.getElementById("recent-records");
  const analysis = payload.analysis;
  const attribution = analysis.attribution;
  const empty = list.querySelector(".empty");
  if (empty) {
    empty.remove();
  }

  const article = document.createElement("article");
  article.className = "record";
  article.dataset.recordId = payload.record_id;
  article.dataset.platform = analysis.request.platform;
  article.dataset.issueCategory = attribution.issue_category;
  article.dataset.responsibility = attribution.primary_responsibility;
  const searchBaseText = `${payload.record_id} ${analysis.request.platform} ${analysis.report}`;
  article.dataset.feedbackStatus = "unreviewed";
  article.dataset.searchBaseText = searchBaseText;
  article.dataset.searchText = searchBaseText;
  article.innerHTML = `
    <div class="record-meta" data-record-meta>
      <strong>${escapeHtml(analysis.request.platform)}</strong>
      <span>${labelFor("issue_category", attribution.issue_category)}</span>
      <span>${labelFor("responsibility", attribution.primary_responsibility)}</span>
      <span>${labelFor("evidence", attribution.evidence_strength)}</span>
    </div>
    <p>${escapeHtml(analysis.report)}</p>
    ${recordDetailHtml(payload.record_id, analysis)}
  `;
  list.prepend(article);
  bindRecordDetails(article);
  bindRecordCopyActions(article);
  refreshRecordFilterViews();
}

function resultCard(title, body) {
  return `
    <article class="result-card">
      <h3>${escapeHtml(title)}</h3>
      <p>${escapeHtml(body || "暂无信息。")}</p>
    </article>
  `;
}

function labelFor(group, value) {
  if (group === "rootCause") {
    return rootCauseLabel(value);
  }
  return labels[group]?.[value] || value || "未知";
}

function rootCauseLabel(value) {
  const rootCauses = {
    unclear_instructions: "说明或引导不清",
    expectation_mismatch: "预期与实际体验有落差",
    customer_service_gap: "客服排障引导不足",
    product_design: "产品设计容易误用",
    quality_signal: "疑似产品质量异常",
    compatibility_limit: "疑似兼容性限制",
    customer_operation: "客户操作或条件不足",
    insufficient_information: "信息不足",
    non_usage_issue: "非产品使用问题",
  };
  return rootCauses[value] || value || "未知";
}

function bindSummaryRange() {
  const select = document.getElementById("summary-range");
  if (!select) {
    return;
  }

  select.addEventListener("change", () => {
    loadRecordsSummary();
    refreshRecordFilterViews();
  });
}

async function loadRecordsSummary() {
  const container = document.getElementById("summary-content");
  if (!container) {
    return;
  }

  const range = document.getElementById("summary-range")?.value || "all";
  const params = new URLSearchParams();
  params.set("range", range);

  try {
    const response = await fetch(`/api/records/summary?${params.toString()}`);
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(readError(payload));
    }
    renderRecordsSummary(payload);
  } catch (error) {
    container.innerHTML = `<p class="summary-error">${escapeHtml(error.message || "概览加载失败，请刷新页面重试。")}</p>`;
  }
}

async function loadIssueTrends() {
  const container = document.getElementById("trend-content");
  if (!container) {
    return;
  }
  const requestId = ++latestIssueTrendRequestId;

  try {
    const response = await fetch("/api/records/trends?period=7d");
    const payload = await response.json();
    if (requestId !== latestIssueTrendRequestId) {
      return;
    }
    if (!response.ok) {
      throw new Error(readError(payload));
    }
    renderIssueTrends(payload);
  } catch (error) {
    if (requestId !== latestIssueTrendRequestId) {
      return;
    }
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
  bindTaskCreateButtons(container);
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
    <li class="trend-row issue-cluster-actions">
      <button
        class="trend-row-button"
        type="button"
        data-issue-trend-filter
        data-trend-platform="${escapeHtml(platform)}"
        data-trend-issue-category="${escapeHtml(issueCategory)}"
        data-trend-responsibility="${escapeHtml(responsibility)}"
        aria-label="${escapeHtml(ariaLabel)}"
      >${content}</button>
      <button
        class="secondary-action task-create-trigger"
        type="button"
        data-task-create
        data-task-source="trend"
        data-task-platform="${escapeHtml(platform)}"
        data-task-issue-category="${escapeHtml(issueCategory)}"
        data-task-responsibility="${escapeHtml(responsibility)}"
        data-task-significant-increase="${item.significant_increase === true}"
      >创建任务</button>
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
  applySummaryIssueClusterFilter({
    platform,
    issueCategory,
    responsibility,
    platformMatch: "exact",
  });
  loadRecordsSummary();
}

function renderRecordsSummary(summary) {
  const container = document.getElementById("summary-content");
  if (!container) {
    return;
  }

  container.innerHTML = `
    <div class="summary-metrics">
      ${summaryMetric("总记录数", summary.total_records)}
      ${summaryMetric("已复核", summary.reviewed_records)}
      ${summaryMetric("已修正", summary.corrected_records)}
    </div>
    <div class="summary-grid">
      ${summaryIssueClusters(summary.top_issue_clusters)}
      ${summaryDistribution("平台分布", "platform", summary.platforms)}
      ${summaryDistribution("问题类型", "issue_category", summary.issue_categories)}
      ${summaryDistribution("责任方", "responsibility", summary.responsibilities)}
      ${summaryDistribution("证据强度", "evidence", summary.evidence_strengths)}
      ${summaryDistribution("复核状态", "feedback", summary.feedback_statuses)}
    </div>
  `;
  bindSummaryPlatformFilters(container);
  bindSummaryIssueClusterFilters(container);
  bindTaskCreateButtons(container);
}

function summaryIssueClusters(items = []) {
  const rows = items.length
    ? items.map(summaryIssueClusterRow).join("")
    : `<li><span>暂无数据</span><strong>0</strong></li>`;

  return `
    <article class="summary-card distribution-card issue-cluster-card">
      <h3>高频问题</h3>
      <ul class="distribution-list">${rows}</ul>
    </article>
  `;
}

function summaryIssueClusterRow(item) {
  const platform = String(item.platform ?? "").trim();
  const issueCategory = String(item.issue_category ?? "").trim();
  const responsibility = String(item.responsibility ?? "").trim();
  const count = item.count ?? 0;
  const issueLabel = labelFor("issue_category", issueCategory);
  const responsibilityLabel = labelFor("responsibility", responsibility);
  const content = `
    <span class="issue-cluster-label">
      <strong>${escapeHtml(platform || "unknown")}</strong>
      <small>
        ${escapeHtml(issueLabel)} / ${escapeHtml(responsibilityLabel)}
      </small>
    </span>
    <strong>${escapeHtml(count)}</strong>
  `;

  if (!isSummaryIssueClusterFilterable(platform, issueCategory, responsibility)) {
    return `<li>${content}</li>`;
  }

  const ariaLabel = `筛选高频问题：${platform}，${issueLabel}，责任方${responsibilityLabel}，共${count}条`;
  return `
    <li class="issue-cluster-actions">
      <button
        class="issue-cluster-filter"
        type="button"
        data-summary-issue-cluster-filter
        data-summary-cluster-platform="${escapeHtml(platform)}"
        data-summary-cluster-issue-category="${escapeHtml(issueCategory)}"
        data-summary-cluster-responsibility="${escapeHtml(responsibility)}"
        aria-label="${escapeHtml(ariaLabel)}"
      >${content}</button>
      <button
        class="secondary-action task-create-trigger"
        type="button"
        data-task-create
        data-task-source="summary"
        data-task-platform="${escapeHtml(platform)}"
        data-task-issue-category="${escapeHtml(issueCategory)}"
        data-task-responsibility="${escapeHtml(responsibility)}"
        data-task-significant-increase="false"
      >创建任务</button>
    </li>
  `;
}

function isSummaryIssueClusterFilterable(platform, issueCategory, responsibility) {
  const issueFilter = document.getElementById("issue-filter");
  const responsibilityFilter = document.getElementById("responsibility-filter");
  return Boolean(
    platform
    && platform.toLowerCase() !== "unknown"
    && selectHasOption(issueFilter, issueCategory)
    && selectHasOption(responsibilityFilter, responsibility)
  );
}

function selectHasOption(select, value) {
  return Boolean(
    select
    && value
    && Array.from(select.options).some((option) => option.value === value)
  );
}

function summaryMetric(label, value, valueAttribute = "") {
  const attribute = valueAttribute ? ` ${valueAttribute}` : "";
  return `
    <article class="summary-card">
      <span>${escapeHtml(label)}</span>
      <strong${attribute}>${escapeHtml(value)}</strong>
    </article>
  `;
}

function summaryDistribution(title, labelGroup, items = []) {
  const rows = items.length
    ? items.map((item) => `
        <li>
          ${summaryDistributionLabel(labelGroup, item.value)}
          <strong>${escapeHtml(item.count)}</strong>
        </li>
      `).join("")
    : `<li><span>暂无数据</span><strong>0</strong></li>`;

  return `
    <article class="summary-card distribution-card">
      <h3>${escapeHtml(title)}</h3>
      <ul class="distribution-list">${rows}</ul>
    </article>
  `;
}

function summaryDistributionLabel(labelGroup, value) {
  const label = labelFor(labelGroup, value);
  if (labelGroup !== "platform") {
    return `<span>${escapeHtml(label)}</span>`;
  }
  return `
    <button
      class="summary-filter-link"
      type="button"
      data-summary-platform-filter="${escapeHtml(value)}"
    >${escapeHtml(label)}</button>
  `;
}

function bindSummaryPlatformFilters(root = document) {
  root.querySelectorAll("[data-summary-platform-filter]").forEach((button) => {
    if (button.dataset.bound === "true") {
      return;
    }
    button.dataset.bound = "true";
    button.addEventListener("click", () => {
      applySummaryPlatformFilter(button.dataset.summaryPlatformFilter || "");
    });
  });
}

function bindSummaryIssueClusterFilters(root = document) {
  root.querySelectorAll("[data-summary-issue-cluster-filter]").forEach((button) => {
    if (button.dataset.bound === "true") {
      return;
    }
    button.dataset.bound = "true";
    button.addEventListener("click", () => {
      applySummaryIssueClusterFilter({
        platform: button.dataset.summaryClusterPlatform || "",
        issueCategory: button.dataset.summaryClusterIssueCategory || "",
        responsibility: button.dataset.summaryClusterResponsibility || "",
      });
    });
  });
}

function applySummaryPlatformFilter(platform) {
  const value = platform.trim();
  const input = document.getElementById("platform-filter");
  if (!value || !input) {
    return;
  }

  input.value = value;
  input.dataset.matchMode = "";
  refreshRecordFilterViews();
  scrollToRecentRecords();
}

function applySummaryIssueClusterFilter({ platform, issueCategory, responsibility, platformMatch = "" }) {
  const platformValue = String(platform || "").trim();
  const platformFilter = document.getElementById("platform-filter");
  const issueFilter = document.getElementById("issue-filter");
  const responsibilityFilter = document.getElementById("responsibility-filter");

  if (
    !platformFilter
    || !issueFilter
    || !responsibilityFilter
    || !platformValue
    || platformValue.toLowerCase() === "unknown"
    || !selectHasOption(issueFilter, issueCategory)
    || !selectHasOption(responsibilityFilter, responsibility)
  ) {
    return;
  }

  platformFilter.value = platformValue;
  platformFilter.dataset.matchMode = platformMatch === "exact" ? "exact" : "";
  issueFilter.value = issueCategory;
  responsibilityFilter.value = responsibility;
  refreshRecordFilterViews();
  scrollToRecentRecords();
}

function scrollToRecentRecords() {
  const recentRecords = document.getElementById("recent-records");
  const target = recentRecords?.closest("section") || recentRecords;
  if (target) {
    target.scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

function bindFilteredExport() {
  const button = document.querySelector("[data-filter-export]");
  if (!button) {
    return;
  }

  button.addEventListener("click", () => {
    window.location.href = buildFilteredExportUrl();
  });
}

function buildExportFilterParams() {
  const params = new URLSearchParams();
  const summaryRange = document.getElementById("summary-range")?.value || "all";
  const query = document.getElementById("record-search")?.value.trim() || "";
  const platformFilter = document.getElementById("platform-filter");
  const platform = platformFilter?.value.trim() || "";
  const issue = document.getElementById("issue-filter")?.value || "";
  const responsibility = document.getElementById("responsibility-filter")?.value || "";
  const feedback = document.getElementById("feedback-filter")?.value || "";

  if (summaryRange !== "all") {
    params.set("range", summaryRange);
  }
  if (query) {
    params.set("q", query);
  }
  if (platform) {
    params.set("platform", platform);
    if (platformFilter?.dataset.matchMode === "exact") {
      params.set("platform_match", "exact");
    }
  }
  if (issue) {
    params.set("issue_category", issue);
  }
  if (responsibility) {
    params.set("responsibility", responsibility);
  }
  if (feedback) {
    params.set("feedback_status", feedback);
  }
  return params;
}

function buildFilteredExportUrl() {
  const params = buildExportFilterParams();
  const queryString = params.toString();
  return queryString ? `/api/records/export.csv?${queryString}` : "/api/records/export.csv";
}

function buildExportCountPreviewUrl() {
  const params = buildExportFilterParams();
  const queryString = params.toString();
  return queryString ? `/api/records/export-count?${queryString}` : "/api/records/export-count";
}

function exportRangeLabel(value) {
  const rangeLabels = {
    all: "全部记录",
    "7d": "最近 7 天",
    "30d": "最近 30 天",
  };
  return rangeLabels[value] || rangeLabels.all;
}

function updateExportFilterSummary() {
  const summary = document.getElementById("export-filter-summary");
  if (!summary) {
    return;
  }

  const query = document.getElementById("record-search")?.value.trim() || "";
  const platform = document.getElementById("platform-filter")?.value.trim() || "";
  const issue = document.getElementById("issue-filter")?.value || "";
  const responsibility = document.getElementById("responsibility-filter")?.value || "";
  const feedback = document.getElementById("feedback-filter")?.value || "";
  const range = document.getElementById("summary-range")?.value || "all";
  const conditions = [];

  if (platform) {
    conditions.push(`平台：${platform}`);
  }
  if (query) {
    conditions.push(`关键词：${query}`);
  }
  if (issue) {
    conditions.push(`问题类型：${labelFor("issue_category", issue)}`);
  }
  if (responsibility) {
    conditions.push(`责任方：${labelFor("responsibility", responsibility)}`);
  }
  if (feedback) {
    conditions.push(`复核状态：${labelFor("feedback", feedback)}`);
  }
  if (range !== "all") {
    conditions.push(`时间：${exportRangeLabel(range)}`);
  }

  summary.textContent = conditions.length
    ? `筛选导出将应用：${conditions.join("；")}`
    : "将导出全部记录";
}

async function updateExportCountPreview() {
  const preview = document.getElementById("export-count-preview");
  if (!preview) {
    return;
  }

  const requestId = latestExportCountRequestId + 1;
  latestExportCountRequestId = requestId;
  preview.textContent = "预计导出数量加载中...";

  try {
    const response = await fetch(buildExportCountPreviewUrl());
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(readError(payload));
    }
    if (requestId !== latestExportCountRequestId) {
      return;
    }
    preview.textContent = `预计导出 ${payload.count} 条`;
  } catch (error) {
    if (requestId === latestExportCountRequestId) {
      preview.textContent = "预计数量暂不可用";
    }
  }
}

function refreshRecordFilterViews() {
  applyRecordFilters();
  updateExportFilterSummary();
  updateExportCountPreview();
  updateReviewQueueToggle();
}

function bindReviewQueueToggle() {
  const button = document.querySelector("[data-review-queue-toggle]");
  if (!button) {
    return;
  }

  button.addEventListener("click", () => toggleReviewQueueFilter());
  updateReviewQueueToggle();
}

function toggleReviewQueueFilter() {
  const feedbackFilter = document.getElementById("feedback-filter");
  if (!feedbackFilter) {
    return;
  }

  if (feedbackFilter.value === "unreviewed") {
    feedbackFilter.value = "";
  } else {
    feedbackFilter.value = "unreviewed";
  }
  refreshRecordFilterViews();
}

function updateReviewQueueToggle() {
  const button = document.querySelector("[data-review-queue-toggle]");
  if (!button) {
    return;
  }

  const feedbackFilter = document.getElementById("feedback-filter");
  const pendingCount = document.querySelectorAll('#recent-records .record[data-feedback-status="unreviewed"]').length;
  const active = feedbackFilter?.value === "unreviewed";
  button.textContent = `只看待复核（${pendingCount}）`;
  button.classList.toggle("is-active", active);
  button.setAttribute("aria-pressed", String(active));
}

function bindRecordDetails(root = document) {
  root.querySelectorAll("[data-record-detail-toggle]").forEach((button) => {
    if (button.dataset.bound === "true") {
      return;
    }
    button.dataset.bound = "true";
    button.addEventListener("click", () => toggleRecordDetail(button));
  });
}

function toggleRecordDetail(button) {
  const detailId = button.getAttribute("aria-controls");
  const detail = detailId ? document.getElementById(detailId) : null;
  if (!detail) {
    return;
  }

  const expanded = button.getAttribute("aria-expanded") === "true";
  button.setAttribute("aria-expanded", String(!expanded));
  button.textContent = expanded ? "查看详情" : "收起详情";
  detail.hidden = expanded;
}

function bindRecordCopyActions(root = document) {
  root.querySelectorAll("[data-record-copy]").forEach((button) => {
    if (button.dataset.bound === "true") {
      return;
    }
    button.dataset.bound = "true";
    button.addEventListener("click", () => copyRecordDetails(button));
  });
}

async function copyRecordDetails(button) {
  const record = button.closest(".record");
  const status = record?.querySelector("[data-record-copy-status]") || null;
  const text = record ? buildRecordDetailCopyText(record) : "";
  if (!text || !navigator.clipboard || !navigator.clipboard.writeText) {
    setRecordCopyStatus(status, "复制失败，请手动选择详情文本", false);
    return;
  }

  try {
    await navigator.clipboard.writeText(text);
    setRecordCopyStatus(status, "已复制详情", true);
  } catch (error) {
    setRecordCopyStatus(status, "复制失败，请手动选择详情文本", false);
  }
}

function buildRecordDetailCopyText(record) {
  const lines = [
    `平台：${record.dataset.platform || "暂无信息"}`,
    `记录 ID：${record.dataset.recordId || "暂无信息"}`,
  ];
  record.querySelectorAll(".record-detail-grid div").forEach((row) => {
    const label = row.querySelector("dt")?.textContent.trim();
    const value = row.querySelector("dd")?.textContent.trim() || "暂无信息";
    if (label) {
      lines.push(`${label}：${value}`);
    }
  });
  return lines.join("\n");
}

function setRecordCopyStatus(status, message, success) {
  if (!status) {
    return;
  }
  status.textContent = message;
  status.classList.toggle("is-success", success);
  status.classList.toggle("is-error", !success);
}

function recordDetailHtml(recordId, analysis, feedback = null) {
  const attribution = analysis.attribution;
  const feedbackStatus = feedback ? (feedback.accepted ? "已认可" : "已修正") : "未复核";
  const feedbackNote = feedback?.note || "暂无信息";
  const detailId = `record-detail-${recordId}`;

  return `
    <button
      class="record-detail-toggle secondary-action"
      type="button"
      data-record-detail-toggle
      aria-expanded="false"
      aria-controls="${escapeHtml(detailId)}"
    >查看详情</button>
    <div id="${escapeHtml(detailId)}" class="record-detail" hidden>
      <button class="record-copy-action secondary-action" type="button" data-record-copy>复制详情</button>
      <p class="record-copy-status" data-record-copy-status aria-live="polite"></p>
      <dl class="record-detail-grid">
        ${recordDetailRow("客户问题", attribution.customer_problem)}
        ${recordDetailRow("问题类型", labelFor("issue_category", attribution.issue_category))}
        ${recordDetailRow("业务原因", listText((attribution.root_causes || []).map((item) => labelFor("rootCause", item))))}
        ${recordDetailRow("优先责任方", labelFor("responsibility", attribution.primary_responsibility))}
        ${recordDetailRow("证据强度", labelFor("evidence", attribution.evidence_strength))}
        ${recordDetailRow("下一步建议", listText(attribution.recommended_actions))}
        ${recordDetailRow("需要补充信息", listText(attribution.missing_information))}
        ${recordDetailRow("人工复核", feedbackStatus, "data-record-feedback-status")}
        ${recordDetailRow("人工备注", feedbackNote, "data-record-feedback-note")}
      </dl>
    </div>
  `;
}

function recordDetailRow(label, value, valueAttribute = "") {
  const attribute = valueAttribute ? ` ${valueAttribute}` : "";
  return `
    <div>
      <dt>${escapeHtml(label)}</dt>
      <dd${attribute}>${escapeHtml(value || "暂无信息")}</dd>
    </div>
  `;
}

function listText(value) {
  if (!Array.isArray(value)) {
    return value || "暂无信息";
  }
  return value.filter(Boolean).join("；") || "暂无信息";
}

function bindRecordFilters() {
  const form = document.getElementById("record-filter");
  if (!form) {
    return;
  }

  form.addEventListener("input", (event) => {
    if (event.target?.id === "platform-filter") {
      event.target.dataset.matchMode = "";
    }
    refreshRecordFilterViews();
  });
  form.addEventListener("change", () => {
    refreshRecordFilterViews();
  });

  const reset = form.querySelector("[data-filter-reset]");
  if (reset) {
    reset.addEventListener("click", () => resetRecordFilters(form));
  }

  refreshRecordFilterViews();
}

function applyRecordFilters() {
  const records = Array.from(document.querySelectorAll("#recent-records .record"));
  const query = document.getElementById("record-search")?.value.trim().toLowerCase() || "";
  const platformFilter = document.getElementById("platform-filter");
  const platform = platformFilter?.value.trim().toLowerCase() || "";
  const platformMatch = platformFilter?.dataset.matchMode || "";
  const issue = document.getElementById("issue-filter")?.value || "";
  const responsibility = document.getElementById("responsibility-filter")?.value || "";
  const feedback = document.getElementById("feedback-filter")?.value || "";
  let visible = 0;

  records.forEach((record) => {
    const matches = recordMatchesFilters(
      record,
      { query, platform, platformMatch, issue, responsibility, feedback },
    );
    record.hidden = !matches;
    if (matches) {
      visible += 1;
    }
  });

  updateFilterState(visible, records.length);
}

function resetRecordFilters(form) {
  form.reset();
  const platformFilter = document.getElementById("platform-filter");
  if (platformFilter) {
    platformFilter.dataset.matchMode = "";
  }
  refreshRecordFilterViews();
}

function recordMatchesFilters(record, filters) {
  const searchText = (record.dataset.searchText || "").toLowerCase();
  const platform = (record.dataset.platform || "").toLowerCase();
  const matchesQuery = !filters.query || searchText.includes(filters.query);
  const matchesPlatform = !filters.platform || (
    filters.platformMatch === "exact"
      ? platform === filters.platform
      : platform.includes(filters.platform)
  );
  const matchesIssue = !filters.issue || record.dataset.issueCategory === filters.issue;
  const matchesResponsibility = !filters.responsibility || record.dataset.responsibility === filters.responsibility;
  const matchesFeedback = !filters.feedback || record.dataset.feedbackStatus === filters.feedback;
  return matchesQuery && matchesPlatform && matchesIssue && matchesResponsibility && matchesFeedback;
}

function updateFilterState(visible, total) {
  const count = document.getElementById("filter-count");
  const empty = document.getElementById("filter-empty");
  if (count) {
    count.textContent = `当前显示 ${visible} / ${total} 条`;
  }
  if (empty) {
    empty.hidden = visible > 0 || total === 0;
  }
}

function bindTaskFilters() {
  ["task-status-filter", "task-priority-filter"].forEach((id) => {
    document.getElementById(id)?.addEventListener("change", () => loadTasks());
  });
}

function buildTaskListUrl() {
  const params = new URLSearchParams();
  const status = document.getElementById("task-status-filter")?.value || "";
  const priority = document.getElementById("task-priority-filter")?.value || "";
  if (status) {
    params.set("status", status);
  }
  if (priority) {
    params.set("priority", priority);
  }
  const query = params.toString();
  return `/api/tasks${query ? `?${query}` : ""}`;
}

async function loadTasks({ highlightTaskId = "" } = {}) {
  const container = document.getElementById("task-content");
  if (!container) {
    return;
  }
  const requestId = ++latestTaskRequestId;
  try {
    const response = await fetch(buildTaskListUrl());
    const payload = await response.json();
    if (requestId !== latestTaskRequestId) {
      return;
    }
    if (!response.ok) {
      throw new Error(readError(payload));
    }
    renderTasks(payload, highlightTaskId);
  } catch (error) {
    if (requestId !== latestTaskRequestId) {
      return;
    }
    container.innerHTML = `<p class="task-error">${escapeHtml(error.message || "任务数据读取失败")}</p>`;
  }
}

function renderTasks(payload, highlightTaskId = "") {
  const container = document.getElementById("task-content");
  if (!container) {
    return;
  }
  const tasks = payload.tasks || [];
  container.innerHTML = `
    <div class="task-metrics">
      ${summaryMetric("待处理", payload.counts?.pending ?? 0)}
      ${summaryMetric("处理中", payload.counts?.in_progress ?? 0)}
      ${summaryMetric("已完成", payload.counts?.completed ?? 0)}
    </div>
    ${tasks.length
      ? `<div class="task-grid">${tasks.map((task) => taskCardHtml(task)).join("")}</div>`
      : `<p class="task-empty">当前筛选下暂无处理任务。</p>`}
  `;
  bindTaskActions(container);
  if (highlightTaskId) {
    highlightTask(highlightTaskId);
  }
}

function taskCardHtml(task, now = new Date()) {
  const localToday = [
    now.getFullYear(),
    String(now.getMonth() + 1).padStart(2, "0"),
    String(now.getDate()).padStart(2, "0"),
  ].join("-");
  const overdue = task.status !== "completed"
    && task.due_date < localToday;
  const source = task.source === "trend" ? "趋势问题" : "高频问题";
  const result = task.status === "completed"
    ? `
      <p class="task-result"><strong>处理结果：</strong>${escapeHtml(task.result || "暂无信息")}</p>
      <p>完成时间：${escapeHtml(task.completed_at || "暂无信息")}</p>
    `
    : "";
  return `
    <article
      class="task-card"
      data-task-id="${escapeHtml(task.id)}"
      data-task-source-range="${escapeHtml(task.source_range)}"
      data-task-platform="${escapeHtml(task.platform)}"
      data-task-issue-category="${escapeHtml(task.issue_category)}"
      data-task-responsibility="${escapeHtml(task.responsibility)}"
    >
      <div class="task-card-header">
        <h3>${escapeHtml(task.title)}</h3>
        <span class="task-status">${escapeHtml(labelFor("task_status", task.status))}</span>
      </div>
      <div class="task-card-meta">
        <span class="task-source">${source}</span>
        <span class="task-priority">${escapeHtml(labelFor("task_priority", task.priority))}优先级</span>
        ${overdue ? `<span class="task-overdue">已逾期</span>` : ""}
      </div>
      <p>责任团队：${escapeHtml(labelFor("responsibility", task.team))}</p>
      <p>截止日期：${escapeHtml(task.due_date)}</p>
      <button class="task-record-link" type="button" data-task-records>${escapeHtml(task.record_count)} 条关联记录</button>
      ${result}
      ${taskActionsHtml(task)}
    </article>
  `;
}

function bindTaskCreateButtons(root = document) {
  root.querySelectorAll("[data-task-create]").forEach((button) => {
    if (button.dataset.bound === "true") {
      return;
    }
    button.dataset.bound = "true";
    button.addEventListener("click", () => openTaskCreateForm(createTaskDraft({
      source: button.dataset.taskSource || "summary",
      platform: button.dataset.taskPlatform || "",
      issueCategory: button.dataset.taskIssueCategory || "",
      responsibility: button.dataset.taskResponsibility || "",
      significantIncrease: button.dataset.taskSignificantIncrease === "true",
    })));
  });
}

function createTaskDraft({
  source,
  platform,
  issueCategory,
  responsibility,
  significantIncrease,
}) {
  const sourceRange = source === "trend"
    ? "7d"
    : document.getElementById("summary-range")?.value || "all";
  const priority = source === "trend" && significantIncrease ? "high" : "medium";
  return {
    source,
    sourceRange,
    platform,
    issueCategory,
    responsibility,
    significantIncrease,
    team: responsibility,
    priority,
    dueDate: suggestedDueDate(priority),
  };
}

function suggestedDueDate(priority, now = new Date()) {
  const days = { high: 3, medium: 7, low: 14 }[priority] || 7;
  const value = new Date(now.getFullYear(), now.getMonth(), now.getDate() + days);
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function openTaskCreateForm(draft) {
  const form = document.getElementById("task-create-form");
  if (!form) {
    return;
  }
  form.hidden = false;
  form.elements.source.value = draft.source;
  form.elements.source_range.value = draft.sourceRange;
  form.elements.platform.value = draft.platform;
  form.elements.issue_category.value = draft.issueCategory;
  form.elements.responsibility.value = draft.responsibility;
  form.elements.team.value = draft.team;
  form.elements.priority.value = draft.priority;
  form.elements.due_date.value = draft.dueDate;
  form.querySelector("[data-task-create-title]").textContent = (
    `${draft.platform} · ${labelFor("issue_category", draft.issueCategory)} · `
    + labelFor("responsibility", draft.responsibility)
  );
  form.querySelector("[data-task-create-source]").textContent = draft.source === "trend"
    ? "来源：近 7 天趋势"
    : `来源：高频问题（${draft.sourceRange}）`;
  clearError(form.querySelector(".form-message"));
  form.scrollIntoView({ behavior: "smooth", block: "center" });
}

function bindTaskCreateForm() {
  const form = document.getElementById("task-create-form");
  if (!form) {
    return;
  }
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    submitTaskCreate(form);
  });
  form.querySelector("[data-task-create-cancel]")?.addEventListener("click", () => {
    form.hidden = true;
  });
  form.elements.priority.addEventListener("change", () => {
    form.elements.due_date.value = suggestedDueDate(form.elements.priority.value);
  });
}

async function submitTaskCreate(form) {
  const button = form.querySelector("button[type='submit']");
  const message = form.querySelector(".form-message");
  const originalLabel = button.textContent;
  setLoading(button, true);
  clearError(message);
  try {
    const response = await fetch("/api/tasks", {
      method: "POST",
      body: new FormData(form),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(readError(payload));
    }
    form.hidden = true;
    if (!payload.created) {
      const status = document.getElementById("task-status-filter");
      const priority = document.getElementById("task-priority-filter");
      if (status) {
        status.value = "";
      }
      if (priority) {
        priority.value = "";
      }
    }
    await loadTasks(payload.created ? {} : { highlightTaskId: payload.task.id });
  } catch (error) {
    showError(message, error.message || "任务创建失败，请重试。");
  } finally {
    setLoading(button, false);
    button.textContent = originalLabel;
  }
}

function highlightTask(taskId) {
  const cards = Array.from(document.querySelectorAll("[data-task-id]"));
  const card = cards.find((item) => item.dataset.taskId === taskId);
  if (!card) {
    return;
  }
  card.classList.add("is-highlighted");
  card.scrollIntoView({ behavior: "smooth", block: "center" });
  setTimeout(() => card.classList.remove("is-highlighted"), 1800);
}

function taskActionsHtml(task) {
  if (task.status === "completed") {
    return "";
  }
  const primary = task.status === "pending"
    ? `<button class="primary-action" type="button" data-task-start>开始处理</button>`
    : `<button class="primary-action" type="button" data-task-complete-toggle>完成任务</button>`;
  return `
    <div class="task-actions">
      ${primary}
      <button class="secondary-action" type="button" data-task-edit>编辑</button>
    </div>
    <p class="form-message" data-task-action-message role="alert"></p>
    <form class="task-edit-form" hidden>
      <label>
        责任团队
        <select name="team">${taskTeamOptions(task.team)}</select>
      </label>
      <label>
        优先级
        <select name="priority">${taskPriorityOptions(task.priority)}</select>
      </label>
      <label>
        截止日期
        <input name="due_date" type="date" value="${escapeHtml(task.due_date)}">
      </label>
      <button class="primary-action" type="submit">保存</button>
      <p class="form-message" role="alert"></p>
    </form>
    <form class="task-complete-form" hidden>
      <label>
        处理结果
        <textarea name="result" rows="3" required></textarea>
      </label>
      <button class="primary-action" type="submit">确认完成</button>
      <p class="form-message" role="alert"></p>
    </form>
  `;
}

function taskTeamOptions(selected) {
  return Object.entries(labels.responsibility)
    .map(([value, label]) => (
      `<option value="${value}"${value === selected ? " selected" : ""}>${escapeHtml(label)}</option>`
    ))
    .join("");
}

function taskPriorityOptions(selected) {
  return Object.entries(labels.task_priority)
    .map(([value, label]) => (
      `<option value="${value}"${value === selected ? " selected" : ""}>${escapeHtml(label)}</option>`
    ))
    .join("");
}

function bindTaskActions(root) {
  root.querySelectorAll("[data-task-id]").forEach((card) => {
    const taskId = card.dataset.taskId;
    card.querySelector("[data-task-start]")?.addEventListener("click", (event) => {
      updateTask(
        taskId,
        { status: "in_progress" },
        card.querySelector("[data-task-action-message]"),
        event.currentTarget,
      );
    });
    card.querySelector("[data-task-edit]")?.addEventListener("click", () => {
      card.querySelector(".task-edit-form").hidden = false;
    });
    card.querySelector("[data-task-complete-toggle]")?.addEventListener("click", () => {
      card.querySelector(".task-complete-form").hidden = false;
    });

    const editForm = card.querySelector(".task-edit-form");
    editForm?.addEventListener("submit", async (event) => {
      event.preventDefault();
      const data = new FormData(editForm);
      await updateTask(
        taskId,
        Object.fromEntries(data.entries()),
        editForm.querySelector(".form-message"),
        editForm.querySelector("button[type='submit']"),
      );
    });

    const completeForm = card.querySelector(".task-complete-form");
    completeForm?.addEventListener("submit", async (event) => {
      event.preventDefault();
      await completeTask(
        taskId,
        completeForm.elements.result.value,
        completeForm.querySelector(".form-message"),
        completeForm.querySelector("button[type='submit']"),
      );
    });

    card.querySelector("[data-task-records]")?.addEventListener("click", () => {
      drilldownTaskRecords({
        source_range: card.dataset.taskSourceRange,
        platform: card.dataset.taskPlatform,
        issue_category: card.dataset.taskIssueCategory,
        responsibility: card.dataset.taskResponsibility,
      });
    });
  });
}

async function updateTask(taskId, changes, messageTarget, button = null) {
  const originalLabel = button?.textContent || "";
  if (messageTarget?.classList) {
    clearError(messageTarget);
  }
  if (button) {
    setLoading(button, true);
  }
  try {
    const response = await fetch(`/api/tasks/${encodeURIComponent(taskId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(changes),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(readError(payload));
    }
    await loadTasks();
    return true;
  } catch (error) {
    if (messageTarget?.classList) {
      showError(messageTarget, error.message || "任务更新失败，请重试。");
    }
    return false;
  } finally {
    if (button) {
      setLoading(button, false);
      button.textContent = originalLabel;
    }
  }
}

async function completeTask(taskId, result, messageTarget, button = null) {
  const cleaned = String(result || "").trim();
  if (!cleaned) {
    showError(messageTarget, "请填写处理结果后再完成任务。");
    return false;
  }
  return updateTask(
    taskId,
    { status: "completed", result: cleaned },
    messageTarget,
    button,
  );
}

function drilldownTaskRecords(task) {
  const range = document.getElementById("summary-range");
  const platform = document.getElementById("platform-filter");
  const issue = document.getElementById("issue-filter");
  const responsibility = document.getElementById("responsibility-filter");
  if (!range || !platform || !issue || !responsibility) {
    return;
  }
  range.value = task.source_range || "all";
  platform.value = task.platform || "";
  platform.dataset.matchMode = "exact";
  issue.value = task.issue_category || "";
  responsibility.value = task.responsibility || "";
  refreshRecordFilterViews();
  loadRecordsSummary();
  scrollToRecentRecords();
}

function readError(payload) {
  if (typeof payload.detail === "string") {
    return payload.detail;
  }
  if (Array.isArray(payload.detail) && payload.detail[0]?.msg) {
    return payload.detail[0].msg;
  }
  return "分析失败，请检查输入后重试。";
}

function showError(errorBox, message) {
  errorBox.textContent = message;
  errorBox.classList.add("is-visible");
}

function clearError(errorBox) {
  errorBox.textContent = "";
  errorBox.classList.remove("is-visible");
}

function setLoading(button, loading) {
  button.disabled = loading;
  if (loading) {
    button.textContent = button.dataset.loadingLabel || "处理中...";
  }
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
