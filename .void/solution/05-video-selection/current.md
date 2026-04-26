# 视频精选架构（Current）

## 文档定位
本文档定义视频精选子域当前生效的首版方案。

它回答的是：
- 05 selection 真正要为谁服务。
- 在当前这台 `Mac` 上，首版怎样务实落地。
- 04 segmentation 的 `point clip` 如何被重新组织成更适合 06 analysis 的分析样本。
- 哪些能力当前要做，哪些能力明确暂缓。

相关文档：
- [视频切片架构（Current）](../04-video-segmentation/current.md)
- [视频精选方案历史（V1）](./history/v1.md)
- [视频精选方案历史（V2）](./history/v2.md)
- [视频精选方案历史（V3）](./history/v3.md)
- [视频精选方案历史（V4）](./history/v4.md)
- [视频分析架构（Current）](../06-video-analysis/current.md)
- [总体架构](../../blueprint/overall-architecture.md)
- [回合起点边界修复验证](../../validation/2026-04-26-video-selection-img3076-rally-start-repair.md)
- [跨视频通用性检查](../../validation/2026-04-26-video-selection-img3026-generalization-check.md)

## 当前生效版本
当前生效版本为 `V4-rally-interval-export`。

它不是“自动挑最好看的视频”，而是“自动组织一组最值得分析的代表样本”。

当前版本的现实目标是：
- 基于 04 输出的 `point clip`，在本地先筛出可分析素材。
- 用轻量规则和可解释信号，尽量补足 `正手 / 反手 / 发球`、场景多样性和精彩回合。
- 当自动判定置信度不足时，把不确定性显式暴露出来，而不是伪装成已经理解了动作语义。
- 保持“精彩击球定位”和“完整回合导出”这两层时间语义同时存在。
- 当导出边界仍然无法回到回合开头时，优先放弃该候选，而不是硬保留一个大粘片。
- 对最终导出边界，优先恢复低阈值 `rally interval`，而不是仅围绕高光窗口向外扩。

## 用户真实诉求
本子域服务的真实目标不是“做视频摘要”，而是为后续技术分析准备一小组高价值样本。

最终希望送给大模型的，不是随机回合，也不是单纯最长片段，而是：
- 能覆盖本次训练中关键动作面的片段。
- 能同时看到做对了什么、做错了什么的片段。
- 能反映不同击球情境，而不是全是同一种底线相持。
- 能包含值得重点复盘的精彩回合。

这决定了精选层的核心对象不是“整段 `point clip` 本身”，而是：
- `analysis candidate`：一个可送去分析的样本单元。

`analysis candidate` 可以有两种形态：
- 直接等于一个 `point clip`。
- 引用一个 `point clip`，并同时保留：
  - `focus_window`
  - `selected_clip_window`

这样设计的原因是：
- 04 当前允许“略粘”，部分 `point clip` 会包含多个回合或较长空档。
- 05 的职责不是重写切片器，但可以在不修改 04 边界的前提下，为分析层定位更值得看的内部时间窗，并把精彩击球放回所属完整回合中。

## 目标与边界
本子域负责：
- 从 04 的候选片段中挑出少量高价值样本。
- 为每个样本补充“为什么选它”的结构化理由。
- 明确本次分析样本的覆盖情况、缺口和低置信度项。

本子域不负责：
- 回合边界重算。
- 完整技术诊断。
- 依赖云端或重训练模型的精细动作识别。
- 代替 06 输出最终的技术结论。

## 硬约束
以下约束高于局部评分，是当前方案层的硬边界。

### 1. 精选目标是“可分析价值”，不是“视频观感最好”
不能因为片段里打得差、失误多或动作变形，就把它过滤掉。

### 2. 最终集合必须满足动作覆盖
最终入选集合加总后必须覆盖：
- `forehand`
- `backhand`
- `serve`，前提是本次原始视频里确实存在发球

如果自动流程无法高置信度确认这些覆盖项，系统不能静默跳过，必须显式输出：
- `coverage_gap`
- `needs_review`

如果由于候选规模不足或质量不可用，客观上无法同时满足全部硬约束，也不能伪装为“已满足”。
必须显式输出：
- `selection_status = constrained_incomplete`
- `infeasible_reasons`
- `review_queue`

### 3. 最终集合应尽量覆盖不同情境
至少应优先争取覆盖：
- `baseline`
- `midcourt`
- `stationary`
- `running`
- `left`
- `center`
- `right`
- `good-example`
- `problem-example`

这些是软约束，不要求每次都齐全，但必须被显式度量。

### 4. 精彩回合必须进入竞争序列
长回合、高击球密度、连续高质量击球的片段，不能在质量过滤时被误杀。

### 5. 对长片段要惩罚“无效内容比率”，但不因为时长本身而否决
片段长不是问题。
问题是：
- 一个片段里混了多个独立回合。
- 回合之间有较长无效内容。

因此当前不采用“超过多少秒就降级”的简单规则，而采用：
- `有效击球窗口占比`
- `回合连续性`
- `空档比率`
- `候选 focus window 密度`

## 执行约束
当前首版必须符合已知环境现实：
- `macOS Apple Silicon`
- 本地可用 `python3`、`ffmpeg`、`ffprobe`
- 本机可通过 `ollama` 运行小模型
- 可以接受轻量 CPU 推理
- 不能把 `CUDA`、云端服务、训练流程作为主路径前提

因此首版推荐的实现形态是：
- `ffmpeg/ffprobe`：探测、抽帧、抽音频特征
- `Python + OpenCV + NumPy`：规则特征和局部跟踪
- `MediaPipe Pose` 或等价 CPU 级姿态能力：只作为轻量增强，不作为重模型前提
- `ollama + 本地小模型`：只作为可选语义复核层，不作为首版唯一依赖

如果姿态能力不可用，系统仍应可运行，只是必须进入更保守的降级路径。
如果本地小模型不可用，系统同样仍应可运行，只是失去一层低置信度样本的语义复核能力。

## 选择对象与输入输出契约
### 输入
05 selection 的标准输入来自 04 的一次切片运行：
- `manifest.json`
- `point_clips/`

每个候选 `point clip` 至少继承以下字段：
- `clip_id`
- `source_video_id`
- `start_time`
- `end_time`
- `duration`
- `confidence`
- `boundary_evidence`
- `export_path`

可选补充输入：
- 用户稳定画像，例如 `handedness`
- 对 `serve` 是否存在的外部先验，例如 `serve_presence = auto/present/absent`
- 本次任务约束，例如“本轮更关注反手”

`handedness` 不应写死在 05 内部。
如果外部已知，应作为显式输入传入；如果未知，05 只能做低置信度推断，不能伪装成确定事实。

### 输出
05 输出的不是单纯片段列表，而是一份可直接被 06 消费的 `selection package`。

推荐顶层字段：
- `selection_version`
- `source_segmentation_run`
- `candidate_pool`
- `selected_clips`
- `coverage_report`
- `review_queue`
- `selection_status`
- `infeasible_reasons`
- `selection_notes`

其中 `selected_clips[]` 至少包含：
- `selection_id`
- `clip_id`
- `source_video_id`
- `source_clip_path`
- `clip_start_time`
- `clip_end_time`
- `focus_window`
- `selected_clip_window`
- `selection_reasons`
- `coverage_roles`
- `semantic_tags`
- `quality_flags`
- `selection_score`
- `confidence`
- `needs_review`

`focus_window` 是首版的重要契约，格式建议为：
- `source_clip_offset_start`
- `source_clip_offset_end`
- `absolute_start_time`
- `absolute_end_time`
- `absolute_timebase = source_video_timeline`

`selected_clip_window` 是当前方案中的重要契约，用来表示最终导出视频应覆盖的完整 rally。

设计约束是：
- `focus_window` 用来表示“最值得分析的精彩击球局部”
- `selected_clip_window` 用来表示“包含该精彩击球的完整回合窗口”

当前版本进一步强化一条硬约束：
- `selected_clip_window` 必须尽量从完整 rally 的开头开始
- 如果起点或终点无法可靠定位，应把该候选视为高风险并降低优先级

如果一个 `point clip` 足够纯净，二者可以重合。
如果一个 `point clip` 内部混有多个回合或较长空档，则：
- `focus_window` 应只指向最值得分析的一段
- `selected_clip_window` 应覆盖该段所属的完整 rally

## 关键判断
### 1. 05 的基本单位应从 `point clip` 升级为 `analysis candidate`
因为 04 当前允许“略粘”，05 不应被迫把整段长片直接送给 06。

因此首版推荐两级对象：
- `clip candidate`：来自 04 的原始 `point clip`
- `analysis candidate`：在 `clip candidate` 内进一步定位的高价值分析窗口

这能在不回写 04 的前提下，解决两个现实问题：
- 长片段混入多个回合
- 片段内部存在较长无效内容

### 2. 语义覆盖依赖“粗识别 + 显式约束”，不依赖单一总分
只按一个综合分排序，几乎一定会出现：
- 全是底线相持
- 全是看起来最稳定的动作
- 没有问题样本
- 发球或反手被遗漏

因此首版采用：
- `先标注`
- `再做受约束选择`

而不是：
- `先总分排序`
- `再看运气有没有覆盖`

### 3. “动作类型识别”首版只做粗粒度、可解释的近似判断
当前不承诺：
- 精确识别每一次挥拍类型
- 逐帧识别击球点
- 自动理解复杂旋转和技战术意图

当前只追求支撑精选所需的粗粒度标签：
- 是否像发球片段
- 是否包含明显正手
- 是否包含明显反手
- 更偏底线还是中场
- 更偏原地还是跑动
- 站位更偏左、中、右
- 更像亮点样本还是问题样本

## 信号来源
首版只依赖当前 `Mac` 上可执行的本地信号。

### 1. 04 segmentation 已有元数据
直接复用：
- `duration`
- `confidence`
- `boundary_evidence`
- `child_point_clip_ids`
- `aggregation_reason`

这些信号可以帮助判断：
- 边界是否可疑
- 是否属于被合并过的长片段
- 是否需要优先做内部 `focus window` 定位

### 2. 本地质量与可用性信号
通过 `ffprobe` 和抽帧得到：
- 分辨率
- 实际码率
- 帧率
- 亮度分布
- 模糊度近似值
- 是否存在大面积黑屏或严重抖动

这层只判断“是否可分析”，不判断“打得好不好”。

### 3. 本地时序信号
通过低成本音视频处理得到：
- 音频瞬态峰值
- 画面运动峰值
- 球员主体位移
- 运动连续区间
- 候选击球窗口密度

这些信号用于：
- 估计一个片段里是否存在多个独立回合
- 找到更值得看的 `focus_window`
- 估计回合是否足够丰富

### 4. 轻量姿态与空间信号
若本地可用 `MediaPipe Pose` 或等价 CPU 级姿态能力，则进一步提取：
- 双肩、双髋、手腕、脚踝的大致位置
- 击球前后的躯干朝向变化
- 挥拍侧相对身体中心的位置
- 击球前位移和击球后恢复的粗指标

这一层只做“提升置信度”，不是首版唯一依赖。

### 5. 本地小模型语义复核
若本机可通过 `ollama` 运行小模型，则可增加一层低成本语义复核，但定位必须克制。

推荐输入形态：
- 单个 `focus_window` 的关键帧序列
- 片段的低成本规则特征摘要
- 可选的站位、运动强度、姿态粗特征

推荐用途：
- 对 `serve / forehand / backhand` 的低置信度候选做二次复核
- 对 `highlight / good-example / problem-example` 做辅助排序
- 生成更自然的 `selection_reasons` 草稿

不推荐让本地小模型直接负责：
- 决定硬约束是否已经满足
- 替代规则层做主筛选
- 输出最终技术诊断

因此在当前方案中，`ollama` 的定位是：
- `rule-only` 主路径之上的可插拔增强层
- 只服务于 `candidate_pool` 或 `review_queue` 的补充判断

## 首版执行流程
### 1. 候选导入
读取 04 的 `manifest.json` 和 `point_clips/`，形成按时间排序的 `clip candidate` 列表。

### 2. 可分析性过滤
先过滤明显不可用的片段，例如：
- 文件损坏
- 严重黑屏
- 画面几乎不可辨认
- 几乎没有任何有效运动或击球迹象

这一步不能因为“打得差”而过滤。

### 3. 内部高价值窗口定位
对每个候选片段做局部扫描，找出 `1-3` 个 `focus_window` 候选。

窗口定位优先依据：
- 音频峰值序列
- 运动峰值序列
- 球员主体位移的连续性
- 长片段中的空档断点

当前实现上，`focus_window` 不只保留一种形态，而是优先生成三类候选：
- `dense-cluster`：片段内部最连续、最适合直接分析的高密度窗口
- `opening-probe`：贴近片头的开局窗口，用于补抓可能存在的发球或发球后第一拍结构
- `wide-motion`：横向位移更明显的窗口，用于补抓跑动中击球和问题样本

当前版本的重要调整是：
- 当本地 `motion_active_intervals` 可用时，内部候选优先围绕它们生成
- 不再默认继承粗粒度 `source_intervals` 作为导出窗口
- 导出视频优先使用 `selected_clip_window`，而不是直接使用 `focus_window`
- 当粗粒度 `source_intervals` 几乎覆盖整段长 clip 时，不再让它污染局部 quiet 检测
- `selected_clip_window` 不再只靠“从高光向前后找 quiet gap”生成，而是先绑定到低阈值 `rally interval`
- 只有在 `rally interval` 落定之后，才再做 quiet-boundary 修正
- 对 `highlight / problem-example / filler` 候选，当前版本会额外通过一层 `in-play gate`
- 明显更像“跨场走动 / 捡球 / 休息段高运动”的候选，会被标记为 `transit-motion-risk` 并尽量排除出最终精选
- 当 `selected_clip_window` 退化成整段长 clip，或仍然无法回到 rally 起点时，应把它视为边界未定位成功的高风险候选

输出结果应包括：
- `effective_play_ratio`
- `dead_time_ratio`
- `focus_window_count`
- `best_focus_window`

如果一个长 `point clip` 内明显包含多个独立回合，05 不需要改写 04 边界，但应至少：
- 只把最有价值的内部窗口送入本轮精选竞争
- 给该片段打上 `multi-rally-risk`
- 保证最终导出的视频窗口尽量覆盖单个完整 rally，而不是只覆盖高光局部
- 如果无法做到上述目标，应优先淘汰该候选，而不是保留一个“看起来完整、实则整段很粘”的输出

### 4. 粗粒度语义打标
对每个候选窗口而不是整段片段，估计以下标签：

#### 动作类型
- `serve_prob`
- `forehand_prob`
- `backhand_prob`

推荐判断逻辑：
- `serve_prob`：优先看片段前部是否出现发球前静止准备、抛球样上举、首次击球接近片头、站位接近底线中央
- `forehand / backhand`：结合 `handedness`、挥拍侧相对躯干中心的位置、击球前后身体转动方向做粗分类

当前首版在没有姿态模型时，允许退化为更保守的 `OpenCV` 近似信号：
- 片段前部的主体横向稳定度
- 前段是否更接近底线中央
- 前段静止后是否出现一次明显爆发
- 主体重心更偏身体左侧还是右侧

#### 场景类型
- `baseline`
- `midcourt`
- `left / center / right`
- `stationary / running`

推荐判断逻辑：
- 以球员脚部或身体中心在画面中的归一化位置近似站位
- 以击球前若干帧位移幅度近似跑动程度

当前实现里，`stationary / running` 不再只看总位移，而是同时结合：
- 横向跨度
- 首尾位移
- 单位时间横向速度

#### 价值类型
- `highlight`
- `good-example`
- `problem-example`

推荐判断逻辑：
- `highlight`：长回合、高击球密度、较高节奏连续性、较少长空档
- `good-example`：动作完整、节奏稳定、回合内部连续性好
- `problem-example`：明显被动、失衡、仓促、回合很快在一次压力击球后终止

这里必须明确：
- `good-example` 和 `problem-example` 只是精选层的粗标签，不是最终技术结论

### 5. 候选池构建
先形成一个比最终结果更宽的 `candidate_pool`，建议 `10-16` 个样本。

入池逻辑应同时考虑：
- 质量可用
- 具备明确覆盖价值
- 具备明显精彩价值
- 具备明显问题暴露价值
- 与已入池候选不完全重复

当前实现上，`candidate_pool` 不再是简单的总分截断，而是会显式保留一部分：
- `opening-probe`
- `wide-motion`
- `stationary`
- `serve-like` 候选

### 6. 受约束选择
从 `candidate_pool` 中选择最终送分析的 `selected_clips`，建议 `6-8` 个。

若本次可用候选不足，实际选择数量应为：
- `min(目标规模, 可用候选数)`

选择顺序建议如下：
1. 先锁定硬约束槽位：`forehand`、`backhand`、`serve-if-exists`
2. 再补软约束：`baseline / midcourt`、`stationary / running`、`left / center / right`
3. 再加入至少一个 `highlight`
4. 再加入至少一个 `problem-example`
5. 最后用相似度惩罚去掉过于重复的样本
6. 去重后必须做一次硬约束回检；若回检失败，优先回填满足硬约束的次优候选

相似度当前不必依赖大型视频嵌入，首版可用以下低成本特征近似：
- 站位分布
- 运动强度分布
- 时长与击球密度
- 片段时间邻近性
- 同一长片内部是否来自相邻窗口

### 7. 生成 review queue
对于以下情况，必须进入 `review_queue`：
- 自动流程无法确认 `forehand / backhand / serve` 覆盖
- 某个覆盖项只有低置信度候选
- 精彩样本和问题样本明显不足
- 在候选规模充足时，候选主要来自少数两个片段，重复度过高

`review_queue` 不是失败，而是首版的安全阀。
它的目标是把人工确认范围压缩到极少数片段，而不是把整次精选退回全人工。

如果本地 `ollama` 小模型可用，则可在进入人工确认前增加一步：
- 先对 `review_queue` 做本地语义复核
- 仅在复核后仍然低置信度时，再保留人工确认

## 约束选择逻辑
首版不采用单一总分，而采用“显式约束 + 局部评分”的混合选择。

### 硬约束槽位
- `must_have_forehand = 1`
- `must_have_backhand = 1`
- `must_have_serve = 1`，当前提满足以下任一条件：
  - 全局 `serve_exists_prob` 超过阈值
  - 全局 `serve_exists_prob` 不确定，但存在 `serve_prob` 较高的候选

若全局 `serve_exists_prob` 明确不足以支持“存在发球”，则输出：
- `serve_presence_likely_absent`

若全局 `serve_exists_prob` 无法确认，则输出：
- `serve_presence_uncertain`
- `review_queue` 中至少保留 `1` 个最高 `serve_prob` 候选

### 软覆盖目标
- `prefer_baseline = 1`
- `prefer_midcourt = 1`
- `prefer_running = 1`
- `prefer_stationary = 1`
- `prefer_left_center_right = diversified`
- `prefer_good_example = 1`
- `prefer_problem_example = 1`
- `prefer_highlight = 1`

### 主要惩罚项
- `dead_time_ratio` 高
- `multi-rally-risk` 高
- `semantic_confidence` 低
- 与已选样本高度重复
- 明显只是准备动作或捡球，没有足够击球信息

### 关键原则
一个长片段如果：
- 覆盖价值很高
- 但内部有较长空档

它不应直接被淘汰，而应优先尝试缩到更小的 `focus_window` 后再参与竞争。

## 与 04 segmentation 的关系
05 必须接受 04 当前现实：
- 04 的主产物仍是 `point clip`
- 某些片段会“略粘”
- 04 当前不承诺完整 `break` 时间轴

因此 05 的策略不是要求 04 先变完美，而是：
- 把 04 的 `point clip` 视为候选容器
- 在容器内部进一步定位分析焦点
- 把 04 的边界风险显式传递给下游

05 不应回写或隐式篡改 04 的切片结果。
如果发现问题，只能：
- 在当前 `selection package` 中标注
- 或把结论沉淀到 `validation`

## 与 06 analysis 的关系
05 输出给 06 的不是“随便几段视频”，而是带上下文的样本集合。

06 至少应收到：
- `selected_clips`
- `selection_reasons`
- `coverage_roles`
- `semantic_tags`
- `focus_window`
- `needs_review`

这样 06 可以：
- 优先看 `focus_window` 而不是整段长片
- 理解为什么某个片段被选中
- 区分“亮点样本”和“问题样本”
- 在模型输出中继承 05 的不确定性标记

## 降级路径
### 1. 没有姿态能力
退化为：
- 质量过滤
- 时序窗口定位
- 基于站位和运动的粗覆盖选择

此时若无法确认 `forehand / backhand / serve`，必须把候选送入 `review_queue`，不能伪装成已满足硬约束。

### 2. 没有本地小模型
退化为：
- 完全依赖规则特征、时序特征与可选姿态特征
- 保留更大的 `review_queue`

这不影响首版可运行性，只会降低部分语义标签的复核能力。

### 3. 切片结果过粘
退化为：
- 尽量只输出内部 `focus_window`
- 降低整段 `clip` 的直接入选权重

### 4. 视频质量不稳定
退化为：
- 优先保留仍能看清动作主干的片段
- 缩小最终集规模
- 保留 `quality_flags`

### 5. 发球是否存在无法确认
退化为：
- 输出 `serve_presence_uncertain`
- 保留最高 `serve_prob` 的候选进入 `review_queue`

## 当前明确暂缓的能力
以下能力当前不应承诺为首版已具备：
- 精确到每一次击球的自动识别
- 精确的球轨迹和落点重建
- 基于大模型或云端服务的精选主路径
- 训练型视频嵌入和大规模聚类
- 跨多次 session 的偏好学习
- 直接根据 05 输出最终技术诊断结论

## 当前推荐的首版结果形态
首版建议输出两层结果：

### `candidate_pool`
更宽的候选池，供调试和少量人工确认使用。

建议规模：
- `10-16`

### `selected_clips`
最终送入 06 的代表样本集。

建议规模：
- `6-8`

如果本次训练内容很单一，可收缩到：
- `4-6`

如果本次素材特别杂，但覆盖要求更高，可放宽到：
- `8-10`

## 当前结论
05 selection 的首版，不应试图在本地一步到位理解完整网球语义。

更务实的路径是：
- 接受 04 当前“可用但略粘”的现实。
- 把精选对象从整段 `point clip` 提升为带 `focus_window` 的 `analysis candidate`。
- 用本地轻量信号先解决“代表性、覆盖性、精彩度、问题暴露”四个核心问题。
- 对 `正手 / 反手 / 发球` 这类硬约束，采用“自动粗识别 + 显式约束 + 小范围 review queue”。
- 若本机 `ollama` 可用，则把本地小模型放在 `review_queue` 和低置信度候选复核层，而不是放到主筛选路径上。

这样可以在当前这台 `Mac` 上先把链路跑通，并且让 06 analysis 收到一组更像“教练会挑出来的样本”，而不是一组随机长片。
