# 视频切片 V1 导出重跑验证

## 文档定位
这份记录验证的不是“边界是怎么推出来的”，而是当前导出阶段是否已经具备稳定重跑能力，以及在本机环境下大致会消耗多少资源。

它主要是 `solution/current` 的运行基线证据。

相关文档：
- 目录入口：[Validation](./README.md)
- 子域索引：[视频切片 V1 验证索引](./video-segmentation-v1-validation-index.md)

## 验证对象
- 当前方案：[视频切片架构（Current）](../solution/04-video-segmentation/current.md)
- 历史方案参照：[视频切片方案历史（V1）](../solution/04-video-segmentation/history/v1.md)
- 证据角色：导出重跑与资源基线
- 验证范围：`V1` 的切片导出重跑能力，不包含新的边界推导
- 验证结论：通过

## 背景与范围
清理 `.work` 下的历史切片产物后，重新执行一次当前可复现的切片导出流程，并记录耗时与资源消耗。

本次执行范围：
- 已清理历史目录：`.work/clips/img_3026/*`
- 保留原始视频备份：`.work/raw-videos/IMG_3026.MOV`
- 重跑方式：基于保留下来的最新 `manifest` 边界结果，重放片段导出

边界说明：
- 当前仓库当时尚未跟踪完整的切片检测代码入口。
- 因此这次验证的是“导出阶段可否重跑”，而不是“边界是否可从源视频重新推导”。
- 导出边界来源于临时备份的旧 `manifest`，随后已重新写入新的运行目录。

## 输入与输出
- 输入视频：`.work/raw-videos/IMG_3026.MOV`
- 边界来源：`/tmp/toward-nadal-segmentation-source-manifest.json`
- 新运行目录：[20260421-215047](/Users/pataphaw/Projects/toward-nadal/.work/clips/img_3026/20260421-215047)
- 新 `manifest`：[manifest.json](/Users/pataphaw/Projects/toward-nadal/.work/clips/img_3026/20260421-215047/manifest.json)
- 资源记录：[resource-metrics.json](/Users/pataphaw/Projects/toward-nadal/.work/clips/img_3026/20260421-215047/logs/resource-metrics.json)
- 单段指标：[per-clip-metrics.json](/Users/pataphaw/Projects/toward-nadal/.work/clips/img_3026/20260421-215047/logs/per-clip-metrics.json)

## 执行结果
- 导出片段数量：`37`
- 本次重跑只导出 `manifest` 中定义的基础片段，不涉及额外聚合产物
- `.work/clips/img_3026` 当前仅保留本次运行目录

## 时间与资源消耗
- 总耗时：`84.613s`
- 峰值 CPU：`911.0%`
- 采样平均 CPU：`627.58%`
- 峰值内存：`1140.45 MB`
- 输出文件总大小：`275388218 bytes`，约 `275.4 MB`

说明：
- CPU 由运行中的 `ffmpeg` 进程采样得到，`911%` 可理解为大约占满 `9.1` 个逻辑核心。
- 内存为采样到的单进程峰值 RSS。

## 磁盘占用
清理前：
- `.work`：`5702068 KB`
- `.work/clips`：`1768880 KB`
- `.work/raw-videos`：`3933180 KB`

重跑后：
- `.work`：`4215032 KB`
- `.work/clips`：`281844 KB`
- `.work/raw-videos`：`3933180 KB`
- 本次运行目录：`281832 KB`
- 本次导出片段目录：`281776 KB`

判断：
- 历史切片目录已清理干净。
- 原始视频备份未受影响。
- 本次重跑后，`.work` 总占用明显下降，主要因为旧的多轮切片产物已删除。

## 关键观察
- 最慢且最大的片段是 `point-009`
- 片段时长：`75.8s`
- 导出耗时：`7.642s`
- 输出大小：`23519268 bytes`
- 该片段峰值内存：`1124464 KB`
- 该片段峰值 CPU：`893.0%`

这说明当前导出成本主要仍由少数长片段驱动，而不是由片段数量本身驱动。

## 对方案的影响
这份记录对当前方案有两个作用：
- 证明导出阶段已经可以在本机环境中稳定重跑，不再依赖一次性人工操作。
- 提供了后续性能对比时可直接复用的资源基线。

这份记录不回答：
- 当前边界质量是否已经足够好。
- 从源视频重推边界的阶段耗时与资源开销。

## 结论
- `work` 目录历史切片产物已清理。
- 切片导出已成功重跑一次。
- 当前可复现的导出阶段在本机 `Mac` 上耗时约 `1m25s`，峰值内存约 `1.14 GB`，CPU 峰值约 `9` 核。
- 若后续要验证“边界检测阶段”的真实耗时与资源，还需要把切片检测脚本或命令入口纳入仓库。
