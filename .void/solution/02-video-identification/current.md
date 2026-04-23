# 视频识别架构（Solution）

## 目标与边界
在系统判断你进行了网球训练后，从 `iPhone` 拍摄的视频里自动定位出对应的一个或多个网球视频。

这不是全相册语义搜索问题，而是一个“先高召回、再高置信复核”的视频归属问题。输入已经有训练时间锚点，因此核心是缩小候选集，再确认哪些视频属于这次训练。

## 架构决策
采用两阶段检索：
- 第一阶段：基于 `PhotoKit` 元数据召回候选视频。
- 第二阶段：基于抽帧、音频和可选 OCR 做内容复核。

一次训练可能对应多个视频，允许多个视频共同归属于同一个 `session`。

## 输入与输出
### 输入
- 运动识别给出的训练时间窗口。
- `PhotoKit` 可访问的视频资产元数据。
- 候选视频的内容数据：抽帧、少量音频窗口、可选 OCR。

### 输出
- 候选视频列表。
- 每个视频的复核结果与置信度。
- session 级聚类结果。
- 可供后续分析链路使用的稳定引用信息。

## 分层职责
### 召回层
召回层只负责把候选范围缩小，不负责最终判定。

主要依据：
- `creationDate`
- `duration`
- `location`
- `mediaType`
- `mediaSubtypes`
- `sourceType`
- `pixelWidth`
- `pixelHeight`

基础过滤建议：
- 只取视频。
- 优先保留 `5 min` 以上的长视频。
- 排除明显无关类型，如 `timelapse`、`screen recording`。
- 时间上允许前后保留缓冲。

### 复核层
复核层负责判断“这是不是网球场景”和“是否属于这次训练”。

对每个候选视频：
- 抽取 `3-7` 帧，覆盖开头、中间、结尾。
- 读取少量音频窗口。
- 必要时增加 OCR。

复核信号优先级：
1. 是否是网球场景。
2. 是否出现网球动作或回合。
3. 是否存在网球相关音频线索。
4. 是否有比分牌、场地名、赛事横幅等文本线索。

## Session 聚类
当一次训练被拆成多个视频时，需要把它们聚成同一个 `session`。

聚类条件：
- 时间连续或接近。
- 位置一致或近似。
- 内容复核结果一致。

聚类的目标不是把每个视频完全合并，而是建立“同一次训练”的稳定归属关系，方便后续分析和检索。

## 置信度
建议同时输出两种分数：
- `asset_confidence`
- `session_confidence`

初始权重可以设为：
- 时间邻近：`0.35`
- 视觉命中：`0.25`
- 位置接近：`0.20`
- 时长合理性：`0.10`
- 音频命中：`0.10`

最终分档：
- `high`
- `medium`
- `low`

这里的目标是稳定表达“可自动确认”“可疑但可用”“证据不足”，不要把不确定样本硬判成真值。

## 关键接口与元数据
### 关键接口
- `PHAsset`：提供视频资产元数据。
- `PHImageManager`：用于请求缩略图或视频内容。
- `PHAssetResource`：用于获取底层资源。
- `AVAssetImageGenerator`：用于按时间点生成视频帧。

### 关键元数据
- `creationDate`
- `duration`
- `location`
- `mediaType`
- `mediaSubtypes`
- `sourceType`
- `pixelWidth`
- `pixelHeight`

这些字段足够支撑第一阶段召回，但不足以单独完成最终判定。

## 降级路径
### 规则增强路径
在主方案上增加：
- 固定球场白名单。
- 固定机位参考帧相似度。
- 常见文件命名规则。

适合长期在少数几个场地拍摄的情况。

### 自有分类模型路径
如果后续积累了足够已确认样本，可进一步训练：
- 场景分类模型。
- 动作分类模型。
- 网球音频分类模型。

这条路径的上限更高，但不适合作为第一阶段起步。

## 风险与观察
### 关键限制
- `creationDate` 和 `location` 可能缺失、偏移或被清洗。
- iCloud 资源可能尚未下载到本机，需要异步取回。
- 长视频常含大量走动、等待、休息，无效密度很低。
- 通用视觉模型容易把网球和其他拍类运动混淆。

### 需要持续观察的点
- 训练时间窗口是否足够稳定。
- 候选召回是否过窄或过宽。
- 复核层是否过度依赖单一信号。
- 室内场馆无位置数据时，元数据区分能力是否明显下降。

## 实施建议
- 先把“时间召回 + 抽样复核”跑通。
- 保存中间证据：候选列表、抽样帧、音频判断、最终分数。
- 保留一个小规模人工复核入口，用于积累高质量训练样本。

## 参考资料
- Apple Developer, PHAsset: https://developer.apple.com/documentation/photos/phasset
- Apple Developer, PHImageManager: https://developer.apple.com/documentation/photos/phimagemanager
- Apple Developer, PHAssetResource: https://developer.apple.com/documentation/photos/phassetresource
- Apple Developer, PHAssetResourceType.video: https://developer.apple.com/documentation/photos/phassetresourcetype/video
- Apple Developer, Retrieving media metadata: https://developer.apple.com/documentation/avfoundation/retrieving-media-metadata
- Apple Developer, AVAssetImageGenerator: https://developer.apple.com/documentation/avfoundation/avassetimagegenerator/generatecgimageasynchronously%28for%3Acompletionhandler%3A%29
- Apple Developer, VNClassifyImageRequest: https://developer.apple.com/documentation/vision/vnclassifyimagerequest
- Apple Developer, VNRecognizeTextRequest: https://developer.apple.com/documentation/vision/vnrecognizetextrequest
- Apple Developer, Analyzing Image Similarity with Feature Print: https://developer.apple.com/documentation/vision/analyzing-image-similarity-with-feature-print
- Apple Developer, MLSoundClassifier: https://developer.apple.com/documentation/createml/mlsoundclassifier
