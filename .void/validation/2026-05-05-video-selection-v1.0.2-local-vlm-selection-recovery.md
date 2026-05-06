# 视频精选 v1.0.2 本地 VLM 有效 selection 恢复验证

## 对应方案版本
- [视频精选方案历史（v1.0.2）](../solution/05-video-selection/history/v1.0.2.md)

## 验证目标
- 验证 `candidate_pool_size` 与 `frames_per_candidate` 不再被实现层静默抬高。
- 验证本地 VLM 在较小 payload 下可以返回合法 `model_judgement`。
- 验证 `selection` 不再依赖非法输出 fallback 伪造成功结果。
- 验证 `IMG_3197` 与 `IMG_3198` 都能从修复后的 `segment` 结果中产出非空 `selected_clips`。

## 代码变更
- [tools/select_analysis_clips.py](/Users/pataphaw/Projects/toward-nadal/tools/select_analysis_clips.py:1)
- [配置方案](../solution/configuration.md)
- [视频精选架构（Current）](../solution/05-video-selection/current.md)

## 输入基线
- `IMG_3197` segment run:
  [.work/clips/img_3197/20260504-220735](/Users/pataphaw/Projects/toward-nadal/.work/clips/img_3197/20260504-220735)
- `IMG_3198` segment run:
  [.work/clips/img_3198/20260504-221814](/Users/pataphaw/Projects/toward-nadal/.work/clips/img_3198/20260504-221814)

修复前已知事实：
- 两个 run 都已恢复 `confirmed` 边界，不再是 `empty-point-clips`。
- 旧版 `05 selection` 仍会超时，或在全部非法输出时继续从 fallback judgement 中产出伪成功 selection。

## 关键验证过程
### 1. 最小探针确认参数真实生效
运行：

```bash
python3 tools/select_analysis_clips.py \
  --run-dir .work/clips/img_3197/20260504-220735 \
  --config config.toml \
  --selection-run-id 20260505-img3197-minprobe-v3 \
  --candidate-pool-size 2 \
  --selected-size 1 \
  --frames-per-candidate 1 \
  --local-vlm-model qwen2.5vl:3b \
  --local-vlm-fallback-model qwen2.5vl:3b \
  --local-vlm-timeout-seconds 180 \
  --local-vlm-max-retries 0
```

结果：
- [selection-package.json](/Users/pataphaw/Projects/toward-nadal/.work/clips/img_3197/20260504-220735/selection_runs/20260505-img3197-minprobe-v3/selection-package.json:1)
- `cv_candidate_pool_count = 2`
- 至少 `1` 个候选返回了合法 judgement：
  [model_response.json](/Users/pataphaw/Projects/toward-nadal/.work/clips/img_3197/20260504-220735/selection_runs/20260505-img3197-minprobe-v3/model_inputs/point-021-candidate-02/model_response.json:1)
- 结果中出现真实语义标签：
  - `in_play = yes`
  - `action_tags = ["forehand"]`
  - `value_tags = ["good_example"]`

结论：
- 参数已真实影响运行时行为。
- 本地 VLM 已能在小 payload 下输出合法结构化结果。

### 2. `IMG_3197` 实用配置恢复 non-empty selection
运行：

```bash
python3 tools/select_analysis_clips.py \
  --run-dir .work/clips/img_3197/20260504-220735 \
  --config config.toml \
  --selection-run-id 20260505-img3197-vldone \
  --candidate-pool-size 4 \
  --selected-size 3 \
  --frames-per-candidate 2 \
  --local-vlm-model qwen2.5vl:3b \
  --local-vlm-fallback-model qwen2.5vl:3b \
  --local-vlm-timeout-seconds 180 \
  --local-vlm-max-retries 0
```

结果：
- [selection-package.json](/Users/pataphaw/Projects/toward-nadal/.work/clips/img_3197/20260504-220735/selection_runs/20260505-img3197-vldone/selection-package.json:1)
- `selection_status = constrained_incomplete`
- `selected_count = 3`
- `in_play_counts = {'yes': 3, 'uncertain': 1}`
- 非空精选导出位于：
  [.work/clips/img_3197/20260504-220735/selected_clips/20260505-img3197-vldone](/Users/pataphaw/Projects/toward-nadal/.work/clips/img_3197/20260504-220735/selected_clips/20260505-img3197-vldone)

代表性结果：
- `selection-01-point-021-candidate-02`
- `selection-02-point-025-candidate-03`
- `selection-03-point-028-candidate-04`

当前限制：
- 该 run 仍缺少 `backhand` 覆盖，因此 `selection_status` 为 `constrained_incomplete`。
- 仍有 `1` 个候选返回非法输出，被正确记为 invalid，而没有被拿去伪造 selection。

### 3. `IMG_3198` 实用配置恢复 non-empty selection
运行：

```bash
python3 tools/select_analysis_clips.py \
  --run-dir .work/clips/img_3198/20260504-221814 \
  --config config.toml \
  --selection-run-id 20260505-img3198-vldone \
  --candidate-pool-size 4 \
  --selected-size 3 \
  --frames-per-candidate 2 \
  --local-vlm-model qwen2.5vl:3b \
  --local-vlm-fallback-model qwen2.5vl:3b \
  --local-vlm-timeout-seconds 180 \
  --local-vlm-max-retries 0
```

结果：
- [selection-package.json](/Users/pataphaw/Projects/toward-nadal/.work/clips/img_3198/20260504-221814/selection_runs/20260505-img3198-vldone/selection-package.json:1)
- `selection_status = constrained_incomplete`
- `selected_count = 3`
- `in_play_counts = {'yes': 4}`
- `invalid output count = 0`
- 非空精选导出位于：
  [.work/clips/img_3198/20260504-221814/selected_clips/20260505-img3198-vldone](/Users/pataphaw/Projects/toward-nadal/.work/clips/img_3198/20260504-221814/selected_clips/20260505-img3198-vldone)

代表性结果：
- `selection-01-point-001-candidate-01`
- `selection-02-point-016-candidate-04`
- `selection-03-point-013-candidate-02`

当前限制：
- 该 run 同样缺少 `backhand` 覆盖，因此仍是 `constrained_incomplete`。

## 验证结论
- `05 selection` 的关键逻辑问题已修复：
  - 参数不再失效。
  - 非法模型输出不再伪装成成功 selection。
  - 两个新视频都已恢复出真实非空 `selected_clips`。
- 当前剩余问题已经从“流程坏掉”收敛成“本地 VLM 语义覆盖有限”：
  - 当前结果偏向 `forehand / good_example`
  - `backhand` 覆盖仍不足
- 这属于下一阶段的质量优化，不再是本轮的 blocking failure。
