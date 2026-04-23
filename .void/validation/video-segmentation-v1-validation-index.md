# 视频切片 V1 验证索引

## 文档定位
本文档用于把 `.void/validation` 中与视频切片 `V1` 实现相关的验证记录收束到同一个索引下。

它回答的是：
- 当前哪些验证记录属于视频切片 `V1`。
- 每份记录在验证 `V1` 的哪一部分。
- 这些记录如何回链到方案层与历史方案文档。

相关文档：
- 子域方案：[视频切片架构（Current）](../solution/04-video-segmentation/current.md)
- 历史版本：[视频切片方案历史（V1）](../solution/04-video-segmentation/history/v1.md)

## 当前关联规则
当前索引只收录满足以下条件的记录：
- 验证对象明确是当前仓库中的视频切片 `V1` 实现。
- 记录内容围绕 `tools/rederive_video_segmentation.py` 或其直接导出产物。
- 结论服务于 `V1` 的边界、导出、资源消耗或回归判断。

后续如果出现 `V2` 或完整 `segment clip` 实现，应新建独立索引，不与 `V1` 混写。

## 已关联记录
### V1 首轮落地
- [2026-04-20-video-segmentation-v1-bootstrap](./2026-04-20-video-segmentation-v1-bootstrap.md)
- 说明：验证 `V1` 初始 `FFmpeg-first` 切片器的首轮调参与真实导出结果。

### 导出重跑
- [2026-04-21-video-segmentation-replay-benchmark](./2026-04-21-video-segmentation-replay-benchmark.md)
- 说明：验证 `V1` 导出阶段的可重跑性、耗时、CPU、内存与磁盘占用。

### 边界重推基线
- [2026-04-22-video-segmentation-boundary-rederive](./2026-04-22-video-segmentation-boundary-rederive.md)
- 说明：验证 `V1` 从源视频重抽信号并重新推导边界的基线结果。

### 运动优先修复
- [2026-04-22-video-segmentation-motion-priority-fix](./2026-04-22-video-segmentation-motion-priority-fix.md)
- 说明：验证 `V1` 将运动证据提升为主候选后，对误拆问题的修复效果与新风险。

## 使用约定
后续新增与视频切片 `V1` 相关的验证记录时，建议保持两条约定：

1. 在验证文档开头增加 `验证对象` 段，明确链接到对应 `solution` 文档与方案版本。
2. 将新记录补入本索引，说明它验证的是 `V1` 的哪一部分。

## 结论
当前 `.void/validation` 中与视频切片相关的四份记录，都应视为视频切片 `V1` 的验证证据，而不是泛化到未来所有版本的通用结论。
