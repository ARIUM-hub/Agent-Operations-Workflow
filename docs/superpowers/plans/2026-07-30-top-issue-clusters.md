# Top Issue Clusters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (recommended) or superpowers:subagent-driven-development when explicitly needed for independent tasks. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在运营概览中展示当前时间范围内 Top 5 的高频问题簇，帮助运营快速看到“哪个平台上的哪类问题由谁优先处理”。

**Architecture:** 扩展现有 `build_records_summary(records)`，在遍历记录时按 `platform + issue_category + primary_responsibility` 做确定性计数，并把 Top 5 作为 `top_issue_clusters` 返回。前端继续请求现有 `/api/records/summary?range=...`，在现有概览网格中新增「高频问题」卡片；不新增 API、存储字段或模型调用。

**Tech Stack:** FastAPI + Jinja2 静态页面，原生 JavaScript，CSS，pytest + TestClient。

---

## File Structure

- Modify: `src/customer_issue_agent/summary.py`
  - 在现有摘要聚合中新增 `top_issue_clusters`。
  - 新增 `_rank_issue_clusters(counter, limit=5)`，保持排序稳定。
- Modify: `tests/test_summary.py`
  - 覆盖问题簇合并、Top 5 截断、排序和未知值兜底。
- Modify: `tests/test_app.py`
  - 覆盖 `/api/records/summary` 返回新字段。
  - 覆盖静态 JS 和 CSS hook。
- Modify: `src/customer_issue_agent/static/app.js`
  - 在 `renderRecordsSummary(summary)` 中渲染 `summaryIssueClusters(summary.top_issue_clusters)`。
  - 新增 `summaryIssueClusters(items = [])` helper。
- Modify: `src/customer_issue_agent/static/styles.css`
  - 给问题簇文本加轻量换行和层级样式。
- Modify: `README.md`
  - 文档化运营概览中的高频问题卡片。

---

### Task 1: Add Backend Summary Cluster Aggregation

**Files:**
- Modify: `tests/test_summary.py`
- Modify: `src/customer_issue_agent/summary.py`
- Test: `tests/test_summary.py`

- [ ] **Step 1: Write failing summary tests**

Replace `tests/test_summary.py` with this content:

```python
from customer_issue_agent.summary import build_records_summary


def _record(
    *,
    platform: object = "Amazon",
    issue_category: object = "function_use",
    responsibility: object = "customer_service_training",
    evidence: object = "likely",
    feedback: dict | None = None,
) -> dict:
    return {
        "analysis": {
            "request": {"platform": platform},
            "attribution": {
                "issue_category": issue_category,
                "primary_responsibility": responsibility,
                "evidence_strength": evidence,
            },
        },
        "feedback": feedback,
    }


def test_build_records_summary_counts_totals_and_dimensions():
    records = [
        _record(platform="Amazon", issue_category="function_use", responsibility="customer_service_training", feedback={"accepted": True}),
        _record(platform="TikTok Shop", issue_category="function_use", responsibility="product", evidence="clear", feedback={"accepted": False}),
        _record(platform="Amazon", issue_category="product_fault", responsibility="product", feedback=None),
    ]

    summary = build_records_summary(records)

    assert summary["total_records"] == 3
    assert summary["reviewed_records"] == 2
    assert summary["corrected_records"] == 1
    assert summary["platforms"] == [
        {"value": "Amazon", "count": 2},
        {"value": "TikTok Shop", "count": 1},
    ]
    assert summary["issue_categories"] == [
        {"value": "function_use", "count": 2},
        {"value": "product_fault", "count": 1},
    ]
    assert summary["responsibilities"] == [
        {"value": "product", "count": 2},
        {"value": "customer_service_training", "count": 1},
    ]
    assert summary["evidence_strengths"] == [
        {"value": "likely", "count": 2},
        {"value": "clear", "count": 1},
    ]
    assert summary["feedback_statuses"] == [
        {"value": "accepted", "count": 1},
        {"value": "corrected", "count": 1},
        {"value": "unreviewed", "count": 1},
    ]


def test_build_records_summary_returns_top_issue_clusters():
    records = [
        _record(platform="Amazon", issue_category="function_use", responsibility="customer_service_training"),
        _record(platform="Amazon", issue_category="function_use", responsibility="customer_service_training"),
        _record(platform="TikTok Shop", issue_category="product_fault", responsibility="product"),
        _record(platform="TikTok Shop", issue_category="product_fault", responsibility="product"),
        _record(platform="Amazon", issue_category="installation", responsibility="customer"),
        _record(platform="eBay", issue_category="logistics", responsibility="platform_policy"),
        _record(platform="Walmart Marketplace", issue_category="quality_expectation", responsibility="product"),
        _record(platform="Shopee", issue_category="function_use", responsibility="customer_service_training"),
        _record(platform="Temu", issue_category="installation", responsibility="customer"),
    ]

    summary = build_records_summary(records)

    assert summary["top_issue_clusters"] == [
        {
            "platform": "Amazon",
            "issue_category": "function_use",
            "responsibility": "customer_service_training",
            "count": 2,
        },
        {
            "platform": "TikTok Shop",
            "issue_category": "product_fault",
            "responsibility": "product",
            "count": 2,
        },
        {
            "platform": "Amazon",
            "issue_category": "installation",
            "responsibility": "customer",
            "count": 1,
        },
        {
            "platform": "eBay",
            "issue_category": "logistics",
            "responsibility": "platform_policy",
            "count": 1,
        },
        {
            "platform": "Shopee",
            "issue_category": "function_use",
            "responsibility": "customer_service_training",
            "count": 1,
        },
    ]


def test_build_records_summary_handles_empty_and_unknown_values():
    assert build_records_summary([]) == {
        "total_records": 0,
        "reviewed_records": 0,
        "corrected_records": 0,
        "platforms": [],
        "issue_categories": [],
        "responsibilities": [],
        "evidence_strengths": [],
        "feedback_statuses": [],
        "top_issue_clusters": [],
    }

    summary = build_records_summary(
        [
            {"analysis": {"request": {}, "attribution": {}}, "feedback": None},
            {"analysis": {"request": {"platform": "   "}, "attribution": {}}, "feedback": None},
        ]
    )

    assert summary["platforms"] == [{"value": "unknown", "count": 2}]
    assert summary["issue_categories"] == [{"value": "unknown", "count": 2}]
    assert summary["responsibilities"] == [{"value": "unknown", "count": 2}]
    assert summary["evidence_strengths"] == [{"value": "unknown", "count": 2}]
    assert summary["feedback_statuses"] == [{"value": "unreviewed", "count": 2}]
    assert summary["top_issue_clusters"] == [
        {
            "platform": "unknown",
            "issue_category": "unknown",
            "responsibility": "unknown",
            "count": 2,
        }
    ]
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
python -m pytest tests/test_summary.py -q
```

Expected: `FAIL` because `top_issue_clusters` is not returned yet.

- [ ] **Step 3: Implement backend aggregation**

Replace `src/customer_issue_agent/summary.py` with this content:

```python
from __future__ import annotations

from collections import Counter
from typing import Any

IssueClusterKey = tuple[str, str, str]


def build_records_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    platforms: Counter[str] = Counter()
    issue_categories: Counter[str] = Counter()
    responsibilities: Counter[str] = Counter()
    evidence_strengths: Counter[str] = Counter()
    feedback_statuses: Counter[str] = Counter()
    issue_clusters: Counter[IssueClusterKey] = Counter()
    reviewed_records = 0
    corrected_records = 0

    for record in records:
        analysis = record.get("analysis") or {}
        request = analysis.get("request") or {}
        attribution = analysis.get("attribution") or {}
        platform = _value(request.get("platform"))
        issue_category = _value(attribution.get("issue_category"))
        responsibility = _value(attribution.get("primary_responsibility"))
        platforms[platform] += 1
        issue_categories[issue_category] += 1
        responsibilities[responsibility] += 1
        evidence_strengths[_value(attribution.get("evidence_strength"))] += 1
        issue_clusters[(platform, issue_category, responsibility)] += 1

        status = _feedback_status(record.get("feedback"))
        feedback_statuses[status] += 1
        if status != "unreviewed":
            reviewed_records += 1
        if status == "corrected":
            corrected_records += 1

    return {
        "total_records": len(records),
        "reviewed_records": reviewed_records,
        "corrected_records": corrected_records,
        "platforms": _rank(platforms),
        "issue_categories": _rank(issue_categories),
        "responsibilities": _rank(responsibilities),
        "evidence_strengths": _rank(evidence_strengths),
        "feedback_statuses": _rank(feedback_statuses),
        "top_issue_clusters": _rank_issue_clusters(issue_clusters),
    }


def _feedback_status(feedback: object) -> str:
    if not isinstance(feedback, dict):
        return "unreviewed"
    return "accepted" if feedback.get("accepted") else "corrected"


def _rank(counter: Counter[str]) -> list[dict[str, int | str]]:
    return [
        {"value": value, "count": count}
        for value, count in sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    ]


def _rank_issue_clusters(counter: Counter[IssueClusterKey], limit: int = 5) -> list[dict[str, int | str]]:
    return [
        {
            "platform": platform,
            "issue_category": issue_category,
            "responsibility": responsibility,
            "count": count,
        }
        for (platform, issue_category, responsibility), count in sorted(
            counter.items(),
            key=lambda item: (-item[1], item[0][0], item[0][1], item[0][2]),
        )[:limit]
    ]


def _value(value: object) -> str:
    if value is None:
        return "unknown"
    stripped = str(value).strip()
    return stripped or "unknown"
```

- [ ] **Step 4: Run tests to verify pass**

Run:

```powershell
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
python -m pytest tests/test_summary.py -q
```

Expected: `3 passed`.

- [ ] **Step 5: Commit backend aggregation**

Run:

```powershell
git add -- tests/test_summary.py src/customer_issue_agent/summary.py
git commit -m "feat: aggregate top issue clusters"
```

Expected: commit succeeds with only `tests/test_summary.py` and `src/customer_issue_agent/summary.py` staged.

---

### Task 2: Render Top Issue Clusters In The Summary Dashboard

**Files:**
- Modify: `tests/test_app.py`
- Modify: `src/customer_issue_agent/static/app.js`
- Test: `tests/test_app.py`

- [ ] **Step 1: Write failing API and JS hook tests**

In `tests/test_app.py`, update `test_records_summary_endpoint_returns_counts` by adding these assertions after the existing distribution assertions:

```python
    assert payload["top_issue_clusters"]
    assert payload["top_issue_clusters"][0]["platform"] == "Amazon"
    assert payload["top_issue_clusters"][0]["count"] == 1
```

Update `test_records_summary_endpoint_returns_empty_summary` by adding:

```python
    assert payload["top_issue_clusters"] == []
```

Update `test_static_app_js_contains_summary_dashboard_hooks` by adding:

```python
    assert "summary.top_issue_clusters" in script
    assert "summaryIssueClusters" in script
    assert "高频问题" in script
```

- [ ] **Step 2: Run focused tests to verify failure**

Run:

```powershell
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
python -m pytest tests/test_app.py::test_records_summary_endpoint_returns_counts tests/test_app.py::test_records_summary_endpoint_returns_empty_summary tests/test_app.py::test_static_app_js_contains_summary_dashboard_hooks -q
```

Expected: `FAIL` because the API response or static JS does not yet include the new dashboard rendering hook.

- [ ] **Step 3: Render the card in `renderRecordsSummary(summary)`**

Modify the `summary-grid` template in `src/customer_issue_agent/static/app.js` so it includes `summaryIssueClusters` before the dimension distributions:

```javascript
    <div class="summary-grid">
      ${summaryIssueClusters(summary.top_issue_clusters)}
      ${summaryDistribution("平台分布", "platform", summary.platforms)}
      ${summaryDistribution("问题类型", "issue_category", summary.issue_categories)}
      ${summaryDistribution("责任方", "responsibility", summary.responsibilities)}
      ${summaryDistribution("证据强度", "evidence", summary.evidence_strengths)}
      ${summaryDistribution("复核状态", "feedback", summary.feedback_statuses)}
    </div>
```

- [ ] **Step 4: Add `summaryIssueClusters(items = [])` helper**

Insert this function immediately before `summaryMetric(label, value)` in `src/customer_issue_agent/static/app.js`:

```javascript
function summaryIssueClusters(items = []) {
  const rows = items.length
    ? items.map((item) => `
        <li>
          <span class="issue-cluster-label">
            <strong>${escapeHtml(item.platform)}</strong>
            <small>
              ${escapeHtml(labelFor("issue_category", item.issue_category))}
              / ${escapeHtml(labelFor("responsibility", item.responsibility))}
            </small>
          </span>
          <strong>${escapeHtml(item.count)}</strong>
        </li>
      `).join("")
    : `<li><span>暂无数据</span><strong>0</strong></li>`;

  return `
    <article class="summary-card distribution-card issue-cluster-card">
      <h3>高频问题</h3>
      <ul class="distribution-list">${rows}</ul>
    </article>
  `;
}
```

- [ ] **Step 5: Run focused tests to verify pass**

Run:

```powershell
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
python -m pytest tests/test_app.py::test_records_summary_endpoint_returns_counts tests/test_app.py::test_records_summary_endpoint_returns_empty_summary tests/test_app.py::test_static_app_js_contains_summary_dashboard_hooks -q
```

Expected: `3 passed`.

- [ ] **Step 6: Commit dashboard rendering**

Run:

```powershell
git add -- tests/test_app.py src/customer_issue_agent/static/app.js
git commit -m "feat: show top issue clusters"
```

Expected: commit succeeds with only `tests/test_app.py` and `src/customer_issue_agent/static/app.js` staged.

---

### Task 3: Add Styles And README Documentation

**Files:**
- Modify: `tests/test_app.py`
- Modify: `src/customer_issue_agent/static/styles.css`
- Modify: `README.md`
- Test: `tests/test_app.py`

- [ ] **Step 1: Write failing CSS hook test**

Update `test_styles_cover_summary_dashboard_components` in `tests/test_app.py` by adding:

```python
    assert ".issue-cluster-card" in css
    assert ".issue-cluster-label" in css
```

- [ ] **Step 2: Run focused CSS hook test to verify failure**

Run:

```powershell
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
python -m pytest tests/test_app.py::test_styles_cover_summary_dashboard_components -q
```

Expected: `FAIL` because `.issue-cluster-card` is not present in `styles.css`.

- [ ] **Step 3: Add CSS for issue cluster rows**

Add this CSS near the existing `.distribution-card` and `.summary-filter-link` rules in `src/customer_issue_agent/static/styles.css`:

```css
.issue-cluster-card {
  grid-column: span 2;
}

.issue-cluster-label {
  display: grid;
  gap: 4px;
}

.issue-cluster-label small {
  color: var(--muted);
  font-size: 13px;
  font-weight: 600;
}
```

Inside the existing `@media (max-width: 900px)` block, add:

```css
  .issue-cluster-card {
    grid-column: span 1;
  }
```

- [ ] **Step 4: Document the new summary card**

In `README.md`, under `## 查看运营概览`, replace this paragraph:

```markdown
工作台会基于当前本地 JSONL 中的全部分析记录生成“运营概览”。概览包含总记录数、已复核数、已修正数，以及平台、问题类型、责任方、证据强度和复核状态分布。
```

With:

```markdown
工作台会基于当前本地 JSONL 中的全部分析记录生成“运营概览”。概览包含总记录数、已复核数、已修正数、高频问题，以及平台、问题类型、责任方、证据强度和复核状态分布。
```

After the platform drilldown paragraph, add:

```markdown
“高频问题”会按平台、问题类型和责任方组合展示 Top 5 问题簇，帮助运营优先查看最集中的客户使用问题；该统计是确定性聚合，不会额外调用模型。
```

- [ ] **Step 5: Run focused CSS test to verify pass**

Run:

```powershell
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
python -m pytest tests/test_app.py::test_styles_cover_summary_dashboard_components -q
```

Expected: `1 passed`.

- [ ] **Step 6: Commit styles and docs**

Run:

```powershell
git add -- tests/test_app.py src/customer_issue_agent/static/styles.css README.md
git commit -m "docs: describe top issue clusters"
```

Expected: commit succeeds with only `tests/test_app.py`, `src/customer_issue_agent/static/styles.css`, and `README.md` staged.

---

### Task 4: Full Verification And Target PR Update

**Files:**
- Verify: repository test suite
- Push: `codex/customer-issue-agent-mvp`

- [ ] **Step 1: Check local status and recent commits**

Run:

```powershell
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
git status --short --branch
git log --oneline -8
```

Expected: working tree is clean. Latest local commits include:

```text
docs: describe top issue clusters
feat: show top issue clusters
feat: aggregate top issue clusters
docs: design top issue clusters
```

- [ ] **Step 2: Run full test suite**

Run:

```powershell
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
python -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 3: Confirm target PR head**

Run:

```powershell
git ls-remote https://github.com/ARIUM-hub/Agent-Operations-Workflow.git refs/heads/codex/customer-issue-agent-mvp
```

Expected: output begins with the current target PR head SHA. If it is `9faff4579c38ce93012edb188dae7f81ee327b7e`, continue with Step 4. If it differs, inspect the remote commits before pushing.

- [ ] **Step 4: Push through a clean temporary worktree**

Because the local `origin` points to `ARIUM-hub/AI-Agent-Development`, use the explicit target URL and a clean worktree rooted at the target PR head.

Run:

```powershell
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$pushPath = 'C:\Users\DF\Documents\开发智能体\.worktrees\top-issue-clusters-clean-push'
if (Test-Path -LiteralPath $pushPath) { Write-Error "clean push worktree path already exists: $pushPath"; exit 1 }
git worktree add -b codex/top-issue-clusters-clean-push $pushPath 9faff4579c38ce93012edb188dae7f81ee327b7e
```

Then in the clean worktree:

```powershell
cd 'C:\Users\DF\Documents\开发智能体\.worktrees\top-issue-clusters-clean-push'
$sourcePath = 'C:\Users\DF\Documents\开发智能体\.worktrees\customer-issue-agent-mvp-continued'
$sourceBranch = 'codex/customer-issue-agent-mvp'
$designCommit = git -C $sourcePath log --format='%H' --grep='^docs: design top issue clusters$' -1 $sourceBranch
$backendCommit = git -C $sourcePath log --format='%H' --grep='^feat: aggregate top issue clusters$' -1 $sourceBranch
$dashboardCommit = git -C $sourcePath log --format='%H' --grep='^feat: show top issue clusters$' -1 $sourceBranch
$docsCommit = git -C $sourcePath log --format='%H' --grep='^docs: describe top issue clusters$' -1 $sourceBranch
if (-not $designCommit -or -not $backendCommit -or -not $dashboardCommit -or -not $docsCommit) {
  Write-Error 'missing one or more top issue cluster commits'
  exit 1
}
git cherry-pick $designCommit $backendCommit $dashboardCommit $docsCommit
python -m pytest -q
git push https://github.com/ARIUM-hub/Agent-Operations-Workflow.git codex/top-issue-clusters-clean-push:codex/customer-issue-agent-mvp
```

Expected: tests pass and push updates PR #2.

- [ ] **Step 5: Confirm PR state**

Run:

```powershell
gh pr view 2 --repo ARIUM-hub/Agent-Operations-Workflow --json number,state,headRefOid,url,title
git ls-remote https://github.com/ARIUM-hub/Agent-Operations-Workflow.git refs/heads/codex/customer-issue-agent-mvp
```

Expected: PR #2 is `OPEN`, and `headRefOid` matches the pushed remote branch SHA.

- [ ] **Step 6: Clean temporary worktree**

Run:

```powershell
cd 'C:\Users\DF\Documents\开发智能体\.worktrees\customer-issue-agent-mvp-continued'
$pushPath = 'C:\Users\DF\Documents\开发智能体\.worktrees\top-issue-clusters-clean-push'
$resolved = (Resolve-Path -LiteralPath $pushPath).Path
if ($resolved -ne $pushPath) { Write-Error "unexpected push path: $resolved"; exit 1 }
git worktree remove $pushPath
git branch -D codex/top-issue-clusters-clean-push
```

Expected: temporary worktree and temporary branch are removed.

---

## Self-Review

- Spec coverage: The plan covers backend `top_issue_clusters`, current time-range reuse through existing summary endpoint, deterministic `platform + issue_category + responsibility` clustering, Top 5 sorting, frontend card rendering, empty/unknown values, README documentation, full tests, and target PR update.
- Completion scan: Every implementation step includes concrete code, commands, and expected outcomes.
- Type consistency: Names are consistent across plan sections: `top_issue_clusters`, `summary.top_issue_clusters`, `summaryIssueClusters`, `issue-cluster-card`, and `issue-cluster-label`.
