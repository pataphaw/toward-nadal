#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import math
import pathlib
import subprocess
import tempfile
import time
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
    "candidate_pool_size": 12,
    "selected_size": 6,
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Select a small set of analysis-ready candidates from a segmentation run."
    )
    parser.add_argument(
        "--run-dir",
        required=True,
        help="Segmentation run directory, or its point_clips/ child directory.",
    )
    parser.add_argument(
        "--output-dir",
        help="Optional output directory. Defaults to <run-dir>/selection_runs/<selection-run-id>.",
    )
    parser.add_argument(
        "--selected-clips-dir",
        help="Optional export directory for selected focus clips. Defaults to <run-dir>/selected_clips/<selection-run-id>/.",
    )
    parser.add_argument(
        "--skip-export-clips",
        action="store_true",
        help="Do not export focus-window video snippets for selected clips.",
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
    parser.add_argument("--analysis-fps", type=float, default=DEFAULTS["analysis_fps"])
    parser.add_argument("--analysis-scale", default=DEFAULTS["analysis_scale"])
    parser.add_argument(
        "--serve-presence",
        choices=("auto", "present", "absent"),
        default="auto",
        help="Override whether this source video should be treated as containing serve clips.",
    )
    parser.add_argument(
        "--ollama-model",
        help="Reserved for optional local model integration. The first usable version keeps rule-only selection.",
    )
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


def build_candidate_pool(candidates: list[dict[str, Any]], *, candidate_pool_size: int) -> list[dict[str, Any]]:
    remaining = sorted(candidates, key=lambda item: item["selection_score"], reverse=True)
    pool: list[dict[str, Any]] = []
    seen_kinds: set[str] = set()
    seen_soft_roles: set[str] = set()
    while remaining and len(pool) < candidate_pool_size:
        best_index = -1
        best_score = -999.0
        for index, candidate in enumerate(remaining):
            semantic_tags = candidate["semantic_tags"]
            bonus = 0.0
            if is_transit_motion_risk(candidate):
                bonus -= 0.22
            window_kind = candidate.get("window_kind", "dense")
            if window_kind not in seen_kinds:
                bonus += 0.08
            if semantic_tags["serve_prob"] >= 0.32 and "serve-like" not in seen_soft_roles:
                bonus += 0.09
            if semantic_tags["movement_mode"]["label"] == "stationary" and "stationary" not in seen_soft_roles:
                bonus += 0.08
            if semantic_tags["value_roles"]["problem-example"] >= 0.56 and "problem-example" not in seen_soft_roles:
                bonus += 0.07
            if semantic_tags["value_roles"]["good-example"] >= 0.68 and "good-example" not in seen_soft_roles:
                bonus += 0.04
            for role in (
                semantic_tags["court_zone"]["label"],
                semantic_tags["side_zone"]["label"],
                semantic_tags["movement_mode"]["label"],
            ):
                if role not in seen_soft_roles:
                    bonus += 0.03
            total = float(candidate["selection_score"]) + bonus
            if total > best_score:
                best_score = total
                best_index = index
        chosen = remaining.pop(best_index)
        pool.append(chosen)
        seen_kinds.add(chosen.get("window_kind", "dense"))
        seen_soft_roles.update(
            {
                chosen["semantic_tags"]["court_zone"]["label"],
                chosen["semantic_tags"]["side_zone"]["label"],
                chosen["semantic_tags"]["movement_mode"]["label"],
            }
        )
        if chosen["semantic_tags"]["serve_prob"] >= 0.32:
            seen_soft_roles.add("serve-like")
        if chosen["semantic_tags"]["value_roles"]["problem-example"] >= 0.56:
            seen_soft_roles.add("problem-example")
        if chosen["semantic_tags"]["value_roles"]["good-example"] >= 0.68:
            seen_soft_roles.add("good-example")
    return pool


def select_final_candidates(
    candidates: list[dict[str, Any]],
    *,
    selected_size: int,
    candidate_pool_size: int,
    serve_presence_mode: str,
) -> dict[str, Any]:
    candidate_pool = build_candidate_pool(candidates, candidate_pool_size=candidate_pool_size)
    selected_target_size = min(selected_size, len(candidate_pool))
    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    review_queue: list[dict[str, Any]] = []
    review_ids: set[str] = set()
    coverage_gap: list[str] = []
    infeasible_reasons: list[str] = []

    if not candidate_pool:
        return {
            "candidate_pool": [],
            "selected_clips": [],
            "review_queue": [],
            "selection_status": "constrained_incomplete",
            "infeasible_reasons": ["no-usable-candidates"],
            "coverage_report": {
                "serve_exists_prob": 0.0,
                "serve_presence_status": "unknown",
                "coverage_gap": ["forehand", "backhand", "candidate-pool-empty"],
                "selected_summary": {
                    "required_roles": {
                        "forehand": False,
                        "backhand": False,
                        "serve": False,
                    },
                    "soft_roles": {
                        "baseline": False,
                        "midcourt": False,
                        "running": False,
                        "stationary": False,
                        "left": False,
                        "center": False,
                        "right": False,
                        "highlight": False,
                        "good-example": False,
                        "problem-example": False,
                    },
                },
            },
        }

    serve_exists_prob = max((float(item["semantic_tags"]["serve_prob"]) for item in candidate_pool), default=0.0)
    serve_presence_status = "likely_absent"
    must_have_serve = False
    if serve_presence_mode == "present":
        serve_presence_status = "user-confirmed-present"
        must_have_serve = True
    elif serve_presence_mode == "absent":
        serve_presence_status = "user-confirmed-absent"
        must_have_serve = False
    elif serve_exists_prob >= DEFAULTS["serve_exists_threshold"]:
        serve_presence_status = "likely_present"
        must_have_serve = True
    elif serve_exists_prob >= DEFAULTS["serve_uncertain_floor"]:
        serve_presence_status = "uncertain"
        must_have_serve = True
    else:
        coverage_gap.append("serve-presence-likely-absent")

    for role in ("forehand", "backhand"):
        candidate = best_candidate_for_role(candidate_pool, selected_ids, role)
        if candidate and float(candidate["semantic_tags"][f"{role}_prob"]) >= DEFAULTS["slot_threshold"]:
            selected.append(candidate)
            selected_ids.add(candidate["selection_id"])
        elif candidate:
            coverage_gap.append(role)
            add_to_review_queue(candidate, review_queue, review_ids)
        else:
            coverage_gap.append(role)

    if must_have_serve:
        candidate = best_candidate_for_role(candidate_pool, selected_ids, "serve")
        if candidate and float(candidate["semantic_tags"]["serve_prob"]) >= DEFAULTS["serve_slot_threshold"]:
            selected.append(candidate)
            selected_ids.add(candidate["selection_id"])
        elif candidate:
            coverage_gap.append("serve")
            add_to_review_queue(candidate, review_queue, review_ids)
        else:
            coverage_gap.append("serve")

    if serve_presence_status == "uncertain":
        coverage_gap.append("serve-presence-uncertain")
        serve_review = best_candidate_for_role(candidate_pool, selected_ids, "serve") or best_candidate_for_role(
            candidate_pool,
            set(),
            "serve",
        )
        if serve_review:
            add_to_review_queue(serve_review, review_queue, review_ids)

    for role in ("highlight", "problem-example"):
        candidate = best_candidate_for_role(candidate_pool, selected_ids, role, require_in_play=True)
        if candidate and is_in_play_candidate(candidate):
            selected.append(candidate)
            selected_ids.add(candidate["selection_id"])
        elif candidate:
            add_to_review_queue(candidate, review_queue, review_ids)

    soft_roles: set[str] = set()
    for candidate in selected:
        soft_roles.update(role for role in candidate["coverage_roles"] if role not in {"forehand", "backhand", "serve"})

    while len(selected) < selected_target_size:
        best: dict[str, Any] | None = None
        best_score = -999.0
        for candidate in candidate_pool:
            if candidate["selection_id"] in selected_ids:
                continue
            if not is_in_play_candidate(candidate):
                continue
            overlap = overlap_penalty(candidate, selected)
            semantic_tags = candidate["semantic_tags"]
            bonus = 0.0
            court_zone = semantic_tags["court_zone"]["label"]
            movement_mode = semantic_tags["movement_mode"]["label"]
            side_zone = semantic_tags["side_zone"]["label"]
            for role in (court_zone, movement_mode, side_zone):
                if role not in soft_roles:
                    bonus += 0.08
            if semantic_tags["value_roles"]["highlight"] >= 0.58 and "highlight" not in soft_roles:
                bonus += 0.08
            if semantic_tags["value_roles"]["problem-example"] >= 0.56 and "problem-example" not in soft_roles:
                bonus += 0.08
            if semantic_tags["value_roles"]["good-example"] >= 0.6 and "good-example" not in soft_roles:
                bonus += 0.08
            total = float(candidate["selection_score"]) + bonus - 0.35 * overlap
            if total > best_score:
                best_score = total
                best = candidate
        if not best:
            break
        selected.append(best)
        selected_ids.add(best["selection_id"])
        soft_roles.update(
            [
                best["semantic_tags"]["court_zone"]["label"],
                best["semantic_tags"]["movement_mode"]["label"],
                best["semantic_tags"]["side_zone"]["label"],
            ]
        )
        if best["semantic_tags"]["value_roles"]["highlight"] >= 0.58:
            soft_roles.add("highlight")
        if best["semantic_tags"]["value_roles"]["problem-example"] >= 0.56:
            soft_roles.add("problem-example")
        if best["semantic_tags"]["value_roles"]["good-example"] >= 0.6:
            soft_roles.add("good-example")

    selected = dedupe_selected_candidates(selected)
    selected_ids = {item["selection_id"] for item in selected}

    required_roles = ["forehand", "backhand"] + (["serve"] if must_have_serve else [])
    missing_required: list[str] = [
        role for role in required_roles if not any(has_role(item, role) for item in selected)
    ]

    for role in missing_required:
        refill = best_candidate_for_role(candidate_pool, selected_ids, role)
        if refill and has_role(refill, role):
            selected.append(refill)
            selected_ids.add(refill["selection_id"])
        elif refill:
            add_to_review_queue(refill, review_queue, review_ids)

    soft_roles = set()
    for candidate in selected:
        soft_roles.update(role for role in candidate["coverage_roles"] if role not in {"forehand", "backhand", "serve"})

    while len(selected) < selected_target_size:
        best: dict[str, Any] | None = None
        best_score = -999.0
        for candidate in candidate_pool:
            if candidate["selection_id"] in selected_ids:
                continue
            if not is_in_play_candidate(candidate):
                continue
            overlap = overlap_penalty(candidate, selected)
            semantic_tags = candidate["semantic_tags"]
            bonus = 0.0
            for role in (
                semantic_tags["court_zone"]["label"],
                semantic_tags["movement_mode"]["label"],
                semantic_tags["side_zone"]["label"],
            ):
                if role not in soft_roles:
                    bonus += 0.06
            if semantic_tags["value_roles"]["highlight"] >= 0.58 and "highlight" not in soft_roles:
                bonus += 0.06
            if semantic_tags["value_roles"]["problem-example"] >= 0.56 and "problem-example" not in soft_roles:
                bonus += 0.06
            if semantic_tags["value_roles"]["good-example"] >= 0.6 and "good-example" not in soft_roles:
                bonus += 0.04
            total = float(candidate["selection_score"]) + bonus - 0.45 * overlap
            if total > best_score:
                best_score = total
                best = candidate
        if not best:
            break
        selected.append(best)
        selected_ids.add(best["selection_id"])
        soft_roles.update(role for role in best["coverage_roles"] if role not in {"forehand", "backhand", "serve"})

    selected = sorted(selected, key=lambda item: float(item["selection_score"]), reverse=True)[:selected_target_size]
    selected_ids = {item["selection_id"] for item in selected}

    missing_required = [
        role for role in required_roles if not any(has_role(item, role) for item in selected)
    ]
    coverage_gap.extend(missing_required)
    for role in missing_required:
        infeasible_reasons.append(f"missing-required-role:{role}")

    if selected_target_size < selected_size:
        infeasible_reasons.append("insufficient-candidate-pool-for-target-size")

    if len(selected) < selected_target_size:
        infeasible_reasons.append("unable-to-fill-selected-size-after-constraints")

    clip_counts: dict[str, int] = {}
    for candidate in candidate_pool:
        clip_counts[candidate["clip_id"]] = clip_counts.get(candidate["clip_id"], 0) + 1
    dominant_from_few = False
    if len(candidate_pool) >= max(4, int(0.75 * candidate_pool_size)) and clip_counts:
        top_two = sorted(clip_counts.values(), reverse=True)[:2]
        dominant_from_few = sum(top_two) / len(candidate_pool) >= 0.7
    if dominant_from_few:
        coverage_gap.append("high-repetition-risk")
        ranked = sorted(candidate_pool, key=lambda item: float(item["selection_score"]), reverse=True)
        for candidate in ranked[:3]:
            add_to_review_queue(candidate, review_queue, review_ids)

    for candidate in candidate_pool:
        if candidate["needs_review"] and candidate["selection_id"] not in review_ids:
            add_to_review_queue(candidate, review_queue, review_ids)
        if len(review_queue) >= 6:
            break

    selected_summary = {
        "required_roles": {
            "forehand": any(has_role(item, "forehand") for item in selected),
            "backhand": any(has_role(item, "backhand") for item in selected),
            "serve": any(has_role(item, "serve") for item in selected),
        },
        "soft_roles": {
            "baseline": any(item["semantic_tags"]["court_zone"]["label"] == "baseline" for item in selected),
            "midcourt": any(item["semantic_tags"]["court_zone"]["label"] == "midcourt" for item in selected),
            "running": any(item["semantic_tags"]["movement_mode"]["label"] == "running" for item in selected),
            "stationary": any(item["semantic_tags"]["movement_mode"]["label"] == "stationary" for item in selected),
            "left": any(item["semantic_tags"]["side_zone"]["label"] == "left" for item in selected),
            "center": any(item["semantic_tags"]["side_zone"]["label"] == "center" for item in selected),
            "right": any(item["semantic_tags"]["side_zone"]["label"] == "right" for item in selected),
            "highlight": any(item["semantic_tags"]["value_roles"]["highlight"] >= 0.58 for item in selected),
            "good-example": any(item["semantic_tags"]["value_roles"]["good-example"] >= 0.6 for item in selected),
            "problem-example": any(item["semantic_tags"]["value_roles"]["problem-example"] >= 0.56 for item in selected),
        },
    }
    selection_status = "ready" if not missing_required and len(selected) >= selected_target_size else "constrained_incomplete"

    return {
        "candidate_pool": candidate_pool,
        "selected_clips": selected,
        "review_queue": review_queue[:6],
        "selection_status": selection_status,
        "infeasible_reasons": sorted(set(infeasible_reasons)),
        "coverage_report": {
            "serve_exists_prob": round(serve_exists_prob, 3),
            "serve_presence_status": serve_presence_status,
            "coverage_gap": sorted(set(coverage_gap)),
            "selected_summary": selected_summary,
        },
    }


def clip_summary_for_notes(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    if not candidates:
        return {
            "candidate_count": 0,
            "avg_selection_score": 0.0,
            "avg_dead_time_ratio": 0.0,
        }
    return {
        "candidate_count": len(candidates),
        "avg_selection_score": round(safe_mean(item["selection_score"] for item in candidates), 3),
        "avg_dead_time_ratio": round(
            safe_mean(item["window_metrics"]["dead_time_ratio"] for item in candidates),
            3,
        ),
    }


def export_selected_focus_clips(
    selected: list[dict[str, Any]],
    export_dir: pathlib.Path,
) -> list[dict[str, Any]]:
    export_dir.mkdir(parents=True, exist_ok=True)
    exports: list[dict[str, Any]] = []
    for index, candidate in enumerate(selected, start=1):
        source_path = pathlib.Path(candidate["source_clip_path"])
        if not source_path.exists():
            raise RuntimeError(f"missing source clip for export: {source_path}")
        selected_window = candidate_overlap_window(candidate)
        start_offset = float(selected_window["source_clip_offset_start"])
        end_offset = float(selected_window["source_clip_offset_end"])
        duration = max(0.001, end_offset - start_offset)
        export_name = f"{index:02d}-{candidate['selection_id']}.mp4"
        export_path = export_dir / export_name
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
                str(source_path),
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
                str(export_path),
            ]
        )
        candidate["exported_focus_clip_path"] = str(export_path)
        exports.append(
            {
                "selection_id": candidate["selection_id"],
                "export_path": str(export_path),
                "source_clip_path": str(source_path),
                "window_kind": candidate.get("window_kind"),
                "export_window_kind": "selected_clip_window" if "selected_clip_window" in candidate else "focus_window",
                "start_offset": round(start_offset, 3),
                "end_offset": round(end_offset, 3),
                "duration": round(duration, 3),
            }
        )
    return exports


def main() -> None:
    args = parse_args()
    run_dir = resolve_run_dir(args.run_dir)
    manifest_path = run_dir / "manifest.json"
    point_dir = run_dir / "point_clips"
    if not manifest_path.exists():
        raise SystemExit(f"Missing manifest.json under {run_dir}")
    if not point_dir.exists():
        raise SystemExit(f"Missing point_clips/ under {run_dir}")

    manifest = json.loads(manifest_path.read_text())
    selection_run_id = args.selection_run_id or time.strftime("%Y%m%d-%H%M%S")
    output_dir = pathlib.Path(args.output_dir).resolve() if args.output_dir else run_dir / "selection_runs" / selection_run_id
    selected_clips_dir = (
        pathlib.Path(args.selected_clips_dir).resolve()
        if args.selected_clips_dir
        else run_dir / "selected_clips" / selection_run_id
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    clip_candidates: list[dict[str, Any]] = []
    clip_debug: list[dict[str, Any]] = []
    started_at = time.time()

    with tempfile.TemporaryDirectory(prefix="selection-") as temp_root:
        temp_root_path = pathlib.Path(temp_root)
        for clip in manifest.get("point_clips", []):
            video_path = pathlib.Path(clip["export_path"])
            if not video_path.exists():
                continue
            probe = ffprobe_json(video_path)
            motion_analysis = extract_motion_features(
                video_path,
                temp_root_path,
                fps=args.analysis_fps,
                scale=args.analysis_scale,
            )
            candidates = generate_candidates_for_clip(
                clip,
                motion_analysis,
                handedness=args.handedness,
            )
            for candidate in candidates:
                streams = probe.get("streams", [])
                video_stream = next((stream for stream in streams if stream.get("codec_type") == "video"), {})
                candidate["source_clip_probe"] = {
                    "codec_name": video_stream.get("codec_name"),
                    "width": video_stream.get("width"),
                    "height": video_stream.get("height"),
                    "bit_rate": video_stream.get("bit_rate") or probe.get("format", {}).get("bit_rate"),
                }
            clip_candidates.extend(candidates)
            clip_debug.append(
                {
                    "clip_id": clip["clip_id"],
                    "clip_duration": clip["duration"],
                    "source_interval_count": len(relative_source_intervals(clip)),
                    "motion_window_count": len(motion_analysis["windows"]),
                    "generated_candidates": clip_summary_for_notes(candidates),
                    "quality": motion_analysis["quality"],
                }
            )

    selection_result = select_final_candidates(
        clip_candidates,
        selected_size=args.selected_size,
        candidate_pool_size=args.candidate_pool_size,
        serve_presence_mode=args.serve_presence,
    )
    selected_clip_exports: list[dict[str, Any]] = []
    if not args.skip_export_clips and selection_result["selected_clips"]:
        selected_clip_exports = export_selected_focus_clips(
            selection_result["selected_clips"],
            selected_clips_dir,
        )
    finished_at = time.time()
    package = {
        "selection_version": "05-v1-local-opencv-enhanced" if cv2 is not None else "05-v1-local-rule-based",
        "source_segmentation_run": {
            "run_dir": str(run_dir),
            "manifest_path": str(manifest_path),
            "input": manifest.get("input"),
            "source_video_id": manifest.get("point_clips", [{}])[0].get("source_video_id"),
            "point_clip_count": manifest.get("counts", {}).get("point_clips"),
        },
        "selection_run_id": selection_run_id,
        "params": {
            "analysis_fps": args.analysis_fps,
            "analysis_scale": args.analysis_scale,
            "candidate_pool_size": args.candidate_pool_size,
            "selected_size": args.selected_size,
            "handedness": args.handedness,
            "serve_presence": args.serve_presence,
            "ollama_model": args.ollama_model,
            "ollama_mode": "not-implemented-yet" if args.ollama_model else "disabled",
            "motion_backend": "opencv" if cv2 is not None else "numpy",
        },
        "candidate_pool": selection_result["candidate_pool"],
        "selected_clips": selection_result["selected_clips"],
        "coverage_report": selection_result["coverage_report"],
        "review_queue": selection_result["review_queue"],
        "selection_status": selection_result["selection_status"],
        "infeasible_reasons": selection_result["infeasible_reasons"],
        "selected_clip_exports_dir": str(selected_clips_dir) if selected_clip_exports else None,
        "selected_clip_exports": selected_clip_exports,
        "selection_notes": {
            "started_at_epoch": round(started_at, 3),
            "finished_at_epoch": round(finished_at, 3),
            "elapsed_seconds": round(finished_at - started_at, 3),
            "candidate_count": len(clip_candidates),
            "clip_debug_summary": clip_debug,
        },
    }
    output_path = output_dir / "selection-package.json"
    output_path.write_text(json.dumps(to_jsonable(package), ensure_ascii=False, indent=2))
    print(str(output_path))
    print(
        json.dumps(
            {
                "selection_run_id": selection_run_id,
                "candidate_count": len(clip_candidates),
                "candidate_pool_count": len(package["candidate_pool"]),
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
