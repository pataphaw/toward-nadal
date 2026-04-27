# 视频精选 v1.0.1 实现规格补强验证

## 文档定位
本文档记录 `05-video-selection` 从 `v1.0.0` 架构草案补强为可实现规格的原因与结论。

它回答的问题是：
- `v1.0.0` 是否足够直接用于代码实现。
- 哪些方案空白会导致实现者自行决策。
- `v1.0.1` 应补齐哪些实现级契约。

## 验证对象
本次验证对应：
- 归档版本：[视频精选方案历史（v1.0.0）](../solution/05-video-selection/history/v1.0.0.md)
- 当前方案：[视频精选架构（Current）](../solution/05-video-selection/current.md)

## 背景
`v1.0.0` 已经明确 selection 应从 CV-only 规则精选器升级为：
- `CV` 候选生成。
- 本地视觉模型 rerank。
- selection 负责约束选择和不确定性暴露。

但用户要求继续检查：
- 新方案是否足够详细。
- 是否可以直接用于代码 / 工程实现。
- blueprint 与其他 solution 是否存在失效或不匹配内容。

## 关键观察
### 1. 方向正确，但实现决策不足
`v1.0.0` 已经解决“路线是什么”，但没有完全解决“第一版怎么写代码”。

主要缺口包括：
- 本地视觉模型 runner 没有锁定。
- 输出 schema 没有字段类型与枚举。
- 模型输入包没有落盘契约。
- rerank 没有固定权重与阈值。
- prompt 与 JSON schema 没有写入方案。

### 2. 下游契约存在不匹配
`06-video-analysis` 仍要求消费 `focus_window` 与情境标签。

而 `v1.0.0` selection 输出改为：
- `candidate_window`
- `export_window`
- `model_judgement`

如果不补兼容策略，下一步实现会在 05 与 06 之间断裂。

### 3. 第一版 runner 应务实锁定为 Ollama
`Ollama` 官方支持：
- vision models 的图像输入。
- structured outputs。
- `qwen2.5vl` 本地视觉模型。

因此 `v1.0.1` 将第一版固定为：
- `provider = ollama`
- `model = qwen2.5vl:7b`
- 输入为关键帧序列，不直接传视频。

`MLX/VLM` 保留为后续 adapter，不进入第一版必需实现。

## 方案影响
本次结论触发 `05-video-selection` patch 版本升级：
- `v1.0.0-cv-candidates-local-vlm-rerank` 归档。
- 当前版本升级为 `v1.0.1-implementation-ready-local-vlm-rerank`。

同步需要调整：
- `blueprint` 中 selection 层与片段价值真值的描述。
- `06-video-analysis` 的输入契约。
- `07-result-persistence` 的片段证据保存契约。
- `configuration` 与 `config.example.toml` 的 selection 配置。

## 结论
`v1.0.0` 不足以直接交给工程实现。

`v1.0.1` 的目标是把方案补齐到以下标准：
- 工程师不需要自行选择 runner。
- 工程师不需要自行设计 JSON schema。
- 工程师不需要自行决定目录结构。
- 工程师不需要自行解释 rerank 规则。
- 下游 06 和 07 能直接消费 05 输出。
