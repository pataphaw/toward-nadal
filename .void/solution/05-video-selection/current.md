# 视频精选架构（Current）

## 文档定位
本文档定义视频精选子域当前生效方案。

当前版本已经从架构草案补齐为实现规格。它必须能直接指导代码实现，不再把关键工程决策留给实现者临场判断。

它回答的是：
- 05 selection 在 `CV` 与本地视觉模型之间如何分工。
- v1 第一版具体使用哪个本地视觉模型运行时。
- `selection_package`、候选、模型输入、模型判断和最终选择的字段契约是什么。
- 如何让 05 输出继续被 06 analysis 与 07 persistence 稳定消费。

相关文档：
- [视频切片架构（Current）](../04-video-segmentation/current.md)
- [视频分析架构（Current）](../06-video-analysis/current.md)
- [结果保存架构（Current）](../07-result-persistence/current.md)
- [配置方案](../configuration.md)
- [总体架构](../../blueprint/overall-architecture.md)
- [视频精选 v1.0.1 实现规格补强验证](../../validation/2026-04-28-video-selection-v1.0.1-implementation-spec.md)
- [视频精选 v1.0.2 本地 VLM 有效 selection 恢复验证](../../validation/2026-05-05-video-selection-v1.0.2-local-vlm-selection-recovery.md)
- [视频精选 v1.0.3 单一最终输出目录验证](../../validation/2026-05-06-video-selection-v1.0.3-single-final-selected-clips.md)
- [视频精选 v1.0.4 本地 VLM 串行稳定性验证](../../validation/2026-05-06-video-selection-v1.0.4-local-vlm-serial-stability.md)

历史方案链路：
- [视频精选方案历史（V1）](./history/v1.md)
- [视频精选方案历史（V2）](./history/v2.md)
- [视频精选方案历史（V3）](./history/v3.md)
- [视频精选方案历史（V4）](./history/v4.md)
- [视频精选方案历史（v0.4.0）](./history/v0.4.0.md)
- [视频精选方案历史（v1.0.0）](./history/v1.0.0.md)
- [视频精选方案历史（v1.0.2）](./history/v1.0.2.md)
- [视频精选方案历史（v1.0.3）](./history/v1.0.3.md)
- [视频精选方案历史（v1.0.4）](./history/v1.0.4.md)

说明：
- 当前方案是一次大规模重设计，用于代码实现时不以历史方案作为实现依据。
- 历史方案仅用于追溯 selection 子域的演进、失败模式和版本替代关系。

## 当前生效版本
当前生效版本为 `v1.0.4-local-vlm-serial-stability`。

这是 `05 selection` 的当前主线：
- `CV` 不再承担最终语义判断。
- `CV` 只负责高召回候选生成、基础质量判断、运动证据提取和候选窗口定位。
- 本地视觉模型负责判断候选是否真正在打球、是否完整、是否值得分析。
- selection 负责过滤、覆盖约束、去重、排序和不确定性暴露。

## 核心结论
selection 的目标不是“找运动最强的片段”，而是“选出最值得送给 06 analysis 的代表样本”。

这个目标已经超出纯 `CV + 规则` 的稳定能力边界。

因此新版方案采用两层职责：
- `CV candidate generation`：便宜、稳定、可解释、高召回，宁可多给候选，不在这里做最终淘汰。
- `local VLM rerank`：较贵、语义更强，负责候选级最终判断，只处理已经被压缩过的小候选池。

## 目标与边界
本子域负责：
- 从 04 的 `point_clips` 中生成一组高召回候选。
- 为每个候选提取可解释的 CV 证据。
- 为每个候选构建模型输入包。
- 调用本地视觉模型输出结构化 `model_judgement`。
- 基于模型判断、覆盖约束和候选质量输出 `selected_clips`。
- 把不确定项显式放入 `review_queue`。

本子域不负责：
- 训练或微调视觉模型。
- 生成最终网球技术诊断。
- 逐帧精确识别每一次击球类型、球路、落点或旋转。
- 依赖云端模型作为主路径。
- 用 CV 规则替代视觉模型做最终语义裁判。

## 能力边界
### CV 应该做什么
`CV` 适合承担确定性强、成本低、可解释的前处理任务：
- 视频可用性检查：黑屏、模糊、抖动、分辨率、帧率。
- 候选窗口定位：运动峰值、连续运动区间、音频瞬态、空档。
- 片段压缩：从长 `point clip` 中提取若干短候选窗口。
- 基础证据提取：运动密度、横向位移、dead time、候选时长、边界风险。
- 候选去重：时间重叠、同源片段、运动轮廓近似重复。

`CV` 不应负责最终判断：
- 是否真的是打球回合。
- 是否是休息、捡球、回位、等待。
- 是否完整覆盖一个 rally。
- 是否是正手、反手、发球的可靠覆盖样本。
- 是否是值得复盘的亮点或问题样本。

### 本地视觉模型应该做什么
本地视觉模型负责候选级语义理解：
- 判断候选是否 `in_play`。
- 判断是否存在明显的休息 / 捡球 / 等待 / 走动。
- 判断候选是否覆盖较完整 rally。
- 粗判是否包含 `forehand`、`backhand`、`serve`。
- 判断候选的复盘价值：`highlight`、`good_example`、`problem_example`。
- 给出简短、可追溯的入选或排除理由。

本地视觉模型不负责：
- 长视频全量扫描。
- 毫秒级边界切割。
- 专业级动作归因。
- 输出最终训练建议。

## v1.0.4 固定实现决策
### 本地模型运行时
v1.0.4 当前固定使用：
- `provider = ollama`
- `endpoint = http://localhost:11434/api/chat`
- `model = qwen2.5vl:3b`
- `fallback_model = qwen2.5vl:3b`
- `temperature = 0`
- `format = json`
- `timeout_seconds = 180`
- `max_retries = 1`

选择理由：
- `Ollama` 官方支持 vision model 的图像输入。
- `qwen2.5vl` 在 Ollama library 中提供 `3b / 7b / 32b / 72b` 版本，并支持 `Text, Image` 输入。
- 关键帧序列输入比直接视频输入更稳定，也更符合 Ollama vision API 的工程形态。
- 当前机器上 `3b + 少量候选 + 少量关键帧` 已验证可以稳定返回有效 judgement，比 `7b` 作为主路径更务实。
- 默认 fallback 不再切到 `7b`，避免一次失败重试直接把本地负载抬高。

### 本地运行时保护
v1.0.4 新增两层保护：

- 全局本地 VLM 锁
  - 同一时间只允许一个 selection run 进入本地模型判断阶段
  - 防止多个视频 run 并发争抢同一个 Ollama 实例
- 调用前 preflight
  - 在真正发起模型请求前检查 `ollama ps`
  - 如果存在残留模型任务，先尝试清理，再等待 Ollama 回到空闲状态
  - 若在等待窗口内仍无法空闲，则本轮直接失败，不带着脏状态继续跑

### 输出目录语义
`selection_runs/` 与 `selected_clips/` 的职责必须分离：

- `selection_runs/<selection_run_id>/`
  - 保存一次 selection run 的完整审计记录
  - 允许多次并存
  - 允许失败、实验性结果和重复片段
- `selected_clips/`
  - 只保存当前被提升为最终结果的一组视频切片
  - 目录下不再按多个 `selection_run_id` 并列保留
  - 每次成功 promotion 时整体覆盖

实现约束：
- 默认情况下，成功 run 会覆盖 `<run-dir>/selected_clips/`。
- 如果只是实验 run，不希望覆盖最终结果，必须显式传 `--skip-promote-selected-clips`。
- `selected_clips/manifest.json` 必须记录当前最终结果来自哪个 `selection_run_id`。

明确暂缓：
- `MLX/VLM` 不作为 v1.0.1 必需实现路径，只保留为后续 `local_vlm_runner` adapter。
- 不在 v1.0.1 中实现云端模型 fallback。

### 模型输入形态
v1.0.4 不把视频文件直接传给模型。

每个候选传入：
- `1-12` 张 JPEG 关键帧，默认 `2` 张。
- 候选元数据。
- CV 证据摘要。
- 固定 prompt，其中显式写出目标 JSON 结构与枚举。

关键帧必须覆盖：
- 候选开头。
- 候选中段。
- 候选结尾。
- CV 运动峰值附近补帧。

### 模型调用方式
实现层应直接调用 Ollama HTTP API，避免新增 Python SDK 依赖。

请求必须满足：
- `stream = false`
- `options.temperature = 0`
- `format = json`
- `messages[0].images` 使用 base64 JPEG 列表
- prompt 中显式嵌入字段、枚举和值域约束

实现约束补充：
- `candidate_pool_size` 和 `frames_per_candidate` 必须真实按输入参数生效，只允许做安全上界/下界钳制，不允许偷偷抬高到固定最小值。
- 模型原始响应必须落盘，哪怕后续 JSON 解析或字段校验失败。
- 如果整轮没有任何合法 `model_judgement`，即使生成了 fallback judgement，也必须输出 `selection_status = model_unavailable`，不能继续产生伪成功的 `selected_clips`。
- 本地模型判断阶段必须串行执行，不允许多个 selection run 并发打同一 Ollama 实例。

如果请求超时、连接失败、模型不存在或返回非 2xx：
- 若当前模型不是 fallback，则尝试 `fallback_model`。
- 若 fallback 仍失败，则本轮输出 `selection_status = model_unavailable`。

## 输入输出契约
### 输入
标准输入来自 04 的一次切片运行：
- `manifest.json`
- `point_clips/`

每个 `point_clip` 至少继承：
- `clip_id: string`
- `source_video_id: string`
- `start_time: number`
- `end_time: number`
- `duration: number`
- `confidence: number`
- `boundary_evidence: object`
- `export_path: string`

可选输入：
- `handedness = right / left / unknown`
- `serve_presence = auto / present / absent`
- `selection_focus: string[]`
- `candidate_pool_size: number`，默认 `4`
- `selected_size: number`，默认 `3`
- `frames_per_candidate: number`，默认 `2`

### 输出
05 输出 `selection_package`。

顶层字段：
- `selection_version: "v1.0.3-single-final-selected-clips"`
- `source_segmentation_run: object`
- `selection_run_id: string`
- `params: object`
- `cv_candidate_pool: cv_candidate[]`
- `model_input_packages: model_input_package[]`
- `model_judgements: model_judgement[]`
- `selected_clips: selected_clip[]`
- `coverage_report: coverage_report`
- `review_queue: selected_clip[]`
- `selection_status: selection_status`
- `infeasible_reasons: string[]`
- `selected_clip_exports_dir: string | null`
- `selected_clip_exports: object[]`
- `selected_clips_result_role: "final" | "trial"`
- `promoted_selected_clips: boolean`
- `selection_notes: object`

`selection_status` 枚举：
- `ready`
- `constrained_incomplete`
- `model_unavailable`
- `model_degraded`
- `no_candidates`

`selected_clips[]` 必须同时保留新版字段和 06 兼容字段：
- `candidate_window`
- `export_window`
- `focus_window`

兼容规则：
- `focus_window` 是 `candidate_window` 的兼容别名。
- 06 analysis 优先消费 `export_window` 对应导出视频。
- 06 analysis 使用 `focus_window` 表示分析焦点。

## 通用数据类型
### `time_window`
所有窗口字段统一使用以下结构：

```json
{
  "source_clip_offset_start": 0.0,
  "source_clip_offset_end": 12.4,
  "absolute_start_time": 128.0,
  "absolute_end_time": 140.4,
  "absolute_timebase": "source_video_timeline"
}
```

约束：
- 单位为秒。
- `source_clip_offset_start >= 0`。
- `source_clip_offset_end > source_clip_offset_start`。
- `absolute_start_time` 与 `absolute_end_time` 基于原始 source video 时间轴。

### `confidence`
所有置信度字段使用 `0.0-1.0`。

分档：
- `>= 0.70`：高置信。
- `0.50-0.69`：中置信。
- `< 0.50`：低置信。

## 核心对象
### `cv_candidate`
`cv_candidate` 是 CV 层输出的候选样本。

必填字段：
- `candidate_id: string`
- `clip_id: string`
- `source_video_id: string`
- `source_clip_path: string`
- `candidate_kind: motion_dense / rally_wide / opening_probe / recovery_probe`
- `candidate_window: time_window`
- `export_window_proposal: time_window`
- `cv_evidence: cv_evidence`
- `cv_risk_flags: string[]`
- `dedupe_key: string`
- `source_clip_probe: object`

语义约束：
- 它只表示这段值得交给视觉模型判断。
- 它不表示这段一定在打球。
- 它不写入 `forehand / backhand / serve / highlight / problem_example` 等语义结论。

### `cv_evidence`
推荐字段：
- `window_duration: number`
- `effective_motion_ratio: number`
- `dead_time_ratio: number`
- `peak_motion_score: number`
- `avg_motion_score: number`
- `motion_span_x: number`
- `motion_path_length: number`
- `audio_interval_overlap: number`
- `quality_flags: string[]`
- `boundary_flags: string[]`

### `model_input_package`
每个候选必须落盘一份模型输入包。

必填字段：
- `candidate_id: string`
- `input_dir: string`
- `frames_dir: string`
- `frame_paths: string[]`
- `frame_count: number`
- `candidate_video_path: string`
- `prompt_path: string`
- `input_json_path: string`
- `schema_version: "model_judgement.v1"`

落盘目录：
- `selection_runs/<selection_run_id>/model_inputs/<candidate_id>/input.json`
- `selection_runs/<selection_run_id>/model_inputs/<candidate_id>/prompt.txt`
- `selection_runs/<selection_run_id>/model_inputs/<candidate_id>/frames/000.jpg`
- `selection_runs/<selection_run_id>/model_inputs/<candidate_id>/frames/001.jpg`
- `selection_runs/<selection_run_id>/model_inputs/<candidate_id>/candidate.mp4`
- `selection_runs/<selection_run_id>/model_inputs/<candidate_id>/model_response.json`
- `selection_runs/<selection_run_id>/model_inputs/<candidate_id>/judgement.json`

缓存规则：
- 如果 `judgement.json` 存在且 `input.json` 中的 `input_hash` 一致，可以复用模型结果。
- 如果 prompt、schema、候选窗口或帧内容变化，必须重新调用模型。

### `model_judgement`
`model_judgement` 是本地视觉模型对单个候选的结构化判断。

必填字段：
- `schema_version: "model_judgement.v1"`
- `candidate_id: string`
- `in_play: yes / no / uncertain`
- `non_play_type: none / picking_ball / resting / walking / waiting / camera_noise / uncertain`
- `rally_completeness: complete / partial_start_missing / partial_end_missing / multi_rally / uncertain`
- `action_tags: string[]`
- `context_tags: string[]`
- `value_tags: string[]`
- `reject_reasons: string[]`
- `selection_reason: string`
- `confidence: number`

字段约束：
- `action_tags[]` 只能包含 `forehand`、`backhand`、`serve`。
- `context_tags[]` 只能包含 `baseline`、`midcourt`、`running`、`stationary`。
- `value_tags[]` 只能包含 `highlight`、`good_example`、`problem_example`。
- `selection_reason` 不超过 `160` 个汉字或 `300` 个英文字符。
- 若 `in_play = no`，`value_tags` 必须为空数组。
- 若模型不确定，必须使用 `uncertain`，不能编造确定标签。

### `selected_clip`
必填字段：
- `selection_id: string`
- `candidate_id: string`
- `clip_id: string`
- `source_video_id: string`
- `source_clip_path: string`
- `candidate_window: time_window`
- `focus_window: time_window`
- `export_window: time_window`
- `cv_evidence: cv_evidence`
- `model_judgement: model_judgement`
- `semantic_tags: object`
- `coverage_roles: string[]`
- `selection_reasons: string[]`
- `selection_score: number`
- `confidence: number`
- `needs_review: boolean`

`semantic_tags` 是 06 兼容字段，由 `model_judgement` 派生：
- `in_play`
- `non_play_type`
- `rally_completeness`
- `action_tags`
- `context_tags`
- `value_tags`
- `model_confidence`

### `coverage_report`
必填字段：
- `required_roles: object`
- `soft_roles: object`
- `coverage_gap: string[]`
- `serve_presence_status: user-confirmed-present / user-confirmed-absent / model-likely-present / model-likely-absent / uncertain`
- `selected_summary: object`

## 模型 prompt
每个候选使用固定任务 prompt。

模板：

```text
你是网球训练视频片段筛选器。你只判断当前候选片段是否适合进入后续技术分析，不输出训练建议。

输入包括按时间顺序排列的关键帧，以及候选元数据和 CV 证据摘要。

请只基于这些关键帧判断：
1. 这段是否真正在打网球。
2. 是否只是休息、捡球、等待、走动或镜头噪声。
3. rally 是否基本完整。
4. 是否能看到明显正手、反手或发球。
5. 是否具备复盘价值：亮点、好例子或问题样本。

如果证据不足，必须输出 uncertain。不要因为动作不好就排除问题样本。不要输出最终技术诊断。

必须严格按 JSON schema 输出，不要输出 schema 之外的字段。
```

## 模型 JSON Schema
实现层应使用等价 JSON Schema 约束 `model_judgement`。

```json
{
  "type": "object",
  "properties": {
    "schema_version": {"const": "model_judgement.v1"},
    "candidate_id": {"type": "string"},
    "in_play": {"enum": ["yes", "no", "uncertain"]},
    "non_play_type": {"enum": ["none", "picking_ball", "resting", "walking", "waiting", "camera_noise", "uncertain"]},
    "rally_completeness": {"enum": ["complete", "partial_start_missing", "partial_end_missing", "multi_rally", "uncertain"]},
    "action_tags": {"type": "array", "items": {"enum": ["forehand", "backhand", "serve"]}},
    "context_tags": {"type": "array", "items": {"enum": ["baseline", "midcourt", "running", "stationary"]}},
    "value_tags": {"type": "array", "items": {"enum": ["highlight", "good_example", "problem_example"]}},
    "reject_reasons": {"type": "array", "items": {"type": "string"}},
    "selection_reason": {"type": "string"},
    "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0}
  },
  "required": [
    "schema_version",
    "candidate_id",
    "in_play",
    "non_play_type",
    "rally_completeness",
    "action_tags",
    "context_tags",
    "value_tags",
    "reject_reasons",
    "selection_reason",
    "confidence"
  ],
  "additionalProperties": false
}
```

## 执行流程
### 1. 导入 04 输出
读取 `manifest.json` 和 `point_clips/`，按源视频时间排序。

如果没有可用 `point_clips`，直接输出：
- `selection_status = no_candidates`
- `infeasible_reasons = ["empty-point-clips"]`

### 2. CV 高召回候选生成
对每个 `point_clip` 执行轻量扫描，生成 `0-3` 个候选窗口。

候选类型：
- `motion_dense`：运动和音频证据密集的窗口。
- `rally_wide`：覆盖更完整回合的宽窗口。
- `opening_probe`：靠近片头，服务发球或回合开局识别。
- `recovery_probe`：捕捉可能的问题样本，例如被动回位、失衡、追球。

CV 层必须避免过度自信：
- 不在这一层强行判定正手、反手、发球。
- 不因为“看起来像休息”就直接丢弃，除非视频几乎无有效画面。
- 不因为 dead time 偏高就直接丢弃长 rally 候选。

### 3. 候选池压缩
默认规模：
- `cv_candidate_pool = 18`
- 可接受范围：`12-24`
- `selected_clips = 6`
- `review_queue <= 6`

压缩规则：
- 同一 `point_clip` 默认最多保留 `2` 个候选。
- 时间高度重叠的候选保留 CV 证据更完整者。
- 保留不同时间段、不同运动强度、不同候选类型。
- 候选不足时宁可减少最终样本，也不制造低质量候选。

### 4. 模型输入构建
为每个 `cv_candidate` 构建 `model_input_package`。

关键帧抽取规则：
- 默认 `9` 帧。
- 至少包含候选窗口的 `0% / 50% / 100%` 附近。
- 剩余帧优先取运动峰值附近。
- 输出 JPEG，长边不超过 `768px`。

候选短视频：
- 从 `export_window_proposal` 导出。
- 命名为 `candidate.mp4`。
- 只用于人工复核和后续调试，不作为 v1.0.1 模型输入主路径。

### 5. 本地视觉模型判断
对每个候选调用 `local_vlm_runner`。

处理规则：
- 成功返回合法 JSON：写入 `judgement.json`。
- 返回非法 JSON：用同一输入重试一次。
- 重试仍失败：候选进入 `review_queue`，并记录 `reject_reasons = ["invalid-model-output"]`。
- 模型不可用：终止模型阶段，输出 `selection_status = model_unavailable`。
- fallback 模型可用但主模型不可用：继续执行，并输出 `selection_status = model_degraded`，除非最终结果仍不完整。

### 6. 候选过滤
硬过滤：
- `in_play = no` 且 `confidence >= 0.70`：排除。
- `non_play_type` 为 `picking_ball / resting / waiting / walking / camera_noise` 且 `confidence >= 0.70`：排除。

降权或 review：
- `in_play = uncertain`。
- `rally_completeness = partial_start_missing / partial_end_missing`。
- `rally_completeness = multi_rally`。
- `confidence < 0.70` 但候选覆盖稀缺角色。

保留规则：
- `problem_example` 不能因为动作差而被过滤。
- 候选只要有独特覆盖价值且模型不明确否定，可以进入 review。

### 7. Rerank 与覆盖选择
选择顺序固定为：
1. 过滤高置信非打球候选。
2. 根据 `serve_presence` 判断是否需要发球槽位。
3. 先填硬覆盖槽位：`forehand`、`backhand`、`serve-if-required`。
4. 再补软覆盖：`highlight`、`problem_example`、`good_example`、`baseline/midcourt`、`running/stationary`。
5. 最后按综合分填满到 `selected_size`。
6. 对最终结果做一次去重与覆盖回检。

综合分：

```text
selection_score =
  0.35 * model_value_score
  + 0.25 * in_play_score
  + 0.15 * completeness_score
  + 0.15 * coverage_bonus
  + 0.10 * diversity_bonus
  - risk_penalty
```

映射规则：
- `model_value_score = max(highlight, good_example, problem_example)`，有对应 `value_tags` 记为 `1.0`，否则 `0.4`。
- `in_play_score = 1.0 / 0.5 / 0.0` 对应 `yes / uncertain / no`。
- `completeness_score = 1.0` for `complete`，`0.55` for `multi_rally`，`0.35` for partial，`0.45` for `uncertain`。
- `coverage_bonus = 1.0` 若补齐缺失硬槽位，`0.6` 若补齐软槽位，`0.0` otherwise。
- `diversity_bonus = 1.0` 若与已选候选不同 `clip_id` 且不同主标签，`0.4` 若只满足其中之一，`0.0` otherwise。
- `risk_penalty = 0.25` 若存在高风险 CV flag，`0.15` 若模型置信度低于 `0.70`，可叠加。

最终规则：
- `in_play = no` 的候选不能进入 `selected_clips`。
- 高置信 `non_play_type != none` 的候选不能进入 `selected_clips`。
- 若可用候选不足，不强行补满，输出 `constrained_incomplete`。

### 8. Review queue
以下候选必须进入 `review_queue`：
- 覆盖硬约束但模型置信度不足。
- 模型认为 `uncertain` 但 CV 证据显示可能有价值。
- 回合边界不完整但候选具备独特技术价值。
- 模型输出不合法或重复失败。
- 最终集合仍缺少关键覆盖项。

`review_queue` 的目标不是替代 selection，而是把人工确认压缩到极少数高价值不确定项。

## 与 04 segmentation 的关系
05 v1.0.1 接受 04 当前现实：
- 04 输出仍然是 `point_clips`。
- 04 允许“略粘”。
- 04 不需要先提供完美 rally 边界。

05 不回写 04，也不要求 04 改成模型驱动切片。

如果 04 的 `point_clip` 过粘：
- 05 在内部生成多个 `cv_candidate`。
- 本地视觉模型判断 `multi_rally`。
- selector 只选最可分析、边界最清晰的候选。

## 与 06 analysis 的关系
05 输出给 06 的是 `selected_clips`。

每个 `selected_clip` 必须包含：
- `focus_window`：分析焦点，兼容 06 当前命名。
- `export_window`：实际导出给 06 观看的视频窗口。
- `model_judgement`：候选级语义判断。
- `cv_evidence`：候选生成证据。
- `coverage_roles`：该片段承担的覆盖角色。
- `needs_review`：是否需要人工确认。

06 应优先消费 `export_window` 对应导出视频；若需要在 prompt 中强调重点，则引用 `focus_window`。

## 与 07 persistence 的关系
07 保存 session note 时，应把每个入选片段的以下内容作为稳定证据保存：
- `selection_id`
- `candidate_id`
- `exported_clip_path`
- `focus_window`
- `export_window`
- `coverage_roles`
- `model_judgement` 摘要
- `needs_review`
- `traceability` 到 `selection-package.json`

不要把完整 `cv_candidate_pool` 或全部关键帧复制进 Obsidian。

## 降级路径
### 1. 模型不可用
输出：
- `selection_status = model_unavailable`
- `cv_candidate_pool`
- `model_input_packages`
- `review_queue`
- `selected_clips = []`

不输出伪自动的 `selected_clips`，除非用户显式允许 `cv_only_fallback`。

### 2. fallback 模型可用
如果 `qwen2.5vl:7b` 不可用但 `qwen2.5vl:3b` 可用：
- 继续运行。
- `selection_status` 初始记为 `model_degraded`。
- 若最终覆盖不足，最终状态改为 `constrained_incomplete`。

### 3. 模型输出不稳定
采用：
- 固定 schema。
- 单候选最多一次重试。
- 失败进入 `review_queue`。

不通过自由文本猜测结构化字段。

### 4. 发球是否存在不确定
若用户未指定 `serve_presence`，以模型对候选池的判断为准。

如果模型也不确定：
- 输出 `serve_presence_status = uncertain`。
- 不把缺发球视为失败。
- 保留最高价值发球疑似候选进入 `review_queue`。

## 实现模块
新版实现建议拆为四个模块，哪怕初期仍在一个脚本中，也应保持函数边界清晰：
- `cv_candidate_builder`：读取 04 输出，生成候选和 CV 证据。
- `model_input_builder`：导出候选短视频与关键帧包。
- `local_vlm_runner`：调用 Ollama 并校验 `model_judgement`。
- `coverage_selector`：融合模型判断、覆盖约束和去重逻辑，输出最终 package。

模块边界：
- CV 模块不写模型语义字段。
- 模型模块不重新扫描长视频。
- selector 不重新解释画面，只消费结构化判断。

## 测试与验收场景
实现 v1.0.1 时至少覆盖以下场景：
- `no_candidates`：空 `point_clips` 输出 `selection_status = no_candidates`。
- `model_unavailable`：Ollama 不可用时输出候选池和空 `selected_clips`。
- `invalid_model_output`：非法 JSON 重试一次，仍失败进入 `review_queue`。
- `non_play_filter`：高置信 `picking_ball / resting / walking` 不进入 `selected_clips`。
- `serve_absent`：`serve_presence = absent` 时不要求发球槽位。
- `candidate_shortage`：可用候选不足时不强行补满。
- `analysis_compat`：每个 `selected_clip` 必须包含 `focus_window`、`export_window`、`model_judgement` 和 `semantic_tags`。
- `traceability`：package 能回溯到 run dir、候选输入包、模型响应和导出片段。

## 当前明确不做
本版本不做：
- 云端模型主路径。
- `MLX/VLM` 第一版 adapter。
- 专项训练或微调。
- 网球球路 / 落点 / 旋转重建。
- 专业动作技术诊断。
- 跨 session 偏好学习。
- 用复杂规则继续模拟视觉语义理解。

## 参考资料
- Ollama Vision: https://docs.ollama.com/capabilities/vision
- Ollama Structured Outputs: https://docs.ollama.com/capabilities/structured-outputs
- Ollama qwen2.5vl: https://ollama.com/library/qwen2.5vl

## 当前结论
`v1.0.1` 的关键变化是把 selection 从“方向正确的架构草案”补齐为“可以直接编码的实现规格”。

工程实现时不应再自行决定：
- 第一版本地视觉模型 runner。
- 模型输入形态。
- JSON schema。
- rerank 权重。
- 下游兼容字段。
- 模型失败时的状态语义。

后续调优应优先围绕：
- 候选池召回率。
- 模型判断 schema 稳定性。
- rerank 结果的人工抽检命中率。
- review queue 是否足够小且足够有用。
