# 视频精选 `img_3076` 回合完整性反馈

## 文档定位
本文档记录视频精选子域在 `img_3076` 上的第一次真实用户反馈，以及由此触发的一轮实现修正。

它回答的问题是：
- `05 selection` 的首个可运行版本，真实效果哪里好，哪里不对。
- 这份反馈具体否定了哪一层逻辑。
- 当前方案应如何根据这份反馈收敛。

## 验证对象
当前验证覆盖两个版本：
- 历史版本：[视频精选方案历史（V1）](../solution/05-video-selection/history/v1.md)
- 当前版本：[视频精选架构（Current）](../solution/05-video-selection/current.md)

验证范围：
- 输入素材：`img_3076`
- 关注点：`selected_clip` 是否保持回合完整性，而不是只保留精彩击球局部

## 背景
在历史版本 `V1-highlight-window-export` 中，`05 selection` 已经能够：
- 选出包含精彩击球的代表样本
- 输出 `selection package`
- 实际导出选中的视频片段

对应运行结果：
- 运行记录：`20260425-img3076-check`
- package：`/Users/pataphaw/Projects/toward-nadal/.work/clips/img_3076/20260423-latest/selection_runs/20260425-img3076-check/selection-package.json`
- 导出目录：`/Users/pataphaw/Projects/toward-nadal/.work/clips/img_3076/20260423-latest/selected_clips/20260425-img3076-check`

## 用户反馈
用户对 `20260425-img3076-check` 的反馈可以归纳为两部分。

优点：
- 对精彩击球的把握较好，基本每个 `selected_clip` 都包含了几个精彩击球

缺点，且是严重问题：
- 大部分 `selected_clip` 的开头和结尾都截断了回合
- `selected_clip` 不应该直接以精彩击球开始或结束
- 精彩击球应被完整地放回其所属回合中

## 关键观察
### 1. 历史版本确实抓到了“精彩击球附近”
这部分反馈和自动输出是一致的。

从 `20260425-img3076-check` 可以看到，选中的大多数窗口都带有：
- `highlight`
- `good-example`
- 部分带有 `problem-example`

因此，这一版并不是“不会找亮点”，而是“只会找亮点附近”。

### 2. 截断的根因不在导出编码，而在时间语义
问题不在于导出阶段压缩了画面，而在于导出的时间窗口本身就被定义成了高光片段。

历史版本的关键缺陷有两个：
- 候选生成优先依赖粗粒度 `source_intervals`
- 实际导出直接使用 `focus_window`

这会导致：
- 在一个很长的 `point clip` 里，先找到最密集的精彩击球局部
- 再把这个局部直接导出成最终 `selected_clip`
- 于是开头和结尾很容易都落在回合内部

### 3. 本地运动序列已经足以提供更细的 rally 结构
对 `img_3076` 的 selected clips 复查后可以看到：
- 原始 `boundary_evidence.source_intervals` 往往很粗
- 但从本地 `motion_active_intervals` 中已经能拆出更细的连续段

这意味着问题不是“本地完全没有能力逼近单回合”，而是：
- 历史版本没有把这层更细的本地运动结构真正用于导出窗口定义

## 本次修正
基于上述反馈，当前版本做了三类调整。

### 1. 候选 seed 从粗区间切到本地运动区间
当本地 `motion_active_intervals` 可用时：
- 候选生成优先以它作为内部 rally seed
- 不再优先继承整段粗粒度 `source_intervals`

这样做的直接目的，是把“一个大粘片”拆回多个更像单回合的局部 cluster。

### 2. 将 `focus_window` 和最终导出窗口拆开
当前版本明确区分：
- `focus_window`
  - 用来表示“最值得分析的精彩击球局部”
- `selected_clip_window`
  - 用来表示“包含该精彩击球的完整 rally 导出窗口”

这使得：
- 亮点定位能力可以保留
- 但最终导出不再被迫截断回合

### 3. 导出逻辑从 `focus_window` 切换为 `selected_clip_window`
当前版本导出视频时，不再直接截取 `focus_window`，而是：
- 优先导出 `selected_clip_window`
- 只有在缺失时才回退到 `focus_window`

## 修正后的执行结果
修正后重新执行了一次 selection：
- 运行记录：`20260425-img3076-rally-v3`
- package：`/Users/pataphaw/Projects/toward-nadal/.work/clips/img_3076/20260423-latest/selection_runs/20260425-img3076-rally-v3/selection-package.json`
- 导出目录：`/Users/pataphaw/Projects/toward-nadal/.work/clips/img_3076/20260423-latest/selected_clips/20260425-img3076-rally-v3`

本次运行的已知约束：
- 用户已明确说明本次训练不包含 `serve`
- 因此本次执行使用 `serve_presence = absent`

结果摘要：
- `selected_count = 6`
- `selection_status = ready`
- `coverage_gap = []`
- 导出窗口长度约在 `10.5s - 35.6s` 之间
- 导出窗口全部来自 `selected_clip_window`

## 当前结论
这份反馈已经改变了 `05 selection` 的当前方案理解。

可以确认的结论有：
- 历史版本 `V1-highlight-window-export` 解决了“亮点定位”，但没有解决“回合完整性”
- 对视频精选而言，“完整 rally” 是比“高光局部”更高一级的输出约束
- 因此当前版本必须同时保留两层时间语义：
  - `focus_window`
  - `selected_clip_window`

## 对方案的影响
这份验证对方案的影响是明确的：
- 历史版本归档到 `solution/05-video-selection/history/v1.md`
- 当前方案不再把“直接导出高光窗口”视为可接受行为
- 当前方案应以“高光定位 + rally-complete export”作为生效版本

## 待继续确认
虽然当前实现已经从逻辑上修正了导出窗口语义，但仍需要用户继续目检：
- 这批 `selected_clips` 是否已经基本做到“完整回合”
- 当前 `motion_active_intervals` 聚出来的 cluster 是否还有误并、误拆

也就是说，这份验证已经完成了“方向确认”，但还没有完成“长期稳定性确认”。
