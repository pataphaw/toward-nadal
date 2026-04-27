# 验证记录（Validation）

## 文档定位
`.void/validation/` 用来沉淀“已经做过的验证、看到的证据、形成的结论”，而不是继续描述方案本身。

当前目录中的记录目前覆盖两个子域：
- 视频切片 `04-video-segmentation`
- 视频精选 `05-video-selection`

每份验证都应按“某个子域的一条证据链”来阅读，而不是把单份文档视为彼此孤立的临时记录。

相关方案入口：
- 当前方案：[视频切片架构（Current）](../solution/04-video-segmentation/current.md)
- 历史方案：[视频切片方案历史（V1）](../solution/04-video-segmentation/history/v1.md)
- 子域索引：[视频切片 V1 验证索引](./video-segmentation-v1-validation-index.md)
- 当前方案：[视频精选架构（Current）](../solution/05-video-selection/current.md)
- 历史方案：[视频精选方案历史（V1）](../solution/05-video-selection/history/v1.md)
- 历史方案：[视频精选方案历史（V4）](../solution/05-video-selection/history/v4.md)
- 历史方案：[视频精选方案历史（v0.4.0）](../solution/05-video-selection/history/v0.4.0.md)
- 历史方案：[视频精选方案历史（v1.0.0）](../solution/05-video-selection/history/v1.0.0.md)

## 当前目录结构
当前目录目前有两个验证子域：
- `video-segmentation-v1`
- `video-selection`

视频切片当前有 `5` 份验证，覆盖五类证据：
- 首轮落地基线：[2026-04-20-video-segmentation-v1-bootstrap](./2026-04-20-video-segmentation-v1-bootstrap.md)
- 导出重跑与资源基线：[2026-04-21-video-segmentation-replay-benchmark](./2026-04-21-video-segmentation-replay-benchmark.md)
- 边界重推基线：[2026-04-22-video-segmentation-boundary-rederive](./2026-04-22-video-segmentation-boundary-rederive.md)
- 误拆修复验证：[2026-04-22-video-segmentation-motion-priority-fix](./2026-04-22-video-segmentation-motion-priority-fix.md)
- 真实使用抽样复核：[2026-04-24-img3076-segmentation-sampling](./2026-04-24-img3076-segmentation-sampling.md)

视频精选当前验证记录按主题分为：
- 旧 CV-heavy 主线的连续反馈链
- 跨视频通用性检查
- `v1.0.0` 主版本升级设计验证

旧 CV-heavy 主线的反馈链：
- 回合完整性反馈与修正：[2026-04-25-video-selection-img3076-rally-completeness](./2026-04-25-video-selection-img3076-rally-completeness.md)

后续边界反馈：
- 回合起点边界反馈与修正：[2026-04-26-video-selection-img3076-rally-start-boundary](./2026-04-26-video-selection-img3076-rally-start-boundary.md)

后续修复验证：
- 回合起点修复验证：[2026-04-26-video-selection-img3076-rally-start-repair](./2026-04-26-video-selection-img3076-rally-start-repair.md)

跨视频通用性检查：
- `img_3026` 通用性检查：[2026-04-26-video-selection-img3026-generalization-check](./2026-04-26-video-selection-img3026-generalization-check.md)

主版本升级设计验证：
- `v1.0.0` 重设计验证：[2026-04-28-video-selection-v1.0.0-redesign](./2026-04-28-video-selection-v1.0.0-redesign.md)
- `v1.0.1` 实现规格补强验证：[2026-04-28-video-selection-v1.0.1-implementation-spec](./2026-04-28-video-selection-v1.0.1-implementation-spec.md)

## 与 Void v0.2.2 的迁移约定
- 现有验证文档保持原文件名与原链接，不做追溯性批量重命名。
- 从下一轮正式修改某个 `solution/current.md` 开始，先归档当前版本，再补对应版本的 `validation`。
- 新增 validation 应显式写出对应的 solution 版本、用户反馈、agent 分析与对问题原因的判断。
- 当验证明确对应某个正式 solution 版本时，优先使用版本号命名；历史探索性记录继续保留描述性命名即可。

## 建议阅读顺序
如果要理解方案如何收敛，建议按时间顺序阅读：

1. [2026-04-20-video-segmentation-v1-bootstrap](./2026-04-20-video-segmentation-v1-bootstrap.md)
2. [2026-04-21-video-segmentation-replay-benchmark](./2026-04-21-video-segmentation-replay-benchmark.md)
3. [2026-04-22-video-segmentation-boundary-rederive](./2026-04-22-video-segmentation-boundary-rederive.md)
4. [2026-04-22-video-segmentation-motion-priority-fix](./2026-04-22-video-segmentation-motion-priority-fix.md)
5. [2026-04-24-img3076-segmentation-sampling](./2026-04-24-img3076-segmentation-sampling.md)

如果要快速定位“当前方案是否暂时可用”，建议优先阅读：

1. [视频切片 V1 验证索引](./video-segmentation-v1-validation-index.md)
2. [2026-04-22-video-segmentation-motion-priority-fix](./2026-04-22-video-segmentation-motion-priority-fix.md)
3. [2026-04-24-img3076-segmentation-sampling](./2026-04-24-img3076-segmentation-sampling.md)

## 当前整理约定
这次整理后，单份验证文档尽量保持以下骨架：
- `文档定位`：这份记录回答什么问题。
- `验证对象`：回链到当前方案、历史方案、验证范围与结论。
- `背景 / 输入 / 方法`：说明证据从哪里来。
- `关键观察 / 结果`：只写当次验证真正看到的事实。
- `结论 / 对方案的影响`：说明这份证据应如何影响当前理解。

这样做的目的不是机械统一格式，而是让每份验证都能回答三个固定问题：
- 它验证的是当前方案，还是历史阶段。
- 它属于“能力基线、资源基线、边界质量、回归修复、用户反馈复核”中的哪一类。
- 它应如何回链到 `solution/current` 与 `solution/history/v1`。
