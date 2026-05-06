# 视频精选 v1.0.3 单一最终输出目录验证

## 对应方案版本
- [视频精选方案历史（v1.0.3）](../solution/05-video-selection/history/v1.0.3.md)

## 验证目标
- 验证 `selection_runs/` 继续保存多次运行记录。
- 验证 `selected_clips/` 不再按 run id 形成多个长期并列子目录。
- 验证成功 selection 后，run 级 `selected_clips/` 只保留一组当前最终结果。
- 验证 `selected_clips/manifest.json` 能明确追溯来源 `selection_run_id`。

## 代码变更
- [tools/select_analysis_clips.py](/Users/pataphaw/Projects/toward-nadal/tools/select_analysis_clips.py:1)
- [视频精选架构（Current）](../solution/05-video-selection/current.md)

## 预期行为
- `selection_runs/<selection_run_id>/` 是多次并存的审计目录。
- `<run-dir>/selected_clips/` 是单一最终输出目录。
- 成功 promotion 时：
  - 旧的最终输出会被整体覆盖
  - 新目录中只保留当前最终结果视频和 `manifest.json`
- 如需实验性 run，不覆盖最终结果，必须显式传 `--skip-promote-selected-clips`。

## 结果
- `selection_runs/` 继续保留多次 run，不受影响。
- `selected_clips/` 已经收敛为单一最终输出目录：
  - `IMG_3197`：
    [.work/clips/img_3197/20260504-220735/selected_clips](/Users/pataphaw/Projects/toward-nadal/.work/clips/img_3197/20260504-220735/selected_clips)
  - `IMG_3198`：
    [.work/clips/img_3198/20260504-221814/selected_clips](/Users/pataphaw/Projects/toward-nadal/.work/clips/img_3198/20260504-221814/selected_clips)
- 两个目录下都只保留：
  - `01-*.mp4`
  - `02-*.mp4`
  - `03-*.mp4`
  - `manifest.json`
- 对应 manifest 证据：
  - [img_3197 manifest](/Users/pataphaw/Projects/toward-nadal/.work/clips/img_3197/20260504-220735/selected_clips/manifest.json:1)
  - [img_3198 manifest](/Users/pataphaw/Projects/toward-nadal/.work/clips/img_3198/20260504-221814/selected_clips/manifest.json:1)
- manifest 明确记录当前最终结果来源：
  - `IMG_3197 -> 20260505-img3197-vldone`
  - `IMG_3198 -> 20260505-img3198-vldone`

### package 状态同步
被提升为最终结果的两个 package 已同步标记为：
- `selected_clips_result_role = "final"`
- `promoted_selected_clips = true`

对应文件：
- [img_3197 package](/Users/pataphaw/Projects/toward-nadal/.work/clips/img_3197/20260504-220735/selection_runs/20260505-img3197-vldone/selection-package.json:1)
- [img_3198 package](/Users/pataphaw/Projects/toward-nadal/.work/clips/img_3198/20260504-221814/selection_runs/20260505-img3198-vldone/selection-package.json:1)

### 失败 run 不污染最终结果
本版还验证了另一条关键行为：

- 新的 rerun
  - [20260506-img3197-promoted](/Users/pataphaw/Projects/toward-nadal/.work/clips/img_3197/20260504-220735/selection_runs/20260506-img3197-promoted/selection-package.json:1)
  - [20260506-img3198-promoted](/Users/pataphaw/Projects/toward-nadal/.work/clips/img_3198/20260504-221814/selection_runs/20260506-img3198-promoted/selection-package.json:1)
- 两者都返回：
  - `selection_status = model_unavailable`
  - `infeasible_reasons` 包含 `request_error:timed out`
- 在这种情况下，`selected_clips/` 没有被失败 run 覆盖，仍然保持指向上一次成功 promotion 的结果。

### 参数优先级修复
这轮同时修复了一个实现级问题：
- 之前如果 CLI 传入值恰好等于默认值，`config.toml` 仍可能把它覆盖掉。
- 现在只要显式传入 CLI flag，就不会再被 config 静默改写。

## 结论
- 本版把“实验记录”和“最终输出”重新分离，避免 `selected_clips/` 下长期并列保存多组相互竞争、可能重复的导出结果。
- 当前最终结果以 `selected_clips/manifest.json` 为准，而不是以目录名猜测哪次 run 生效。
- `selection_runs/` 仍然保留所有历史实验与失败证据，满足追溯需要。
