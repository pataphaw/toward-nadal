# 视频切片 V1 验证索引

## 文档定位
本文档是 `video-segmentation-v1` 的子域索引，用来把分散的单次验证记录收束为一条可回溯的证据链。

它回答的是：
- 当前哪些记录属于视频切片 `V1`。
- 每份记录在验证 `V1` 的哪一部分。
- 这些记录分别如何支撑 `solution/current` 与 `solution/history/v1`。

目录级入口见：
- [Validation](./README.md)

方案入口见：
- 当前方案：[视频切片架构（Current）](../solution/04-video-segmentation/current.md)
- 历史方案：[视频切片方案历史（V1）](../solution/04-video-segmentation/history/v1.md)
- 阶段快照：[视频切片阶段快照（V1.1-segment-stable-beta）](../solution/04-video-segmentation/history/v1.1-segment-stable-beta.md)

## 适用范围
当前索引只收录同时满足以下条件的记录：
- 验证对象明确是当前仓库中的视频切片 `V1` 实现或其历史收敛过程。
- 记录内容围绕 `tools/rederive_video_segmentation.py`、更早期切片入口，或其直接导出产物。
- 结论直接服务于 `V1` 的能力判断、资源判断、边界判断或回归判断。

如果后续出现 `V2`、完整 `segment clip` 时间轴验证，或 `05 selection` 的独立验证，应新建独立索引，不与本页混写。

## 方案回链关系
这些验证记录同时服务两类方案文档，但角色不同：

- 对 [视频切片架构（Current）](../solution/04-video-segmentation/current.md)：
  - 提供“当前实现现在能做到什么、还做不到什么”的证据。
  - 支撑当前关于“运动优先、音频辅助、宁可略粘不要断回合”的判断。

- 对 [视频切片方案历史（V1）](../solution/04-video-segmentation/history/v1.md)：
  - 提供“为什么会从早期实现演进到今天”的阶段性证据。
  - 说明哪些历史路径已被吸收，哪些结论只属于某个阶段。

## 已关联记录
### 1. 首轮落地基线
- 文档：[2026-04-20-video-segmentation-v1-bootstrap](./2026-04-20-video-segmentation-v1-bootstrap.md)
- 验证类别：能力基线
- 关联方案：主要归属 `history/v1`，同时为 `current` 提供最早可运行基线
- 回答问题：本机上是否已经跑通第一条可用的 `FFmpeg-first` 切片闭环
- 结论摘要：已跑通，但当时仍是“能跑通”的阶段，不足以代表当前边界质量

### 2. 导出重跑与资源基线
- 文档：[2026-04-21-video-segmentation-replay-benchmark](./2026-04-21-video-segmentation-replay-benchmark.md)
- 验证类别：重跑 / 资源基线
- 关联方案：主要支撑 `current`
- 回答问题：当前导出阶段是否可重跑，以及本机资源开销大致是多少
- 结论摘要：导出可重跑，资源占用在当前本机环境下可接受

### 3. 边界重推基线
- 文档：[2026-04-22-video-segmentation-boundary-rederive](./2026-04-22-video-segmentation-boundary-rederive.md)
- 验证类别：边界重推基线
- 关联方案：同时支撑 `history/v1` 与 `current`
- 回答问题：仓库是否已经拥有“从源视频重抽信号并重新推边界”的稳定入口
- 结论摘要：入口已建立，但当时仍偏音频优先，长片段粘连问题明显

### 4. 运动优先修复
- 文档：[2026-04-22-video-segmentation-motion-priority-fix](./2026-04-22-video-segmentation-motion-priority-fix.md)
- 验证类别：回归修复 / 边界策略修正
- 关联方案：主要支撑 `current`
- 回答问题：把运动证据提升为主候选之后，是否修复了“同一回合被误拆”的关键问题
- 结论摘要：特定误拆已被修复，但代价是长片段粘连风险上升

### 5. 真实使用抽样复核
- 文档：[2026-04-24-img3076-segmentation-sampling](./2026-04-24-img3076-segmentation-sampling.md)
- 验证类别：用户反馈复核
- 关联方案：主要支撑 `current`
- 回答问题：在真实新素材上，当前 `V1` 的主要矛盾到底是“断回合”还是“多回合粘连”
- 结论摘要：当前版本已明显向“保护回合完整性”倾斜，主矛盾转为多回合粘连与长无效内容吸收

### 6. `img_3132` 回合边界硬约束修复
- 文档：[2026-04-30-img3132-rally-boundary-hard-constraint](./2026-04-30-img3132-rally-boundary-hard-constraint.md)
- 验证类别：边界问题归因 / 规则硬化修复
- 关联方案：主要支撑 `current`
- 回答问题：为何会出现“开头/结尾截断回合”，以及如何把“完整回合起止”变成可执行约束
- 结论摘要：主因定位在 `segment_video` 的边界逻辑；已移除提前截尾路径，并引入 `boundary_status` 与 selection 端边界状态过滤

## 推荐阅读路径
### 想看演进脉络
按时间顺序阅读 `1 -> 6`。

### 想看当前方案的可信边界
优先阅读 `3 -> 4 -> 5 -> 6`。

### 想看历史方案为什么被替代
优先阅读 `1 -> 3 -> 4`，再回到 [视频切片方案历史（V1）](../solution/04-video-segmentation/history/v1.md)。

## 记录约定
后续新增 `V1` 验证记录时，建议至少补齐以下信息：

1. `验证对象`
   - 明确链接到 `solution/current` 或 `solution/history/v1`
   - 写清验证范围、证据角色与结论

2. `文档定位`
   - 说明这份记录解决的是哪一类验证问题

3. `对方案的影响`
   - 说明该结论应被视为当前事实、历史事实，还是仅限某次样本的局部观察

## 结论
当前 `.void/validation/` 中这六份记录，应一起视为视频切片 `V1` 的验证证据集。

它们不是“同一个结论的重复表达”，而是分别承担：
- 初始可运行性证明
- 导出重跑证明
- 边界重推基线证明
- 关键误拆修复证明
- 真实使用反馈复核
- 硬约束边界问题修复证明

把这六份记录串起来，才能较完整地解释 `solution/current` 为什么收敛成今天的样子。
