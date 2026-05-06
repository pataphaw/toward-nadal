#!/usr/bin/env python3

from __future__ import annotations

import argparse
import base64
import contextlib
import fcntl
import hashlib
import json
import math
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from typing import Any, Iterable, Sequence

import numpy as np

try:
    import cv2
except ImportError:
    cv2 = None


DEFAULTS = {
    "analysis_fps": 2.0,
    "analysis_scale": "96:54",
    "motion_base_threshold": 4.5,
    "motion_active_gap_seconds": 1.5,
    "motion_min_span_seconds": 2.0,
    "focus_join_gap_seconds": 4.0,
    "focus_pre_roll_seconds": 0.8,
    "focus_post_roll_seconds": 1.2,
    "focus_min_seconds": 6.0,
    "focus_max_seconds": 24.0,
    "focus_target_seconds": 16.0,
    "focus_opening_seconds": 10.0,
    "focus_wide_motion_seconds": 12.0,
    "rally_pre_roll_seconds": 2.0,
    "rally_post_roll_seconds": 2.0,
    "rally_active_score_floor": 0.18,
    "rally_active_score_ceiling": 0.34,
    "rally_active_ratio_floor": 0.02,
    "rally_active_ratio_ceiling": 0.04,
    "rally_active_gap_seconds": 2.0,
    "rally_active_min_span_seconds": 2.5,
    "rally_quiet_score_threshold": 0.18,
    "rally_quiet_active_ratio_threshold": 0.035,
    "rally_quiet_gap_seconds": 3.5,
    "max_focus_windows_per_clip": 3,
    "candidate_pool_size": 4,
    "selected_size": 3,
    "frames_per_candidate": 2,
    "config_path": "config.toml",
    "local_vlm_provider": "ollama",
    "local_vlm_endpoint": "http://localhost:11434/api/chat",
    "local_vlm_model": "qwen2.5vl:3b",
    "local_vlm_fallback_model": "qwen2.5vl:3b",
    "local_vlm_timeout_seconds": 120,
    "local_vlm_max_retries": 1,
    "local_vlm_temperature": 0.0,
    "serve_exists_threshold": 0.58,
    "serve_uncertain_floor": 0.33,
    "slot_threshold": 0.45,
    "serve_slot_threshold": 0.6,
    "left_zone_threshold": 0.46,
    "right_zone_threshold": 0.54,
    "baseline_threshold": 0.72,
    "midcourt_threshold": 0.64,
    "running_span_threshold": 0.24,
    "running_disp_threshold": 0.14,
    "running_speed_threshold": 0.065,
    "stationary_span_threshold": 0.18,
    "stationary_disp_threshold": 0.08,
    "stationary_speed_threshold": 0.055,
    "blur_threshold": 8.0,
    "dark_threshold": 28.0,
    "bright_threshold": 226.0,
    "opencv_diff_percentile": 92.0,
    "opencv_min_component_area_ratio": 0.0025,
}

MODEL_JUDGEMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "schema_version": {"const": "model_judgement.v1"},
        "candidate_id": {"type": "string"},
        "in_play": {"enum": ["yes", "no", "uncertain"]},
        "non_play_type": {
            "enum": ["none", "picking_ball", "resting", "walking", "waiting", "camera_noise", "uncertain"]
        },
        "rally_completeness": {
            "enum": ["complete", "partial_start_missing", "partial_end_missing", "multi_rally", "uncertain"]
        },
        "action_tags": {"type": "array", "items": {"enum": ["forehand", "backhand", "serve"]}},
        "context_tags": {"type": "array", "items": {"enum": ["baseline", "midcourt", "running", "stationary"]}},
        "value_tags": {"type": "array", "items": {"enum": ["highlight", "good_example", "problem_example"]}},
        "reject_reasons": {"type": "array", "items": {"type": "string"}},
        "selection_reason": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
    },
    "required": [
        "schema_version",
        "candidate_id",
        "in_play",
        "non_play_type",
        "rally_completeness",
        "action_tags",
        "context_tags",
        "value_tags",
        "reject_reasons",
        "selection_reason",
        "confidence",
    ],
    "additionalProperties": False,
}

MODEL_PROMPT_TEMPLATE = """你是网球训练视频片段筛选器。你只判断当前候选片段是否适合进入后续技术分析，不输出训练建议。

输入包括按时间顺序排列的关键帧，以及候选元数据和 CV 证据摘要。

请只基于这些关键帧判断：
1. 这段是否真正在打网球。
2. 是否只是休息、捡球、等待、走动或镜头噪声。
3. rally 是否基本完整。
4. 是否能看到明显正手、反手或发球。
5. 是否具备复盘价值：亮点、好例子或问题样本。

如果证据不足，必须输出 uncertain。不要因为动作不好就排除问题样本。不要输出最终技术诊断。

必须只输出一个 JSON object，且字段必须完整，不能省略，不能添加额外字段。

输出格式固定如下：
{
  "schema_version": "model_judgement.v1",
  "candidate_id": "<输入里的 candidate_id>",
  "in_play": "yes|no|uncertain",
  "non_play_type": "none|picking_ball|resting|walking|waiting|camera_noise|uncertain",
  "rally_completeness": "complete|partial_start_missing|partial_end_missing|multi_rally|uncertain",
  "action_tags": ["forehand|backhand|serve"],
  "context_tags": ["baseline|midcourt|running|stationary"],
  "value_tags": ["highlight|good_example|problem_example"],
  "reject_reasons": ["..."],
  "selection_reason": "...",
  "confidence": 0.0
}

规则补充：
- 如果 in_play = "yes"，non_play_type 应为 "none" 或 "uncertain"。
- 如果 in_play = "no"，value_tags 必须为空数组。
- confidence 必须是 0 到 1 之间的数字。
- 如果没有明显证据，不要猜，使用 uncertain。"""


def run_command(args: Sequence[str], *, capture_stdout: bool = False) -> str:
    result = subprocess.run(
        list(args),
        check=False,
        text=True,
        stdout=subprocess.PIPE if capture_stdout else subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(args)}\n{result.stderr[-1200:]}")
    return result.stdout if capture_stdout else result.stderr


def ffprobe_json(video_path: pathlib.Path) -> dict[str, Any]:
    return json.loads(
        run_command(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_streams",
                "-show_format",
                "-of",
                "json",
                str(video_path),
            ],
            capture_stdout=True,
        )
    )


def ollama_ps_rows() -> list[dict[str, str]]:
    raw = run_command(["ollama", "ps"], capture_stdout=True)
    lines = [line.rstrip() for line in raw.splitlines() if line.strip()]
    if len(lines) <= 1:
        return []
    rows: list[dict[str, str]] = []
    for line in lines[1:]:
        parts = line.split()
        if not parts:
            continue
        rows.append({"name": parts[0], "raw": line})
    return rows


def stop_ollama_model(model_name: str) -> None:
    if not model_name:
        return
    run_command(["ollama", "stop", model_name], capture_stdout=True)


def ensure_ollama_idle(*, wait_timeout_seconds: int = 45, poll_seconds: float = 1.5) -> list[dict[str, str]]:
    rows = ollama_ps_rows()
    if not rows:
        return []
    for row in rows:
        try:
            stop_ollama_model(row["name"])
        except RuntimeError:
            # Best-effort cleanup; continue into polling because stop may race with teardown.
            pass
    deadline = time.time() + wait_timeout_seconds
    last_rows = rows
    while time.time() < deadline:
        rows = ollama_ps_rows()
        if not rows:
            return []
        last_rows = rows
        time.sleep(poll_seconds)
    return last_rows


@contextlib.contextmanager
def local_vlm_lock(lock_path: pathlib.Path) -> Iterable[None]:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("w", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        handle.write(str(time.time()))
        handle.flush()
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Select a small set of analysis-ready candidates from a segmentation run."
    )
    parser.add_argument(
        "--run-dir",
        required=True,
        help="Segmentation run directory, or its point_clips/ child directory.",
    )
    parser.add_argument("--config", default=DEFAULTS["config_path"], help="Optional local config.toml path.")
    parser.add_argument(
        "--output-dir",
        help="Optional output directory. Defaults to <run-dir>/selection_runs/<selection-run-id>.",
    )
    parser.add_argument(
        "--selected-clips-dir",
        help="Optional export directory for promoted selected clips. Defaults to <run-dir>/selected_clips/.",
    )
    parser.add_argument(
        "--skip-export-clips",
        action="store_true",
        help="Do not export focus-window video snippets for selected clips.",
    )
    parser.add_argument(
        "--skip-promote-selected-clips",
        action="store_true",
        help="Do not overwrite the run-level selected_clips/ final output directory for this run.",
    )
    parser.add_argument("--selection-run-id", help="Optional stable selection run id.")
    parser.add_argument(
        "--handedness",
        choices=("right", "left", "unknown"),
        default="unknown",
        help="Optional stable player handedness used for weak forehand/backhand heuristics.",
    )
    parser.add_argument("--candidate-pool-size", type=int, default=DEFAULTS["candidate_pool_size"])
    parser.add_argument("--selected-size", type=int, default=DEFAULTS["selected_size"])
    parser.add_argument("--frames-per-candidate", type=int, default=DEFAULTS["frames_per_candidate"])
    parser.add_argument("--analysis-fps", type=float, default=DEFAULTS["analysis_fps"])
    parser.add_argument("--analysis-scale", default=DEFAULTS["analysis_scale"])
    parser.add_argument(
        "--serve-presence",
        choices=("auto", "present", "absent"),
        default="auto",
        help="Override whether this source video should be treated as containing serve clips.",
    )
    parser.add_argument("--local-vlm-provider", default=DEFAULTS["local_vlm_provider"])
    parser.add_argument("--local-vlm-endpoint", default=DEFAULTS["local_vlm_endpoint"])
    parser.add_argument("--local-vlm-model", default=DEFAULTS["local_vlm_model"])
    parser.add_argument("--local-vlm-fallback-model", default=DEFAULTS["local_vlm_fallback_model"])
    parser.add_argument("--local-vlm-timeout-seconds", type=int, default=DEFAULTS["local_vlm_timeout_seconds"])
    parser.add_argument("--local-vlm-max-retries", type=int, default=DEFAULTS["local_vlm_max_retries"])
    parser.add_argument("--local-vlm-temperature", type=float, default=DEFAULTS["local_vlm_temperature"])
    return parser.parse_args()


def resolve_run_dir(raw_path: str) -> pathlib.Path:
    path = pathlib.Path(raw_path).resolve()
    if path.name == "point_clips" and (path.parent / "manifest.json").exists():
        return path.parent
    return path


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def safe_mean(values: Iterable[float], default: float = 0.0) -> float:
    seq = list(values)
    return float(sum(seq) / len(seq)) if seq else default


def to_jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [to_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [to_jsonable(item) for item in value]
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    return value


def union_duration(intervals: list[tuple[float, float]]) -> float:
    if not intervals:
        return 0.0
    merged: list[tuple[float, float]] = []
    for start, end in sorted(intervals):
        if end <= start:
            continue
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
            continue
        merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    return sum(end - start for start, end in merged)


def overlap_duration(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def cluster_intervals(
    intervals: list[dict[str, Any]],
    *,
    join_gap_seconds: float,
) -> list[dict[str, Any]]:
    clusters: list[dict[str, Any]] = []
    for interval in sorted(intervals, key=lambda item: item["start"]):
        if not clusters:
            clusters.append(
                {
                    "start": interval["start"],
                    "end": interval["end"],
                    "intervals": [interval],
                }
            )
            continue
        prev = clusters[-1]
        if interval["start"] - prev["end"] <= join_gap_seconds:
            prev["end"] = max(prev["end"], interval["end"])
            prev["intervals"].append(interval)
        else:
            clusters.append(
                {
                    "start": interval["start"],
                    "end": interval["end"],
                    "intervals": [interval],
                }
            )
    return clusters


def normalize_scores(values: np.ndarray) -> np.ndarray:
    if values.size == 0:
        return values
    low = float(np.percentile(values, 5))
    high = float(np.percentile(values, 95))
    if high - low < 1e-6:
        return np.zeros_like(values, dtype=float)
    return np.clip((values - low) / (high - low), 0.0, 1.0)


def smooth_1d(values: np.ndarray, window_size: int = 9) -> np.ndarray:
    if values.size == 0:
        return values
    window_size = max(1, window_size)
    if window_size % 2 == 0:
        window_size += 1
    if values.size < window_size:
        return values.astype(float)
    kernel = np.ones(window_size, dtype=float) / window_size
    return np.convolve(values.astype(float), kernel, mode="same")


def quality_from_sampled_frames(sampled: np.ndarray) -> dict[str, Any]:
    sampled_float = sampled.astype(np.float32)
    brightness_mean = float(sampled_float.mean())
    brightness_std = float(sampled_float.std())
    if cv2 is not None:
        blur_values = [float(cv2.Laplacian(frame, cv2.CV_32F).var()) for frame in sampled_float]
        blur_score = safe_mean(blur_values)
    else:
        grad_x = np.diff(sampled_float, axis=2)
        grad_y = np.diff(sampled_float, axis=1)
        blur_score = float(np.mean(np.abs(grad_x)) + np.mean(np.abs(grad_y)))
    quality_flags: list[str] = []
    if brightness_mean <= DEFAULTS["dark_threshold"]:
        quality_flags.append("dark")
    if brightness_mean >= DEFAULTS["bright_threshold"]:
        quality_flags.append("overbright")
    if blur_score <= DEFAULTS["blur_threshold"]:
        quality_flags.append("soft")
    if brightness_std < 6.0 and brightness_mean < 20.0:
        quality_flags.append("near-black")
    return {
        "brightness_mean": round(brightness_mean, 3),
        "brightness_std": round(brightness_std, 3),
        "blur_score": round(blur_score, 3),
        "quality_flags": quality_flags,
    }


def extract_motion_features_numpy(
    frames: np.ndarray,
    *,
    fps: float,
) -> list[dict[str, Any]]:
    height, width = frames.shape[1:]
    roi_y0 = int(height * 0.25)
    x_coords = np.arange(width, dtype=np.float32)[None, :]
    y_coords = np.arange(height - roi_y0, dtype=np.float32)[:, None] + roi_y0
    windows: list[dict[str, Any]] = []
    for index in range(1, len(frames)):
        diff = np.abs(frames[index].astype(np.int16) - frames[index - 1].astype(np.int16)).astype(np.float32)
        roi = diff[roi_y0:, :]
        motion_score = float(roi.mean())
        threshold = max(12.0, float(roi.mean() + roi.std()))
        mask = roi >= threshold
        active_ratio = float(mask.mean())
        anchor_x = 0.5
        anchor_y = 0.78
        component_area_ratio = 0.0
        bbox_height_ratio = 0.0
        bbox_width_ratio = 0.0
        component_found = False
        if mask.any():
            weights = roi * mask
            weight_sum = float(weights.sum())
            anchor_x = float((weights * x_coords).sum() / weight_sum / width)
            anchor_y = float((weights * y_coords).sum() / weight_sum / height)
            component_area_ratio = active_ratio
        windows.append(
            {
                "time": index / fps,
                "motion_score": motion_score,
                "active_ratio": active_ratio,
                "anchor_x": anchor_x,
                "anchor_y": anchor_y,
                "energy_peak_x": anchor_x,
                "energy_peak_y": anchor_y,
                "component_area_ratio": component_area_ratio,
                "bbox_height_ratio": bbox_height_ratio,
                "bbox_width_ratio": bbox_width_ratio,
                "component_found": component_found,
                "backend": "numpy",
            }
        )
    return windows


def extract_motion_features_cv2(
    frames: np.ndarray,
    *,
    fps: float,
) -> list[dict[str, Any]]:
    assert cv2 is not None
    height, width = frames.shape[1:]
    roi_y0 = int(height * 0.28)
    roi_height = height - roi_y0
    open_kernel = np.ones((3, 3), dtype=np.uint8)
    dilate_kernel = np.ones((5, 5), dtype=np.uint8)
    windows: list[dict[str, Any]] = []
    prev_blur = cv2.GaussianBlur(frames[0], (5, 5), 0)
    for index in range(1, len(frames)):
        current_blur = cv2.GaussianBlur(frames[index], (5, 5), 0)
        diff = cv2.absdiff(current_blur, prev_blur)
        prev_blur = current_blur
        roi = diff[roi_y0:, :]
        motion_score = float(roi.mean())
        threshold_value = max(
            10.0,
            float(np.percentile(roi, DEFAULTS["opencv_diff_percentile"])),
        )
        _, mask = cv2.threshold(roi, threshold_value, 255, cv2.THRESH_BINARY)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, open_kernel)
        mask = cv2.dilate(mask, dilate_kernel, iterations=1)
        active_ratio = float(np.count_nonzero(mask) / mask.size)
        col_energy = smooth_1d(roi.astype(np.float32).sum(axis=0), window_size=9)
        row_energy = smooth_1d(roi.astype(np.float32).sum(axis=1), window_size=7)
        energy_peak_x = float(np.argmax(col_energy) / width) if col_energy.size else 0.5
        energy_peak_y = float((roi_y0 + int(np.argmax(row_energy))) / height) if row_energy.size else 0.75

        anchor_x = 0.5
        anchor_y = 0.8
        component_area_ratio = 0.0
        bbox_height_ratio = 0.0
        bbox_width_ratio = 0.0
        component_found = False
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        best_score = -1.0
        for contour in contours:
            area = float(cv2.contourArea(contour))
            if area <= 0:
                continue
            area_ratio = area / mask.size
            if area_ratio < DEFAULTS["opencv_min_component_area_ratio"]:
                continue
            x, y, w, h = cv2.boundingRect(contour)
            bottomness = (y + h) / roi_height
            score = area_ratio * (0.7 + 0.3 * bottomness)
            if score <= best_score:
                continue
            best_score = score
            component_found = True
            component_area_ratio = area_ratio
            bbox_height_ratio = h / roi_height
            bbox_width_ratio = w / width
            moments = cv2.moments(contour)
            if moments["m00"]:
                centroid_x = moments["m10"] / moments["m00"]
            else:
                centroid_x = x + w / 2.0
            anchor_x = float(centroid_x / width)
            anchor_y = float((roi_y0 + y + 0.72 * h) / height)

        if not component_found and active_ratio > 0:
            ys, xs = np.where(mask > 0)
            if len(xs):
                anchor_x = float(xs.mean() / width)
                anchor_y = float((roi_y0 + ys.max()) / height)
        elif component_found and bbox_width_ratio >= 0.55:
            anchor_x = energy_peak_x
            anchor_y = max(anchor_y, energy_peak_y)

        windows.append(
            {
                "time": index / fps,
                "motion_score": float(motion_score + 14.0 * component_area_ratio + 8.0 * active_ratio),
                "raw_motion_score": motion_score,
                "active_ratio": active_ratio,
                "anchor_x": anchor_x,
                "anchor_y": anchor_y,
                "energy_peak_x": energy_peak_x,
                "energy_peak_y": energy_peak_y,
                "component_area_ratio": component_area_ratio,
                "bbox_height_ratio": bbox_height_ratio,
                "bbox_width_ratio": bbox_width_ratio,
                "component_found": component_found,
                "backend": "opencv",
            }
        )
    return windows


def extract_motion_features(
    video_path: pathlib.Path,
    temp_dir: pathlib.Path,
    *,
    fps: float,
    scale: str,
) -> dict[str, Any]:
    width, height = [int(part) for part in scale.split(":")]
    raw_path = temp_dir / "frames.raw"
    run_command(
        [
            "ffmpeg",
            "-v",
            "error",
            "-hide_banner",
            "-i",
            str(video_path),
            "-vf",
            f"fps={fps},scale={scale}:flags=fast_bilinear,format=gray",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "gray",
            str(raw_path),
        ]
    )
    raw_bytes = raw_path.read_bytes()
    raw_path.unlink(missing_ok=True)

    frame_size = width * height
    if len(raw_bytes) < frame_size * 2:
        return {
            "windows": [],
            "quality": {
                "brightness_mean": None,
                "brightness_std": None,
                "blur_score": None,
                "quality_flags": ["too-short-for-analysis"],
            },
        }

    frame_count = len(raw_bytes) // frame_size
    frames = np.frombuffer(raw_bytes[: frame_count * frame_size], dtype=np.uint8).reshape((frame_count, height, width))
    sample_stride = max(1, frame_count // 12)
    sampled = frames[::sample_stride][:12]
    quality = quality_from_sampled_frames(sampled)
    if cv2 is not None:
        windows = extract_motion_features_cv2(frames, fps=fps)
        quality["analysis_backend"] = "opencv"
    else:
        windows = extract_motion_features_numpy(frames, fps=fps)
        quality["analysis_backend"] = "numpy"

    return {
        "windows": windows,
        "quality": quality,
    }


def build_motion_active_intervals(motion_windows: list[dict[str, Any]], *, fps: float) -> list[dict[str, Any]]:
    if not motion_windows:
        return []
    scores = np.array([window["motion_score"] for window in motion_windows], dtype=float)
    threshold = max(
        DEFAULTS["motion_base_threshold"],
        float(np.percentile(scores, 75)),
        float(np.median(scores) + 0.75 * np.std(scores)),
    )
    frame_duration = 1.0 / fps
    active_times = [window["time"] for window in motion_windows if window["motion_score"] >= threshold]
    if not active_times:
        return []
    intervals: list[dict[str, Any]] = []
    start = active_times[0]
    prev = active_times[0]
    for time_point in active_times[1:]:
        if time_point - prev <= DEFAULTS["motion_active_gap_seconds"] + 1e-6:
            prev = time_point
            continue
        end = prev + frame_duration
        if end - start >= DEFAULTS["motion_min_span_seconds"]:
            intervals.append({"kind": "motion_local", "start": start, "end": end})
        start = time_point
        prev = time_point
    end = prev + frame_duration
    if end - start >= DEFAULTS["motion_min_span_seconds"]:
        intervals.append({"kind": "motion_local", "start": start, "end": end})
    return intervals


def relative_source_intervals(clip: dict[str, Any]) -> list[dict[str, Any]]:
    intervals: list[dict[str, Any]] = []
    for item in clip.get("boundary_evidence", {}).get("source_intervals", []):
        start = max(0.0, float(item["start"]) - float(clip["start_time"]))
        end = min(float(clip["duration"]), float(item["end"]) - float(clip["start_time"]))
        if end <= start:
            continue
        intervals.append({"kind": item["kind"], "start": start, "end": end})
    return intervals


def score_at_times(
    motion_windows: list[dict[str, Any]],
    relative_intervals: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not motion_windows:
        return []
    motion_scores = np.array([window["motion_score"] for window in motion_windows], dtype=float)
    norm_motion = normalize_scores(motion_scores)
    area_scores = np.array([window.get("component_area_ratio", window["active_ratio"]) for window in motion_windows], dtype=float)
    norm_area = normalize_scores(area_scores)
    series: list[dict[str, Any]] = []
    for idx, window in enumerate(motion_windows):
        time_point = float(window["time"])
        interval_boost = 0.0
        interval_kinds: set[str] = set()
        for interval in relative_intervals:
            if interval["start"] <= time_point <= interval["end"]:
                interval_boost = max(interval_boost, 0.35 if interval["kind"] == "audio" else 0.25)
                interval_kinds.add(interval["kind"])
        score = clamp(
            0.65 * float(norm_motion[idx])
            + 0.2 * float(norm_area[idx])
            + 0.15 * float(window["active_ratio"])
            + interval_boost,
            0.0,
            1.0,
        )
        series.append(
            {
                "time": time_point,
                "score": score,
                "motion_score": float(window["motion_score"]),
                "raw_motion_score": float(window.get("raw_motion_score", window["motion_score"])),
                "active_ratio": float(window["active_ratio"]),
                "anchor_x": float(window.get("anchor_x", 0.5)),
                "anchor_y": float(window.get("anchor_y", 0.8)),
                "component_area_ratio": float(window.get("component_area_ratio", window["active_ratio"])),
                "bbox_height_ratio": float(window.get("bbox_height_ratio", 0.0)),
                "bbox_width_ratio": float(window.get("bbox_width_ratio", 0.0)),
                "component_found": bool(window.get("component_found", False)),
                "interval_kinds": sorted(interval_kinds),
            }
        )
    return series


def find_densest_subwindow(
    series: list[dict[str, Any]],
    *,
    start: float,
    end: float,
    min_seconds: float,
    max_seconds: float,
    target_seconds: float,
) -> tuple[float, float]:
    local = [item for item in series if start <= item["time"] <= end]
    if not local:
        return start, end
    times = np.array([item["time"] for item in local], dtype=float)
    scores = np.array([item["score"] for item in local], dtype=float)
    cluster_duration = max(end - start, min_seconds)
    window_size = clamp(target_seconds if cluster_duration > target_seconds else cluster_duration, min_seconds, max_seconds)
    best_score = -1.0
    best_window = (start, min(end, start + window_size))
    for left_idx, left_time in enumerate(times):
        right_time = min(end, left_time + window_size)
        mask = (times >= left_time) & (times <= right_time)
        if not mask.any():
            continue
        density = float(scores[mask].mean())
        duration_bonus = min(1.0, (right_time - left_time) / target_seconds)
        value = density * (0.75 + 0.25 * duration_bonus)
        if value > best_score:
            best_score = value
            best_window = (left_time, right_time)
    return best_window


def find_widest_motion_subwindow(
    series: list[dict[str, Any]],
    *,
    start: float,
    end: float,
    min_seconds: float,
    max_seconds: float,
    target_seconds: float,
) -> tuple[float, float]:
    local = [item for item in series if start <= item["time"] <= end]
    if not local:
        return start, end
    times = np.array([item["time"] for item in local], dtype=float)
    scores = np.array([item["score"] for item in local], dtype=float)
    x_values = np.array([item["anchor_x"] for item in local], dtype=float)
    cluster_duration = max(end - start, min_seconds)
    window_size = clamp(target_seconds if cluster_duration > target_seconds else cluster_duration, min_seconds, max_seconds)
    best_score = -1.0
    best_window = (start, min(end, start + window_size))
    for left_idx, left_time in enumerate(times):
        right_time = min(end, left_time + window_size)
        mask = (times >= left_time) & (times <= right_time)
        if not mask.any():
            continue
        local_scores = scores[mask]
        local_x = x_values[mask]
        local_duration = max(0.001, right_time - left_time)
        x_span = float(np.percentile(local_x, 90) - np.percentile(local_x, 10))
        path_length = float(np.sum(np.abs(np.diff(local_x)))) if local_x.size >= 2 else 0.0
        lateral_speed = path_length / local_duration
        score_std = float(local_scores.std())
        value = (
            0.42 * clamp(x_span / 0.28, 0.0, 1.0)
            + 0.24 * clamp(lateral_speed / 0.075, 0.0, 1.0)
            + 0.2 * float(local_scores.mean())
            + 0.14 * clamp(score_std / 0.18, 0.0, 1.0)
        )
        if value > best_score:
            best_score = value
            best_window = (left_time, right_time)
    return best_window


def infer_series_frame_duration(series: list[dict[str, Any]]) -> float:
    if len(series) < 2:
        return 0.5
    diffs = [
        float(series[index]["time"]) - float(series[index - 1]["time"])
        for index in range(1, len(series))
        if float(series[index]["time"]) > float(series[index - 1]["time"])
    ]
    if not diffs:
        return 0.5
    return max(0.001, float(np.median(np.array(diffs, dtype=float))))


def build_rally_active_intervals(series: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not series:
        return []
    frame_duration = infer_series_frame_duration(series)
    score_values = np.array([item["score"] for item in series], dtype=float)
    active_ratio_values = np.array([item["active_ratio"] for item in series], dtype=float)
    score_threshold = clamp(
        float(np.percentile(score_values, 35)),
        DEFAULTS["rally_active_score_floor"],
        DEFAULTS["rally_active_score_ceiling"],
    )
    active_ratio_threshold = clamp(
        float(np.percentile(active_ratio_values, 35)),
        DEFAULTS["rally_active_ratio_floor"],
        DEFAULTS["rally_active_ratio_ceiling"],
    )

    def is_rally_active(item: dict[str, Any]) -> bool:
        return (
            float(item["score"]) >= score_threshold
            or float(item["active_ratio"]) >= active_ratio_threshold
        )

    active_times = [float(item["time"]) for item in series if is_rally_active(item)]
    if not active_times:
        return []

    intervals: list[dict[str, Any]] = []
    start = active_times[0]
    prev = active_times[0]
    for time_point in active_times[1:]:
        if time_point - prev <= DEFAULTS["rally_active_gap_seconds"] + 1e-6:
            prev = time_point
            continue
        end = prev + frame_duration
        if end - start >= DEFAULTS["rally_active_min_span_seconds"]:
            intervals.append({"kind": "rally_local", "start": start, "end": end})
        start = time_point
        prev = time_point
    end = prev + frame_duration
    if end - start >= DEFAULTS["rally_active_min_span_seconds"]:
        intervals.append({"kind": "rally_local", "start": start, "end": end})
    return intervals


def choose_rally_interval_for_focus(
    intervals: list[dict[str, Any]],
    *,
    focus_start: float,
    focus_end: float,
) -> dict[str, Any] | None:
    if not intervals:
        return None
    focus_mid = (focus_start + focus_end) / 2.0
    best: dict[str, Any] | None = None
    best_score = -999.0
    for interval in intervals:
        start = float(interval["start"])
        end = float(interval["end"])
        overlap = overlap_duration(focus_start, focus_end, start, end)
        contains_mid = 1.0 if start <= focus_mid <= end else 0.0
        distance = 0.0 if contains_mid else min(abs(focus_mid - start), abs(focus_mid - end))
        duration = end - start
        score = 3.0 * contains_mid + 1.6 * overlap - 0.05 * distance - 0.01 * abs(duration - 18.0)
        if score > best_score:
            best_score = score
            best = interval
    return best


def expand_window_to_quiet_bounds(
    series: list[dict[str, Any]],
    *,
    seed_start: float,
    seed_end: float,
    clip_duration: float,
) -> tuple[float, float]:
    if not series:
        return seed_start, seed_end
    frame_duration = infer_series_frame_duration(series)
    quiet_gap_frames = max(1, int(math.ceil(DEFAULTS["rally_quiet_gap_seconds"] / frame_duration)))

    def is_quiet(item: dict[str, Any]) -> bool:
        return (
            float(item["score"]) < DEFAULTS["rally_quiet_score_threshold"]
            and float(item["active_ratio"]) < DEFAULTS["rally_quiet_active_ratio_threshold"]
        )

    left_idx = 0
    while left_idx + 1 < len(series) and float(series[left_idx + 1]["time"]) <= seed_start:
        left_idx += 1
    right_idx = len(series) - 1
    while right_idx - 1 >= 0 and float(series[right_idx - 1]["time"]) >= seed_end:
        right_idx -= 1

    start_index = left_idx
    quiet_run = 0
    for idx in range(left_idx, -1, -1):
        if is_quiet(series[idx]):
            quiet_run += 1
        else:
            quiet_run = 0
        if quiet_run >= quiet_gap_frames:
            start_index = min(len(series) - 1, idx + quiet_gap_frames)
            break
        start_index = idx

    end_index = right_idx
    quiet_run = 0
    for idx in range(right_idx, len(series)):
        if is_quiet(series[idx]):
            quiet_run += 1
        else:
            quiet_run = 0
        if quiet_run >= quiet_gap_frames:
            end_index = max(0, idx - quiet_gap_frames)
            break
        end_index = idx

    window_start = clamp(float(series[start_index]["time"]) - DEFAULTS["rally_pre_roll_seconds"], 0.0, clip_duration)
    window_end = clamp(float(series[end_index]["time"]) + frame_duration + DEFAULTS["rally_post_roll_seconds"], 0.0, clip_duration)
    if window_end <= window_start:
        return seed_start, seed_end
    return window_start, window_end


def find_rally_export_window(
    series: list[dict[str, Any]],
    *,
    focus_start: float,
    focus_end: float,
    clip_duration: float,
) -> tuple[float, float]:
    if not series:
        return focus_start, focus_end
    rally_intervals = build_rally_active_intervals(series)
    rally_interval = choose_rally_interval_for_focus(
        rally_intervals,
        focus_start=focus_start,
        focus_end=focus_end,
    )
    if rally_interval is not None:
        return expand_window_to_quiet_bounds(
            series,
            seed_start=float(rally_interval["start"]),
            seed_end=float(rally_interval["end"]),
            clip_duration=clip_duration,
        )
    return expand_window_to_quiet_bounds(
        series,
        seed_start=focus_start,
        seed_end=focus_end,
        clip_duration=clip_duration,
    )


def dedupe_windows(windows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    for window in sorted(windows, key=lambda item: item["window_value_score"], reverse=True):
        duplicated = False
        for prev in deduped:
            overlap = overlap_duration(
                window["focus_window"]["source_clip_offset_start"],
                window["focus_window"]["source_clip_offset_end"],
                prev["focus_window"]["source_clip_offset_start"],
                prev["focus_window"]["source_clip_offset_end"],
            )
            denom = min(
                window["focus_window"]["source_clip_offset_end"] - window["focus_window"]["source_clip_offset_start"],
                prev["focus_window"]["source_clip_offset_end"] - prev["focus_window"]["source_clip_offset_start"],
            )
            if denom > 0 and overlap / denom >= 0.7:
                same_kind = window.get("window_kind") == prev.get("window_kind")
                start_delta = abs(
                    window["focus_window"]["source_clip_offset_start"]
                    - prev["focus_window"]["source_clip_offset_start"]
                )
                if not same_kind and (
                    "opening-probe" in {window.get("window_kind"), prev.get("window_kind")}
                    or start_delta >= 2.5
                ):
                    continue
                duplicated = True
                break
        if not duplicated:
            deduped.append(window)
    return deduped


def candidate_overlap_window(candidate: dict[str, Any]) -> dict[str, Any]:
    return candidate.get("selected_clip_window", candidate["focus_window"])


def classify_side_zone(x_value: float) -> tuple[str, float]:
    if x_value <= DEFAULTS["left_zone_threshold"]:
        return "left", 0.7
    if x_value >= DEFAULTS["right_zone_threshold"]:
        return "right", 0.7
    return "center", 0.65


def classify_court_zone(y_value: float) -> tuple[str, float]:
    if y_value >= DEFAULTS["baseline_threshold"]:
        return "baseline", 0.72
    if y_value >= DEFAULTS["midcourt_threshold"]:
        return "midcourt", 0.58
    return "midcourt", 0.68


def classify_movement(x_span: float, displacement: float, lateral_speed: float) -> tuple[str, float]:
    if (
        x_span >= DEFAULTS["running_span_threshold"]
        or displacement >= DEFAULTS["running_disp_threshold"]
        or lateral_speed >= DEFAULTS["running_speed_threshold"]
    ):
        return "running", 0.7
    if (
        x_span <= DEFAULTS["stationary_span_threshold"]
        and displacement <= DEFAULTS["stationary_disp_threshold"]
        and lateral_speed <= DEFAULTS["stationary_speed_threshold"]
    ):
        return "stationary", 0.68
    return "stationary", 0.56


def count_direction_changes(values: np.ndarray, *, min_step: float = 0.02) -> int:
    if len(values) < 3:
        return 0
    diffs = np.diff(values.astype(float))
    filtered = [diff for diff in diffs if abs(diff) >= min_step]
    if len(filtered) < 2:
        return 0
    changes = 0
    prev_sign = 1 if filtered[0] > 0 else -1
    for diff in filtered[1:]:
        sign = 1 if diff > 0 else -1
        if sign != prev_sign:
            changes += 1
        prev_sign = sign
    return changes


def compute_window_features(
    clip: dict[str, Any],
    window_start: float,
    window_end: float,
    series: list[dict[str, Any]],
    metric_intervals: list[dict[str, Any]],
    quality: dict[str, Any],
    handedness: str,
) -> dict[str, Any]:
    relevant = [item for item in series if window_start <= item["time"] <= window_end]
    if not relevant:
        relevant = series
    window_duration = max(0.001, window_end - window_start)
    interval_overlap = sum(
        overlap_duration(window_start, window_end, interval["start"], interval["end"])
        for interval in metric_intervals
    )
    effective_play_ratio = clamp(interval_overlap / window_duration, 0.0, 1.0)
    dead_time_ratio = 1.0 - effective_play_ratio

    weights = np.array([max(item["score"], 0.05) for item in relevant], dtype=float)
    weight_sum = float(weights.sum())
    score_values = np.array([item["score"] for item in relevant], dtype=float)
    mean_x = float(np.dot(np.array([item["anchor_x"] for item in relevant]), weights) / weight_sum)
    mean_y = float(np.dot(np.array([item["anchor_y"] for item in relevant]), weights) / weight_sum)
    peak_motion = float(max(item["motion_score"] for item in relevant))
    avg_score = float(np.dot(np.array([item["score"] for item in relevant]), weights) / weight_sum)
    x_values = np.array([item["anchor_x"] for item in relevant], dtype=float)
    y_values = np.array([item["anchor_y"] for item in relevant], dtype=float)
    area_values = np.array([item["component_area_ratio"] for item in relevant], dtype=float)
    height_values = np.array([item["bbox_height_ratio"] for item in relevant], dtype=float)
    x_span = float(np.percentile(x_values, 90) - np.percentile(x_values, 10))
    displacement = float(abs(x_values[-1] - x_values[0])) if len(x_values) >= 2 else 0.0
    path_length = float(np.sum(np.abs(np.diff(x_values)))) if len(x_values) >= 2 else 0.0
    lateral_speed = path_length / window_duration
    direction_changes = count_direction_changes(x_values)
    trajectory_linearity = displacement / max(path_length, 0.001) if path_length > 0 else 0.0
    mean_area = float(np.dot(area_values, weights) / weight_sum) if len(area_values) else 0.0
    mean_height = float(np.dot(height_values, weights) / weight_sum) if len(height_values) else 0.0
    peak_score = float(score_values.max()) if len(score_values) else 0.0
    p90_score = float(np.percentile(score_values, 90)) if len(score_values) else 0.0
    score_std = float(score_values.std()) if len(score_values) else 0.0

    early_cutoff = window_start + min(4.0, max(2.5, window_duration * 0.33))
    early = [item for item in relevant if item["time"] <= early_cutoff]
    if not early:
        early = relevant[: max(1, len(relevant) // 3)]
    late = [item for item in relevant if item["time"] >= early_cutoff]
    if not late:
        late = relevant

    early_weights = np.array([max(item["score"], 0.05) for item in early], dtype=float)
    early_weight_sum = float(early_weights.sum())
    early_x_values = np.array([item["anchor_x"] for item in early], dtype=float)
    early_y_values = np.array([item["anchor_y"] for item in early], dtype=float)
    early_mean_x = float(np.dot(early_x_values, early_weights) / early_weight_sum)
    early_mean_y = float(np.dot(early_y_values, early_weights) / early_weight_sum)
    early_height_values = np.array([item["bbox_height_ratio"] for item in early], dtype=float)
    early_mean_height = float(np.dot(early_height_values, early_weights) / early_weight_sum) if len(early_height_values) else 0.0
    early_x_span = float(np.percentile(early_x_values, 90) - np.percentile(early_x_values, 10))
    early_path_length = float(np.sum(np.abs(np.diff(early_x_values)))) if len(early_x_values) >= 2 else 0.0
    early_direction_changes = count_direction_changes(early_x_values)
    early_duration = max(0.001, float(early[-1]["time"] - early[0]["time"])) if len(early) >= 2 else min(2.0, window_duration)
    early_speed = early_path_length / max(early_duration, 0.001)
    early_score_mean = safe_mean(item["score"] for item in early)
    late_peak_score = max(float(item["score"]) for item in late)

    side_zone, side_conf = classify_side_zone(mean_x)
    distance_score = mean_y
    court_zone, court_conf = classify_court_zone(distance_score)
    movement_mode, movement_conf = classify_movement(x_span, displacement, lateral_speed)

    # Weak first-pass handedness heuristic. Unknown handedness keeps both low-confidence.
    forehand_prob = 0.22
    backhand_prob = 0.22
    if handedness == "right":
        if side_zone == "left":
            forehand_prob = 0.58
            backhand_prob = 0.18
        elif side_zone == "right":
            backhand_prob = 0.58
            forehand_prob = 0.18
    elif handedness == "left":
        if side_zone == "left":
            backhand_prob = 0.58
            forehand_prob = 0.18
        elif side_zone == "right":
            forehand_prob = 0.58
            backhand_prob = 0.18
    if movement_mode == "running":
        forehand_prob = clamp(forehand_prob + 0.04, 0.0, 0.78)
        backhand_prob = clamp(backhand_prob + 0.04, 0.0, 0.78)
    elif movement_mode == "stationary":
        forehand_prob = clamp(forehand_prob + 0.02, 0.0, 0.76)
        backhand_prob = clamp(backhand_prob + 0.02, 0.0, 0.76)

    early_start = window_start <= 3.0
    early_centeredness = clamp(1.0 - abs(early_mean_x - 0.5) / 0.18, 0.0, 1.0)
    early_baseline_presence = clamp((early_mean_y - 0.68) / 0.08, 0.0, 1.0)
    opening_compactness = clamp(1.0 - early_x_span / 0.18, 0.0, 1.0)
    opening_stillness = clamp(1.0 - early_speed / 0.06, 0.0, 1.0)
    serve_shape_score = (
        0.3 * early_centeredness
        + 0.24 * early_baseline_presence
        + 0.22 * opening_compactness
        + 0.14 * opening_stillness
        + 0.1 * clamp((late_peak_score - early_score_mean - 0.1) / 0.35, 0.0, 1.0)
    )
    serve_prob = 0.0
    if early_start:
        serve_prob += 0.16
    serve_prob += 0.34 * serve_shape_score
    if window_duration <= 12.0:
        serve_prob += 0.08
    elif window_duration <= 16.0:
        serve_prob += 0.04
    if dead_time_ratio <= 0.18:
        serve_prob += 0.04
    if early_mean_height >= 0.18 or mean_height >= 0.2:
        serve_prob += 0.04
    if float(clip["duration"]) <= 24.0:
        serve_prob += 0.06
    elif float(clip["duration"]) <= 32.0:
        serve_prob += 0.03
    serve_prob = clamp(serve_prob, 0.0, 0.84)
    action_prob = max(forehand_prob, backhand_prob, serve_prob)

    duration_norm = clamp(window_duration / 20.0, 0.0, 1.0)
    stable_movement = clamp(1.0 - x_span / 0.34, 0.0, 1.0) * 0.55 + clamp(1.0 - lateral_speed / 0.08, 0.0, 1.0) * 0.45
    volatility = (
        0.35 * clamp(x_span / 0.32, 0.0, 1.0)
        + 0.25 * clamp(displacement / 0.18, 0.0, 1.0)
        + 0.25 * clamp(lateral_speed / 0.08, 0.0, 1.0)
        + 0.15 * clamp(score_std / 0.18, 0.0, 1.0)
    )
    highlight_score = clamp(
        0.26 * effective_play_ratio
        + 0.24 * avg_score
        + 0.18 * p90_score
        + 0.12 * duration_norm
        + 0.12 * clamp(score_std / 0.16, 0.0, 1.0)
        + 0.08 * clamp(mean_area / 0.035, 0.0, 1.0),
        0.0,
        1.0,
    )
    good_example_score = clamp(
        0.34 * effective_play_ratio
        + 0.22 * stable_movement
        + 0.16 * avg_score
        + 0.12 * duration_norm
        + 0.1 * clamp(mean_area / 0.04, 0.0, 1.0)
        + 0.06 * opening_compactness,
        0.0,
        1.0,
    )
    abruptness = clamp((0.22 - window_duration / 30.0), 0.0, 0.22) / 0.22
    problem_example_score = clamp(
        0.22 * dead_time_ratio
        + 0.18 * abruptness
        + 0.3 * volatility
        + 0.2 * (1.0 - stable_movement)
        + 0.1 * (1.0 if movement_mode == "running" else 0.2),
        0.0,
        1.0,
    )

    semantic_confidence = clamp(
        0.2 * side_conf
        + 0.18 * court_conf
        + 0.18 * movement_conf
        + 0.16 * avg_score
        + 0.14 * effective_play_ratio
        + 0.14 * clamp(mean_area / 0.03, 0.0, 1.0),
        0.0,
        1.0,
    )

    quality_flags = list(quality["quality_flags"])
    if dead_time_ratio >= 0.45:
        quality_flags.append("high-dead-time")

    center_crossing = abs(early_mean_x - mean_x)
    late_window_ratio = window_start / max(float(clip["duration"]), 0.001)
    transit_motion_risk = (
        x_span >= 0.6
        and early_direction_changes == 0
        and center_crossing >= 0.22
        and 0.38 <= mean_x <= 0.62
        and action_prob < 0.35
        and late_window_ratio >= 0.45
    )
    if transit_motion_risk:
        quality_flags.append("transit-motion-risk")

    semantic_tags = {
        "serve_prob": round(serve_prob, 3),
        "forehand_prob": round(forehand_prob, 3),
        "backhand_prob": round(backhand_prob, 3),
        "action_prob": round(action_prob, 3),
        "court_zone": {"label": court_zone, "confidence": round(court_conf, 3)},
        "movement_mode": {"label": movement_mode, "confidence": round(movement_conf, 3)},
        "side_zone": {"label": side_zone, "confidence": round(side_conf, 3)},
        "value_roles": {
            "highlight": round(highlight_score, 3),
            "good-example": round(good_example_score, 3),
            "problem-example": round(problem_example_score, 3),
        },
        "in_play_confidence": round(
            clamp(
                0.28 * effective_play_ratio
                + 0.18 * avg_score
                + 0.18 * clamp(direction_changes / 3.0, 0.0, 1.0)
                + 0.16 * clamp((1.0 - trajectory_linearity) / 0.45, 0.0, 1.0)
                + 0.2 * action_prob
                - (0.28 if transit_motion_risk else 0.0),
                0.0,
                1.0,
            ),
            3,
        ),
        "semantic_confidence": round(semantic_confidence, 3),
    }

    coverage_roles: list[str] = []
    coverage_roles.append(court_zone)
    coverage_roles.append(movement_mode)
    coverage_roles.append(side_zone)
    if highlight_score >= 0.58:
        coverage_roles.append("highlight")
    if good_example_score >= 0.6:
        coverage_roles.append("good-example")
    if problem_example_score >= 0.56:
        coverage_roles.append("problem-example")
    if serve_prob >= DEFAULTS["serve_slot_threshold"]:
        coverage_roles.append("serve")
    if forehand_prob >= DEFAULTS["slot_threshold"]:
        coverage_roles.append("forehand")
    if backhand_prob >= DEFAULTS["slot_threshold"]:
        coverage_roles.append("backhand")

    selection_score = clamp(
        0.4 * highlight_score
        + 0.2 * good_example_score
        + 0.15 * problem_example_score
        + 0.15 * effective_play_ratio
        + 0.1 * semantic_confidence,
        0.0,
        1.0,
    )
    reason_tags = [
        f"focus-window {window_duration:.1f}s",
        f"play-ratio {effective_play_ratio:.2f}",
        f"{court_zone}/{movement_mode}/{side_zone}",
    ]
    if "highlight" in coverage_roles:
        reason_tags.append("highlight candidate")
    if "problem-example" in coverage_roles:
        reason_tags.append("problem-example candidate")
    if "good-example" in coverage_roles:
        reason_tags.append("good-example candidate")
    if "serve" in coverage_roles:
        reason_tags.append("serve-like opening")
    if transit_motion_risk:
        reason_tags.append("transit-motion-risk")

    return {
        "window_duration": round(window_duration, 3),
        "effective_play_ratio": round(effective_play_ratio, 3),
        "dead_time_ratio": round(dead_time_ratio, 3),
        "peak_motion": round(peak_motion, 3),
        "avg_score": round(avg_score, 3),
        "centroid_summary": {
            "mean_x": round(mean_x, 3),
            "mean_y": round(mean_y, 3),
            "distance_score": round(distance_score, 3),
            "x_span": round(x_span, 3),
            "displacement": round(displacement, 3),
            "path_length": round(path_length, 3),
            "lateral_speed": round(lateral_speed, 3),
            "direction_changes": int(direction_changes),
            "trajectory_linearity": round(trajectory_linearity, 3),
            "mean_area": round(mean_area, 4),
            "mean_height": round(mean_height, 4),
            "early_mean_x": round(early_mean_x, 3),
            "early_mean_y": round(early_mean_y, 3),
            "early_x_span": round(early_x_span, 3),
            "early_speed": round(early_speed, 3),
            "early_direction_changes": int(early_direction_changes),
            "center_crossing": round(center_crossing, 3),
            "serve_shape_score": round(serve_shape_score, 3),
        },
        "semantic_tags": semantic_tags,
        "coverage_roles": coverage_roles,
        "selection_score": round(selection_score, 3),
        "quality_flags": quality_flags,
        "selection_reasons": reason_tags,
    }


def generate_candidates_for_clip(
    clip: dict[str, Any],
    motion_analysis: dict[str, Any],
    *,
    handedness: str,
) -> list[dict[str, Any]]:
    relative_intervals = relative_source_intervals(clip)
    fallback_motion_intervals = build_motion_active_intervals(
        motion_analysis["windows"],
        fps=DEFAULTS["analysis_fps"],
    )
    focus_seed_intervals = fallback_motion_intervals or relative_intervals
    metric_intervals = fallback_motion_intervals or relative_intervals
    if not focus_seed_intervals:
        return []

    relative_coverage = 0.0
    if relative_intervals and clip.get("duration"):
        relative_coverage = union_duration(
            [(float(item["start"]), float(item["end"])) for item in relative_intervals]
        ) / max(float(clip["duration"]), 0.001)
    if relative_intervals and (relative_coverage <= 0.65 or len(relative_intervals) >= 3):
        score_intervals = relative_intervals
    else:
        score_intervals = fallback_motion_intervals

    series = score_at_times(motion_analysis["windows"], score_intervals)
    clusters = cluster_intervals(
        focus_seed_intervals,
        join_gap_seconds=DEFAULTS["focus_join_gap_seconds"],
    )
    clip_duration = float(clip["duration"])
    proposed: list[dict[str, Any]] = []
    cluster_candidate_index = 0

    def append_candidate(
        *,
        cluster: dict[str, Any],
        inner_start: float,
        inner_end: float,
        window_kind: str,
    ) -> None:
        nonlocal cluster_candidate_index
        focus_start = clamp(inner_start - DEFAULTS["focus_pre_roll_seconds"], 0.0, clip_duration)
        focus_end = clamp(inner_end + DEFAULTS["focus_post_roll_seconds"], 0.0, clip_duration)
        if focus_end - focus_start < DEFAULTS["focus_min_seconds"]:
            pad = (DEFAULTS["focus_min_seconds"] - (focus_end - focus_start)) / 2.0
            focus_start = clamp(focus_start - pad, 0.0, clip_duration)
            focus_end = clamp(focus_end + pad, 0.0, clip_duration)
        clip_window_start, clip_window_end = find_rally_export_window(
            series,
            focus_start=focus_start,
            focus_end=focus_end,
            clip_duration=clip_duration,
        )
        if window_kind == "opening-probe":
            clip_window_start = 0.0
        if clip_window_end <= clip_window_start:
            clip_window_start = focus_start
            clip_window_end = focus_end

        features = compute_window_features(
            clip,
            focus_start,
            focus_end,
            series,
            metric_intervals,
            motion_analysis["quality"],
            handedness,
        )
        cluster_duration = cluster["end"] - cluster["start"]
        multi_rally_risk = cluster_duration >= 36.0 or (
            len(cluster["intervals"]) >= 3 and features["dead_time_ratio"] >= 0.22
        )
        if multi_rally_risk:
            features["quality_flags"] = sorted(set(features["quality_flags"] + ["multi-rally-risk"]))
        clip_window_duration = clip_window_end - clip_window_start
        boundary_penalty = 0.0
        unresolved_flags: list[str] = []
        if clip_duration >= 45.0 and focus_start >= 8.0 and clip_window_start <= 0.5:
            unresolved_flags.append("rally-start-unresolved")
            boundary_penalty += 0.12
        if clip_duration >= 45.0 and focus_end <= clip_duration - 8.0 and clip_window_end >= clip_duration - 0.5:
            unresolved_flags.append("rally-end-unresolved")
            boundary_penalty += 0.12
        if clip_duration >= 60.0 and clip_window_duration / max(clip_duration, 0.001) >= 0.82:
            unresolved_flags.append("whole-clip-window-risk")
            boundary_penalty += 0.08
        if unresolved_flags:
            features["quality_flags"] = sorted(set(features["quality_flags"] + unresolved_flags))
            features["selection_reasons"] = features["selection_reasons"] + unresolved_flags
        absolute_start = float(clip["start_time"]) + focus_start
        absolute_end = float(clip["start_time"]) + focus_end
        clip_absolute_start = float(clip["start_time"]) + clip_window_start
        clip_absolute_end = float(clip["start_time"]) + clip_window_end
        cluster_candidate_index += 1
        proposed.append(
            {
                "selection_id": f"{clip['clip_id']}-focus-{cluster_candidate_index:02d}",
                "clip_id": clip["clip_id"],
                "source_video_id": clip["source_video_id"],
                "source_clip_path": clip["export_path"],
                "clip_start_time": round(float(clip["start_time"]), 3),
                "clip_end_time": round(float(clip["end_time"]), 3),
                "clip_duration": round(float(clip["duration"]), 3),
                "window_kind": window_kind,
                "focus_window": {
                    "source_clip_offset_start": round(focus_start, 3),
                    "source_clip_offset_end": round(focus_end, 3),
                    "absolute_start_time": round(absolute_start, 3),
                    "absolute_end_time": round(absolute_end, 3),
                    "absolute_timebase": "source_video_timeline",
                },
                "selected_clip_window": {
                    "source_clip_offset_start": round(clip_window_start, 3),
                    "source_clip_offset_end": round(clip_window_end, 3),
                    "absolute_start_time": round(clip_absolute_start, 3),
                    "absolute_end_time": round(clip_absolute_end, 3),
                    "absolute_timebase": "source_video_timeline",
                },
                "selection_reasons": [window_kind] + features["selection_reasons"],
                "coverage_roles": features["coverage_roles"],
                "semantic_tags": features["semantic_tags"],
                "quality_flags": features["quality_flags"],
                "selection_score": round(clamp(features["selection_score"] - boundary_penalty, 0.0, 1.0), 3),
                "confidence": features["semantic_tags"]["semantic_confidence"],
                "needs_review": features["semantic_tags"]["semantic_confidence"] < 0.52,
                "window_metrics": {
                    "window_duration": features["window_duration"],
                    "effective_play_ratio": features["effective_play_ratio"],
                    "dead_time_ratio": features["dead_time_ratio"],
                    "peak_motion": features["peak_motion"],
                    "avg_score": features["avg_score"],
                    "centroid_summary": features["centroid_summary"],
                },
                "window_value_score": round(
                    clamp(features["selection_score"] - boundary_penalty, 0.0, 1.0)
                    + 0.15 * features["effective_play_ratio"]
                    + (0.04 if window_kind == "opening-probe" else 0.0),
                    3,
                ),
            }
        )

    for cluster_index, cluster in enumerate(clusters, start=1):
        cluster_duration = cluster["end"] - cluster["start"]
        if cluster_duration > DEFAULTS["focus_max_seconds"]:
            target = clamp(cluster_duration * 0.35 + 4.0, DEFAULTS["focus_target_seconds"], DEFAULTS["focus_max_seconds"])
            dense_start, dense_end = find_densest_subwindow(
                series,
                start=cluster["start"],
                end=cluster["end"],
                min_seconds=DEFAULTS["focus_min_seconds"],
                max_seconds=DEFAULTS["focus_max_seconds"],
                target_seconds=target,
            )
        else:
            dense_start, dense_end = cluster["start"], cluster["end"]
        append_candidate(
            cluster=cluster,
            inner_start=dense_start,
            inner_end=dense_end,
            window_kind=f"dense-cluster-{cluster_index}",
        )

        if cluster_index == 1 and cluster["start"] <= 4.0:
            opening_end = min(
                clip_duration,
                max(
                    DEFAULTS["focus_min_seconds"],
                    min(DEFAULTS["focus_opening_seconds"], cluster["end"] + 1.2),
                ),
            )
            append_candidate(
                cluster=cluster,
                inner_start=0.0,
                inner_end=opening_end,
                window_kind="opening-probe",
            )

        if cluster_duration >= 12.0 or clip_duration >= 18.0:
            wide_target = clamp(
                DEFAULTS["focus_wide_motion_seconds"],
                DEFAULTS["focus_min_seconds"],
                DEFAULTS["focus_max_seconds"],
            )
            wide_start, wide_end = find_widest_motion_subwindow(
                series,
                start=cluster["start"],
                end=cluster["end"],
                min_seconds=DEFAULTS["focus_min_seconds"],
                max_seconds=DEFAULTS["focus_max_seconds"],
                target_seconds=wide_target,
            )
            append_candidate(
                cluster=cluster,
                inner_start=wide_start,
                inner_end=wide_end,
                window_kind=f"wide-motion-{cluster_index}",
            )

    return dedupe_windows(proposed)[: DEFAULTS["max_focus_windows_per_clip"]]


def overlap_penalty(candidate: dict[str, Any], selected: list[dict[str, Any]]) -> float:
    penalty = 0.0
    candidate_window = candidate_overlap_window(candidate)
    for prev in selected:
        if candidate["clip_id"] != prev["clip_id"]:
            continue
        prev_window = candidate_overlap_window(prev)
        overlap = overlap_duration(
            candidate_window["source_clip_offset_start"],
            candidate_window["source_clip_offset_end"],
            prev_window["source_clip_offset_start"],
            prev_window["source_clip_offset_end"],
        )
        candidate_duration = (
            candidate_window["source_clip_offset_end"] - candidate_window["source_clip_offset_start"]
        )
        if candidate_duration > 0:
            penalty = max(penalty, overlap / candidate_duration)
    return penalty


def best_candidate_for_role(
    candidates: list[dict[str, Any]],
    selected_ids: set[str],
    role: str,
    *,
    require_in_play: bool = False,
) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    best_score = -1.0
    for candidate in candidates:
        if candidate["selection_id"] in selected_ids:
            continue
        if require_in_play and not is_in_play_candidate(candidate):
            continue
        if role == "serve":
            role_score = float(candidate["semantic_tags"]["serve_prob"])
        elif role == "forehand":
            role_score = float(candidate["semantic_tags"]["forehand_prob"])
        elif role == "backhand":
            role_score = float(candidate["semantic_tags"]["backhand_prob"])
        elif role == "highlight":
            role_score = float(candidate["semantic_tags"]["value_roles"]["highlight"])
        elif role == "problem-example":
            role_score = float(candidate["semantic_tags"]["value_roles"]["problem-example"])
        else:
            role_score = 0.0
        total_score = role_score + 0.2 * float(candidate["selection_score"])
        if total_score > best_score:
            best_score = total_score
            best = candidate
    return best


def add_to_review_queue(candidate: dict[str, Any], review_queue: list[dict[str, Any]], review_ids: set[str]) -> None:
    selection_id = candidate["selection_id"]
    if selection_id in review_ids:
        return
    review_queue.append(candidate)
    review_ids.add(selection_id)


def has_role(candidate: dict[str, Any], role: str) -> bool:
    tags = candidate["semantic_tags"]
    if role == "serve":
        return float(tags["serve_prob"]) >= DEFAULTS["serve_slot_threshold"]
    if role == "forehand":
        return float(tags["forehand_prob"]) >= DEFAULTS["slot_threshold"]
    if role == "backhand":
        return float(tags["backhand_prob"]) >= DEFAULTS["slot_threshold"]
    return False


def is_transit_motion_risk(candidate: dict[str, Any]) -> bool:
    return "transit-motion-risk" in candidate.get("quality_flags", [])


def is_in_play_candidate(candidate: dict[str, Any]) -> bool:
    tags = candidate["semantic_tags"]
    if is_transit_motion_risk(candidate):
        return False
    if float(tags.get("in_play_confidence", 0.0)) >= 0.5:
        return True
    return max(
        float(tags.get("forehand_prob", 0.0)),
        float(tags.get("backhand_prob", 0.0)),
        float(tags.get("serve_prob", 0.0)),
    ) >= 0.5


def dedupe_selected_candidates(selected: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    for candidate in sorted(selected, key=lambda item: float(item["selection_score"]), reverse=True):
        duplicated = False
        candidate_window = candidate_overlap_window(candidate)
        for prev in deduped:
            if candidate["clip_id"] != prev["clip_id"]:
                continue
            prev_window = candidate_overlap_window(prev)
            overlap = overlap_duration(
                candidate_window["source_clip_offset_start"],
                candidate_window["source_clip_offset_end"],
                prev_window["source_clip_offset_start"],
                prev_window["source_clip_offset_end"],
            )
            candidate_duration = (
                candidate_window["source_clip_offset_end"]
                - candidate_window["source_clip_offset_start"]
            )
            prev_duration = (
                prev_window["source_clip_offset_end"] - prev_window["source_clip_offset_start"]
            )
            denom = min(candidate_duration, prev_duration)
            if denom > 0 and overlap / denom >= 0.72:
                duplicated = True
                break
        if not duplicated:
            deduped.append(candidate)
    return deduped


def parse_simple_toml(path: pathlib.Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    current_section = ""
    config: dict[str, Any] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current_section = line[1:-1].strip()
            continue
        if "=" not in line or not current_section:
            continue
        key, raw_value = [part.strip() for part in line.split("=", 1)]
        if raw_value.startswith('"') and raw_value.endswith('"'):
            value: Any = raw_value[1:-1]
        elif raw_value.lower() in {"true", "false"}:
            value = raw_value.lower() == "true"
        else:
            try:
                value = int(raw_value)
            except ValueError:
                try:
                    value = float(raw_value)
                except ValueError:
                    value = raw_value
        config[f"{current_section}.{key}"] = value
    return config


def apply_config_defaults(args: argparse.Namespace) -> None:
    config = parse_simple_toml(pathlib.Path(args.config).expanduser())
    explicit_flags = set(sys.argv[1:])
    mapping = {
        "selection.candidate_pool_size": ("candidate_pool_size", DEFAULTS["candidate_pool_size"]),
        "selection.selected_size": ("selected_size", DEFAULTS["selected_size"]),
        "selection.frames_per_candidate": ("frames_per_candidate", DEFAULTS["frames_per_candidate"]),
        "selection.local_vlm.provider": ("local_vlm_provider", DEFAULTS["local_vlm_provider"]),
        "selection.local_vlm.endpoint": ("local_vlm_endpoint", DEFAULTS["local_vlm_endpoint"]),
        "selection.local_vlm.model": ("local_vlm_model", DEFAULTS["local_vlm_model"]),
        "selection.local_vlm.fallback_model": ("local_vlm_fallback_model", DEFAULTS["local_vlm_fallback_model"]),
        "selection.local_vlm.timeout_seconds": ("local_vlm_timeout_seconds", DEFAULTS["local_vlm_timeout_seconds"]),
        "selection.local_vlm.max_retries": ("local_vlm_max_retries", DEFAULTS["local_vlm_max_retries"]),
        "selection.local_vlm.temperature": ("local_vlm_temperature", DEFAULTS["local_vlm_temperature"]),
    }
    for config_key, (arg_name, default_value) in mapping.items():
        if config_key not in config:
            continue
        flag_name = f"--{arg_name.replace('_', '-')}"
        if flag_name in explicit_flags:
            continue
        if getattr(args, arg_name) != default_value:
            continue
        setattr(args, arg_name, config[config_key])


def to_time_window(clip: dict[str, Any], start_offset: float, end_offset: float) -> dict[str, Any]:
    return {
        "source_clip_offset_start": round(start_offset, 3),
        "source_clip_offset_end": round(end_offset, 3),
        "absolute_start_time": round(float(clip["start_time"]) + start_offset, 3),
        "absolute_end_time": round(float(clip["start_time"]) + end_offset, 3),
        "absolute_timebase": "source_video_timeline",
    }


def candidate_kind_from_window_kind(window_kind: str) -> str:
    lower = window_kind.lower()
    if "opening" in lower:
        return "opening_probe"
    if "wide" in lower:
        return "rally_wide"
    if "recovery" in lower:
        return "recovery_probe"
    return "motion_dense"


def build_cv_candidate_pool(raw_candidates: list[dict[str, Any]], *, candidate_pool_size: int) -> list[dict[str, Any]]:
    remaining = sorted(raw_candidates, key=lambda item: float(item["window_value_score"]), reverse=True)
    selected: list[dict[str, Any]] = []
    per_clip_count: dict[str, int] = {}
    seen_kinds: set[str] = set()

    while remaining and len(selected) < candidate_pool_size:
        best_index = -1
        best_score = -999.0
        for index, candidate in enumerate(remaining):
            clip_id = str(candidate["clip_id"])
            if per_clip_count.get(clip_id, 0) >= 2:
                continue
            overlap_pen = 0.0
            for prev in selected:
                if prev["clip_id"] != clip_id:
                    continue
                overlap = overlap_duration(
                    candidate["focus_window"]["source_clip_offset_start"],
                    candidate["focus_window"]["source_clip_offset_end"],
                    prev["focus_window"]["source_clip_offset_start"],
                    prev["focus_window"]["source_clip_offset_end"],
                )
                duration = max(
                    0.001,
                    candidate["focus_window"]["source_clip_offset_end"]
                    - candidate["focus_window"]["source_clip_offset_start"],
                )
                overlap_pen = max(overlap_pen, overlap / duration)
            kind = candidate_kind_from_window_kind(candidate.get("window_kind", "motion_dense"))
            diversity_bonus = 0.08 if kind not in seen_kinds else 0.0
            score = float(candidate["window_value_score"]) + diversity_bonus - 0.35 * overlap_pen
            if score > best_score:
                best_score = score
                best_index = index
        if best_index < 0:
            break
        chosen = remaining.pop(best_index)
        selected.append(chosen)
        per_clip_count[chosen["clip_id"]] = per_clip_count.get(chosen["clip_id"], 0) + 1
        seen_kinds.add(candidate_kind_from_window_kind(chosen.get("window_kind", "motion_dense")))

    pool: list[dict[str, Any]] = []
    for index, candidate in enumerate(selected, start=1):
        clip = {
            "clip_id": candidate["clip_id"],
            "source_video_id": candidate["source_video_id"],
            "start_time": candidate["clip_start_time"],
        }
        candidate_id = f"{candidate['clip_id']}-candidate-{index:02d}"
        focus_window = candidate["focus_window"]
        export_window = candidate.get("selected_clip_window", focus_window)
        cv_evidence = {
            "window_duration": float(candidate["window_metrics"]["window_duration"]),
            "effective_motion_ratio": float(candidate["window_metrics"]["effective_play_ratio"]),
            "dead_time_ratio": float(candidate["window_metrics"]["dead_time_ratio"]),
            "peak_motion_score": float(candidate["window_metrics"]["peak_motion"]),
            "avg_motion_score": float(candidate["window_metrics"]["avg_score"]),
            "motion_span_x": float(candidate["window_metrics"]["centroid_summary"]["x_span"]),
            "motion_path_length": float(candidate["window_metrics"]["centroid_summary"]["path_length"]),
            "audio_interval_overlap": float(candidate["window_metrics"]["effective_play_ratio"]),
            "quality_flags": list(candidate.get("quality_flags", [])),
            "boundary_flags": [flag for flag in candidate.get("quality_flags", []) if "unresolved" in flag],
        }
        dedupe_key = hashlib.sha1(
            (
                f"{candidate['clip_id']}|{focus_window['source_clip_offset_start']:.3f}|"
                f"{focus_window['source_clip_offset_end']:.3f}|{candidate_kind_from_window_kind(candidate.get('window_kind', ''))}"
            ).encode("utf-8")
        ).hexdigest()[:16]
        pool.append(
            {
                "candidate_id": candidate_id,
                "clip_id": candidate["clip_id"],
                "source_video_id": candidate["source_video_id"],
                "source_clip_path": candidate["source_clip_path"],
                "candidate_kind": candidate_kind_from_window_kind(candidate.get("window_kind", "motion_dense")),
                "candidate_window": to_time_window(
                    clip,
                    float(focus_window["source_clip_offset_start"]),
                    float(focus_window["source_clip_offset_end"]),
                ),
                "export_window_proposal": to_time_window(
                    clip,
                    float(export_window["source_clip_offset_start"]),
                    float(export_window["source_clip_offset_end"]),
                ),
                "cv_evidence": cv_evidence,
                "cv_risk_flags": list(candidate.get("quality_flags", [])),
                "dedupe_key": dedupe_key,
                "source_clip_probe": candidate.get("source_clip_probe", {}),
                "cv_pre_score": round(float(candidate.get("window_value_score", 0.0)), 3),
            }
        )
    return pool


def export_window_video(
    *,
    source_clip_path: pathlib.Path,
    window: dict[str, Any],
    output_path: pathlib.Path,
) -> None:
    start_offset = float(window["source_clip_offset_start"])
    end_offset = float(window["source_clip_offset_end"])
    duration = max(0.001, end_offset - start_offset)
    run_command(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-hide_banner",
            "-ss",
            f"{start_offset:.3f}",
            "-i",
            str(source_clip_path),
            "-t",
            f"{duration:.3f}",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "18",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            str(output_path),
        ]
    )


def extract_candidate_frames(candidate_video_path: pathlib.Path, frames_dir: pathlib.Path, frame_count: int) -> list[str]:
    probe = ffprobe_json(candidate_video_path)
    duration = float(probe.get("format", {}).get("duration") or 0.0)
    max_time = max(0.0, duration - 0.001)
    base_positions = [0.0, 0.5, 1.0]
    if frame_count > 3:
        base_positions.extend(index / (frame_count - 1) for index in range(frame_count))
    positions = []
    seen = set()
    for value in base_positions:
        key = round(value, 4)
        if key in seen:
            continue
        seen.add(key)
        positions.append(value)
    timestamps = [round(clamp(value, 0.0, 1.0) * max_time, 3) for value in positions[:frame_count]]
    while len(timestamps) < frame_count:
        timestamps.append(round(max_time, 3))

    frames_dir.mkdir(parents=True, exist_ok=True)
    output_paths: list[str] = []
    for index, ts in enumerate(timestamps):
        frame_path = frames_dir / f"{index:03d}.jpg"
        attempts = [ts, max(0.0, ts - 0.25), max(0.0, ts - 0.75), 0.0]
        generated = False
        last_error = ""
        for attempt_ts in attempts:
            command = [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-hide_banner",
                "-ss",
                f"{attempt_ts:.3f}",
                "-i",
                str(candidate_video_path),
                "-frames:v",
                "1",
                "-vf",
                "scale='if(gt(iw,ih),min(iw,768),-2)':'if(gt(ih,iw),min(ih,768),-2)'",
                "-q:v",
                "2",
                "-strict",
                "-1",
                str(frame_path),
            ]
            try:
                run_command(command)
            except RuntimeError as exc:
                last_error = str(exc)
                continue
            if frame_path.exists() and frame_path.stat().st_size > 0:
                generated = True
                break
        if not generated:
            raise RuntimeError(f"failed to extract frame {index} for {candidate_video_path}: {last_error[:200]}")
        output_paths.append(str(frame_path))
    return output_paths


def build_model_input_packages(
    cv_candidate_pool: list[dict[str, Any]],
    output_dir: pathlib.Path,
    *,
    frames_per_candidate: int,
) -> list[dict[str, Any]]:
    model_inputs_dir = output_dir / "model_inputs"
    model_inputs_dir.mkdir(parents=True, exist_ok=True)
    packages: list[dict[str, Any]] = []
    for candidate in cv_candidate_pool:
        candidate_id = str(candidate["candidate_id"])
        input_dir = model_inputs_dir / candidate_id
        frames_dir = input_dir / "frames"
        input_dir.mkdir(parents=True, exist_ok=True)
        candidate_video_path = input_dir / "candidate.mp4"
        prompt_path = input_dir / "prompt.txt"
        input_json_path = input_dir / "input.json"

        export_window_video(
            source_clip_path=pathlib.Path(candidate["source_clip_path"]),
            window=candidate["export_window_proposal"],
            output_path=candidate_video_path,
        )
        frame_paths = extract_candidate_frames(candidate_video_path, frames_dir, max(1, min(12, frames_per_candidate)))
        prompt_path.write_text(MODEL_PROMPT_TEMPLATE, encoding="utf-8")

        input_payload = {
            "schema_version": "model_judgement.v1",
            "candidate_id": candidate_id,
            "candidate_window": candidate["candidate_window"],
            "export_window_proposal": candidate["export_window_proposal"],
            "cv_evidence": candidate["cv_evidence"],
            "cv_risk_flags": candidate["cv_risk_flags"],
            "frame_paths": frame_paths,
        }
        input_hash = hashlib.sha1(json.dumps(input_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
        input_payload["input_hash"] = input_hash
        input_json_path.write_text(json.dumps(input_payload, ensure_ascii=False, indent=2), encoding="utf-8")

        package = {
            "candidate_id": candidate_id,
            "input_dir": str(input_dir),
            "frames_dir": str(frames_dir),
            "frame_paths": frame_paths,
            "frame_count": len(frame_paths),
            "candidate_video_path": str(candidate_video_path),
            "prompt_path": str(prompt_path),
            "input_json_path": str(input_json_path),
            "schema_version": "model_judgement.v1",
            "input_hash": input_hash,
        }
        packages.append(package)
    return packages


def parse_json_maybe_wrapped(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3:
            text = "\n".join(lines[1:-1]).strip()
    return json.loads(text)


def validate_model_judgement(payload: dict[str, Any], *, candidate_id: str) -> dict[str, Any]:
    required = MODEL_JUDGEMENT_SCHEMA["required"]
    for key in required:
        if key not in payload:
            raise ValueError(f"missing field: {key}")
    if payload["schema_version"] != "model_judgement.v1":
        raise ValueError("schema_version must be model_judgement.v1")
    if payload["candidate_id"] != candidate_id:
        raise ValueError("candidate_id mismatch")
    enum_fields = {
        "in_play": {"yes", "no", "uncertain"},
        "non_play_type": {"none", "picking_ball", "resting", "walking", "waiting", "camera_noise", "uncertain"},
        "rally_completeness": {"complete", "partial_start_missing", "partial_end_missing", "multi_rally", "uncertain"},
    }
    for field, allowed in enum_fields.items():
        if payload[field] not in allowed:
            raise ValueError(f"{field} out of enum")
    array_enums = {
        "action_tags": {"forehand", "backhand", "serve"},
        "context_tags": {"baseline", "midcourt", "running", "stationary"},
        "value_tags": {"highlight", "good_example", "problem_example"},
    }
    normalized = dict(payload)
    for field, allowed in array_enums.items():
        values = [str(item) for item in payload[field]]
        if any(value not in allowed for value in values):
            raise ValueError(f"{field} out of enum")
        normalized[field] = sorted(set(values))
    normalized["reject_reasons"] = [str(item) for item in payload["reject_reasons"]]
    normalized["selection_reason"] = str(payload["selection_reason"])[:300]
    confidence = float(payload["confidence"])
    if confidence < 0.0 or confidence > 1.0:
        raise ValueError("confidence out of range")
    normalized["confidence"] = round(confidence, 3)
    if normalized["in_play"] == "yes" and normalized["non_play_type"] not in {"none", "uncertain"}:
        normalized["non_play_type"] = "uncertain"
    if normalized["in_play"] == "no":
        normalized["value_tags"] = []
    return normalized


def call_ollama_chat(
    *,
    endpoint: str,
    model: str,
    prompt: str,
    image_paths: list[str],
    candidate_payload: dict[str, Any],
    timeout_seconds: int,
    temperature: float,
) -> tuple[str, str]:
    images_base64 = [base64.b64encode(pathlib.Path(path).read_bytes()).decode("ascii") for path in image_paths]
    prompt_payload = {
        key: value
        for key, value in candidate_payload.items()
        if key not in {"frame_paths", "input_hash"}
    }
    user_prompt = (
        f"{prompt}\n\n候选元数据与 CV 证据：\n"
        f"{json.dumps(prompt_payload, ensure_ascii=False)}\n\n"
        "请返回严格 JSON。"
    )
    payload = {
        "model": model,
        "stream": False,
        "format": "json",
        "options": {"temperature": float(temperature), "num_predict": 220},
        "messages": [{"role": "user", "content": user_prompt, "images": images_base64}],
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(endpoint, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            raw_body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"http_error:{exc.code}:{detail[:400]}")
    except Exception as exc:
        raise RuntimeError(f"request_error:{exc}")
    response = json.loads(raw_body)
    content = response.get("message", {}).get("content", "")
    if not content:
        raise RuntimeError("empty_model_content")
    return content, raw_body


def run_model_judgements(
    model_input_packages: list[dict[str, Any]],
    *,
    endpoint: str,
    primary_model: str,
    fallback_model: str,
    timeout_seconds: int,
    max_retries: int,
    temperature: float,
) -> tuple[list[dict[str, Any]], bool, bool, str | None]:
    judgements: list[dict[str, Any]] = []
    any_success = False
    used_fallback = False
    last_global_error: str | None = None
    models = [primary_model]
    if fallback_model and fallback_model != primary_model:
        models.append(fallback_model)
    pending_rows = ensure_ollama_idle()
    if pending_rows:
        return [], False, False, f"ollama_not_idle:{'; '.join(row['name'] for row in pending_rows)}"
    try:
        for package in model_input_packages:
            candidate_id = str(package["candidate_id"])
            candidate_payload = json.loads(pathlib.Path(package["input_json_path"]).read_text(encoding="utf-8"))
            prompt = pathlib.Path(package["prompt_path"]).read_text(encoding="utf-8")
            success = False
            last_error = ""
            transport_error = False
            response_path = pathlib.Path(package["input_dir"]) / "model_response.json"
            judgement_path = pathlib.Path(package["input_dir"]) / "judgement.json"

            for model_name in models:
                for _ in range(max(1, max_retries + 1)):
                    try:
                        raw_content, raw_response = call_ollama_chat(
                            endpoint=endpoint,
                            model=model_name,
                            prompt=prompt,
                            image_paths=list(package["frame_paths"]),
                            candidate_payload=candidate_payload,
                            timeout_seconds=timeout_seconds,
                            temperature=temperature,
                        )
                        response_path.write_text(raw_response, encoding="utf-8")
                        raw_judgement = parse_json_maybe_wrapped(raw_content)
                        judgement = validate_model_judgement(raw_judgement, candidate_id=candidate_id)
                        judgement["model_name"] = model_name
                        judgement_path.write_text(json.dumps(judgement, ensure_ascii=False, indent=2), encoding="utf-8")
                        judgements.append(judgement)
                        any_success = True
                        if model_name == fallback_model and model_name != primary_model:
                            used_fallback = True
                        success = True
                        break
                    except RuntimeError as exc:
                        last_error = str(exc)
                        last_global_error = last_error
                        transport_error = True
                    except (json.JSONDecodeError, ValueError) as exc:
                        last_error = str(exc)
                        last_global_error = last_error
                        transport_error = False
                        continue
                if success:
                    break
            if not success:
                if transport_error and not any_success:
                    return [], any_success, used_fallback, last_error
                fallback = {
                    "schema_version": "model_judgement.v1",
                    "candidate_id": candidate_id,
                    "in_play": "uncertain",
                    "non_play_type": "uncertain",
                    "rally_completeness": "uncertain",
                    "action_tags": [],
                    "context_tags": [],
                    "value_tags": [],
                    "reject_reasons": ["invalid-model-output", last_error[:160]],
                    "selection_reason": "Model output invalid after retry.",
                    "confidence": 0.0,
                    "model_name": None,
                }
                judgement_path.write_text(json.dumps(fallback, ensure_ascii=False, indent=2), encoding="utf-8")
                judgements.append(fallback)
        return judgements, any_success, used_fallback, None if any_success else last_global_error
    finally:
        for model_name in reversed(models):
            try:
                stop_ollama_model(model_name)
            except RuntimeError:
                pass


def derive_semantic_tags(judgement: dict[str, Any]) -> dict[str, Any]:
    return {
        "in_play": judgement["in_play"],
        "non_play_type": judgement["non_play_type"],
        "rally_completeness": judgement["rally_completeness"],
        "action_tags": list(judgement["action_tags"]),
        "context_tags": list(judgement["context_tags"]),
        "value_tags": list(judgement["value_tags"]),
        "model_confidence": float(judgement["confidence"]),
    }


def candidate_main_tag(semantic_tags: dict[str, Any]) -> str:
    for key in ("value_tags", "action_tags", "context_tags"):
        values = semantic_tags.get(key) or []
        if values:
            return str(values[0])
    return "unknown"


def candidate_is_hard_filtered(judgement: dict[str, Any]) -> bool:
    confidence = float(judgement["confidence"])
    if judgement["in_play"] == "no":
        return True
    if judgement["in_play"] == "no" and confidence >= 0.7:
        return True
    if judgement["non_play_type"] != "none" and judgement["non_play_type"] != "uncertain" and confidence >= 0.7:
        return True
    return False


def coverage_roles_from_semantics(semantic_tags: dict[str, Any]) -> list[str]:
    roles = set()
    roles.update(semantic_tags["action_tags"])
    roles.update(semantic_tags["context_tags"])
    roles.update(semantic_tags["value_tags"])
    return sorted(roles)


def compute_selection_score(
    *,
    candidate: dict[str, Any],
    judgement: dict[str, Any],
    selected: list[dict[str, Any]],
    missing_hard: set[str],
    missing_soft: set[str],
) -> float:
    semantic_tags = derive_semantic_tags(judgement)
    model_value_score = 1.0 if semantic_tags["value_tags"] else 0.4
    in_play_score = {"yes": 1.0, "uncertain": 0.5, "no": 0.0}[semantic_tags["in_play"]]
    completeness_score = {
        "complete": 1.0,
        "multi_rally": 0.55,
        "partial_start_missing": 0.35,
        "partial_end_missing": 0.35,
        "uncertain": 0.45,
    }[semantic_tags["rally_completeness"]]
    candidate_roles = set(coverage_roles_from_semantics(semantic_tags))
    if candidate_roles & missing_hard:
        coverage_bonus = 1.0
    elif candidate_roles & missing_soft:
        coverage_bonus = 0.6
    else:
        coverage_bonus = 0.0

    diversity_bonus = 0.0
    if not selected:
        diversity_bonus = 1.0
    else:
        distinct_clip = all(item["clip_id"] != candidate["clip_id"] for item in selected)
        current_main_tag = candidate_main_tag(semantic_tags)
        distinct_tag = all(candidate_main_tag(item["semantic_tags"]) != current_main_tag for item in selected)
        if distinct_clip and distinct_tag:
            diversity_bonus = 1.0
        elif distinct_clip or distinct_tag:
            diversity_bonus = 0.4

    risk_penalty = 0.0
    high_risk_flags = {
        "transit-motion-risk",
        "multi-rally-risk",
        "rally-start-unresolved",
        "rally-end-unresolved",
        "whole-clip-window-risk",
        "near-black",
        "soft",
    }
    if any(flag in high_risk_flags for flag in candidate["cv_risk_flags"]):
        risk_penalty += 0.25
    if float(judgement["confidence"]) < 0.7:
        risk_penalty += 0.15

    score = (
        0.35 * model_value_score
        + 0.25 * in_play_score
        + 0.15 * completeness_score
        + 0.15 * coverage_bonus
        + 0.10 * diversity_bonus
        - risk_penalty
    )
    score += 0.05 * float(candidate.get("cv_pre_score", 0.0))
    return round(clamp(score, 0.0, 1.0), 3)


def clip_overlap_ratio(a: dict[str, Any], b: dict[str, Any]) -> float:
    if a["clip_id"] != b["clip_id"]:
        return 0.0
    a_window = a["candidate_window"]
    b_window = b["candidate_window"]
    overlap = overlap_duration(
        float(a_window["source_clip_offset_start"]),
        float(a_window["source_clip_offset_end"]),
        float(b_window["source_clip_offset_start"]),
        float(b_window["source_clip_offset_end"]),
    )
    a_duration = max(0.001, float(a_window["source_clip_offset_end"]) - float(a_window["source_clip_offset_start"]))
    b_duration = max(0.001, float(b_window["source_clip_offset_end"]) - float(b_window["source_clip_offset_start"]))
    return overlap / min(a_duration, b_duration)


def select_with_coverage(
    cv_candidate_pool: list[dict[str, Any]],
    model_judgements: list[dict[str, Any]],
    *,
    selected_size: int,
    serve_presence_mode: str,
) -> dict[str, Any]:
    judgement_by_candidate = {item["candidate_id"]: item for item in model_judgements}
    records: list[dict[str, Any]] = []
    review_queue: list[dict[str, Any]] = []
    infeasible_reasons: list[str] = []
    coverage_gap: list[str] = []

    for candidate in cv_candidate_pool:
        judgement = judgement_by_candidate.get(candidate["candidate_id"])
        if not judgement:
            continue
        semantic_tags = derive_semantic_tags(judgement)
        needs_review = (
            judgement["in_play"] == "uncertain"
            or judgement["rally_completeness"] in {"partial_start_missing", "partial_end_missing", "multi_rally", "uncertain"}
            or float(judgement["confidence"]) < 0.7
            or bool(judgement["reject_reasons"])
        )
        record = {
            "candidate_id": candidate["candidate_id"],
            "clip_id": candidate["clip_id"],
            "source_video_id": candidate["source_video_id"],
            "source_clip_path": candidate["source_clip_path"],
            "candidate_window": candidate["candidate_window"],
            "focus_window": candidate["candidate_window"],
            "export_window": candidate["export_window_proposal"],
            "cv_evidence": candidate["cv_evidence"],
            "cv_risk_flags": candidate["cv_risk_flags"],
            "model_judgement": judgement,
            "semantic_tags": semantic_tags,
            "coverage_roles": coverage_roles_from_semantics(semantic_tags),
            "selection_reasons": [judgement["selection_reason"], f"candidate_kind:{candidate['candidate_kind']}"],
            "selection_score": 0.0,
            "confidence": float(judgement["confidence"]),
            "needs_review": needs_review,
        }
        records.append(record)
        if needs_review:
            review_queue.append(record)

    serve_candidates = [
        item for item in records if "serve" in item["semantic_tags"]["action_tags"] and item["model_judgement"]["in_play"] != "no"
    ]
    serve_likely = any(float(item["confidence"]) >= 0.7 for item in serve_candidates)
    if serve_presence_mode == "present":
        serve_presence_status = "user-confirmed-present"
        require_serve = True
    elif serve_presence_mode == "absent":
        serve_presence_status = "user-confirmed-absent"
        require_serve = False
    elif serve_likely:
        serve_presence_status = "model-likely-present"
        require_serve = True
    elif serve_candidates:
        serve_presence_status = "uncertain"
        require_serve = False
        coverage_gap.append("serve-presence-uncertain")
    else:
        serve_presence_status = "model-likely-absent"
        require_serve = False

    hard_roles = {"forehand", "backhand"}
    if require_serve:
        hard_roles.add("serve")
    soft_roles = {"highlight", "problem_example", "good_example", "baseline", "midcourt", "running", "stationary"}
    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()

    def pick_best(filter_fn) -> dict[str, Any] | None:
        best = None
        best_score = -1.0
        missing_hard = {role for role in hard_roles if role not in {r for item in selected for r in item["coverage_roles"]}}
        missing_soft = {role for role in soft_roles if role not in {r for item in selected for r in item["coverage_roles"]}}
        for item in records:
            if item["candidate_id"] in selected_ids:
                continue
            if candidate_is_hard_filtered(item["model_judgement"]):
                continue
            if not filter_fn(item):
                continue
            score = compute_selection_score(
                candidate=next(c for c in cv_candidate_pool if c["candidate_id"] == item["candidate_id"]),
                judgement=item["model_judgement"],
                selected=selected,
                missing_hard=missing_hard,
                missing_soft=missing_soft,
            )
            overlap_penalty = max((clip_overlap_ratio(item, prev) for prev in selected), default=0.0)
            score = score - 0.4 * overlap_penalty
            if score > best_score:
                best_score = score
                best = dict(item)
                best["selection_score"] = round(clamp(score, 0.0, 1.0), 3)
        return best

    for role in sorted(hard_roles):
        chosen = pick_best(lambda item, role=role: role in item["coverage_roles"])
        if chosen:
            selected.append(chosen)
            selected_ids.add(chosen["candidate_id"])
        else:
            coverage_gap.append(role)
            infeasible_reasons.append(f"missing-required-role:{role}")

    for role in ("highlight", "problem_example", "good_example"):
        if len(selected) >= selected_size:
            break
        chosen = pick_best(lambda item, role=role: role in item["coverage_roles"])
        if chosen:
            selected.append(chosen)
            selected_ids.add(chosen["candidate_id"])

    while len(selected) < selected_size:
        chosen = pick_best(lambda item: True)
        if not chosen:
            break
        selected.append(chosen)
        selected_ids.add(chosen["candidate_id"])

    selected_deduped: list[dict[str, Any]] = []
    for item in sorted(selected, key=lambda row: float(row["selection_score"]), reverse=True):
        if any(clip_overlap_ratio(item, prev) >= 0.72 for prev in selected_deduped):
            continue
        selected_deduped.append(item)
    selected = selected_deduped[:selected_size]
    if len(selected) < min(selected_size, len(records)):
        infeasible_reasons.append("unable-to-fill-selected-size-after-constraints")

    required_roles_covered = {role: any(role in item["coverage_roles"] for item in selected) for role in ("forehand", "backhand", "serve")}
    missing_hard_roles = [role for role, covered in required_roles_covered.items() if role in hard_roles and not covered]
    coverage_gap.extend(missing_hard_roles)
    if missing_hard_roles:
        infeasible_reasons.extend([f"missing-required-role:{role}" for role in missing_hard_roles])

    selection_status = "ready"
    if missing_hard_roles or len(selected) < max(1, min(selected_size, len(records))):
        selection_status = "constrained_incomplete"

    selected_with_ids: list[dict[str, Any]] = []
    for index, item in enumerate(selected, start=1):
        row = dict(item)
        row["selection_id"] = f"selection-{index:02d}-{row['candidate_id']}"
        row["selected_clip_window"] = row["export_window"]
        selected_with_ids.append(row)

    review_rows: list[dict[str, Any]] = []
    for row in review_queue:
        if row["candidate_id"] in {item["candidate_id"] for item in selected_with_ids}:
            continue
        review_rows.append(row)
        if len(review_rows) >= 6:
            break

    selected_summary = {
        "required_roles": required_roles_covered,
        "soft_roles": {role: any(role in item["coverage_roles"] for item in selected_with_ids) for role in soft_roles},
        "selected_count": len(selected_with_ids),
    }
    coverage_report = {
        "required_roles": {"forehand": True, "backhand": True, "serve": require_serve},
        "soft_roles": sorted(soft_roles),
        "coverage_gap": sorted(set(coverage_gap)),
        "serve_presence_status": serve_presence_status,
        "selected_summary": selected_summary,
    }
    return {
        "selected_clips": selected_with_ids,
        "review_queue": review_rows,
        "selection_status": selection_status,
        "coverage_report": coverage_report,
        "infeasible_reasons": sorted(set(infeasible_reasons)),
    }


def export_selected_clips(
    selected: list[dict[str, Any]],
    export_dir: pathlib.Path,
    *,
    selection_run_id: str,
) -> list[dict[str, Any]]:
    if export_dir.exists():
        shutil.rmtree(export_dir)
    export_dir.mkdir(parents=True, exist_ok=True)
    exports: list[dict[str, Any]] = []
    for index, candidate in enumerate(selected, start=1):
        source_path = pathlib.Path(candidate["source_clip_path"])
        if not source_path.exists():
            continue
        export_path = export_dir / f"{index:02d}-{candidate['selection_id']}.mp4"
        export_window_video(source_clip_path=source_path, window=candidate["export_window"], output_path=export_path)
        candidate["exported_clip_path"] = str(export_path)
        exports.append(
            {
                "selection_id": candidate["selection_id"],
                "candidate_id": candidate["candidate_id"],
                "export_path": str(export_path),
                "source_clip_path": str(source_path),
                "start_offset": candidate["export_window"]["source_clip_offset_start"],
                "end_offset": candidate["export_window"]["source_clip_offset_end"],
                "duration": round(
                    float(candidate["export_window"]["source_clip_offset_end"])
                    - float(candidate["export_window"]["source_clip_offset_start"]),
                    3,
                ),
            }
        )
    manifest = {
        "selection_run_id": selection_run_id,
        "exported_at_epoch": round(time.time(), 3),
        "selected_count": len(exports),
        "exports": exports,
    }
    (export_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return exports


def main() -> None:
    args = parse_args()
    apply_config_defaults(args)
    run_dir = resolve_run_dir(args.run_dir)
    manifest_path = run_dir / "manifest.json"
    point_dir = run_dir / "point_clips"
    if not manifest_path.exists():
        raise SystemExit(f"Missing manifest.json under {run_dir}")
    if not point_dir.exists():
        raise SystemExit(f"Missing point_clips/ under {run_dir}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    point_clips = [clip for clip in manifest.get("point_clips", []) if pathlib.Path(clip.get("export_path", "")).exists()]
    point_clips = [
        clip
        for clip in point_clips
        if clip.get("boundary_evidence", {}).get("boundary_status", "confirmed") == "confirmed"
    ]
    selection_run_id = args.selection_run_id or time.strftime("%Y%m%d-%H%M%S")
    output_dir = pathlib.Path(args.output_dir).resolve() if args.output_dir else run_dir / "selection_runs" / selection_run_id
    selected_clips_dir = (
        pathlib.Path(args.selected_clips_dir).resolve()
        if args.selected_clips_dir
        else run_dir / "selected_clips"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    started_at = time.time()

    if not point_clips:
        package = {
            "selection_version": "v1.0.1-implementation-ready-local-vlm-rerank",
            "source_segmentation_run": {
                "run_dir": str(run_dir),
                "manifest_path": str(manifest_path),
                "input": manifest.get("input"),
                "source_video_id": None,
                "point_clip_count": 0,
            },
            "selection_run_id": selection_run_id,
            "params": {"candidate_pool_size": args.candidate_pool_size, "selected_size": args.selected_size},
            "cv_candidate_pool": [],
            "candidate_pool": [],
            "model_input_packages": [],
            "model_judgements": [],
            "selected_clips": [],
            "coverage_report": {
                "required_roles": {"forehand": True, "backhand": True, "serve": False},
                "soft_roles": [],
                "coverage_gap": ["empty-point-clips"],
                "serve_presence_status": "uncertain",
                "selected_summary": {"required_roles": {}, "soft_roles": {}, "selected_count": 0},
            },
            "review_queue": [],
            "selection_status": "no_candidates",
            "infeasible_reasons": ["empty-point-clips"],
            "selected_clip_exports_dir": None,
            "selected_clip_exports": [],
            "selected_clips_result_role": "trial",
            "promoted_selected_clips": False,
            "selection_notes": {},
        }
        output_path = output_dir / "selection-package.json"
        output_path.write_text(json.dumps(to_jsonable(package), ensure_ascii=False, indent=2), encoding="utf-8")
        print(str(output_path))
        return

    raw_candidates: list[dict[str, Any]] = []
    clip_debug: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="selection-") as temp_root:
        temp_root_path = pathlib.Path(temp_root)
        for clip in point_clips:
            video_path = pathlib.Path(clip["export_path"])
            probe = ffprobe_json(video_path)
            motion_analysis = extract_motion_features(video_path, temp_root_path, fps=args.analysis_fps, scale=args.analysis_scale)
            generated = generate_candidates_for_clip(clip, motion_analysis, handedness=args.handedness)
            streams = probe.get("streams", [])
            video_stream = next((stream for stream in streams if stream.get("codec_type") == "video"), {})
            for candidate in generated:
                candidate["source_clip_probe"] = {
                    "codec_name": video_stream.get("codec_name"),
                    "width": video_stream.get("width"),
                    "height": video_stream.get("height"),
                    "bit_rate": video_stream.get("bit_rate") or probe.get("format", {}).get("bit_rate"),
                }
            raw_candidates.extend(generated)
            clip_debug.append(
                {
                    "clip_id": clip["clip_id"],
                    "clip_duration": clip["duration"],
                    "source_interval_count": len(relative_source_intervals(clip)),
                    "motion_window_count": len(motion_analysis["windows"]),
                    "generated_candidates": len(generated),
                    "quality": motion_analysis["quality"],
                }
            )

    candidate_pool_size = max(1, int(args.candidate_pool_size))
    frames_per_candidate = max(1, min(12, int(args.frames_per_candidate)))
    cv_candidate_pool = build_cv_candidate_pool(raw_candidates, candidate_pool_size=candidate_pool_size)
    model_input_packages = build_model_input_packages(
        cv_candidate_pool,
        output_dir,
        frames_per_candidate=frames_per_candidate,
    )

    lock_root = run_dir.parents[2] if len(run_dir.parents) >= 3 else run_dir
    lock_path = lock_root / ".local_vlm.lock"
    with local_vlm_lock(lock_path):
        model_judgements, model_any_success, used_fallback, model_error = run_model_judgements(
            model_input_packages,
            endpoint=str(args.local_vlm_endpoint),
            primary_model=str(args.local_vlm_model),
            fallback_model=str(args.local_vlm_fallback_model),
            timeout_seconds=int(args.local_vlm_timeout_seconds),
            max_retries=int(args.local_vlm_max_retries),
            temperature=float(args.local_vlm_temperature),
        )

    selected_clip_exports: list[dict[str, Any]] = []
    if not model_any_success and model_error:
        selection_result = {
            "selected_clips": [],
            "review_queue": [],
            "coverage_report": {
                "required_roles": {"forehand": True, "backhand": True, "serve": False},
                "soft_roles": [],
                "coverage_gap": ["model-unavailable"],
                "serve_presence_status": "uncertain",
                "selected_summary": {"required_roles": {}, "soft_roles": {}, "selected_count": 0},
            },
            "selection_status": "model_unavailable",
            "infeasible_reasons": ["model-unavailable", model_error[:160]],
        }
    else:
        selection_result = select_with_coverage(
            cv_candidate_pool,
            model_judgements,
            selected_size=int(args.selected_size),
            serve_presence_mode=str(args.serve_presence),
        )
        if used_fallback and selection_result["selection_status"] == "ready":
            selection_result["selection_status"] = "model_degraded"
        should_promote = not args.skip_export_clips and not args.skip_promote_selected_clips
        if should_promote and selection_result["selected_clips"]:
            selected_clip_exports = export_selected_clips(
                selection_result["selected_clips"],
                selected_clips_dir,
                selection_run_id=selection_run_id,
            )

    finished_at = time.time()
    package = {
        "selection_version": "v1.0.2-local-vlm-selection-recovery",
        "source_segmentation_run": {
            "run_dir": str(run_dir),
            "manifest_path": str(manifest_path),
            "input": manifest.get("input"),
            "source_video_id": point_clips[0].get("source_video_id") if point_clips else None,
            "point_clip_count": len(point_clips),
        },
        "selection_run_id": selection_run_id,
        "params": {
            "analysis_fps": args.analysis_fps,
            "analysis_scale": args.analysis_scale,
            "candidate_pool_size": args.candidate_pool_size,
            "selected_size": args.selected_size,
            "frames_per_candidate": args.frames_per_candidate,
            "handedness": args.handedness,
            "serve_presence": args.serve_presence,
            "local_vlm": {
                "provider": args.local_vlm_provider,
                "endpoint": args.local_vlm_endpoint,
                "model": args.local_vlm_model,
                "fallback_model": args.local_vlm_fallback_model,
                "timeout_seconds": args.local_vlm_timeout_seconds,
                "max_retries": args.local_vlm_max_retries,
                "temperature": args.local_vlm_temperature,
            },
            "motion_backend": "opencv" if cv2 is not None else "numpy",
        },
        "cv_candidate_pool": cv_candidate_pool,
        "candidate_pool": cv_candidate_pool,
        "model_input_packages": model_input_packages,
        "model_judgements": model_judgements,
        "selected_clips": selection_result["selected_clips"],
        "coverage_report": selection_result["coverage_report"],
        "review_queue": selection_result["review_queue"][:6],
        "selection_status": selection_result["selection_status"],
        "infeasible_reasons": selection_result["infeasible_reasons"],
        "selected_clip_exports_dir": str(selected_clips_dir) if selected_clip_exports else None,
        "selected_clip_exports": selected_clip_exports,
        "selected_clips_result_role": "final" if selected_clip_exports else "trial",
        "promoted_selected_clips": bool(selected_clip_exports),
        "selection_notes": {
            "started_at_epoch": round(started_at, 3),
            "finished_at_epoch": round(finished_at, 3),
            "elapsed_seconds": round(finished_at - started_at, 3),
            "raw_candidate_count": len(raw_candidates),
            "cv_candidate_pool_count": len(cv_candidate_pool),
            "model_judgement_count": len(model_judgements),
            "clip_debug_summary": clip_debug,
        },
    }

    output_path = output_dir / "selection-package.json"
    output_path.write_text(json.dumps(to_jsonable(package), ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(output_path))
    print(
        json.dumps(
            {
                "selection_run_id": selection_run_id,
                "raw_candidate_count": len(raw_candidates),
                "cv_candidate_pool_count": len(cv_candidate_pool),
                "selected_count": len(package["selected_clips"]),
                "selection_status": package["selection_status"],
                "coverage_gap": package["coverage_report"]["coverage_gap"],
                "elapsed_seconds": round(finished_at - started_at, 3),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
