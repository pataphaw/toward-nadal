# 视频分析架构（Current）

## 文档定位
本文档定义视频分析子域当前生效方案。

当前版本不是一次性脚本说明，而是 `06-video-analysis` 的最小可用正式闭环。  
它的目标是在满足当前明确需求的前提下，先建立一条可稳定复用的分析链路；不提前为未来场景引入尚未被需求证明的复杂性。

相关文档：
- [视频精选架构（Current）](../05-video-selection/current.md)
- [结果保存架构（Current）](../07-result-persistence/current.md)
- [配置方案](../configuration.md)
- [总体架构](../../blueprint/overall-architecture.md)

## 当前生效版本
当前生效版本为 `v1.0.0-minimal-openrouter-gemini-keyframe`。

它的核心判断如下：
- 初版要建立正式闭环，而不是临时跑通一次分析。
- 初版先固定一条最短可用路径，不提前做多 provider 抽象。
- 初版直接消费 05 已导出的分析视频，不重复做 selection 发现与重组。
- 初版直接读取 Obsidian 记忆目录中的现有文档，不提前实现复杂检索层。

## 目标与边界
本子域负责：
- 读取一次 `selection-package.json` 对应的 `selected_clips`
- 从每个已导出的视频切片中抽取关键帧
- 结合当前记忆目录中的 Markdown 文档构造分析输入
- 调用外部模型完成网球技术分析
- 输出结构化分析结果与可读摘要

本子域不负责：
- 原始视频同步、切片与精选
- 自动发现最新 selection 结果
- 复杂记忆检索、向量索引或语义召回
- 训练计划执行
- 正式写回 Obsidian session note

## 当前主路径
初版固定采用：
- `05 selection` 导出的短视频切片
- 关键帧序列
- OpenRouter
- `Gemini 2.5 Flash`
- 结构化 JSON 输出

当前不实现：
- 原生视频直传分析
- 多模型 provider 切换
- 云端与本地多路径自动降级

说明：
- 未来仍保留“直接传视频分析”的升级方向。
- 但在当前版本中，这只是后续演进方向，不进入实现主线。

### 当前模型选择
- 主模型：`Gemini 2.5 Flash`
- 备选模型：`Gemini 2.5 Pro`

原因只保留三点：
- 你的场景是网球视频/图片分析，Gemini 系列对多模态理解更贴近后续“直接传视频”的主方向。
- `Gemini 2.5 Flash` 的效果与成本更平衡，适合先作为默认工作模型。
- `Gemini 2.5 Pro` 成本更高，但在复杂判断和疑难片段上更适合作为保守备选。

## 输入契约
### CLI 输入
初版 CLI 只支持两个参数：
- `--selection-package <path>`
- `--config <path>`

调用方必须显式提供目标 `selection-package.json` 路径。  
当前版本不负责从 `.work` 目录中自动发现“最新可分析 run”。

### 上游输入
分析层当前直接消费 05 的 `selection-package.json`。

只要满足以下条件，就进入分析：
- `selected_clips` 非空
- 每个待分析条目存在 `exported_clip_path`
- `exported_clip_path` 指向的视频文件存在

当前版本至少识别以下字段：
- `selection_id`
- `clip_id`
- `source_video_id`
- `exported_clip_path`
- `focus_window`
- `export_window`
- `coverage_roles`
- `model_judgement`
- `cv_evidence`

其中：
- `exported_clip_path` 是当前主观看对象。
- `export_window` 表示实际上游导出的观看区间。
- `focus_window` 表示片段内更值得关注的技术焦点。
- `model_judgement` 与 `cv_evidence` 只作为 selection 证据，不作为最终技术诊断。

## 记忆输入策略
当前版本不单独实现复杂记忆子系统。

记忆直接来自：
- `config.toml`
- `memory.obsidian_vault_dir`

分析前直接读取该目录下全部 `.md` 文档，并将其作为附加上下文输入模型。

当前策略固定为：
- 保留文档相对路径
- 保留文档标题或文件名
- 保留文档全文
- 按路径顺序拼接

若上下文超过输入预算，只做最小裁剪：
- 优先保留 `00_Profile/`
- 其余文档按路径顺序截断

当前不做：
- embedding
- rerank
- 主题过滤
- 冲突消解
- 独立 `context_pack` 子系统

如果后续验证表明记忆长度、噪声或组织方式开始稳定影响分析质量，再把这部分升级为单独方案。

## 分析链路
当前分析链路固定为：
1. 读取 `selection-package.json`
2. 提取 `selected_clips`
3. 打开每个 `exported_clip_path`
4. 从每个视频均匀抽取固定数量关键帧
5. 读取 Obsidian 记忆目录中的 Markdown 文档
6. 组装固定 prompt
7. 通过 OpenRouter 调用 `Gemini 2.5 Flash`，必要时回退到 `Gemini 2.5 Pro`
8. 校验输出结构
9. 写出结构化结果与可读摘要

当前链路的重点是先把“精选片段 -> 结构化技术分析”这条路径跑稳。  
凡是不直接影响这条主路径成立的复杂性，都不在初版中引入。

## Prompt 约束
当前 prompt 目标是固定任务边界，而不是追求高度灵活。

建议固定包含以下区块：
1. `角色与任务`
2. `分析规则`
3. `历史记忆`
4. `视频片段清单`
5. `输出合同`

其中分析规则至少要求模型：
- 只基于视频证据和给定上下文判断
- 区分 `observed`、`inferred`、`uncertain`
- 不把 selection 的中间判断直接当作最终技术结论

## 输出契约
当前版本输出两类结果：
- 机读结果：`analysis-result.json`
- 人读结果：`analysis-report.md`

`analysis-result.json` 至少包含：
- `session_summary`
- `goal_assessment`
- `state_assessment`
- `top_findings[]`
- `priority_actions[]`
- `keep_doing[]`
- `clip_notes[]`
- `open_questions[]`
- `next_session_focus`

这组字段直接覆盖当前明确需求：
- 当前技术、训练和核心目标，以及当天达成度
- 当天状态的整体判断
- 当天的主要问题与后续改进方案
- 当天发挥好的方面与后续保持方式

每条关键结论至少应带：
- `status`
- `confidence`
- `evidence`

`analysis-report.md` 的职责只是把结构化结果转成便于阅读的摘要。  
正式事实源仍应以 `analysis-result.json` 为准。

## 输出位置
当前版本把结果写入 `.work`，不直接写回 Obsidian。

推荐输出目录位于对应 selection run 下，例如：
- `selection_runs/<selection-run-id>/analysis_runs/<analysis-run-id>/`

当前版本最少写出：
- `analysis-result.json`
- `analysis-report.md`

当前不要求额外生成：
- `context-pack.json`
- `analysis-prompt.json`
- `traceability.json`

若后续排障或复用需要，再补充这些中间产物。

## 配置要求
当前版本除已有配置外，还需要最小分析配置。

建议新增：
- `[analysis]`
- `[analysis.openrouter]`

至少应支持：
- 分析模型名
- 备选模型名
- API key 的环境变量名
- 单次调用超时
- 每个片段抽取的关键帧数量

当前约束如下：
- `config.toml` 必须是合法 TOML
- `memory.obsidian_vault_dir` 必须存在
- 分析所需 API key 必须可读取

## 失败策略
当前版本只处理最关键的失败场景，并明确失败，不做复杂自动修复。

应直接失败的情况：
- `selected_clips` 为空
- `exported_clip_path` 不存在
- 无法读取记忆目录
- 配置缺失
- 模型返回的 JSON 不满足输出契约

当前不采用的降级方式：
- 自动回退到其他 provider
- 退化为自由文本散文输出
- 跳过结构校验直接落盘

## 风险与后续演进
### 当前主要风险
- 关键帧可能丢失连续动作细节
- 全量记忆文档可能引入噪声
- 输出 schema 过弱会影响后续复用

### 明确保留的后续方向
- 直接视频输入分析
- selection package 自动发现
- 记忆检索与裁剪优化
- 与 `07-result-persistence` 的正式衔接

这些方向都是真实演进方向，但当前版本不提前实现。  
只有当验证明确暴露出瓶颈时，再把对应部分升级为更复杂的独立方案。
