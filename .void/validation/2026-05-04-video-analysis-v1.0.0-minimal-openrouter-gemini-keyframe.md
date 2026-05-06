# 视频分析 v1.0.0 最小闭环验证

## 文档定位
本文档记录 `06-video-analysis` 首个可运行版本的实现与实测结果。

它回答的问题是：
- 当前方案是否已经形成最小正式闭环。
- `OpenRouter + Gemini` 是否已经可稳定跑通一次真实分析。
- 当前实现的边界和已知缺口是什么。

## 验证对象
本次验证对应：
- 历史快照：[视频分析方案历史（v1.0.0）](../solution/06-video-analysis/history/v1.0.0.md)
- 当前方案：[视频分析架构（Current）](../solution/06-video-analysis/current.md)

## 验证范围
本次验证覆盖：
- 方案文档从占位稿收敛为可实现版本。
- 最小 CLI 分析脚本落地。
- `OpenRouter + Gemini 2.5 Flash` 主路径跑通。
- `Gemini 2.5 Pro` 备选模型跑通。
- 输出结果能落为结构化 JSON 与 Markdown 摘要。

本次不覆盖：
- 原生视频直传分析。
- selection 自动发现。
- `no_candidates` 场景自动降级。
- Obsidian 正式落盘。

## 实现证据
当前实现文件：
- [tools/analyse_session.py](/Users/pataphaw/Projects/toward-nadal/tools/analyse_session.py:1)
- [config.example.toml](/Users/pataphaw/Projects/toward-nadal/config.example.toml:1)
- [配置方案](../solution/configuration.md)

当前实现主路径：
- 输入：`selection-package.json`
- 媒体：`selected_clips` 的导出视频
- 模型：`OpenRouter -> Gemini 2.5 Flash`
- 备选：`Gemini 2.5 Pro`
- 输出：`analysis-result.json`、`analysis-report.md`

## 实测结果
### 1. Gemini Flash 主路径已跑通
正式 selected clips 样本：
- [selection-package.json](/Users/pataphaw/Projects/toward-nadal/.work/clips/img_3076/20260423-latest/selection_runs/20260429-img3076-vlm-final/selection-package.json:1)

产出结果：
- [analysis-result.json](/Users/pataphaw/Projects/toward-nadal/.work/clips/img_3076/20260423-latest/selection_runs/20260429-img3076-vlm-final/analysis_runs/20260504-085212/analysis-result.json:1)
- [analysis-report.md](/Users/pataphaw/Projects/toward-nadal/.work/clips/img_3076/20260423-latest/selection_runs/20260429-img3076-vlm-final/analysis_runs/20260504-085212/analysis-report.md:1)

关键结论：
- 实际使用模型为 `google/gemini-2.5-flash`
- 输出包含 `session_summary`、`goal_assessment`、`state_assessment`、`top_findings`、`priority_actions` 等稳定字段
- 结构化结果与 Markdown 摘要都已成功落盘

### 2. Gemini Pro 备选路径已跑通
由于两个新视频都处于 `no_candidates`，本次使用随机 `point_clips` 构造了一份临时分析包：
- [selection-package.json](/Users/pataphaw/Projects/toward-nadal/.work/manual_analysis/20260504-random-point-clips/selection-package.json:1)

对应 prompt 证据：
- [system-prompt.txt](/Users/pataphaw/Projects/toward-nadal/.work/manual_analysis/20260504-random-point-clips/system-prompt.txt:1)
- [user-prompt.txt](/Users/pataphaw/Projects/toward-nadal/.work/manual_analysis/20260504-random-point-clips/user-prompt.txt:1)

产出结果：
- [analysis-result.json](/Users/pataphaw/Projects/toward-nadal/.work/manual_analysis/20260504-random-point-clips/analysis_runs/20260504-094853/analysis-result.json:1)
- [analysis-report.md](/Users/pataphaw/Projects/toward-nadal/.work/manual_analysis/20260504-random-point-clips/analysis_runs/20260504-094853/analysis-report.md:1)

关键结论：
- 实际使用模型为 `google/gemini-2.5-pro`
- 结果比 `Flash` 更倾向于给出更硬、更聚焦执行差距的判断
- 说明主备模型切换链路已经真实可用

## 新视频验证观察
两个新视频的切片和精选结果如下：
- [IMG_3197 selection rerun](/Users/pataphaw/Projects/toward-nadal/.work/clips/img_3197/20260504-082914/selection_runs/20260504-img3197-rerun/selection-package.json:1)
- [IMG_3198 selection rerun](/Users/pataphaw/Projects/toward-nadal/.work/clips/img_3198/20260504-083432/selection_runs/20260504-img3198-rerun/selection-package.json:1)

观察结论：
- 两次 selection 都不是执行失败，而是 `selection_status = no_candidates`
- 根因不是没有 `point_clips`，而是当前 05 selection 只接收 `boundary_status = confirmed`
- 这两个 run 的 `point_clips` 全部为 `boundary_status = uncertain`
- 因此 06 当前版本无法直接消费它们

这说明当前 `06` 的代码链路已通，但对上游 `05` 的依赖边界也已经被真实暴露。

## 结论
`v1.0.0-minimal-openrouter-gemini-keyframe` 已经形成最小正式闭环。

当前可以确认：
- 方案文档与实现一致。
- `Gemini 2.5 Flash` 已可作为默认工作模型。
- `Gemini 2.5 Pro` 已可作为保守备选。
- 输出契约已具备后续复用基础。

当前仍需后续迭代的问题：
- `no_candidates` 的降级路径尚未设计。
- 关键帧方案仍不是最终视频分析形态。
- 记忆输入仍偏粗糙，后续需要更细的组织与裁剪。
