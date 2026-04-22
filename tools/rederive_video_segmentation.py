#!/usr/bin/env python3

import argparse
import hashlib
import json
import pathlib
import re
import subprocess
import time


DEFAULT_PARAMS = {
    "window_seconds": 0.4,
    "active_gap_seconds": 0.6,
    "min_active_span_seconds": 2.0,
    "pre_roll_seconds": 1.2,
    "post_roll_seconds": 1.4,
    "min_point_duration": 5.0,
    "max_point_duration": 35.0,
    "fragment_gap_seconds": 12.0,
    "fragment_short_point_seconds": 14.0,
    "fragment_max_combined_duration": 90.0,
    "rms_threshold_dbfs": -32.8,
    "motion_fps": 2.0,
    "motion_scale": "64:36",
    "motion_activity_threshold": 4.5,
    "motion_cluster_gap_seconds": 2.0,
    "min_motion_span_seconds": 3.0,
    "motion_audio_join_gap_seconds": 3.0,
    "motion_fragment_gap_seconds": 15.0,
    "motion_split_gap_seconds": 20.0,
    "motion_roi_left_ratio": 0.2,
    "motion_roi_right_ratio": 0.8,
    "motion_roi_top_ratio": 0.1,
    "motion_roi_bottom_ratio": 0.95,
    "motion_roi_boost": 1.35,
    "force_split_above_seconds": 45.0,
    "split_gap_seconds": 4.5,
    "video_encoder": "libx264",
    "audio_encoder": "aac",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True)
    parser.add_argument("--work-root", required=True)
    parser.add_argument("--source-video-id", required=True)
    parser.add_argument("--run-id")
    parser.add_argument("--collect-resources", action="store_true")
    return parser.parse_args()


def run_command(args, *, capture_stdout=False, resource_tracker=None):
    stdout = subprocess.PIPE if capture_stdout else subprocess.DEVNULL
    proc = subprocess.Popen(args, stdout=stdout, stderr=subprocess.PIPE, text=not capture_stdout)
    while proc.poll() is None:
        if resource_tracker:
            resource_tracker.poll_pid(proc.pid)
        time.sleep(0.5)
    out, err = proc.communicate()
    if resource_tracker:
        resource_tracker.poll_pid(proc.pid)
    if proc.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(args)}\n{err[-1200:]}")
    return out if capture_stdout else err


class ResourceTracker:
    def __init__(self, enabled: bool):
        self.enabled = enabled
        self.peak_rss_kb = 0
        self.peak_cpu_percent = 0.0
        self.cpu_samples = []

    def poll_pid(self, pid: int) -> None:
        if not self.enabled:
            return
        try:
            sample = subprocess.check_output(
                ["ps", "-o", "rss=,%cpu=", "-p", str(pid)],
                text=True,
            ).strip()
        except Exception:
            return
        if not sample:
            return
        parts = sample.split()
        if len(parts) < 2:
            return
        try:
            rss_kb = int(float(parts[0]))
            cpu_percent = float(parts[1])
        except ValueError:
            return
        self.peak_rss_kb = max(self.peak_rss_kb, rss_kb)
        self.peak_cpu_percent = max(self.peak_cpu_percent, cpu_percent)
        self.cpu_samples.append(cpu_percent)

    def summary(self) -> dict:
        return {
            "peak_rss_mb": round(self.peak_rss_kb / 1024, 2),
            "peak_cpu_percent": round(self.peak_cpu_percent, 2),
            "avg_sampled_cpu_percent": round(sum(self.cpu_samples) / len(self.cpu_samples), 2)
            if self.cpu_samples
            else None,
        }


def ffprobe_json(video_path: pathlib.Path) -> dict:
    out = subprocess.check_output(
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
        text=True,
    )
    return json.loads(out)


def sha256_prefix_1mb(video_path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with video_path.open("rb") as handle:
        digest.update(handle.read(1024 * 1024))
    return digest.hexdigest()


def extract_audio_windows(video_path: pathlib.Path, log_path: pathlib.Path, tracker: ResourceTracker) -> list[dict]:
    window_samples = int(48000 * DEFAULT_PARAMS["window_seconds"])
    run_command(
        [
            "ffmpeg",
            "-v",
            "error",
            "-hide_banner",
            "-i",
            str(video_path),
            "-vn",
            "-af",
            (
                f"asetnsamples=n={window_samples}:p=0,"
                "astats=metadata=1:reset=1,"
                f"ametadata=print:file={log_path}"
            ),
            "-f",
            "null",
            "-",
        ],
        resource_tracker=tracker,
    )

    windows = []
    pts_time = None
    pattern = re.compile(r"pts_time:([0-9.]+)")
    for line in log_path.read_text().splitlines():
        if line.startswith("frame:"):
            match = pattern.search(line)
            pts_time = float(match.group(1)) if match else None
        elif "lavfi.astats.Overall.RMS_level=" in line and pts_time is not None:
            windows.append(
                {
                    "time": pts_time,
                    "rms_level": float(line.split("=")[1]),
                }
            )
            pts_time = None
    return windows


def extract_motion_windows(video_path: pathlib.Path, motion_log_path: pathlib.Path, tracker: ResourceTracker) -> list[dict]:
    width, height = [int(part) for part in DEFAULT_PARAMS["motion_scale"].split(":")]
    frame_size = width * height
    x0 = max(0, min(width - 1, int(width * DEFAULT_PARAMS["motion_roi_left_ratio"])))
    x1 = max(x0 + 1, min(width, int(width * DEFAULT_PARAMS["motion_roi_right_ratio"])))
    y0 = max(0, min(height - 1, int(height * DEFAULT_PARAMS["motion_roi_top_ratio"])))
    y1 = max(y0 + 1, min(height, int(height * DEFAULT_PARAMS["motion_roi_bottom_ratio"])))
    roi_indices = [y * width + x for y in range(y0, y1) for x in range(x0, x1)]
    raw_path = motion_log_path.with_suffix(".raw")
    run_command(
        [
            "ffmpeg",
            "-v",
            "error",
            "-hide_banner",
            "-i",
            str(video_path),
            "-vf",
            (
                f"fps={DEFAULT_PARAMS['motion_fps']},"
                f"scale={DEFAULT_PARAMS['motion_scale']}:flags=fast_bilinear,"
                "format=gray"
            ),
            "-f",
            "rawvideo",
            "-pix_fmt",
            "gray",
            str(raw_path),
        ],
        resource_tracker=tracker,
    )
    raw_bytes = raw_path.read_bytes()
    raw_path.unlink(missing_ok=True)

    frames = [raw_bytes[i : i + frame_size] for i in range(0, len(raw_bytes), frame_size)]
    windows = []
    for index in range(1, len(frames)):
        prev_frame = frames[index - 1]
        frame = frames[index]
        mean_abs_diff = sum(abs(a - b) for a, b in zip(prev_frame, frame)) / frame_size
        roi_abs_diff = sum(abs(prev_frame[idx] - frame[idx]) for idx in roi_indices) / len(roi_indices)
        motion_score = max(mean_abs_diff, roi_abs_diff * DEFAULT_PARAMS["motion_roi_boost"])
        windows.append(
            {
                "time": index / DEFAULT_PARAMS["motion_fps"],
                "mean_abs_diff": mean_abs_diff,
                "roi_abs_diff": roi_abs_diff,
                "motion_score": motion_score,
            }
        )
    motion_log_path.write_text(json.dumps(windows, ensure_ascii=False, indent=2))
    return windows


def build_audio_intervals(audio_windows: list[dict]) -> list[tuple[float, float]]:
    active_times = [
        window["time"]
        for window in audio_windows
        if window["rms_level"] >= DEFAULT_PARAMS["rms_threshold_dbfs"]
    ]
    intervals = []
    if not active_times:
        return intervals

    start = active_times[0]
    prev = active_times[0]
    for time_point in active_times[1:]:
        if time_point - prev <= DEFAULT_PARAMS["active_gap_seconds"] + 1e-6:
            prev = time_point
            continue
        end = prev + DEFAULT_PARAMS["window_seconds"]
        if end - start >= DEFAULT_PARAMS["min_active_span_seconds"]:
            intervals.append((start, end))
        start = time_point
        prev = time_point

    end = prev + DEFAULT_PARAMS["window_seconds"]
    if end - start >= DEFAULT_PARAMS["min_active_span_seconds"]:
        intervals.append((start, end))
    return intervals


def build_motion_clusters(motion_windows: list[dict]) -> list[tuple[float, float]]:
    active_windows = [
        window
        for window in motion_windows
        if window["motion_score"] >= DEFAULT_PARAMS["motion_activity_threshold"]
    ]
    clusters = []
    if not active_windows:
        return clusters

    start = active_windows[0]["time"]
    prev = active_windows[0]["time"]
    frame_duration = 1.0 / DEFAULT_PARAMS["motion_fps"]
    for window in active_windows[1:]:
        time_point = window["time"]
        if time_point - prev <= DEFAULT_PARAMS["motion_cluster_gap_seconds"]:
            prev = time_point
            continue
        duration = prev + frame_duration - start
        if duration >= DEFAULT_PARAMS["min_motion_span_seconds"]:
            clusters.append((start, prev + frame_duration))
        start = time_point
        prev = time_point

    duration = prev + frame_duration - start
    if duration >= DEFAULT_PARAMS["min_motion_span_seconds"]:
        clusters.append((start, prev + frame_duration))
    return clusters


def fuse_primary_intervals(
    audio_intervals: list[tuple[float, float]],
    motion_intervals: list[tuple[float, float]],
) -> list[dict]:
    intervals = [
        {"start": start, "end": end, "sources": {"motion"}, "parts": [("motion", (start, end))]}
        for start, end in motion_intervals
    ]

    for start, end in audio_intervals:
        attached = False
        for interval in intervals:
            gap = max(0.0, max(start - interval["end"], interval["start"] - end))
            if gap <= DEFAULT_PARAMS["motion_audio_join_gap_seconds"]:
                interval["start"] = min(interval["start"], start)
                interval["end"] = max(interval["end"], end)
                interval["sources"].add("audio")
                interval["parts"].append(("audio", (start, end)))
                attached = True
                break
        if not attached:
            intervals.append(
                {"start": start, "end": end, "sources": {"audio"}, "parts": [("audio", (start, end))]}
            )

    intervals.sort(key=lambda item: item["start"])
    return intervals


def group_primary_intervals(intervals: list[dict]) -> list[list[dict]]:
    groups: list[list[dict]] = []
    for interval in intervals:
        if not groups:
            groups.append([interval])
            continue
        group = groups[-1]
        prev = group[-1]
        gap = interval["start"] - prev["end"]
        prev_duration = prev["end"] - prev["start"]
        curr_duration = interval["end"] - interval["start"]
        combined_duration = interval["end"] - group[0]["start"]
        has_motion = "motion" in prev["sources"] or "motion" in interval["sources"]
        if (
            has_motion
            and gap <= DEFAULT_PARAMS["motion_fragment_gap_seconds"]
            and combined_duration <= DEFAULT_PARAMS["fragment_max_combined_duration"]
        ) or (
            gap <= DEFAULT_PARAMS["fragment_gap_seconds"]
            and combined_duration <= DEFAULT_PARAMS["fragment_max_combined_duration"]
            and (
                prev_duration <= DEFAULT_PARAMS["fragment_short_point_seconds"]
                or curr_duration <= DEFAULT_PARAMS["fragment_short_point_seconds"]
            )
        ):
            group.append(interval)
        else:
            groups.append([interval])
    return groups


def split_group(group: list[dict]) -> list[list[dict]]:
    duration = group[-1]["end"] - group[0]["start"]
    if duration <= DEFAULT_PARAMS["force_split_above_seconds"] or len(group) <= 1:
        return [group]

    candidate_gaps = []
    for index, (prev, curr) in enumerate(zip(group, group[1:]), start=1):
        gap = curr["start"] - prev["end"]
        split_gap = (
            DEFAULT_PARAMS["motion_split_gap_seconds"]
            if "motion" in prev["sources"] and "motion" in curr["sources"]
            else DEFAULT_PARAMS["split_gap_seconds"]
        )
        if gap >= split_gap:
            candidate_gaps.append((gap, index))
    if not candidate_gaps:
        return [group]

    _, split_index = max(candidate_gaps)
    return split_group(group[:split_index]) + split_group(group[split_index:])


def expand_segments(grouped_segments: list[list[dict]], duration_seconds: float) -> list[dict]:
    expanded = []
    for segment in grouped_segments:
        start_time = max(0.0, segment[0]["start"] - DEFAULT_PARAMS["pre_roll_seconds"])
        end_time = min(duration_seconds, segment[-1]["end"] + DEFAULT_PARAMS["post_roll_seconds"])
        duration = end_time - start_time
        if duration < DEFAULT_PARAMS["min_point_duration"]:
            continue
        expanded.append(
            {
                "start_time": start_time,
                "end_time": end_time,
                "duration": duration,
                "source_intervals": [
                    {
                        "kind": part_kind,
                        "start": start,
                        "end": end,
                    }
                    for item in segment
                    for part_kind, (start, end) in item["parts"]
                ],
                "evidence_sources": sorted({source for item in segment for source in item["sources"]}),
            }
        )

    expanded.sort(key=lambda item: item["start_time"])
    for prev, curr in zip(expanded, expanded[1:]):
        if curr["start_time"] < prev["end_time"]:
            midpoint = round((curr["start_time"] + prev["end_time"]) / 2, 3)
            prev["end_time"] = midpoint
            prev["duration"] = round(prev["end_time"] - prev["start_time"], 3)
            curr["start_time"] = midpoint
            curr["duration"] = round(curr["end_time"] - curr["start_time"], 3)
    return expanded


def format_time_label(seconds: float) -> str:
    total_millis = int(round(seconds * 1000))
    hours = total_millis // 3_600_000
    total_millis %= 3_600_000
    minutes = total_millis // 60_000
    total_millis %= 60_000
    secs = total_millis // 1000
    millis = total_millis % 1000
    return f"{hours:02d}-{minutes:02d}-{secs:02d}.{millis:03d}"


def export_point_clips(
    video_path: pathlib.Path,
    point_dir: pathlib.Path,
    source_video_id: str,
    segments: list[dict],
    tracker: ResourceTracker,
) -> list[dict]:
    clips = []
    for index, segment in enumerate(segments, start=1):
        clip_id = f"point-{index:03d}"
        output_name = (
            f"{clip_id}_{format_time_label(segment['start_time'])}_{format_time_label(segment['end_time'])}.mp4"
        )
        output_path = point_dir / output_name
        run_command(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-ss",
            f"{segment['start_time']:.3f}",
                "-to",
                f"{segment['end_time']:.3f}",
                "-i",
                str(video_path),
                "-map",
                "0:v:0",
                "-map",
                "0:a:0?",
                "-c:v",
                DEFAULT_PARAMS["video_encoder"],
                "-preset",
                "veryfast",
                "-crf",
                "22",
                "-c:a",
                DEFAULT_PARAMS["audio_encoder"],
                "-movflags",
                "+faststart",
                str(output_path),
            ],
            resource_tracker=tracker,
        )
        duration_flag = "long" if segment["duration"] > DEFAULT_PARAMS["max_point_duration"] else "normal"
        confidence = 0.55 if duration_flag == "long" else 0.75
        clips.append(
            {
                "clip_id": clip_id,
                "source_video_id": source_video_id,
                "start_time": round(segment["start_time"], 3),
                "end_time": round(segment["end_time"], 3),
                "duration": round(segment["duration"], 3),
                "confidence": confidence,
                "boundary_evidence": {
                    "duration_flag": duration_flag,
                    "evidence_sources": segment["evidence_sources"],
                    "source_intervals": [
                        {
                            "kind": item["kind"],
                            "start": round(item["start"], 3),
                            "end": round(item["end"], 3),
                        }
                        for item in segment["source_intervals"]
                    ],
                },
                "export_path": str(output_path),
                "point_index": index,
                "child_point_clip_ids": None,
                "aggregation_reason": None,
            }
        )
    return clips


def main() -> None:
    args = parse_args()
    video_path = pathlib.Path(args.video).resolve()
    work_root = pathlib.Path(args.work_root).resolve()
    run_id = args.run_id or time.strftime("%Y%m%d-%H%M%S")
    run_dir = work_root / args.source_video_id / run_id
    logs_dir = run_dir / "logs"
    point_dir = run_dir / "point_clips"
    logs_dir.mkdir(parents=True, exist_ok=True)
    point_dir.mkdir(parents=True, exist_ok=True)

    tracker = ResourceTracker(enabled=args.collect_resources)
    started_at = time.time()

    probe = ffprobe_json(video_path)
    duration_seconds = float(probe["format"]["duration"])

    audio_log_path = logs_dir / "ffmpeg-audio-levels.log"
    motion_log_path = logs_dir / "motion-windows.json"
    audio_windows = extract_audio_windows(video_path, audio_log_path, tracker)
    motion_windows = extract_motion_windows(video_path, motion_log_path, tracker)

    audio_intervals = build_audio_intervals(audio_windows)
    motion_clusters = build_motion_clusters(motion_windows)
    primary_intervals = fuse_primary_intervals(audio_intervals, motion_clusters)
    grouped = group_primary_intervals(primary_intervals)
    split_segments: list[list[tuple[float, float]]] = []
    for group in grouped:
        split_segments.extend(split_group(group))
    expanded_segments = expand_segments(split_segments, duration_seconds)
    point_clips = export_point_clips(video_path, point_dir, args.source_video_id, expanded_segments, tracker)

    finished_at = time.time()
    output_size_bytes = sum(pathlib.Path(item["export_path"]).stat().st_size for item in point_clips)
    manifest = {
        "input": str(video_path),
        "backup": {
            "source_path": str(video_path),
            "backup_path": str(video_path),
            "source_size_bytes": video_path.stat().st_size,
            "sha256_prefix_1mb": sha256_prefix_1mb(video_path),
        },
        "probe": probe,
        "params": DEFAULT_PARAMS,
        "counts": {
            "level_windows": len(audio_windows),
            "motion_windows": len(motion_windows),
            "motion_clusters": len(motion_clusters),
            "active_intervals": len(audio_intervals),
            "primary_intervals": len(primary_intervals),
            "grouped_intervals": len(grouped),
            "point_clips": len(point_clips),
            "compact_clips": 0,
        },
        "point_clips": point_clips,
        "compact_clips": [],
        "logs": {
            "audio_levels": str(audio_log_path),
            "motion_windows": str(motion_log_path),
        },
        "rederived": {
            "started_at_epoch": started_at,
            "finished_at_epoch": finished_at,
            "elapsed_seconds": round(finished_at - started_at, 3),
            "resource_usage": tracker.summary(),
            "output_size_bytes": output_size_bytes,
        },
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    print(str(run_dir))
    print(
        json.dumps(
            {
                "run_id": run_id,
                "point_clips": len(point_clips),
                "elapsed_seconds": round(finished_at - started_at, 3),
                "output_size_bytes": output_size_bytes,
                **tracker.summary(),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
