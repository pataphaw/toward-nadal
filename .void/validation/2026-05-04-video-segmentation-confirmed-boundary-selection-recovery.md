# 视频切片 confirmed 边界恢复验证

## 文档定位
本文档记录 `04-video-segmentation` 为恢复 `05 selection` 可消费性而进行的一次边界确认修复。

它回答的问题是：
- 为什么新素材的 selection 会整体失效。
- 04 的修复是否把 `point_clips` 从“全 uncertain”恢复到“部分 confirmed”。
- `compact_clips` 是否已经从当前实现中正式退出。

## 验证对象
本次验证对应：
- 归档版本：[视频切片阶段快照（V1.2-confirmed-boundary-selection-recovery）](../solution/04-video-segmentation/history/v1.2-confirmed-boundary-selection-recovery.md)
- 当前方案：[视频切片架构（Current）](../solution/04-video-segmentation/current.md)

## 修复前事实
两个新视频在旧逻辑下都出现相同问题：
- `manifest.json` 中存在大量 `point_clips`
- `export_path` 有效
- 但所有片段的 `boundary_status` 都是 `uncertain`
- `selection` 入口只接收 `confirmed`
- 因此 `selection_status = no_candidates`，且 `infeasible_reasons = ["empty-point-clips"]`

旧结果证据：
- [IMG_3197 rerun package](/Users/pataphaw/Projects/toward-nadal/.work/clips/img_3197/20260504-082914/selection_runs/20260504-img3197-rerun/selection-package.json:1)
- [IMG_3198 rerun package](/Users/pataphaw/Projects/toward-nadal/.work/clips/img_3198/20260504-083432/selection_runs/20260504-img3198-rerun/selection-package.json:1)

## 根因
根因链路已确认：
1. `segment_video.py` 的 `enrich_boundary_evidence` 把“无静音锚点”直接视为 `uncertain`
2. 这两段真实素材里 `silences = 0`
3. 因而全部 `point_clips` 被打成 `uncertain`
4. `select_analysis_clips.py` 在入口阶段过滤掉所有非 `confirmed` 片段

这说明 selection 失败不是模型问题，而是 04 边界确认策略过严。

## 修复内容
本次修复包括：
- 收窄 `uncertain` 条件，不再把“无静音锚点”直接视为失败
- 保留锚点证据，但将其降级为辅助信息
- 只将高风险长片段、过短片段等保留为 `uncertain`
- 删除 `compact_clips` 的实际导出逻辑，并恢复到 `compact_clips: []` 兼容字段

## 结果观察
### IMG_3197
修复后重跑切片：
- [manifest.json](/Users/pataphaw/Projects/toward-nadal/.work/clips/img_3197/20260504-220735/manifest.json:1)

边界分布：
- `confirmed = 18`
- `uncertain = 15`

这说明修复已经把原先“全 uncertain”的状态恢复为“部分 confirmed，可进入 selection”。

### IMG_3198
修复后重跑切片：
- [manifest.json](/Users/pataphaw/Projects/toward-nadal/.work/clips/img_3198/20260504-221814/manifest.json:1)

边界分布：
- `confirmed = 15`
- `uncertain = 16`

这说明 `IMG_3198` 也已从“全 uncertain”恢复为“部分 confirmed，可进入 selection”。

### 修复后的 selection 结果
修复后重新执行轻量 selection：
- [IMG_3197 fastfix package](/Users/pataphaw/Projects/toward-nadal/.work/clips/img_3197/20260504-220735/selection_runs/20260504-img3197-fastfix/selection-package.json:1)
- [IMG_3198 fastfix package](/Users/pataphaw/Projects/toward-nadal/.work/clips/img_3198/20260504-221814/selection_runs/20260504-img3198-fastfix/selection-package.json:1)

关键观察：
- 两个 run 都不再出现 `empty-point-clips`
- 两个 run 都已成功进入 `cv_candidate_pool` 构造阶段
- 两个 run 的新失败状态为 `selection_status = model_unavailable`
- 直接原因都是 `request_error:timed out`

这说明本次修复已经消除了“04 把 05 入口清空”的逻辑问题；新的阻塞点变成了本地 VLM 在当前超时配置下未完成候选判定。

### compact_clips
修复后新 run 已满足：
- `counts.compact_clips = 0`
- `manifest.compact_clips = []`
- 新 run 不再导出 `compact_clips/` 目录作为当前主方案产物

## 结论
当前已经可以确认：
- `selection` 失效的直接原因是 04 边界确认逻辑，而不是 05 rerank
- 修复后的 04 已能恢复 `confirmed` 片段产出
- `compact_clips` 已被移出当前实现主线
- `empty-point-clips` 这一逻辑故障已被消除

当前新的后续问题是：
- 本地 VLM 路径在当前超时设置下出现 `model_unavailable`
- 这已不再是 04 边界确认问题，而是 05 运行时 / 超时策略问题
