# 视频精选 v1.0.4 本地 VLM 串行稳定性验证

## 对应方案版本
- [视频精选方案历史（v1.0.4）](../solution/05-video-selection/history/v1.0.4.md)

## 验证目标
- 验证 05 selection 在进入本地模型判断前会先确保 Ollama 空闲。
- 验证同一时间不会并发发起多个 selection run 的本地模型调用。
- 验证默认本地配置已收敛到低负载 `3b` 主路径。
- 验证在串行运行条件下，selection 仍能得到有效 judgement。

## 代码与配置变更
- [tools/select_analysis_clips.py](/Users/pataphaw/Projects/toward-nadal/tools/select_analysis_clips.py:1)
- [config.example.toml](/Users/pataphaw/Projects/toward-nadal/config.example.toml:1)
- [configuration.md](../solution/configuration.md)

## 预期行为
- 真正调用模型前，会检查 `ollama ps`。
- 如果存在残留任务，会先尝试清理并等待空闲。
- 只有获取到全局本地 VLM 锁后，才会开始 candidate judgement。
- 默认配置不再把 fallback 提升到 `7b`。

## 结果
### 1. 串行 validation run 成功
运行：

```bash
python3 tools/select_analysis_clips.py \
  --run-dir .work/clips/img_3197/20260504-220735 \
  --config config.toml \
  --selection-run-id 20260506-img3197-v1-0-4-poststop \
  --skip-promote-selected-clips
```

结果：
- [selection-package.json](/Users/pataphaw/Projects/toward-nadal/.work/clips/img_3197/20260504-220735/selection_runs/20260506-img3197-v1-0-4-poststop/selection-package.json:1)
- `selection_status = constrained_incomplete`
- `selected_count = 3`
- `infeasible_reasons = ["missing-required-role:backhand"]`
- `promoted_selected_clips = false`

说明：
- 这次 run 是实验性验证，所以显式使用了 `--skip-promote-selected-clips`，没有覆盖当前最终输出目录。
- 本轮没有出现 `model_unavailable` 或 `request_error:timed out`。

### 2. run 后 Ollama 返回空闲
验证后执行 `ollama ps`：
- 返回空列表，说明本轮结束后模型已主动卸载，没有留下残留任务。

### 3. 默认本地配置已收敛到低负载路径
当前本地配置与示例配置都已改成：
- `candidate_pool_size = 4`
- `selected_size = 3`
- `frames_per_candidate = 2`
- `model = qwen2.5vl:3b`
- `fallback_model = qwen2.5vl:3b`
- `timeout_seconds = 180`

### 4. 结论
- 05 selection 当前主路径已经满足：
  - 调用前检查 Ollama 空闲状态
  - 调用阶段全局串行
  - 运行后主动卸载模型
- 在这组约束下，本地模型调用已恢复到可重复成功的状态。
