# 视频切片重跑验证记录

## 验证对象
- 子域方案：[视频切片架构（Solution）](../solution/04-video-segmentation.md)
- 实现版本：[视频切片 V1 实现文档](../implementation/04-video-segmentation-v1.md)
- 验证范围：`V1` 的切片导出重跑能力，不包含新的边界推导

## 目的
清理 `.work` 下的历史切片产物后，重新执行一次当前可复现的切片导出流程，并记录耗时与资源消耗。

## 执行范围
- 已清理历史目录：`.work/clips/img_3026/*`
- 保留原始视频备份：`.work/raw-videos/IMG_3026.MOV`
- 本次重跑方式：基于保留下来的最新 `manifest` 边界结果，重放片段导出

说明：
- 当前仓库未跟踪完整的切片检测代码入口。
- 因此这次执行验证的是“切片导出阶段”的重跑，而不是重新推导边界。
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

补充说明：
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

## 观察
- 最慢且最大的片段是 `point-009`
- 片段时长：`75.8s`
- 导出耗时：`7.642s`
- 输出大小：`23519268 bytes`
- 该片段峰值内存：`1124464 KB`
- 该片段峰值 CPU：`893.0%`

## 结论
- `work` 目录历史切片产物已清理。
- 切片导出已成功重跑一次。
- 当前可复现的导出阶段在本机 `Mac` 上耗时约 `1m25s`，峰值内存约 `1.14 GB`，CPU 峰值约 `9` 核。
- 若后续要验证“边界检测阶段”的真实耗时与资源，还需要把切片检测脚本或命令入口纳入仓库。
