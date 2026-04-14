# 结果保存架构

## 目标与边界
本子域负责把每次训练的分析结果稳定落到 `Obsidian`，并保证后续可以检索、回溯、复用。

边界如下：
- 输入是“分析结果 + 片段证据 + 必要上下文”
- 输出是“可追踪的 session note + 可复用的结构化字段”
- 不负责视频同步、切片、精选和分析本身
- 不负责训练计划执行，只负责保存和复用分析产物

核心判断不变：
- 把 `Obsidian` 当作纯文本数据库
- 每次训练保留一份 `session note` 作为唯一事实源
- 主写入方式采用直接写 vault 内的 `.md` 文件
- `CLI` 和 `URI` 只作为辅助入口

## 输入与输出
### 输入
结果保存层的标准输入来自分析层，至少包括：
- 本次训练的结构化分析结果
- `selected_clips` 与其稳定引用
- 用于复用的上下文摘要
- `traceability` 信息

### 输出
结果保存层的标准输出是一个可持续消费的 session note，至少满足：
- 人可以直接读懂这次训练的结论、问题和行动项
- 机器可以继续检索、引用和生成下一次 prompt

建议输出稳定承载以下内容：
- `frontmatter`
- `Session Capsule`
- `Clips`
- `Findings`
- `Actions`
- `Traceability`
- `Open Questions`
- `Prompt Capsule`

## Session Note 作为事实源
session note 是这次训练的唯一事实源，其他派生内容都应回指它。

其职责如下：
- 记录本次训练的最终结论
- 记录片段引用与证据路径
- 记录可执行的下一步动作
- 记录可供后续 prompt 复用的最小上下文

其边界如下：
- 不存放大量原始素材
- 不承载临时中间态
- 不替代历史检索库

## Frontmatter 与正文职责
### Frontmatter
`frontmatter` 只放稳定、可检索、低噪声的结构化字段。

建议保留的字段类型：
- 身份字段，如 `type`、`schema_version`、`session_id`
- 时间字段，如 `date`、`start_time`、`end_time`
- 状态字段，如 `status`、`detection_mode`、`detection_confidence`
- 关联字段，如 `source_videos`、`selected_clips`、`related_sessions`
- 检索字段，如 `tags`、`next_focus`

### 正文
正文承载解释性内容和可读性更强的分析结果。

正文更适合放：
- session 结论
- 片段说明
- 关键问题
- 行动项
- 追溯关系
- 给后续分析使用的 `Prompt Capsule`

职责划分原则很简单：
- 稳定索引用 `frontmatter`
- 解释和复盘用正文
- 长文本不要塞进 properties

## 存储布局
建议按日期分层组织训练笔记：
- `Tennis/Training/YYYY/YYYY-MM-DD/`

同级可选放置：
- `assets/`
- `clips/`

布局目标不是美观，而是让 session、片段和附件有稳定位置，便于同步和引用。

文件层建议保持一篇训练一份主文档，避免把一次 session 拆成多个主事实源。若某些高价值片段需要反复单独引用，再考虑拆成子 note，并在主文档中汇总链接。

## 写入链路
### 主写入
主链路是直接写 vault 内的 `.md` 文件。

这样做的原因是：
- vault 本质上就是本地文件夹
- 外部写入后 Obsidian 会自动刷新
- 这条链路最稳，也最可移植

### 辅助写入
`Obsidian CLI` 和 `Obsidian URI` 只适合做补写、打开、轻量追加和属性操作。

它们的定位是：
- 帮助触发编辑器内动作
- 方便做小范围自动化
- 不承担唯一写入契约

### 模板层
模板只负责骨架，不负责数据契约。

可用的模板层包括：
- Core Templates
- 社区模板插件

但最终落盘结构仍应以 `Markdown + YAML + wikilink` 为准。

## 检索复用
结果保存层的第二个目标，是让后续分析可以直接复用历史结果。

建议的复用方式：
- 用 properties 承载稳定索引字段
- 用正文承载解释性结论
- 用 `wikilink` 连接 session、片段和历史笔记
- 用 `Prompt Capsule` 保留最少但够用的上下文

复用时优先取：
- 当前水平
- 近期问题
- 近期已验证有效的修正
- 下次训练重点

不建议把全文复制到下一次 prompt。更稳的方式是让后续流程引用 `session note` 的稳定结构，而不是复刻整篇内容。

## 降级路径
主路径不可用时，优先降级写入方式，而不是放弃结构。

可用降级路径：
- 直接文件写入失败时，先用 `CLI` 或 `URI` 做补写
- 临时无法补全结构时，先落最小可用 session note，再异步补齐字段
- 若片段或证据太多，先保留主结论和关键引用，再拆分子 note

不建议的降级方式：
- 直接退化成自由文本流水账
- 直接丢弃 `frontmatter`
- 直接把原始大文件塞进 vault 当主存储

## 风险与观察
### 主要风险
- `frontmatter` 过度膨胀，会失去索引价值
- 原始长视频直接放入 vault，会拖慢同步、备份和检索
- 过度依赖 `URI`，会把写入链路绑到应用状态和编码细节上
- 过度依赖社区插件，会把存储契约绑到插件行为上

### 观察点
- 哪些字段最常被后续检索命中
- 哪些正文内容最常被复用到下一次 prompt
- 哪些 note 最常被拆成子 note
- 哪些写入方式最容易失败或失真

## 参考资料
- Obsidian Help, How Obsidian stores data: https://help.obsidian.md/data-storage
- Obsidian Help, Properties: https://help.obsidian.md/properties
- Obsidian Help, Internal links: https://help.obsidian.md/Linking%20notes%20and%20files/Internal%20links
- Obsidian Help, Attachments: https://help.obsidian.md/attachments
- Obsidian Help, Templates: https://obsidian.md/help/Plugins/Templates
- Obsidian Help, Obsidian URI: https://obsidian.md/help/uri
- Obsidian Help, Obsidian CLI: https://help.obsidian.md/cli
- Obsidian Help, File formats: https://help.obsidian.md/file-formats
- Obsidian Help, Bases: https://help.obsidian.md/bases
