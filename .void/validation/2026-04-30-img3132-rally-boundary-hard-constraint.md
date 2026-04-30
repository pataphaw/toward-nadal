# 视频切片 `img_3132` 回合边界硬约束修复验证

## 文档定位
本文档记录 `img_3132` 在切片与精选链路上的边界问题分析、已实施修复，以及后续抽查方法。

本轮目标是落实硬约束：
- 所有视频片段必须以完整回合开始
- 所有视频片段必须以完整回合结束
- 不允许开头或结尾截断回合

## 验证对象
当前验证明确关联以下方案版本：
- 当前方案：[视频切片架构（Current）](../solution/04-video-segmentation/current.md)
- 阶段快照：[视频切片阶段快照（V1.1-segment-stable-beta）](../solution/04-video-segmentation/history/v1.1-segment-stable-beta.md)
- 历史主线：[视频切片方案历史（V1）](../solution/04-video-segmentation/history/v1.md)

## 问题复现与样本
用户指出两类问题：
- 结尾被过早切断（当前回合未结束）
- 开头从回合中途开始（未从完整回合开始）

代表样本：
- `point-006_00-02-10.000_00-02-29.500.mp4`
- `point-024_00-17-16.100_00-17-48.500.mp4`
- `point-049_00-36-28.500_00-36-47.000.mp4`
- `point-026_00-18-31.700_00-19-41.100.mp4`
- `point-011_00-05-36.900_00-06-18.300.mp4`

## 根因分析
### 1) 主因在切片层，不在精选层
对 `point-006-candidate-07` 的回查显示：
- `candidate_window` 只覆盖片段中间窗口
- `export_window_proposal` 仍是整段 `point_clip`（0.0 到 clip end）

说明精选没有主动把末尾再切短，问题来自上游 `point_clips` 边界。

### 2) 结尾被截断来自 `segment_video` 的 tail trim 规则
`tools/segment_video.py` 的 `split_point_clips_on_motion_gaps()` 原逻辑会在特定条件下将 `final_end` 回退到 `prev_cluster.end + buffer`，导致回合尾部被提前裁掉。

### 3) 开头被截断来自“活动窗口起点”而非“回合起点锚定”
当前策略按音频/运动活动区间推起点，再加固定 `pre_roll`。当回合前段活动较弱时，容易从中段进入。

### 4) 证据缺失导致不可追溯
`20260429-213649/manifest.json` 中 `point_clips` 的 `boundary_evidence` 为空对象，无法解释每段起止依据，也无法在 selection 端做可靠质量拦截。

## 本轮已实施修复
### A. 取消会提前截尾的行为
文件：`tools/segment_video.py`
- 在 `split_point_clips_on_motion_gaps()` 中移除尾部回退裁剪路径。
- 保持 `final_end = clip.end_time`，避免“回合未结束先截断”。

### B. 增加边界证据增强与完整性状态
文件：`tools/segment_video.py`
- 新增 `enrich_boundary_evidence()`，为每个 `point_clip` 补齐：
  - `start_anchor` / `end_anchor`
  - `boundary_status` (`confirmed` / `uncertain`)
  - `uncertain_reason`
  - `anchor_confidence`
  - `source_signals`
- 规则：
  - 缺失起/止锚点，或片段过短时，标记为 `uncertain`
  - `uncertain` 片段下调置信度

### C. 在精选入口过滤不确定边界片段
文件：`tools/select_analysis_clips.py`
- 读取 `manifest.point_clips` 后，只保留 `boundary_status == "confirmed"` 的片段进入候选生成。
- 防止边界不完整片段进入精选链路。

## 已完成校验
- `python3 -m py_compile tools/segment_video.py tools/select_analysis_clips.py` 通过。
- 代码 diff 已确认覆盖上述三项改动。

## 抽查与后续验证流程
下一轮人工抽查建议固定三组：
1. 用户点名问题样本（优先回归）
2. 随机抽样 10 段
3. 最短时长段（高风险边界段）

每段统一检查：
- 开头是否在完整回合前准备动作处进入
- 结尾是否覆盖到回合结束后的自然停顿
- 是否出现中途断入/断出

## 结论
本轮已将“回合结尾提前截断”的明确代码路径移除，并把“边界完整性”升级为显式状态与过滤条件。

这使边界问题从“难以解释的隐性错误”变为“可追溯、可拦截、可迭代”的显性质量控制流程。

## 用户复核结论（2026-04-30）
用户在新一轮抽查后的结论是：
- 整体效果“好了很多”。
- 仍然存在少量“结尾提前截断”现象。

基于该结论，当前版本定位为：
- 阶段性稳定版本，可支撑后续子域并行推进。
- 切片边界仍有残余缺陷，但本轮不继续优化，暂时冻结该子域实现并转向其他模块。
