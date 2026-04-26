# 视频精选 `img_3076` 回合起点修复验证

## 文档定位
本文档记录视频精选子域在 `img_3076` 上针对“selected clip 仍然从回合中途开始”的第三轮修复。

它回答的问题是：
- 上一版为什么已经知道“边界可能不对”，却仍然没能稳定回到 rally 开头。
- 本轮修复后的实现，是否已经把导出边界从“围绕高光扩长”推进到“先落到完整回合，再导出”。

## 验证对象
当前验证覆盖两个版本：
- 历史版本：[视频精选方案历史（V3）](../solution/05-video-selection/history/v3.md)
- 当前版本：[视频精选架构（Current）](../solution/05-video-selection/current.md)

关联前序验证：
- [2026-04-25-video-selection-img3076-rally-completeness](./2026-04-25-video-selection-img3076-rally-completeness.md)
- [2026-04-26-video-selection-img3076-rally-start-boundary](./2026-04-26-video-selection-img3076-rally-start-boundary.md)

## 背景
上一轮之后，系统已经开始：
- 把 `rally-start-unresolved` 视为高风险信号
- 对明显退化成整段大粘片的候选做降权

但用户继续抽查后指出：
- 效果“好了一些”
- `03 / 04 / 05` 仍然从一个回合的中间开始
- 目标不是“尽量更像完整回合”，而是“必须尽量从完整回合片段开始”

## 本轮问题重述
上一版的核心问题不是：
- 不知道哪些候选有风险

而是：
- 即使知道有风险，导出窗口的生成方式仍然主要依赖“围绕高光往前后找 quiet gap”

这会导致一个典型偏差：
- 高光前面如果还有几拍较弱、但仍属于同一 rally 的内容
- 系统容易把它们视为“与高光无关的低活动区”
- 最终把导出起点压到 rally 中段

## 关键观察
### 1. `V3` 仍然把“高光定位逻辑”部分复用到了“回合起点定位”
这使得 `selected_clip_window` 的生成仍然受到高阈值运动证据的影响。

对边界来说，这层信号通常过强：
- 它适合回答“哪里最精彩”
- 不适合回答“回合究竟从哪一拍开始”

### 2. `V3` 的真实问题样本集中在几个局部高光贴边导出
在 `20260425-img3076-rally-v3` 中，用户点名问题主要落在：
- `point-004-focus-08`
- `point-005-focus-05`
- `point-015-focus-12`

它们的共同特征是：
- `focus_window` 定位得不差
- 但 `selected_clip_window` 起点仍然只比 `focus_window` 早一点点
- 导出逻辑本质上仍然是“高光附近裁长一点”

### 3. 修复方向必须从“quiet gap 检测”升级到“低阈值 rally interval 恢复”
本轮修复的关键不是继续调 `pre-roll`，也不是继续加惩罚项，而是新增一层更弱、更宽松的边界语义：
- 用低阈值分数和低阈值活动比率，先恢复 clip 内的局部 `rally interval`
- 再把 `focus_window` 归属到某个 `rally interval`
- 最后才对这个 `rally interval` 做 quiet-boundary 修正

## 本轮修正
基于上述观察，当前版本引入了三类修正。

### 1. 新增低阈值 `rally interval` 推断
当前版本不再只靠高阈值 `motion_active_intervals`。

而是：
- 基于 `score_at_times` 的局部时序
- 使用更低阈值的 `score` 与 `active_ratio`
- 构建专门用于边界恢复的 `rally_local intervals`

这层区间的职责只有一个：
- 尽量覆盖单个完整 rally，而不是只覆盖高光段

### 2. `selected_clip_window` 先绑定到 `rally interval`
当前版本的导出边界生成顺序改为：
1. 先定位 `focus_window`
2. 再找到与 `focus_window` 对应的低阈值 `rally interval`
3. 最后在该 `rally interval` 外围做 quiet-boundary 修正

这和上一版的区别是：
- 上一版是“围绕高光扩长”
- 当前版是“先找到完整回合，再导出”

### 3. 仍然保留高风险候选降权
如果即使经过 `rally interval` 恢复后：
- `selected_clip_window` 仍然退化成整段长 clip
- 或者明显无法回到 rally 起点

则它仍然会被：
- 标记为边界高风险
- 在 selection 中降低优先级

## 修正后的执行结果
本轮修正后重新执行了一次 selection：
- 运行记录：`20260426-img3076-rally-v8`
- package：`/Users/pataphaw/Projects/toward-nadal/.work/clips/img_3076/20260423-latest/selection_runs/20260426-img3076-rally-v8/selection-package.json`
- 导出目录：`/Users/pataphaw/Projects/toward-nadal/.work/clips/img_3076/20260423-latest/selected_clips/20260426-img3076-rally-v8`

本次运行的已知约束：
- 用户已明确说明本次训练不包含 `serve`
- 因此本次执行使用 `serve_presence = absent`

结果摘要：
- `selected_count = 6`
- `selection_status = ready`
- `coverage_gap = []`
- 问题样本 `point-004` 与 `point-015` 已不再进入最终精选结果
- `point-005` 的导出起点从贴近局部高光，回退到了该段第二个 rally 的更早起点附近

## 当前结论
这轮修复后的核心变化不是“继续扩长导出窗口”，而是：
- 把导出边界和高光定位彻底拆成两套阈值体系
- 让 `selected_clip_window` 先归属到一个更完整的 `rally interval`

这比单纯做风险降权更接近真实目标。

## 对方案的影响
这份验证对方案的影响是明确的：
- `V3-rally-start-aware-selection` 被归档到 `solution/history/v3.md`
- 当前版本升级为 `V4-rally-interval-export`
- 当前方案的“完整 rally 导出”不再定义为“高光窗口向外扩长”，而是“低阈值 rally interval + quiet-boundary 修正”

## 待继续确认
这轮修复已经把上一版最明显的中途开头样本排掉或前移了边界，但仍需要继续目检确认两件事：
- `20260426-img3076-rally-v8` 中的 6 个导出片段，是否已经基本满足“从完整回合开头开始”
- 是否还存在个别 `point clip` 本身就不是从完整 rally 开头开始，导致 05 已无法进一步恢复
