# 视频切片 V1 实现文档

## 文档定位
本文档记录视频切片子域当前已经落地的 `V1` 实现。

它回答的是：
- 当前脚本实际实现了什么。
- 输入、输出、目录产物和参数契约是什么。
- 当前验证到什么程度。
- 还有哪些缺口、阻塞和下一步。

它不重复方案比较与架构取舍。方案层内容见：
- [视频切片架构（Solution）](../solution/04-video-segmentation.md)

## 实现入口
当前 `V1` 的实现入口是：
- [tools/rederive_video_segmentation.py](/Users/pataphaw/Projects/toward-nadal/tools/rederive_video_segmentation.py:1)

`V1` 的落地方式是单脚本本地重推，不依赖额外 Python 科学计算库。

## V1 范围
`V1` 当前只覆盖以下能力：
- 对单个长视频做探测。
- 提取音频时间窗与低成本画面运动时间窗。
- 以“运动优先于音频”的规则构造候选区段。
- 导出 `point clip`。
- 生成 `manifest`、日志和边界证据。

`V1` 当前不覆盖：
- `break clip` 导出。
- 完整时间轴覆盖。
- 统一的 `segment clip` 模型。
- 无音频视频的可靠降级路径。
- 外部配置文件驱动的参数管理。

## 运行前提
`V1` 依赖以下运行条件：
- `macOS` 本地环境。
- `ffmpeg`
- `ffprobe`
- `python3`

当前脚本没有依赖 `numpy`、`opencv-python`、`librosa`、`mediapipe`、`torch`。

## 当前里程碑状态
### 已落地
- `ffprobe` 探测视频和流信息。
- 基于 `astats` 的音频时间窗提取。
- 基于低帧率灰度帧差的运动时间窗提取。
- 中心区域 `ROI` 加权的运动分数。
- 音频区段与运动区段融合。
- 候选区段分组、强制拆分与前后扩展。
- 重编码导出 `point clip`。
- `manifest.json`、日志和资源使用统计。

### 已验证
- “运动优先于音频”的修复已生效。
- 同一回合被音频误拆的典型案例已被修复。
- 当前版本能显著减少手工切片工作量，但仍不是完整时间轴方案。

### 待完成
- `break clip` 与全覆盖时间轴。
- 长片段二次细分。
- 参数外置与版本化配置。
- 无音频场景降级。
- 更系统的固定样本回归流程。

## 输入与运行方式
脚本参数如下：
- `--video`
- `--work-root`
- `--source-video-id`
- `--run-id`
- `--collect-resources`

输出目录结构为：
- `<work-root>/<source_video_id>/<run_id>/manifest.json`
- `<work-root>/<source_video_id>/<run_id>/logs/`
- `<work-root>/<source_video_id>/<run_id>/point_clips/`

当前一个已验证运行样例如下：
- 运行目录：[20260422-074627](/Users/pataphaw/Projects/toward-nadal/.work/clips/img_3026/20260422-074627)

## V1 实现流程
### 1. 素材探测
脚本先调用 `ffprobe` 获取容器和流信息，读取视频总时长，并把结果写入 `manifest.probe`。

### 2. 音频时间窗提取
脚本通过 `ffmpeg + astats + ametadata` 生成固定窗口的音频日志，再按 `RMS` 阈值构造音频活跃区段。

当前实现特点：
- 以固定窗口扫描，而不是逐事件检测。
- 音频主要提供辅助边界证据。

### 3. 运动时间窗提取
脚本用 `ffmpeg` 抽取低帧率灰度帧，计算相邻帧差，生成逐窗运动分数。

当前实现的关键点：
- 低采样率，成本可控。
- 对中心区域做额外加权。
- 最终使用 `motion_score = max(mean_abs_diff, roi_abs_diff * roi_boost)`。

### 4. 候选区段融合
当前 `V1` 不是一个显式命名状态机，而是一套“区段融合 + 分组 + 拆分”的启发式流程。

具体做法是：
- 先把运动簇作为主候选证据。
- 再把足够接近的音频区段吸附到已有候选上。
- 对彼此间隔较短的候选做进一步合组。
- 对持续时间过长且存在足够大间隙的组做递归拆分。

这一步体现了当前 `V1` 的真实实现边界：
- 它已经落实了“运动优先于音频”。
- 但它还不是方案层所设想的完整 `point/break` 语义状态机。

### 5. 片段扩展与重叠修正
候选组在导出前会增加前后缓冲，并在相邻片段发生重叠时按中点切开，避免导出后出现互相覆盖。

### 6. 导出 `point clip`
当前脚本逐段调用 `ffmpeg` 导出 `point clip`，并写入片段级元数据。

当前默认编码参数是：
- `video_encoder = libx264`
- `audio_encoder = aac`

这说明当前 `V1` 的实现重点是边界可用性，而不是硬件加速最优。

### 7. 产物落盘
脚本最终输出：
- `manifest.json`
- 音频和运动日志
- `point_clips/` 目录

`manifest` 同时记录输入探测结果、参数快照、计数信息、片段列表和本次运行资源统计。

## 当前参数组织
参数当前全部硬编码在脚本的 `DEFAULT_PARAMS` 中，尚未外置。

### 音频窗口相关
- `window_seconds = 0.4`
- `active_gap_seconds = 0.6`
- `min_active_span_seconds = 2.0`
- `rms_threshold_dbfs = -32.8`

### 运动提取相关
- `motion_fps = 2.0`
- `motion_scale = 64:36`
- `motion_activity_threshold = 4.5`
- `motion_cluster_gap_seconds = 2.0`
- `min_motion_span_seconds = 3.0`

### 中心区域加权相关
- `motion_roi_left_ratio = 0.2`
- `motion_roi_right_ratio = 0.8`
- `motion_roi_top_ratio = 0.1`
- `motion_roi_bottom_ratio = 0.95`
- `motion_roi_boost = 1.35`

### 合并与拆分相关
- `motion_audio_join_gap_seconds = 3.0`
- `fragment_gap_seconds = 12.0`
- `motion_fragment_gap_seconds = 15.0`
- `fragment_short_point_seconds = 14.0`
- `fragment_max_combined_duration = 90.0`
- `force_split_above_seconds = 45.0`
- `split_gap_seconds = 4.5`
- `motion_split_gap_seconds = 20.0`

### 导出相关
- `pre_roll_seconds = 1.2`
- `post_roll_seconds = 1.4`
- `min_point_duration = 5.0`
- `max_point_duration = 35.0`

这些参数当前的现实作用是：
- 优先减少误拆和误删。
- 容忍更长的 `point clip`。
- 用可解释阈值替代学习型边界判断。

## 当前输出契约
### `manifest.json`
当前 `manifest` 顶层包含以下关键字段：
- `input`
- `backup`
- `probe`
- `params`
- `counts`
- `point_clips`
- `compact_clips`
- `logs`
- `rederived`

其中当前状态是：
- `point_clips` 为主产物。
- `compact_clips` 固定为空数组，仅作为兼容占位。

### `point clip`
每个 `point clip` 当前至少包含：
- `clip_id`
- `source_video_id`
- `start_time`
- `end_time`
- `duration`
- `confidence`
- `boundary_evidence`
- `export_path`
- `point_index`
- `child_point_clip_ids`
- `aggregation_reason`

### `boundary_evidence`
当前 `boundary_evidence` 记录的是实现层证据，而不是高层语义标签。

至少包含：
- `duration_flag`
- `evidence_sources`
- `source_intervals`

这意味着当前 `V1` 已经具备基本可追踪性，但还没有上升到统一 `segment clip` 语义契约。

## 当前验证状态
截至 `2026-04-22`，与 `V1` 直接相关的验证记录包括：
- [2026-04-21-video-segmentation-replay-benchmark](../validation/2026-04-21-video-segmentation-replay-benchmark.md)
- [2026-04-22-video-segmentation-boundary-rederive](../validation/2026-04-22-video-segmentation-boundary-rederive.md)
- [2026-04-22-video-segmentation-motion-priority-fix](../validation/2026-04-22-video-segmentation-motion-priority-fix.md)

当前已确认事实：
- “运动优先于音频”的调整已经落地。
- 在 `img_3026` 的 `20260422-074627` 运行中，脚本导出了 `43` 个 `point clip`。
- 覆盖率约为 `74.05%`。
- 原先被错误拆开的 `28/29` 典型案例，已在修复后被合并保留。

## 当前阻塞与缺口
### 1. 仍不是完整时间轴方案
当前导出物仍然只覆盖被判定为 `point` 的区段，尚未补齐 `break` 区段，因此不能无缝拼回原视频。

### 2. 实现形态仍偏启发式
当前逻辑核心是区段融合与阈值拆分，不是显式的回合语义状态机。

这不是错误，但需要在文档上明确：
- 方案层描述的是目标架构。
- `V1` 真实实现是较保守的启发式切片器。

### 3. 长片段处理仍偏保守
当前规则对长片段更多是降低置信度，而不是稳定地做二次细分，因此仍可能导出明显偏长的片段。

### 4. 参数仍散落在代码中
当前参数没有独立配置文件，也没有按运行版本做显式配置管理，不利于长期回归和跨样本比较。

### 5. 无音频降级未落地
方案层要求为无音频或音频极差场景设计降级路径，但当前脚本还没有形成可靠实现。

## 下一步
建议按以下顺序推进：

1. 先把 `segment clip` 契约补齐，加入 `break` 并实现全时间轴覆盖。
2. 把参数从 `DEFAULT_PARAMS` 外置，形成可记录、可比较的运行配置。
3. 对超长 `point clip` 增加二次细分策略，而不是只降置信度。
4. 为无音频或极差音频场景补充明确降级路径。
5. 固化一组回归样本，把每次规则调整都落到 `validation` 证据中。

## 结论
当前 `V1` 已经不是“纯音频切片”，而是一个以低成本运动证据为主、音频为辅的启发式本地切片器。

它已经解决了最关键的第一阶段问题：
- 降低手工切片成本。
- 修复典型的音频误删回合问题。

但它仍然停留在“`point-first` 的局部可用实现”，还没有达到方案层定义的完整 `segment clip` 时间轴目标。
