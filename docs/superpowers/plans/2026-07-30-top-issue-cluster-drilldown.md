# Top Issue Cluster Drilldown Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (recommended) or superpowers:subagent-driven-development when explicitly needed for independent tasks. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让运营点击“高频问题”问题簇后，一键按平台、问题类型和责任方筛选当前最近 10 条记录，同时保留关键词、复核状态和现有导出链路。

**Architecture:** 保持后端摘要 API、JSONL 存储和模型逻辑不变，只增强现有 `summaryIssueClusters()` 前端渲染。有效问题簇使用原生按钮和专用 `data-*` 属性，点击后通过新的组合筛选 helper 写入三个现有控件，再复用 `refreshRecordFilterViews()` 与共享滚动 helper；无法完整映射到筛选控件的问题簇保持只读。

**Tech Stack:** FastAPI + Jinja2 静态页面，原生 JavaScript，CSS，pytest + TestClient，Node.js 语法检查。

---

## File Structure

- Modify: `src/customer_issue_agent/static/app.js`
  - 把有效问题簇渲染为可访问按钮。
  - 新增可下钻判断、事件绑定、原子组合筛选和共享滚动 helper。
- Modify: `src/customer_issue_agent/static/styles.css`
  - 增加问题簇按钮默认、悬停和键盘焦点样式。
- Modify: `tests/test_app.py`
  - 覆盖 JavaScript 交互钩子和 CSS 状态钩子。
- Modify: `README.md`
  - 说明下钻范围、保留筛选条件和预计导出数量语义。

不修改 `src/customer_issue_agent/app.py`、`summary.py`、模板、存储或领域枚举。

---

### Task 1: Add Accessible Issue Cluster Drilldown Behavior

**Files:**
- Modify: `tests/test_app.py`
- Modify: `src/customer_issue_agent/static/app.js`
- Test: `tests/test_app.py::test_static_app_js_contains_summary_dashboard_hooks`

- [ ] **Step 1: Write the failing JavaScript hook assertions**

In `tests/test_app.py`, append these assertions to `test_static_app_js_contains_summary_dashboard_hooks` after the existing `scrollIntoView` assertion:

```python
    assert "summaryIssueClusterRow" in script
    assert "isSummaryIssueClusterFilterable" in script
    assert "selectHasOption" in script
    assert "data-summary-issue-cluster-filter" in script
    assert "data-summary-cluster-platform" in script
    assert "data-summary-cluster-issue-category" in script
    assert "data-summary-cluster-responsibility" in script
    assert "bindSummaryIssueClusterFilters" in script
    assert "applySummaryIssueClusterFilter" in script
    assert "scrollToRecentRecords" in script
```

- [ ] **Step 2: Run the focused test to verify RED**

Run:

```powershell
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
python -m pytest tests/test_app.py::test_static_app_js_contains_summary_dashboard_hooks -q
```

Expected: `FAIL` because `summaryIssueClusterRow` and the drilldown data attributes do not exist yet.

- [ ] **Step 3: Render valid issue clusters as buttons**

In `src/customer_issue_agent/static/app.js`, replace the current `summaryIssueClusters(items = [])` function with the following functions:

```javascript
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
    <li>
      <button
        class="issue-cluster-filter"
        type="button"
        data-summary-issue-cluster-filter
        data-summary-cluster-platform="${escapeHtml(platform)}"
        data-summary-cluster-issue-category="${escapeHtml(issueCategory)}"
        data-summary-cluster-responsibility="${escapeHtml(responsibility)}"
        aria-label="${escapeHtml(ariaLabel)}"
      >${content}</button>
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
```

This keeps empty and invalid clusters read-only. `selectHasOption()` checks the real filter options, so stale historical values cannot produce a partial drilldown.

- [ ] **Step 4: Bind issue cluster buttons after each summary render**

In `renderRecordsSummary(summary)`, add the new binding immediately after the existing platform binding:

```javascript
  bindSummaryPlatformFilters(container);
  bindSummaryIssueClusterFilters(container);
```

Insert this function immediately after `bindSummaryPlatformFilters(root = document)`:

```javascript
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
```

- [ ] **Step 5: Apply all three filters atomically and share scrolling**

Replace `applySummaryPlatformFilter(platform)` with this block, which also defines the new drilldown and shared scroll helper:

```javascript
function applySummaryPlatformFilter(platform) {
  const value = platform.trim();
  const input = document.getElementById("platform-filter");
  if (!value || !input) {
    return;
  }

  input.value = value;
  refreshRecordFilterViews();
  scrollToRecentRecords();
}

function applySummaryIssueClusterFilter({ platform, issueCategory, responsibility }) {
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
```

Do not read or write `record-search`, `feedback-filter`, or `summary-range` in `applySummaryIssueClusterFilter()`. Their current values must survive the drilldown.

- [ ] **Step 6: Run focused tests and JavaScript syntax verification**

Run:

```powershell
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
python -m pytest tests/test_app.py::test_static_app_js_contains_summary_dashboard_hooks -q
node --check src/customer_issue_agent/static/app.js
```

Expected: `1 passed`, and `node --check` exits with code `0` and no output.

- [ ] **Step 7: Inspect and commit the JavaScript behavior**

Run:

```powershell
git diff --check
git status --short
git diff -- src/customer_issue_agent/static/app.js tests/test_app.py
git add -- tests/test_app.py src/customer_issue_agent/static/app.js
git diff --cached --name-only
git commit -m "feat: drill down top issue clusters"
```

Expected: the commit contains only `tests/test_app.py` and `src/customer_issue_agent/static/app.js`.

---

### Task 2: Add Interaction Styles And Documentation

**Files:**
- Modify: `tests/test_app.py`
- Modify: `src/customer_issue_agent/static/styles.css`
- Modify: `README.md`
- Test: `tests/test_app.py::test_styles_cover_summary_dashboard_components`

- [ ] **Step 1: Write the failing CSS state assertions**

In `tests/test_app.py`, append these assertions to `test_styles_cover_summary_dashboard_components`:

```python
    assert ".issue-cluster-filter" in css
    assert ".issue-cluster-filter:hover" in css
    assert ".issue-cluster-filter:focus-visible" in css
```

- [ ] **Step 2: Run the focused CSS test to verify RED**

Run:

```powershell
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
python -m pytest tests/test_app.py::test_styles_cover_summary_dashboard_components -q
```

Expected: `FAIL` because `.issue-cluster-filter` does not exist yet.

- [ ] **Step 3: Add accessible issue cluster button styles**

In `src/customer_issue_agent/static/styles.css`, insert the following rules immediately after `.issue-cluster-label small`:

```css
.issue-cluster-filter {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  width: 100%;
  border: 0;
  border-radius: 6px;
  padding: 2px 0;
  background: transparent;
  color: inherit;
  cursor: pointer;
  font: inherit;
  text-align: left;
}

.issue-cluster-filter:hover {
  color: var(--accent);
}

.issue-cluster-filter:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 4px;
}
```

The existing `.issue-cluster-card`, `.issue-cluster-label`, list layout, and `@media (max-width: 900px)` rules remain unchanged.

- [ ] **Step 4: Document drilldown behavior and scope**

In `README.md`, under `## 查看运营概览`, replace the existing high-frequency issue paragraph:

```markdown
“高频问题”会按平台、问题类型和责任方组合展示 Top 5 问题簇，适用于当前记录中的任意海外电商平台，帮助运营优先查看最集中的客户使用问题；该统计是确定性聚合，不会额外调用模型。
```

With:

```markdown
“高频问题”会按平台、问题类型和责任方组合展示 Top 5 问题簇，适用于当前记录中的任意海外电商平台，帮助运营优先查看最集中的客户使用问题；该统计是确定性聚合，不会额外调用模型。点击有效问题簇会把平台、问题类型和责任方填入“最近记录”筛选栏，并保留已有关键词和复核状态；页面只筛选当前最近 10 条样本，筛选导出条件和预计导出数量仍基于全部本地 JSONL 记录及当前概览时间范围。
```

- [ ] **Step 5: Run focused tests to verify GREEN**

Run:

```powershell
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
python -m pytest tests/test_app.py::test_styles_cover_summary_dashboard_components tests/test_app.py::test_static_app_js_contains_summary_dashboard_hooks -q
node --check src/customer_issue_agent/static/app.js
```

Expected: `2 passed`, and `node --check` exits with code `0` and no output.

- [ ] **Step 6: Inspect and commit styles and documentation**

Run:

```powershell
git diff --check
git status --short
git diff -- README.md src/customer_issue_agent/static/styles.css tests/test_app.py
git add -- tests/test_app.py src/customer_issue_agent/static/styles.css README.md
git diff --cached --name-only
git commit -m "docs: describe top issue cluster drilldown"
```

Expected: the commit contains only `tests/test_app.py`, `src/customer_issue_agent/static/styles.css`, and `README.md`.

---

### Task 3: Full Verification And Target PR Update

**Files:**
- Verify: repository test suite and JavaScript syntax
- Push: target branch `codex/customer-issue-agent-mvp`

- [ ] **Step 1: Check local commits and clean working tree**

Run:

```powershell
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
git status --short --branch
git log --oneline -8
git diff --check
```

Expected: the working tree is clean. Recent commits include:

```text
docs: describe top issue cluster drilldown
feat: drill down top issue clusters
docs: plan top issue cluster drilldown
docs: design top issue cluster drilldown
```

- [ ] **Step 2: Run complete local verification**

Run:

```powershell
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
python -m pytest -q
node --check src/customer_issue_agent/static/app.js
```

Expected: all pytest tests pass, and `node --check` exits with code `0` and no output.

- [ ] **Step 3: Review the implementation against the approved design**

Run:

```powershell
$designCommit = git log --format='%H' --grep='^docs: design top issue cluster drilldown$' -1
git diff "$designCommit^..HEAD" -- src/customer_issue_agent/static/app.js src/customer_issue_agent/static/styles.css tests/test_app.py README.md docs/superpowers/specs/2026-07-30-top-issue-cluster-drilldown-design.md docs/superpowers/plans/2026-07-30-top-issue-cluster-drilldown.md
```

Verify all of these points from the diff:

1. Only valid clusters become buttons; empty or unrepresentable clusters remain static.
2. Dynamic text and attributes use `escapeHtml()`.
3. The click applies platform, issue category, and responsibility atomically.
4. Keyword, feedback status, and summary range are not modified.
5. `refreshRecordFilterViews()` and shared scrolling are called after a valid click.
6. Existing platform drilldown still uses the same refresh and scroll behavior.
7. Hover and `focus-visible` states exist.
8. No backend API, template, storage, or model file changed.

If any point is false, stop and correct it with a focused failing test before continuing.

- [ ] **Step 4: Confirm the target PR and remote head**

Run:

```powershell
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$targetUrl = 'https://github.com/ARIUM-hub/Agent-Operations-Workflow.git'
$targetRef = 'refs/heads/codex/customer-issue-agent-mvp'
git ls-remote $targetUrl $targetRef
gh pr view 2 --repo ARIUM-hub/Agent-Operations-Workflow --json number,state,headRefName,headRefOid,url,title
```

Expected: PR #2 is `OPEN`, its `headRefName` is `codex/customer-issue-agent-mvp`, and `headRefOid` matches `git ls-remote`.

- [ ] **Step 5: Create a clean push worktree from the current remote head**

Run from the development worktree:

```powershell
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$targetUrl = 'https://github.com/ARIUM-hub/Agent-Operations-Workflow.git'
$targetRef = 'refs/heads/codex/customer-issue-agent-mvp'
$remoteLine = git ls-remote $targetUrl $targetRef
if (-not $remoteLine) { Write-Error 'target branch not found'; exit 1 }
$remoteHead = ($remoteLine -split "`t")[0]
$pushPath = 'C:\Users\DF\Documents\开发智能体\.worktrees\top-issue-cluster-drilldown-clean-push'
if (Test-Path -LiteralPath $pushPath) { Write-Error "clean push worktree path already exists: $pushPath"; exit 1 }

git cat-file -e "$remoteHead^{commit}" 2>$null
if ($LASTEXITCODE -ne 0) {
  git fetch $targetUrl "${targetRef}:refs/remotes/target/customer-issue-agent-mvp"
}

git worktree add -b codex/top-issue-cluster-drilldown-clean-push $pushPath $remoteHead
```

Expected: the clean worktree is created exactly at `$pushPath` and starts at the current target PR head, preserving any remote commits added since the previous feature.

- [ ] **Step 6: Cherry-pick only this feature's commits**

Run in the clean push worktree:

```powershell
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$sourcePath = 'C:\Users\DF\Documents\开发智能体\.worktrees\customer-issue-agent-mvp-continued'
$sourceBranch = 'codex/customer-issue-agent-mvp'
$designCommit = git -C $sourcePath log --format='%H' --grep='^docs: design top issue cluster drilldown$' -1 $sourceBranch
$planCommit = git -C $sourcePath log --format='%H' --grep='^docs: plan top issue cluster drilldown$' -1 $sourceBranch
$behaviorCommit = git -C $sourcePath log --format='%H' --grep='^feat: drill down top issue clusters$' -1 $sourceBranch
$docsCommit = git -C $sourcePath log --format='%H' --grep='^docs: describe top issue cluster drilldown$' -1 $sourceBranch

if (-not $designCommit -or -not $planCommit -or -not $behaviorCommit -or -not $docsCommit) {
  Write-Error 'missing one or more top issue cluster drilldown commits'
  exit 1
}

git cherry-pick $designCommit $planCommit $behaviorCommit $docsCommit
git status --short --branch
git log --oneline -6
```

Expected: four commits are cherry-picked without conflicts and the clean worktree has no uncommitted changes.

- [ ] **Step 7: Verify the exact clean history that will be pushed**

Run in the clean push worktree:

```powershell
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$designCommit = git log --format='%H' --grep='^docs: design top issue cluster drilldown$' -1
if (-not $designCommit) { Write-Error 'design commit not found in clean history'; exit 1 }
$remoteHead = git rev-parse "$designCommit^"
python -m pytest -q
node --check src/customer_issue_agent/static/app.js
git diff "$remoteHead..HEAD" --check
git status --short --branch
$pushHead = git rev-parse HEAD
Write-Output "push_head=$pushHead"
```

Expected: all tests pass, JavaScript syntax is valid, the working tree is clean, and `push_head` is printed.

- [ ] **Step 8: Push explicitly to the target repository**

Run in the clean push worktree:

```powershell
git push https://github.com/ARIUM-hub/Agent-Operations-Workflow.git codex/top-issue-cluster-drilldown-clean-push:codex/customer-issue-agent-mvp
```

Expected: a fast-forward update of `codex/customer-issue-agent-mvp`. Do not push through local `origin`, because it points to the old repository.

- [ ] **Step 9: Confirm PR state and pushed SHA**

Run:

```powershell
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$pushHead = git rev-parse HEAD
gh pr view 2 --repo ARIUM-hub/Agent-Operations-Workflow --json number,state,headRefOid,url,title
git ls-remote https://github.com/ARIUM-hub/Agent-Operations-Workflow.git refs/heads/codex/customer-issue-agent-mvp
Write-Output "expected_push_head=$pushHead"
```

Expected: PR #2 remains `OPEN`, and both commands report the same SHA as `$pushHead`.

- [ ] **Step 10: Remove only the temporary clean push worktree**

Run from the development worktree:

```powershell
$pushPath = 'C:\Users\DF\Documents\开发智能体\.worktrees\top-issue-cluster-drilldown-clean-push'
$resolved = (Resolve-Path -LiteralPath $pushPath).Path
$expected = [System.IO.Path]::GetFullPath($pushPath)
if (-not [string]::Equals($resolved, $expected, [System.StringComparison]::OrdinalIgnoreCase)) {
  Write-Error "unexpected push path: $resolved"
  exit 1
}

git worktree remove $expected
git branch -D codex/top-issue-cluster-drilldown-clean-push
Write-Output "removed=$expected"
```

Expected: only the temporary worktree and temporary local branch are removed. The development worktree, target PR branch, old repository, and unrelated task data remain untouched.

---

## Self-Review

- Spec coverage: The plan covers valid and invalid cluster rendering, full-row native buttons, escaped attributes and text, keyboard labels and focus, atomic three-field filtering, preservation of keyword/feedback/range, current-10-only behavior, export count reuse, empty states, shared scrolling, README documentation, full verification, and target PR update.
- Scope check: The feature is one front-end interaction flow. It does not add a record API, pagination, active/toggle state, backend changes, storage changes, or model calls.
- Type and naming consistency: `summaryIssueClusterRow`, `isSummaryIssueClusterFilterable`, `selectHasOption`, `bindSummaryIssueClusterFilters`, `applySummaryIssueClusterFilter`, `scrollToRecentRecords`, and all `data-summary-cluster-*` names are consistent across tests and implementation steps.
- Safety check: The push process starts from the current target remote head, uses the explicit target repository URL, cherry-picks only this feature's four commits, verifies the clean history, and validates the exact temporary path before cleanup.
