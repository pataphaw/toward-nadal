# 运动识别架构

## 目标与边界
本问题域负责判断“你是否进入了一次网球训练或比赛窗口”，并输出一个可供后续视频检索使用的时间段与置信度。

本问题域不负责视频分析、不负责视频切片，也不负责最终训练复盘；它只提供“训练发生了什么时间”的入口信号。

目标偏好保持不变：
- 优先使用 `Apple Watch` / `iPhone` 的被动信号自动识别。
- 允许低打扰的轻确认，但不希望频繁人工介入。
- 如果完全自动识别不稳定，允许用户手动点一次 `Tennis` workout 作为 fallback。

## 输入与输出
### 输入
- `Apple Watch` 的健康与运动信号。
- `iPhone` 可获得的补充信号。
- 可选的手动 `Tennis` workout 标记。

### 输出
- `candidate_session_window`：候选训练窗口。
- `sport_label`：当前是否倾向于网球。
- `confidence`：置信度分档。
- `confirmation_needed`：是否需要轻确认。
- `source`：本次判断的主要来源，便于后续追踪。

## 核心决策
### 决策 1：不把“系统自动识别网球”当作真值
基于 Apple 公开能力，更稳妥的理解是：系统能帮助发现“你在运动”，但不能稳定地向第三方提供一个可直接当作真值的 `tennis detected` 事件。

### 决策 2：拆成两层判断
先做“训练窗口检测”，再做“网球倾向判断”。  
原因很直接：网球、羽毛球、壁球、篮球、HIIT 在心率与步频上会有重叠，单层硬判定风险过高。

### 决策 3：保留最小人工 fallback
如果你愿意手动点一次 `Workout -> Tennis`，这条路径仍然是第一阶段最稳的真值来源。

## 组件划分
### 1. 信号采集层
负责读取可用的被动信号，包括：
- `heartRate`
- `activeEnergyBurned`
- `appleExerciseTime`
- `appleMoveTime`
- `stepCount`
- `distanceWalkingRunning`
- `walkingHeartRateAverage`
- `heartRateVariabilitySDNN`
- `CMPedometer` cadence
- `CMMotionActivityManager` 运动状态

### 2. 训练窗口检测器
负责识别“这一段时间像一次训练”。
它输出的是窗口候选，不是运动类别结论。

### 3. 网球倾向判定器
负责在候选窗口上判断“像不像网球”。
它不追求一次性绝对正确，而是给出概率分层。

### 4. 轻确认触发器
只在置信度落入灰区时触发，避免频繁打断。

### 5. 真值回退入口
当自动识别不足以稳定工作时，允许用户直接点一次 `Tennis` workout。

## 处理流程
1. 采集被动运动信号。
2. 检测是否存在连续的训练窗口。
3. 在窗口内计算网球倾向。
4. 输出 `likely tennis`、`possible tennis` 或 `not enough evidence`。
5. 仅在 `possible tennis` 时请求轻确认。
6. 若用户主动标记 `Tennis` workout，则提升为高置信度真值。

## 关键数据与信号
### 训练窗口相关
- 心率是否持续抬升。
- 活动能量是否明显增加。
- 步数、步频、移动时间是否呈现间歇性爆发。
- 训练时长是否接近一次真实网球活动。

### 网球相关
- 运动强度是否表现为“爆发 - 停顿 - 再爆发”的节奏。
- 是否更像场地内移动，而非匀速持续运动。
- 若位置可用，是否与常见球场位置接近。

### 不足以单独定性的信号
- 仅靠心率阈值。
- 仅靠步频阈值。
- 仅靠能量消耗阈值。

## 状态与置信度
建议将结果分成三档：
- `likely tennis`：多个信号一致，且没有明显反证。
- `possible tennis`：有部分一致性，但仍存在歧义。
- `not enough evidence`：信号不足或互相冲突。

置信度的作用不是“伪装成绝对正确”，而是决定是否需要轻确认，以及是否可以直接进入后续视频检索。

## 降级路径
- 首选降级：`possible tennis` 时请求一次轻确认。
- 次级降级：用户手动点一次 `Tennis` workout。
- 最保守降级：只产出候选训练窗口，不强行下结论。

## 不推荐路径
- 把 `Workout reminders` 直接当作“已自动识别网球”。
- 只靠单一阈值做判定。
- 把主识别链路放到 `Mac` 端。

## 风险与观察
### 风险
- 容易与羽毛球、壁球、篮球、HIIT 混淆。
- 长时间热身、休息、捡球会稀释信号。
- 漏判会直接影响后续视频定位。

### 观察点
- 你的常见训练时长。
- 你的典型心率区间。
- 你是否经常手动点 `Tennis` workout。
- 误判主要来自哪类运动。

## 实施分层
### 第一阶段
- 先做“候选训练窗口”，不要追求直接确认为网球。
- 用规则和简单打分模型跑通闭环。
- 记录误判与漏判样本。

### 第二阶段
- 引入个人历史样本做个性化分类。
- 根据你常见的球场、训练时长和心率区间逐步收敛。

## 参考资料
- Apple Support, Change settings in Workout on Apple Watch: https://support.apple.com/guide/watch/change-settings-in-workout-apde0be691be/watchos
- Apple Support, Workout types on Apple Watch: https://support.apple.com/en-tm/105089
- Apple Developer, HealthKit: https://developer.apple.com/documentation/healthkit
- Apple Developer, Running workout sessions: https://developer.apple.com/documentation/healthkit/running-workout-sessions
- Apple Developer, CMPedometer: https://developer.apple.com/documentation/coremotion/cmpedometer
- Apple Developer, CMMotionActivityManager: https://developer.apple.com/documentation/coremotion/cmmotionactivitymanager
