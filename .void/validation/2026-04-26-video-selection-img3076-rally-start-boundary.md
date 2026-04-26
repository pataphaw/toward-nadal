# 视频精选 `img_3076` 回合起点边界反馈

## 文档定位
本文档记录视频精选子域在 `img_3076` 上收到的第二轮真实反馈，以及由此触发的边界修正。

它回答的问题是：
- 为什么 `selected_clip` 虽然比历史版本更长，却仍然不是从完整回合开头开始。
- 当前方案应如何把“完整 rally”从一个模糊目标，收束为明确的边界约束。

## 验证对象
当前验证覆盖两个版本：
- 历史版本：[视频精选方案历史（V2）](../solution/05-video-selection/history/v2.md)
- 当前版本：[视频精选架构（Current）](../solution/05-video-selection/current.md)

关联上一轮反馈：
- [2026-04-25-video-selection-img3076-rally-completeness](./2026-04-25-video-selection-img3076-rally-completeness.md)

## 背景
在 `V2-rally-complete-export` 阶段，系统已经能够：
- 把 `focus_window` 和 `selected_clip_window` 分开
- 让导出片段明显比纯高光窗口更长

但用户继续抽查后指出：
- 效果“好了一些”
- `03 / 04 / 05` 仍然是从一个回合的中间开始
- 目标不是“稍微扩长”，而是“必须尽量从完整回合片段开始”

## 用户反馈
本轮反馈的核心只有一条，但约束非常强：
- `selected_clip` 一定要从一个完整回合片段开始

这意味着：
- 精彩击球仍然要保留
- 但不能因为保留精彩击球，就牺牲回合起点的完整性

## 关键观察
### 1. `V2` 的问题不在“导出窗口太短”，而在“导出窗口的起点语义仍然不对”
`V2` 的导出片段已经变长。
问题是：
- 它们仍然围绕高光片段向外扩
- 但扩出来的起点并不等于回合开头

因此，问题从一开始就不是“多加几秒 pre-roll”能解决的。

### 2. 高阈值 motion cluster 适合定位亮点，不适合直接充当 rally 起点
历史版本在候选生成中主要依赖更强的运动证据去定位高价值窗口。

这层信号对“哪里更精彩”是有效的，但对“回合究竟从哪里开始”并不可靠。

直接后果是：
- 高光片段常常定位得准
- 但起点仍然偏晚

### 3. 当边界无法可靠定位时，系统应优先放弃该候选，而不是硬保留
本轮反馈推动出的最重要方案变化，不是新的识别技巧，而是新的选择原则：
- 如果某个候选的 `selected_clip_window` 仍然退化成整段长 `point clip`
- 或者仍然无法明确回到单回合开头
- 那它应被视为高风险候选，并在 selection 中被明显降权

这比“继续强行导出一个看似更完整、实则更粘的长片”更符合 05 的目标。

## 本次修正
基于上述反馈，当前版本引入了三类修正。

### 1. `focus_window` 与 `selected_clip_window` 的职责再次分离
当前版本明确要求：
- `focus_window` 只服务于语义判断和代表性评分
- `selected_clip_window` 只服务于最终导出边界

这样可以避免：
- 一旦导出窗口扩长，语义标签也被拖钝

### 2. 去除粗粒度 `source_intervals` 对局部 quiet 检测的污染
在长 `point clip` 上，`source_intervals` 往往几乎覆盖整段。

如果继续拿它给局部时序加 boost，会导致：
- 真正的 quiet gap 被抬平
- `selected_clip_window` 更容易一路扩成整段 clip

当前版本因此改为：
- 对局部时序打分优先使用本地 motion evidence
- 不再默认接受粗粒度 `source_intervals` 的整段加权

### 3. 对“边界未定位成功”的候选显式降权
当前版本新增了一条选择原则：
- 如果 `selected_clip_window` 退化成整段长 `point clip`
- 或者明显无法定位起点/终点
- 就给它打上高风险标记并降低入选优先级

这不是单纯的坏样本过滤，而是：
- 把“无法保证完整回合”的样本，从主候选池中尽量排出去

## 修正后的执行结果
本轮修正后重新执行了一次 selection：
- 运行记录：`20260426-img3076-rally-v7`
- package：`/Users/pataphaw/Projects/toward-nadal/.work/clips/img_3076/20260423-latest/selection_runs/20260426-img3076-rally-v7/selection-package.json`
- 导出目录：`/Users/pataphaw/Projects/toward-nadal/.work/clips/img_3076/20260423-latest/selected_clips/20260426-img3076-rally-v7`

本次运行的已知约束：
- 用户已明确说明本次训练不包含 `serve`
- 因此本次执行使用 `serve_presence = absent`

结果摘要：
- `selected_count = 6`
- `selection_status = ready`
- `coverage_gap = []`
- 导出窗口大多收缩到 `9.6s - 41.0s`
- 未再优先保留那些只能退化成整段大粘片的候选

## 当前结论
这轮反馈让当前方案多了一条非常重要的现实约束：
- 对 `05 selection` 来说，“完整 rally” 不只是比 `focus_window` 更长
- 而是必须尽量回到回合开头
- 如果做不到，就应优先换候选，而不是保留一个边界不清的长片

## 对方案的影响
这份验证对方案的影响是明确的：
- `V2-rally-complete-export` 被归档到 `solution/history/v2.md`
- 当前版本不再把“扩长但仍从中途开始”的导出结果视为可接受
- 当前版本应以“高光定位 + 起点边界约束 + 高风险候选降权”作为生效版本

## 待继续确认
当前实现已经明显朝正确方向推进，但仍需要继续目检确认两件事：
- 当前 `v7` 这批片段是否已经基本做到从完整回合开头开始
- 是否还存在个别“虽然没有整段退化，但起点仍偏晚”的边界问题
