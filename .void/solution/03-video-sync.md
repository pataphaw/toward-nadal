# 视频同步架构

## 目标与边界
长视频不适合直接在 `iPhone` 上做后续处理。这个子域的目标不是“最快传完”，而是把训练视频稳定送到 `MacBook` 的后处理入口，尽量自动，尽量少人工介入。

边界也要明确：
- 这里解决的是“视频从 iPhone 到 Mac 的可用交付”。
- 这里不负责运动识别、视频切片、视频精选和模型分析。
- 这里不把 `AirDrop` 视为主链路，也不把 `Finder`、`Continuity Camera` 当作视频库搬运通道。

## 当前决策
主链路保持不变：
- `iCloud Photos -> Mac Photos -> PhotoKit 自动监听与导出`

辅助路径保留两条：
- `USB + Image Capture / Photos` 作为离线兜底。
- `AirDrop` 作为近场临时补救。

## 为什么是这条链路
`iCloud Photos` 的价值不在于“局域网附近传输”，而在于把视频先稳定同步到同一份照片库里，再由 `Mac` 端消费。对长视频、大文件和持续同步，这条链路比临时投递更适合作为主通路。

`AirDrop` 更适合单次补发，不适合承担“自动发现、自动投递、自动入库”的长期职责。这个判断保持不变。

## 主链路
### 同步层
同步层的职责是把 iPhone 上的新视频稳定送到 Mac 可访问的照片库中。

职责包括：
- 保证两端使用同一 Apple Account。
- 保证两端都开启 `iCloud Photos`。
- 保证 Mac 端使用 `Photos`，并选择 `Download Originals to this Mac`。
- 维护“视频已经到达 Mac 照片库”的可观测状态。

### 消费层
消费层的职责不是“同步”，而是“消费同步结果”。

职责包括：
- 监听照片库变化。
- 识别新到达的视频资产。
- 导出原始视频资源到后续处理目录。
- 记录导出结果、失败原因和重试状态。

这两层要分开。同步层负责到达，消费层负责落盘与交接。

## 生命周期
建议把单个视频的处理生命周期看成一个小状态机，而不是一次性脚本。

可用状态：
- `new`
- `synced_to_photos`
- `eligible_for_export`
- `exporting`
- `exported`
- `retry_waiting`
- `failed`
- `ignored`

典型流转：
1. 视频进入照片库后，先进入 `synced_to_photos`。
2. 消费层判断它是否值得导出，进入 `eligible_for_export` 或 `ignored`。
3. 满足条件后进入 `exporting`。
4. 成功后进入 `exported`。
5. 失败后进入 `retry_waiting`，重试耗尽后进入 `failed`。

这个状态机的目的不是复杂化，而是让长视频、延迟同步和重复触发都能被稳定处理。

## 去重与幂等
这条链路必须默认会重复触发，不能假设每个视频只会来一次。

处理原则：
- 以稳定资产标识为主做去重。
- 以“已导出记录”判断是否需要再次写入。
- 同一个视频的重复监听事件不能生成多个输出文件。
- 同一个导出目标下，重复执行应得到同样结果，或者安全跳过。

幂等目标很简单：同一资产反复触发，最终只应有一份有效导出和一条清晰记录。

## 降级路径
主链路优先，但必须有明确回退。

### 有线导入
`USB + Image Capture` 或 `Photos` 手动导入，作为最稳的离线回退。

适用场景：
- iCloud 存储不足。
- 网络上传太慢。
- 某次训练后需要立即拿到原始视频。

### 近场补救
`AirDrop` 只用于临时补发，不承担长期自动链路。

## 风险与观察
主要风险来自同步链路本身，而不是后处理逻辑。

需要持续观察的点：
- 上传和下载耗时。
- Mac 端照片库权限。
- `System Photo Library` 设置是否正确。
- 本地空间是否足够。
- 长视频是否因网络或 iCloud 状态出现延迟到达。

如果主链路不稳定，优先回到“先能到达，再谈自动化”的原则，不要在传输层过早叠加复杂策略。

## 实施顺序
建议先做最小闭环，再补增强能力。

1. 先打通 `iCloud Photos -> Mac Photos -> 导出目录`。
2. 再补照片库监听与导出。
3. 再补去重、断点恢复和补偿检查。
4. 最后才考虑近场自动化或更细的状态管理。

## 参考资料
- Apple Support, Set up and use iCloud Photos: https://support.apple.com/en-us/108782
- Apple Support, Transfer photos and videos from iPhone or iPad to Mac or PC: https://support.apple.com/en-us/HT201734
- Apple Support, Overview of importing photos and videos on Mac: https://support.apple.com/guide/photos/phta58cd90d3/mac
- Apple Support, Image Capture User Guide: https://support.apple.com/guide/image-capture/if-a-device-doesnt-work-with-image-capture-imgcp1007/mac
- Apple Support, Use AirDrop to send items to nearby Apple devices: https://support.apple.com/guide/iphone/use-airdrop-to-send-items-to-nearby-devices-iphcd8b9f0af/ios
- Apple Developer, PHPhotoLibrary: https://developer.apple.com/documentation/photos/phphotolibrary
- Apple Developer, Delivering an Enhanced Privacy Experience in Your Photos App: https://developer.apple.com/documentation/photokit/delivering-an-enhanced-privacy-experience-in-your-photos-app
- Apple Developer, PHAssetResourceType.video: https://developer.apple.com/documentation/photos/phassetresourcetype/video
