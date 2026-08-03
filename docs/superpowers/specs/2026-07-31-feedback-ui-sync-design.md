# 反馈保存后 UI 即时同步设计

## 背景

客户使用问题归因智能体已经支持单条与批量分析、人工反馈、最近记录筛选、待复核快捷入口、筛选导出、运营概览和高频问题下钻。当前反馈 POST 成功后，页面只在表单下方显示“已保存”文案，不会同步记录卡片的复核状态。

这会造成多个可见不一致：

- 当前记录仍标记为 `unreviewed`。
- “只看待复核”中的记录不会移出，数量不会减少。
- 批次摘要的待复核数量保持初始值。
- 最近记录详情和复制内容仍显示“未复核”与旧备注。
- 运营概览中的已复核数、已修正数和复核状态分布需要刷新页面后才更新。

本轮目标是在后端确认反馈保存成功后，集中同步同一记录在页面中的所有视图，让运营可以连续复核而无需刷新页面。

## 目标

1. 保存成功后立即把记录状态更新为 `accepted` 或 `corrected`。
2. 同一记录同时出现在单条结果、批次结果和最近记录时，所有实例保持一致。
3. 新增或更新中文状态标签，不重复创建标签。
4. 立即更新最近记录详情中的“人工复核”和“人工备注”。
5. 复制详情时读取更新后的状态与备注。
6. 重新生成最近记录的关键词搜索文本，使新备注可搜索、旧备注不再命中。
7. 刷新最近记录筛选、待复核数量、导出条件提示和预计导出数量。
8. 启用“只看待复核”时，已保存记录立即从当前列表隐藏。
9. 重新计算当前批次的待复核数量。
10. 每次反馈保存成功后刷新运营概览一次。
11. 反馈表单保存后继续可编辑和再次提交。

## 非目标

- 不做提交前的乐观更新。
- 不刷新整个页面。
- 不锁定反馈表单，也不新增“重新编辑”模式。
- 不自动跳转到下一条待复核记录。
- 不新增撤销反馈或反馈历史界面。
- 不改变原始归因的问题类型、责任方或报告内容。
- 不在卡片主标签中展示修正后的问题类型与责任方；这些字段继续保存在反馈记录与 CSV 导出中。
- 不新增后端 API、存储字段或模型调用。
- 不修改供应商、代理通道或本地模型转发逻辑。

## 采用方案

采用“保存成功后集中同步 UI”。`submitFeedbackForm(form)` 继续负责反馈请求和成功/失败提示。POST 成功后，它调用新的本地同步入口，再分别触发现有的筛选刷新和运营概览刷新。

不采用以下方案：

- 保存后刷新整个页面。虽然数据一致，但会丢失当前筛选、滚动位置、展开详情和批次上下文。
- 提交前乐观更新。保存失败时需要回滚多个卡片、详情、筛选和统计，复杂度高且容易出现残留状态。
- 只更新当前反馈表单附近的卡片。反馈表单位于单条或批次结果区，而参与最近记录筛选的是另一张同记录卡片，局部更新无法形成一致闭环。

## DOM 状态契约

### 记录容器

单条分析结果、批次结果卡片和最近记录卡片统一提供：

- `data-record-id`：记录 ID。
- `data-feedback-status`：`unreviewed`、`accepted` 或 `corrected`。

初次分析生成的单条与批次结果默认为 `unreviewed`。服务端渲染的最近记录继续根据已保存反馈生成真实状态。

同步逻辑不使用带动态记录 ID 的 CSS 选择器，而是遍历 `[data-record-id]` 后按 `dataset.recordId` 精确比较，避免记录 ID 中特殊字符带来选择器转义问题。

### 状态标签容器

所有可展示状态标签的元信息区域增加 `data-record-meta`：

- 单条结果使用现有 `.summary-strip`。
- 批次结果和最近记录使用现有 `.record-meta`。

状态标签继续使用 `.feedback-pill`。同步时先查找已有标签：存在则更新 `textContent`，不存在则创建 `span.feedback-pill` 并追加到 `data-record-meta`。重复提交不会生成多个标签。

### 详情字段

服务端模板和 `recordDetailHtml()` 生成的详情增加：

- `data-record-feedback-status`：人工复核文本节点。
- `data-record-feedback-note`：人工备注文本节点。

同步时使用 `textContent` 写入“已认可”或“已修正”，备注为空时写入“暂无信息”。这样可以保证备注中的 HTML 字符只作为文本显示。

`buildRecordDetailCopyText(record)` 已从详情 `dt/dd` 读取文本，因此详情 DOM 更新后，复制内容会自然使用最新状态和备注，不新增第二套复制数据。

### 搜索文本

最近记录增加 `data-search-base-text`，只包含记录 ID、平台和原始报告，不包含反馈备注。`data-search-text` 继续作为实际关键词过滤字段。

- 服务端渲染时：基础文本不含备注，实际搜索文本为基础文本加当前备注。
- 新分析插入最近记录时：基础文本与实际搜索文本初始相同。
- 反馈同步时：实际搜索文本重建为基础文本加最新备注。

该方式可以在重复修改备注时移除旧备注，避免简单追加导致历史备注继续被关键词筛选命中。

### 批次待复核指标

批次摘要中的待复核数字增加 `data-batch-pending-count`。批次结果卡片都提供 `data-feedback-status`。

反馈同步后，从当前 `.batch-list` 内重新统计 `data-feedback-status="unreviewed"` 的记录数量，再写入指标。采用重新计算而不是简单减一，可以正确处理重复提交、从已认可改为已修正以及页面中缺少部分卡片等情况。

## 前端组件

### 反馈视图模型

新增 `feedbackUiState(feedback)`，把 API 返回反馈归一为：

```javascript
{
  value: "accepted" | "corrected",
  label: "已认可" | "已修正",
  note: string,
}
```

该 helper 集中定义状态值、中文文案和空备注兜底，避免各更新函数重复判断 `feedback.accepted`。

### 集中同步入口

新增 `syncFeedbackUi(recordId, feedback)`，执行以下本地同步：

1. 调用 `feedbackUiState(feedback)`。
2. 遍历所有 `[data-record-id]`，筛出相同记录 ID 的视图。
3. 对每个视图调用 `updateRecordFeedbackView(record, state)`。
4. 调用 `updateBatchPendingCount()` 重新计算批次待复核数量。

找不到任何匹配记录时不抛错，仍允许后续筛选与运营概览刷新继续执行。

### 单视图更新

`updateRecordFeedbackView(record, state)` 负责：

- 写入 `record.dataset.feedbackStatus`。
- 更新或创建 `.feedback-pill`。
- 更新详情中的复核状态和备注文本。
- 如果记录具有 `data-search-base-text`，重建 `data-search-text`。

这个函数只修改传入记录视图，不发请求，也不直接刷新筛选，便于独立测试和复用。

### 提交成功流程

`submitFeedbackForm(form)` 在响应成功后按以下顺序执行：

1. `syncFeedbackUi(payload.record_id, payload.feedback)`。
2. `refreshRecordFilterViews()`。
3. `loadRecordsSummary()`。
4. 更新当前表单成功提示。

`refreshRecordFilterViews()` 会复用现有链路：

- 按当前筛选重新显示或隐藏最近记录。
- 更新“当前显示”数量和空状态。
- 更新筛选导出条件提示。
- 请求真实预计导出数量。
- 更新“只看待复核”按钮数量与激活状态。

`loadRecordsSummary()` 会使用当前概览时间范围请求现有摘要接口，并重新渲染运营概览。每次成功保存只调用一次。

反馈成功提示不等待概览请求完成。`loadRecordsSummary()` 已在内部处理错误，因此概览刷新失败不会回滚已成功保存的反馈，也不会把反馈表单改为失败提示。

## 数据流

1. 用户在单条或批次结果中提交反馈表单。
2. 前端 POST 到现有 `/api/records/{record_id}/feedback`。
3. 后端写入 JSONL 反馈事件并返回 `{record_id, feedback}`。
4. 前端归一反馈 UI 状态。
5. 前端按记录 ID 更新页面中所有对应卡片。
6. 前端重算批次待复核数量。
7. 前端刷新最近记录筛选与待复核数量。
8. 前端刷新运营概览一次。
9. 用户继续编辑当前表单，或处理下一条仍可见记录。

## 筛选行为

- 未启用复核状态筛选：记录保留在最近记录列表中，状态标签立即变化。
- 启用“只看待复核”或选择“未复核”：记录状态更新后立即隐藏，待复核数量减一。
- 选择“已认可”：保存认可反馈后记录变为可见；保存修正反馈后记录隐藏。
- 选择“已修正”：保存修正反馈后记录变为可见；保存认可反馈后记录隐藏。
- 关键词筛选：新备注立即参与当前页面最近记录筛选，旧备注不再命中。
- 平台、问题类型、责任方和概览时间范围保持不变。

## 重复提交

反馈表单保持可编辑。用户可以从已认可改为已修正，或从已修正改为已认可：

- API 继续追加新的反馈事件，并以最新反馈作为当前状态。
- 状态标签原位更新，不新增第二个标签。
- 详情与备注覆盖为最新值。
- 搜索文本使用最新备注重建。
- 批次待复核数量保持基于 `unreviewed` 的实际计数，不因 reviewed 状态之间切换而变化。
- 运营概览重新请求后展示最新聚合结果。

## 错误与边界处理

- POST 返回非成功状态：不调用任何同步函数，保持原页面状态并显示现有错误提示。
- 响应成功但页面没有对应记录视图：不报错，仍刷新筛选和运营概览。
- 记录视图缺少元信息容器：跳过状态标签，只更新其他可用钩子。
- 记录视图缺少详情字段：跳过详情更新。
- 页面没有批次摘要：跳过批次计数更新。
- 备注为空：详情显示“暂无信息”，搜索文本只使用基础文本。
- 备注包含 HTML：通过 `textContent` 和数据属性处理，不执行 HTML。
- 运营概览刷新失败：概览显示现有错误状态，反馈保存仍保持成功。
- 预计导出数量刷新失败：继续显示现有“预计数量暂不可用”。

## 文件改动

- Modify: `src/customer_issue_agent/static/app.js`
  - 增加反馈 UI 状态归一、集中同步、单视图更新、标签更新、批次计数和搜索文本重建。
  - 在反馈成功后刷新筛选与运营概览。
  - 为动态单条、批次和最近记录添加状态与元信息钩子。
- Modify: `src/customer_issue_agent/templates/index.html`
  - 为服务端最近记录添加元信息、详情和搜索基础文本钩子。
- Modify: `tests/test_app.py`
  - 覆盖服务端模板和静态 JavaScript 钩子。
- Create: `tests/js/test_feedback_ui.mjs`
  - 使用 Node 内置 `node:test`、`assert` 和轻量 DOM stub 验证真实同步行为。
- Modify: `README.md`
  - 说明反馈保存后记录、筛选、批次摘要、详情和运营概览会即时同步。

不修改后端路由、存储、领域模型、归因规则或 CSS 视觉系统。

## 测试策略

### pytest 契约测试

更新 `tests/test_app.py`，覆盖：

- 服务端记录包含 `data-record-meta`。
- 服务端详情包含 `data-record-feedback-status` 和 `data-record-feedback-note`。
- 服务端最近记录包含 `data-search-base-text`。
- JavaScript 包含 `feedbackUiState`、`syncFeedbackUi`、`updateRecordFeedbackView`、`updateFeedbackPill` 和 `updateBatchPendingCount`。
- 反馈成功路径调用 `refreshRecordFilterViews()` 和 `loadRecordsSummary()`。

### Node 行为测试

新增 `tests/js/test_feedback_ui.mjs`，通过 Node 内置 VM 加载真实 `app.js`，使用轻量 DOM stub 覆盖：

1. 已认可反馈更新所有同 ID 视图。
2. 已修正反馈使用正确状态值和中文标签。
3. 已有状态标签原位更新，没有重复标签。
4. 新备注更新详情与搜索文本，旧备注被替换。
5. 缺少最近记录或部分 DOM 钩子时不抛错。
6. 批次待复核数量按当前卡片状态重新计算。
7. 同步函数只修改目标记录 ID。
8. 表单成功路径触发本地同步、筛选刷新和一次概览刷新。
9. 表单失败路径不触发同步。

不引入 npm 包或浏览器测试框架。

### 完整验证

```powershell
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
python -m pytest -q
node --test tests/js/test_feedback_ui.mjs
node --check src/customer_issue_agent/static/app.js
git diff --check
```

## 验收标准

1. 反馈保存成功后无需刷新页面即可看到最新复核状态。
2. 所有同记录 ID 的可见卡片状态一致。
3. 最近记录详情与复制内容使用最新状态和备注。
4. 关键词筛选使用最新备注，不保留旧备注命中。
5. “只看待复核”时已处理记录立即移出，数量准确。
6. 当前批次待复核数量准确且重复提交不会错误减一。
7. 运营概览每次成功保存只刷新一次。
8. 表单保持可编辑，重复提交更新而不是复制状态标签。
9. 保存失败不改变任何本地反馈状态。
10. 不新增后端 API、存储字段、npm 依赖或模型调用。
11. pytest、Node 行为测试、JavaScript 语法和差异检查全部通过。
