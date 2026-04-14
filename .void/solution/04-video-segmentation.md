# 视频切片架构（Solution）

## 目标
把长时间网球视频切成适合后续精选和分析的片段，核心目标不是固定时长切块，而是尽量恢复“一分”级别的语义边界，并在必要时把多个紧凑分点聚合成更适合复盘的片段。

## 边界
### 做什么
- 识别并剔除无效内容。
- 找到 point 级边界。
- 将紧凑分点合并为可复盘片段。
- 保留每个片段的时间证据，供后续精选和分析使用。

### 不做什么
- 不在这一层做技术好坏判断。
- 不负责最终精选和分析结论。
- 不追求逐帧级完美边界，允许几秒级误差，只要 point 语义完整。

## 输入输出
### 输入
- 长视频文件，通常单段 5 分钟以上，可能超过 30 分钟。
- 可用的辅助信号：音频、画面运动、人体姿态、球轨迹、计分牌。

### 输出
- 一组切片片段。
- 每个片段带时间戳、来源视频和边界证据。
- 每个片段保留所属 point 的索引，便于后续回溯。

## 当前决策
采用“多阶段、弱监督、多模态”的切片架构：
- 先做活跃段与非活跃段粗筛。
- 再做 point 级边界检测。
- 再做边界精修。
- 最后按密度聚合。

这条主线保持不变，原因是你的真实视频机位、光照、遮挡和音频条件不稳定，直接依赖单一端到端模型风险过高。

## 分层 Pipeline
### L1 粗筛
目标是先把明显无效区间剔除。

典型无效段包括：
- 回合间停顿。
- 换边。
- 休息。
- 捡球。
- 长时间空白段。

可用信号：
- 音频静默窗。
- 画面整体运动强度。
- 明显场景变化。

推荐工具只作为起点，不作为最终判定：
- `FFmpeg silencedetect`
- `PySceneDetect`
- 光流或基础运动量统计

### L2 边界检测
将视频过程建模为少量状态：
- `serve`
- `rally`
- `dead_ball`
- `changeover`

这一层的重点是把短暂停顿和真正的换边、休息区分开，避免把一分切碎。

实现上可用带滞回的状态机，或 `HMM` 这类更平滑的状态建模方法。

### L3 边界精修
当画面条件允许时，再用更强信号微调起止点：
- 球轨迹。
- 人体姿态。
- 球员启动与收尾动作。

这一层只做局部修正，不改变前两层的主判断。

### L4 聚合
如果多个 point 之间间隔很短、语义连续，则允许聚合成一个更紧凑的复盘片段。

聚合后仍要保留：
- point 级索引。
- 原始边界。
- 聚合原因。

## 组件职责
### 音频粗筛
负责发现明显的静默窗和节律变化。

### 运动粗筛
负责识别明显在打球、明显不在打球、以及过渡状态。

### 状态层
负责把零散信号收敛成 `serve / rally / dead_ball / changeover` 这类可解释状态。

### 精修层
负责在局部范围内修正边界，不负责全局切分。

### 聚合层
负责把过碎但语义连续的 point 片段合并为更适合分析的单元。

## 状态模型
### 状态定义
- `serve`：发球准备到发球完成。
- `rally`：有效对打。
- `dead_ball`：死球、停顿、捡球等非对打区间。
- `changeover`：换边或较长休息。

### 状态转换原则
- 短暂停顿不应直接切换成新 point。
- 死球后的短尾巴应尽量保留在当前 point 内。
- 只有当状态变化稳定出现时，才触发边界。

### 设计目标
- 降低误切。
- 保留完整回合语义。
- 允许对边界作小范围平滑。

## 切片产物契约
每个切片至少要保留以下信息：
- `clip_id`
- `source_video_id`
- `start_time`
- `end_time`
- `point_index`
- `segment_type`
- `boundary_evidence`
- `aggregation_group_id`，如有聚合

建议再补充：
- `confidence`
- `signals_used`
- `notes`

契约的核心要求是可追踪，而不是字段尽量多。后续精选和分析都要依赖这些元数据回溯来源。

## 阶段化演进
### V1 基线
只做粗筛：
- `silencedetect`
- `PySceneDetect`
- 运动阈值

目标是先把明显无效内容剔除干净。

### V2 主方案
在 V1 基础上加入状态机或 `HMM`，显式区分：
- 活跃分点。
- 短暂停顿。
- 长暂停顿。
- 换边和休息。

这是当前推荐主方案。

### V3 增强方案
在稳定数据积累后，再引入：
- `GEBD`
- 时间动作分割
- 球轨迹模型

这适合第二阶段升级，不适合第一阶段上来就做。

## 降级路径
- 音频不可用时，退化为视觉运动和场景变化。
- 视觉条件差时，只做粗筛，不强求精确边界。
- 球轨迹不可用时，不影响主流程，只影响局部精修。
- 计分牌缺失时，不影响主流程，直接忽略。

降级策略的原则是：宁可保守切片，也不要输出看似精确但语义错误的边界。

## 风险与观察
### 主要风险
- 风噪和邻场噪声会削弱音频效果。
- 手持晃动、遮挡和机位变化会削弱视觉效果。
- 普通手机训练视频未必能稳定看到球轨迹或计分牌。
- 短暂停顿最容易被误切成两个 point。
- 发球前准备和死球后短尾巴容易丢失。

### 需要持续观察
- 不同机位下，粗筛和精修各自的收益。
- 聚合阈值是否会过度压缩有效回合。
- 哪类边界误差最常出现。
- 哪些信号在你的真实视频里最稳定。

## 实施建议
- 优先把“剔除无效段”做稳，再追求边界精度。
- 所有切片结果都保留时间戳证据，便于回看与调参。
- 允许边界误差落在几秒量级，只要 point 语义完整即可。

## 参考资料
- FFmpeg `silencedetect`: https://ffmpeg.org/ffmpeg-filters.html#silencedetect
- PySceneDetect API: https://www.scenedetect.com/api/
- OpenCV Optical Flow: https://docs.opencv.org/4.x/d4/dee/tutorial_optical_flow.html
- MediaPipe Pose Landmarker: https://ai.google.dev/edge/mediapipe/solutions/vision/pose_landmarker
- GEBD benchmark repo: https://github.com/StanLei52/GEBD
- TrackNet paper: https://doi.org/10.1109/AVSS.2019.8909871
- TrackNet repo: https://gitlab.nol.cs.nycu.edu.tw/open-source/TrackNet
- Automatic rally detection in tennis: https://www.tandfonline.com/doi/abs/10.1080/19346182.2013.819007
- Temporal Action Segmentation survey: https://pubmed.ncbi.nlm.nih.gov/37874699/
- Acoustic tennis timing detection: https://www.mdpi.com/2411-5142/10/1/47
