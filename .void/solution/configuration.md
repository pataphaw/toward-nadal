# 配置方案（Solution）

## 问题
当前系统需要一份最小可用的本地配置，用来告诉后续流程：
- 长期记忆应写入哪个 `Obsidian` 目录。
- 原始视频从哪里读取。
- 拆分后的小视频放到哪里。
- selection 阶段使用哪个本地视觉模型运行时。

这些信息都与运行机器强相关，不适合直接写死在代码里。

## 当前决策
采用仓库根目录的 `TOML` 配置文件作为第一阶段方案。

提交内容包含：
- `config.example.toml`：配置模板，作为字段契约与示例。
- `.gitignore` 中忽略 `config.toml`：避免提交个人机器上的绝对路径。

## 选择理由
### 为什么是 `TOML`
- 字段少，层级浅，用 `TOML` 足够表达。
- 可读性强，适合人工维护。
- 支持注释，便于保留字段语义。
- 后续若引入代码读取，常见语言都有稳定解析库。

### 为什么不直接提交真实 `config.toml`
- 这三个路径都高度依赖个人机器目录结构。
- 真实路径通常包含隐私信息或个人目录约定。
- 当前仓库尚未进入多人协作复杂阶段，但仍应先避免把“用户本地环境”误当成“项目默认配置”。

## 字段约定
`[memory].obsidian_vault_dir`
- 表示记忆、报告等内容最终沉淀到的 `Obsidian` 目录。
- 现阶段只支持 `Obsidian`，因此不额外引入存储类型枚举。

`[video].raw_dir`
- 表示原始长视频的读取目录。

`[video].clips_dir`
- 表示长视频拆分后的小视频及相关派生文件的工作目录。

`[selection].candidate_pool_size`
- 表示 05 selection 进入本地视觉模型判断前保留的 CV 候选数量。
- 默认值为 `4`。

`[selection].selected_size`
- 表示最终希望输出的代表片段数量。
- 这就是运行结果里 `selected_count` 的配置来源。
- 默认值为 `3`。

`[selection].frames_per_candidate`
- 表示每个候选传给本地视觉模型的关键帧数量。
- 默认值为 `2`。

`[selection.local_vlm].provider`
- 表示本地视觉模型运行时。
- v1.0.1 固定支持 `ollama`。

`[selection.local_vlm].endpoint`
- 表示 Ollama HTTP API 地址。
- 默认值为 `http://localhost:11434/api/chat`。

`[selection.local_vlm].model`
- 表示主视觉模型。
- v1.0.2 默认值为 `qwen2.5vl:3b`。

`[selection.local_vlm].fallback_model`
- 表示主模型不可用时的降级模型。
- 当前默认值与主模型保持一致，即 `qwen2.5vl:3b`，避免默认路径再额外加载更重的第二个模型。

`[selection.local_vlm].timeout_seconds`
- 表示单次模型请求超时时间。
- 当前建议值为 `180`。

`[selection.local_vlm].max_retries`
- 表示模型输出非法时的重试次数。
- 默认值为 `1`。

`[selection.local_vlm].temperature`
- 表示模型采样温度。
- v1.0.1 固定建议为 `0`，用于提高结构化输出稳定性。

## 约束
- 配置值应使用绝对路径。
- `clips_dir` 应视为可重复生成的工作目录，而不是长期知识库。
- selection 的本地视觉模型配置是运行依赖，不应写死在代码中。
- 05 selection 当前主路径要求串行使用本地模型，不应并行发起多个 selection run 争抢同一个 Ollama 实例。
- 05 selection 在实际调用前应先检查 `ollama ps`，必要时清理残留模型任务，确保本轮调用从空闲状态开始。
- 若本地模型不可用，05 selection 应输出 `model_unavailable`，不应静默退回 CV-only 自动精选。
- 若模型只返回非法结构化结果，05 selection 也应输出 `model_unavailable`，不应继续用 fallback judgement 伪造成功 selection。
- 若未来出现多环境、云端对象存储或多个输入目录，再考虑扩展配置层级，而不是现在提前抽象。

`[analysis].frames_per_clip`
- 表示 06 analysis 从每个已导出视频切片中抽取的关键帧数量。
- 当前最小正式版本默认值为 `6`。

`[analysis].max_memory_chars`
- 表示 06 analysis 读取 Obsidian 记忆文档后，允许拼接进 prompt 的最大字符数。
- 当前最小正式版本默认值为 `32000`。

`[analysis.openrouter].model`
- 表示 06 analysis 当前主用的 OpenRouter 模型。
- 当前默认值为 `google/gemini-2.5-flash`。

`[analysis.openrouter].fallback_model`
- 表示 06 analysis 当前的备选模型。
- 当前默认值为 `google/gemini-2.5-pro`。

`[analysis.openrouter].api_key_env_var`
- 表示存放 OpenRouter API key 的环境变量名。
- 当前默认值为 `OPENROUTER_API_KEY`。

`[analysis.openrouter].api_base`
- 表示 OpenRouter Chat Completions API 地址。
- 当前默认值为 `https://openrouter.ai/api/v1/chat/completions`。

`[analysis.openrouter].timeout_seconds`
- 表示一次完整分析调用的超时时间。
- 当前默认值为 `180`。

`[analysis.openrouter].image_detail`
- 表示关键帧传给 OpenAI 时的 detail 策略。
- 当前默认值为 `low`，用于控制输入成本。
