# 2026-04-29-video-selection-img3026-non-rally-false-positive

## 文档定位
记录 `05 selection v1.0.1` 在 `img_3026` 全量运行中的严重误选：最终入选片段中有两段并非网球回合。

本记录回答三个问题：
1. 错误是否成立（证据层面）。
2. 为什么会发生（机制层面）。
3. 该错误对当前方案可用性的影响是什么（决策层面）。

## 验证对象
- 方案版本：`v1.0.1-implementation-ready-local-vlm-rerank`
- 本地模型依赖（本次实跑）：
  - `provider = ollama`
  - `endpoint = http://localhost:11434/api/chat`
  - `model = qwen2.5vl:7b`
  - `fallback_model = qwen2.5vl:3b`
- 运行包：
  - `selection-package.json`：`/Users/pataphaw/Projects/toward-nadal/.work/clips/img_3026/20260422-074627/selection_runs/20260429-img3026-vlm-final/selection-package.json`
  - 导出目录：`/Users/pataphaw/Projects/toward-nadal/.work/clips/img_3026/20260422-074627/selected_clips/20260429-img3026-vlm-final`
- 用户反馈（原文）：
  - `3026 的 04 selection，根本不是网球回合`
  - `3026 的 06 selection，根本不是网球回合`

## 关键结论
用户反馈成立。

`selected_clips` 中以下两条是误选：
- `selection-04-point-015-candidate-07`
- `selection-06-point-002-candidate-08`

两条片段都应视为“非有效回合 / 非可分析回合”，不应进入最终 selection 结果。

## 证据
### 1. 结果对象证据
来自 `selection-package.json`：

- `selection-04-point-015-candidate-07`
  - `selection_score = 0.823`
  - `semantic_tags.in_play = yes`
  - `model_judgement.in_play = yes`
  - `model_judgement.action_tags = ["backhand","serve"]`
  - `model_judgement.selection_reason = "rally_complete"`

- `selection-06-point-002-candidate-08`
  - `selection_score = 0.733`
  - `semantic_tags.in_play = yes`
  - `model_judgement.in_play = yes`
  - `model_judgement.action_tags = ["backhand","forehand","serve"]`
  - `model_judgement.selection_reason` 描述为“active tennis match”

这两条都被系统判成 in-play 且语义积极，因此进入最终入选集合。

### 2. 画面证据
对导出片段抽样帧（`/tmp/selection-issue-3026/04-*.jpg`, `/tmp/selection-issue-3026/06-*.jpg`）观察：
- 主体行为以走动、站位、回位为主。
- 看不到稳定且连续的击球-来回球交换。
- 画面呈现“场上有人活动”，但不构成可分析回合。

结论：这是典型的“有人在场 + 有运动”被误判为“在打球回合”。

## 根因分析
### 根因 1：模型语义误判被直接信任
当前流程把 `model_judgement.in_play = yes` 作为强正信号，但缺少“回合真实性二次校验”。

在本次误选中，模型把“走动/准备/回位”误判为 `in_play=yes`，并且附带了错误 `action_tags`（甚至含 `serve`），系统没有机制拦截这类矛盾高分样本。

### 根因 2：候选窗口对“非回合活动”区分不足
这两条样本的 `cv_evidence.effective_motion_ratio` 均较高（约 `0.67-0.80`），CV 侧把“有人运动”当成了“回合候选”的强证据。

在网球视频里，走动、捡球、回位同样会产生显著运动与音频，单靠运动密度不能区分是否是 rally。

### 根因 3：rerank 打分对“假阳性动作标签”过敏感
当前评分把 `action_tags/value_tags` 带来的正向加分权重偏高，且没有“标签一致性惩罚”：
- 当 `in_play=yes` 但缺乏明确 rally 结构时，仍能拿到高分。
- `serve` 标签被错误触发后，会帮助样本填充硬覆盖槽位，从而被优先选中。

### 根因 4：`needs_review=true` 不阻断入选
两条误选都被标记为 `needs_review=true`，但当前策略允许“先入选，再标记 review”。

在严重误判场景下，这会把明显错误片段直接暴露到最终结果，而不是降级到 review-only。

## 影响评估
- 严重性：`high`
- 影响范围：`05 selection` 的最终结果可信度
- 直接后果：最终 `selected_clips` 混入非回合片段，影响后续 `06 analysis` 输入质量
- 是否阻塞继续使用：`部分阻塞`
  - 方案整体优于纯 CV（用户反馈已确认）
  - 但“非回合误选”属于高风险错误，必须进入下一轮修复

## 后续修复方向（记录，不在本次变更内实施）
1. 引入 `in_play_consistency_gate`：
   - 当 `in_play=yes` 但 `rally_completeness=uncertain/partial` 且存在静态/回位特征时，强制降权或转入 review-only。
2. 引入 `non_rally_pattern` 规则：
   - 基于关键帧序列和 CV 证据识别“走动/站位/捡球”模式，命中后禁止进入最终 selected。
3. 调整覆盖策略：
   - `serve` 覆盖槽位不再完全信任单次标签，需满足额外证据（动作连续性或多候选一致性）。
4. 调整 `needs_review` 策略：
   - 对高风险不确定样本采用“只入 review_queue，不入 selected_clips”的硬策略。

## 结论
本次反馈不是“审美偏差”，而是明确的错误入选。

`v1.0.1` 已验证可跑通、总体效果优于纯 CV，但在“非回合假阳性”上仍有结构性缺陷。该缺陷已被证据确认，必须作为下一轮优先修复项。
