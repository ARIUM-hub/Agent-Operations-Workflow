# 高频问题聚类摘要设计

## 背景

当前运营概览已经能展示总记录数、复核状态、平台分布、问题类型、责任方和证据强度。它适合回答“各维度分别是什么情况”，但运营同学还需要快速知道“哪些平台上的哪些问题最集中、应该优先看哪一类”。

本次功能目标是在不新增模型请求的前提下，用现有结构化分析结果生成确定性的高频问题聚类摘要，帮助运营从分布统计进一步进入优先级判断。

## 目标

1. 在 `/api/records/summary` 返回中新增 `top_issue_clusters`。
2. 聚类只基于当前摘要范围内的记录，继续复用已有 `summary-range` 时间范围过滤。
3. 每个问题簇由 `平台 + 问题类型 + 责任方` 组成。
4. 默认返回 Top 5 问题簇，按数量降序排序，数量相同按平台、问题类型、责任方稳定排序。
5. 前端在运营概览区域新增「高频问题」卡片，展示每个问题簇和数量。
6. 不新增模型调用、不新增存储字段、不新增独立 API。

## 非目标

1. 不做语义聚类，不把相似文本报告交给模型合并。
2. 不做平台别名归一化，例如 `Amazon` 与 `Amazon US` 本轮仍视为不同平台。
3. 不做点击筛选联动。平台分布已有点击筛选，本轮只展示高频问题簇。
4. 不改变现有 CSV 导出、复核保存、批量分析和记录筛选逻辑。

## 推荐方案

采用确定性组合键聚类。后端在 `build_records_summary(records)` 遍历记录时，读取：

- `analysis.request.platform`
- `analysis.attribution.issue_category`
- `analysis.attribution.primary_responsibility`

然后用三者组成问题簇 key 并计数。缺失、空白或 `None` 继续复用现有 `_value()` 规则归为 `unknown`。

返回结构示例：

```json
{
  "top_issue_clusters": [
    {
      "platform": "Amazon",
      "issue_category": "function_use",
      "responsibility": "customer_service_training",
      "count": 4
    }
  ]
}
```

前端继续使用 `labelFor("issue_category", value)` 和 `labelFor("responsibility", value)` 显示中文标签。平台值直接显示用户输入或批量上传时选择的平台。

## UI 与交互

运营概览现有结构保持不变：

1. 上方继续显示总记录数、已复核、已修正。
2. 下方分布网格新增一个「高频问题」卡片。
3. 高频问题卡片每行展示：

```text
Amazon / 功能不会用或设置失败 / 客服培训或话术
4
```

如果没有记录，卡片显示“暂无数据 0”。该卡片不提供点击动作，避免和平台分布点击筛选产生混淆。

## 数据流

1. 用户打开页面或切换运营概览时间范围。
2. 前端请求 `/api/records/summary?range=<range>`。
3. 后端先用现有 `filter_records(..., range=range)` 获取范围内记录。
4. `build_records_summary(records)` 同时生成维度分布和 `top_issue_clusters`。
5. 前端 `renderRecordsSummary(summary)` 渲染指标、维度分布和高频问题簇。

## 错误处理

1. 记录缺少 `analysis`、`request` 或 `attribution` 时，不抛错，按 `unknown` 参与聚类。
2. `top_issue_clusters` 为空时，前端显示空态。
3. 摘要接口加载失败时，继续沿用现有“概览加载失败，请刷新页面重试。”提示。

## 测试策略

1. 更新 `tests/test_summary.py`，覆盖同平台同问题同责任方的聚合、Top 排序和空值归一。
2. 更新 `tests/test_app.py` 摘要接口测试，确认响应包含 `top_issue_clusters`。
3. 更新静态 JS hook 测试，确认前端包含 `summary.top_issue_clusters`、`summaryIssueClusters` 或等价渲染 helper，以及「高频问题」文案。
4. 运行完整测试套件，确认现有摘要、筛选、导出、复核、批量分析和本地服务测试不回归。

## 验收标准

1. 运营概览展示「高频问题」卡片。
2. `top_issue_clusters` 只统计当前时间范围内的记录。
3. 相同 `平台 + 问题类型 + 责任方` 被合并计数。
4. 前端显示中文问题类型和责任方标签。
5. 本轮没有新增模型请求、独立 API 或存储字段。
6. 全量测试通过。
