#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import wave
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

try:
    import audioop  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - Python 3.13+
    audioop = None  # type: ignore


@dataclass
class Interval:
    start: float
    end: float

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass
class Clip:
    clip_id: str
    source_video_id: str
    start_time: float
    end_time: float
    duration: float
    confidence: float
    boundary_evidence: Dict[str, object]
    export_path: Optional[str] = None
    point_index: Optional[int] = None
    child_point_clip_ids: Optional[List[str]] = None
    aggregation_reason: Optional[str] = None


DEFAULTS = {
    "raw_dir": ".work/raw-videos",
    "clips_dir": ".work/clips",
    "window_seconds": 0.4,
    "active_gap_seconds": 1.2,
    "min_active_span_seconds": 2.0,
    "pre_roll_seconds": 1.5,
    "post_roll_seconds": 1.5,
    "min_point_duration": 5.0,
    "max_point_duration": 35.0,
    "compact_gap_seconds": 8.0,
    "compact_max_duration": 75.0,
    "compact_max_points": 3,
    "min_silence_duration": 1.2,
    "fragment_gap_seconds": 12.0,
    "fragment_short_point_seconds": 14.0,
    "fragment_max_combined_duration": 90.0,
    "motion_fps": 2.0,
    "motion_cluster_gap_seconds": 2.0,
    "motion_split_gap_seconds": 10.0,
    "motion_tail_trim_gap_seconds": 8.0,
    "motion_tail_cluster_max_seconds": 4.0,
    "motion_buffer_seconds": 1.0,
    "backup_hash_bytes": 1024 * 1024,
}


def run(cmd: Sequence[str], *, capture_output: bool = False, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        list(cmd),
        check=check,
        text=True,
        capture_output=capture_output,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Segment a long-form tennis video into point and compact clips.")
    parser.add_argument("--input", required=True, help="Absolute path to the source video.")
    parser.add_argument("--config", default="config.toml", help="Optional local config file.")
    parser.add_argument("--raw-dir", help="Directory used to store a backed-up copy of the source video.")
    parser.add_argument("--clips-dir", help="Directory used to store generated clips and manifests.")
    parser.add_argument("--analysis-only", action="store_true", help="Compute manifests without exporting clip videos.")
    parser.add_argument("--force-backup", action="store_true", help="Overwrite an existing backup copy if present.")
    parser.add_argument("--window-seconds", type=float, default=DEFAULTS["window_seconds"])
    parser.add_argument("--active-gap-seconds", type=float, default=DEFAULTS["active_gap_seconds"])
    parser.add_argument("--min-active-span-seconds", type=float, default=DEFAULTS["min_active_span_seconds"])
    parser.add_argument("--pre-roll-seconds", type=float, default=DEFAULTS["pre_roll_seconds"])
    parser.add_argument("--post-roll-seconds", type=float, default=DEFAULTS["post_roll_seconds"])
    parser.add_argument("--min-point-duration", type=float, default=DEFAULTS["min_point_duration"])
    parser.add_argument("--max-point-duration", type=float, default=DEFAULTS["max_point_duration"])
    parser.add_argument("--compact-gap-seconds", type=float, default=DEFAULTS["compact_gap_seconds"])
    parser.add_argument("--compact-max-duration", type=float, default=DEFAULTS["compact_max_duration"])
    parser.add_argument("--compact-max-points", type=int, default=DEFAULTS["compact_max_points"])
    parser.add_argument("--min-silence-duration", type=float, default=DEFAULTS["min_silence_duration"])
    parser.add_argument("--fragment-gap-seconds", type=float, default=DEFAULTS["fragment_gap_seconds"])
    parser.add_argument("--fragment-short-point-seconds", type=float, default=DEFAULTS["fragment_short_point_seconds"])
    parser.add_argument("--fragment-max-combined-duration", type=float, default=DEFAULTS["fragment_max_combined_duration"])
    parser.add_argument("--motion-fps", type=float, default=DEFAULTS["motion_fps"])
    parser.add_argument("--motion-cluster-gap-seconds", type=float, default=DEFAULTS["motion_cluster_gap_seconds"])
    parser.add_argument("--motion-split-gap-seconds", type=float, default=DEFAULTS["motion_split_gap_seconds"])
    parser.add_argument("--motion-tail-trim-gap-seconds", type=float, default=DEFAULTS["motion_tail_trim_gap_seconds"])
    parser.add_argument("--motion-tail-cluster-max-seconds", type=float, default=DEFAULTS["motion_tail_cluster_max_seconds"])
    parser.add_argument("--motion-buffer-seconds", type=float, default=DEFAULTS["motion_buffer_seconds"])
    parser.add_argument("--rms-threshold-dbfs", type=float, help="Optional manual RMS threshold override.")
    parser.add_argument("--silence-threshold-dbfs", type=float, help="Optional manual silencedetect threshold override.")
    parser.add_argument(
        "--video-encoder",
        choices=("libx264", "h264_videotoolbox"),
        default="libx264",
        help="Video encoder used for exported clips. Default stays on libx264 because videotoolbox is unstable in the current environment.",
    )
    parser.add_argument("--skip-compact", action="store_true", help="Only generate point clips for this run.")
    return parser.parse_args()


def load_local_config(path: Path) -> Dict[str, str]:
    if not path.exists():
        return {}

    config: Dict[str, str] = {}
    current_section: Optional[str] = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current_section = line.strip("[]")
            continue
        match = re.match(r'([A-Za-z0-9_]+)\s*=\s*"(.*)"\s*$', line)
        if not match or current_section is None:
            continue
        key = f"{current_section}.{match.group(1)}"
        config[key] = match.group(2)
    return config


def resolve_work_dirs(args: argparse.Namespace) -> Tuple[Path, Path]:
    config = load_local_config(Path(args.config))
    raw_dir = args.raw_dir or config.get("video.raw_dir", DEFAULTS["raw_dir"])
    clips_dir = args.clips_dir or config.get("video.clips_dir", DEFAULTS["clips_dir"])

    if raw_dir.startswith("/absolute/path/"):
        raw_dir = DEFAULTS["raw_dir"]
    if clips_dir.startswith("/absolute/path/"):
        clips_dir = DEFAULTS["clips_dir"]

    return Path(raw_dir).expanduser(), Path(clips_dir).expanduser()


def probe_video(path: Path) -> Dict[str, object]:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    result = run(cmd, capture_output=True)
    return json.loads(result.stdout)


def checksum_prefix(path: Path, bytes_to_hash: int) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        digest.update(handle.read(bytes_to_hash))
    return digest.hexdigest()


def backup_source(source: Path, raw_dir: Path, force: bool) -> Dict[str, object]:
    raw_dir.mkdir(parents=True, exist_ok=True)
    backup_path = raw_dir / source.name
    source_size = source.stat().st_size
    source_prefix = checksum_prefix(source, DEFAULTS["backup_hash_bytes"])

    if backup_path.exists():
        same_size = backup_path.stat().st_size == source_size
        same_prefix = checksum_prefix(backup_path, DEFAULTS["backup_hash_bytes"]) == source_prefix
        if force and (not same_size or not same_prefix):
            shutil.copy2(source, backup_path)
        elif not same_size or not same_prefix:
            raise RuntimeError(f"Backup already exists but does not match source: {backup_path}")
    else:
        shutil.copy2(source, backup_path)

    return {
        "source_path": str(source),
        "backup_path": str(backup_path),
        "source_size_bytes": source_size,
        "sha256_prefix_1mb": source_prefix,
    }


def extract_pcm_wav(source: Path, temp_dir: Path) -> Path:
    wav_path = temp_dir / "audio.wav"
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(source),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        str(wav_path),
    ]
    run(cmd)
    return wav_path


def quantile(sorted_values: Sequence[float], q: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = max(0.0, min(1.0, q)) * (len(sorted_values) - 1)
    low = math.floor(pos)
    high = math.ceil(pos)
    if low == high:
        return sorted_values[low]
    weight = pos - low
    return sorted_values[low] * (1.0 - weight) + sorted_values[high] * weight


def dbfs_from_rms(rms: int) -> float:
    if rms <= 0:
        return -96.0
    return 20.0 * math.log10(rms / 32768.0)


def _tomono_pcm_s16le(chunk: bytes, channels: int) -> bytes:
    if channels <= 1:
        return chunk
    if len(chunk) % (2 * channels) != 0:
        return chunk
    out = bytearray()
    for offset in range(0, len(chunk), 2 * channels):
        total = 0
        for channel in range(channels):
            start = offset + channel * 2
            sample = int.from_bytes(chunk[start : start + 2], byteorder="little", signed=True)
            total += sample
        avg = int(total / channels)
        if avg > 32767:
            avg = 32767
        elif avg < -32768:
            avg = -32768
        out.extend(int(avg).to_bytes(2, byteorder="little", signed=True))
    return bytes(out)


def _rms_pcm_s16le(chunk: bytes) -> int:
    if not chunk or len(chunk) % 2 != 0:
        return 0
    sample_count = len(chunk) // 2
    total_square = 0.0
    for offset in range(0, len(chunk), 2):
        sample = int.from_bytes(chunk[offset : offset + 2], byteorder="little", signed=True)
        total_square += float(sample * sample)
    return int(math.sqrt(total_square / sample_count))


def extract_level_windows(wav_path: Path, window_seconds: float) -> List[Tuple[float, float]]:
    with wave.open(str(wav_path), "rb") as wav:
        frame_rate = wav.getframerate()
        sample_width = wav.getsampwidth()
        channels = wav.getnchannels()
        window_frames = max(1, int(frame_rate * window_seconds))
        windows: List[Tuple[float, float]] = []
        index = 0
        while True:
            chunk = wav.readframes(window_frames)
            if not chunk:
                break
            if channels > 1:
                if audioop is not None:
                    chunk = audioop.tomono(chunk, sample_width, 0.5, 0.5)
                elif sample_width == 2:
                    chunk = _tomono_pcm_s16le(chunk, channels)
            if audioop is not None:
                rms = audioop.rms(chunk, sample_width)
            elif sample_width == 2:
                rms = _rms_pcm_s16le(chunk)
            else:
                raise RuntimeError("audioop is unavailable and fallback currently supports only PCM s16le audio.")
            windows.append((index * window_seconds, dbfs_from_rms(rms)))
            index += 1
        return windows


def extract_motion_windows(source: Path, fps: float) -> List[Tuple[float, float]]:
    width, height = 64, 36
    frame_size = width * height
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(source),
        "-vf",
        f"fps={fps},scale={width}:{height},format=gray",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "gray",
        "pipe:1",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    if proc.stdout is None:
        raise RuntimeError("Failed to capture motion frames from ffmpeg.")

    previous: Optional[bytes] = None
    motion_windows: List[Tuple[float, float]] = []
    frame_index = 0
    while True:
        chunk = proc.stdout.read(frame_size)
        if not chunk or len(chunk) < frame_size:
            break
        if previous is not None:
            diff = sum(abs(curr - prev) for curr, prev in zip(chunk, previous)) / frame_size
            motion_windows.append((frame_index / fps, diff))
        previous = chunk
        frame_index += 1

    return_code = proc.wait()
    if return_code != 0:
        raise RuntimeError(f"ffmpeg motion extraction failed with exit code {return_code}")
    return motion_windows


def detect_silences(source: Path, output_log: Path, min_silence_duration: float, threshold_dbfs: float) -> List[Interval]:
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-i",
        str(source),
        "-vn",
        "-af",
        f"silencedetect=noise={threshold_dbfs:.1f}dB:d={min_silence_duration:.2f}",
        "-f",
        "null",
        "-",
    ]
    result = run(cmd, capture_output=True, check=False)
    output_log.write_text(result.stderr, encoding="utf-8")

    silences: List[Interval] = []
    current_start: Optional[float] = None
    for line in result.stderr.splitlines():
        start_match = re.search(r"silence_start: ([0-9.]+)", line)
        if start_match:
            current_start = float(start_match.group(1))
            continue
        end_match = re.search(r"silence_end: ([0-9.]+)", line)
        if end_match and current_start is not None:
            silences.append(Interval(current_start, float(end_match.group(1))))
            current_start = None
    return silences


def merge_intervals(intervals: Iterable[Interval], gap_tolerance: float) -> List[Interval]:
    ordered = sorted((i for i in intervals if i.duration > 0), key=lambda i: i.start)
    if not ordered:
        return []
    merged = [ordered[0]]
    for interval in ordered[1:]:
        last = merged[-1]
        if interval.start <= last.end + gap_tolerance:
            last.end = max(last.end, interval.end)
        else:
            merged.append(Interval(interval.start, interval.end))
    return merged


def build_active_intervals(level_windows: Sequence[Tuple[float, float]], threshold_dbfs: float, window_seconds: float, active_gap_seconds: float) -> List[Interval]:
    raw = [
        Interval(start, start + window_seconds)
        for start, dbfs in level_windows
        if dbfs >= threshold_dbfs
    ]
    return merge_intervals(raw, active_gap_seconds)


def filter_short_intervals(intervals: Sequence[Interval], min_duration: float) -> List[Interval]:
    return [interval for interval in intervals if interval.duration >= min_duration]


def refine_long_intervals(
    intervals: Sequence[Interval],
    level_windows: Sequence[Tuple[float, float]],
    base_threshold_dbfs: float,
    window_seconds: float,
    active_gap_seconds: float,
    max_point_duration: float,
) -> List[Interval]:
    refined: List[Interval] = []
    for interval in intervals:
        if interval.duration <= max_point_duration * 1.8:
            refined.append(interval)
            continue

        subset = [
            (start, dbfs)
            for start, dbfs in level_windows
            if interval.start <= start <= interval.end
        ]
        replacement: Optional[List[Interval]] = None
        for bump in (1.5, 2.5, 3.5):
            candidate = filter_short_intervals(
                build_active_intervals(
                    subset,
                    base_threshold_dbfs + bump,
                    window_seconds,
                    max(0.4, active_gap_seconds / 2.0),
                ),
                1.0,
            )
            if len(candidate) < 2:
                continue
            if max(item.duration for item in candidate) < interval.duration * 0.85:
                replacement = candidate
                break

        if replacement:
            refined.extend(replacement)
        else:
            refined.append(interval)
    return refined


def extend_and_filter_intervals(
    intervals: Sequence[Interval],
    duration: float,
    pre_roll: float,
    post_roll: float,
    min_duration: float,
    merge_gap_seconds: float,
) -> List[Interval]:
    expanded = [
        Interval(max(0.0, interval.start - pre_roll), min(duration, interval.end + post_roll))
        for interval in intervals
    ]
    merged = merge_intervals(expanded, merge_gap_seconds)
    return [interval for interval in merged if interval.duration >= min_duration]


def nearest_silence_before(silences: Sequence[Interval], point_start: float, max_distance: float = 6.0) -> Optional[Interval]:
    candidates = [silence for silence in silences if silence.end <= point_start and point_start - silence.end <= max_distance]
    return candidates[-1] if candidates else None


def nearest_silence_after(silences: Sequence[Interval], point_end: float, max_distance: float = 6.0) -> Optional[Interval]:
    candidates = [silence for silence in silences if silence.start >= point_end and silence.start - point_end <= max_distance]
    return candidates[0] if candidates else None


def clip_confidence(duration: float, min_point_duration: float, max_point_duration: float, supporting_silence_count: int) -> float:
    confidence = 0.55
    if min_point_duration <= duration <= max_point_duration:
        confidence += 0.20
    elif duration <= max_point_duration * 1.5:
        confidence += 0.08
    confidence += min(0.20, supporting_silence_count * 0.08)
    return round(min(0.98, confidence), 2)


def build_point_clips(
    intervals: Sequence[Interval],
    silences: Sequence[Interval],
    source_video_id: str,
    min_point_duration: float,
    max_point_duration: float,
) -> List[Clip]:
    clips: List[Clip] = []
    for index, interval in enumerate(intervals, start=1):
        start_silence = nearest_silence_before(silences, interval.start)
        end_silence = nearest_silence_after(silences, interval.end)
        support_count = int(start_silence is not None) + int(end_silence is not None)
        clip = Clip(
            clip_id=f"point-{index:03d}",
            source_video_id=source_video_id,
            start_time=round(interval.start, 3),
            end_time=round(interval.end, 3),
            duration=round(interval.duration, 3),
            point_index=index,
            confidence=clip_confidence(interval.duration, min_point_duration, max_point_duration, support_count),
            boundary_evidence={
                "supporting_silence_before": asdict(start_silence) if start_silence else None,
                "supporting_silence_after": asdict(end_silence) if end_silence else None,
                "duration_flag": "long" if interval.duration > max_point_duration else "normal",
            },
        )
        clips.append(clip)
    return clips


def merge_fragmented_point_clips(
    point_clips: Sequence[Clip],
    fragment_gap_seconds: float,
    fragment_short_point_seconds: float,
    fragment_max_combined_duration: float,
) -> List[Clip]:
    if not point_clips:
        return []

    merged: List[Clip] = []
    current = Clip(**asdict(point_clips[0]))
    merge_sources = [point_clips[0].clip_id]

    def should_merge(left: Clip, right: Clip) -> bool:
        gap = right.start_time - left.end_time
        if gap < 0 or gap > fragment_gap_seconds:
            return False
        combined_duration = right.end_time - left.start_time
        if combined_duration > fragment_max_combined_duration:
            return False
        if gap <= 4.0:
            return True
        return left.duration <= fragment_short_point_seconds or right.duration <= fragment_short_point_seconds

    for candidate in point_clips[1:]:
        if should_merge(current, candidate):
            current.end_time = candidate.end_time
            current.duration = round(current.end_time - current.start_time, 3)
            current.confidence = round(min(current.confidence, candidate.confidence), 2)
            merge_sources.append(candidate.clip_id)
            current.boundary_evidence = {
                **current.boundary_evidence,
                "merged_from": merge_sources[:],
                "merge_reason": f"gap<={fragment_gap_seconds}s and short-point bridge",
            }
        else:
            merged.append(current)
            current = Clip(**asdict(candidate))
            merge_sources = [candidate.clip_id]
    merged.append(current)

    for index, clip in enumerate(merged, start=1):
        clip.clip_id = f"point-{index:03d}"
        clip.point_index = index
    return merged


def build_compact_clips(
    point_clips: Sequence[Clip],
    source_video_id: str,
    compact_gap_seconds: float,
    compact_max_duration: float,
    compact_max_points: int,
) -> List[Clip]:
    compacts: List[Clip] = []
    current: List[Clip] = []

    def flush(group: List[Clip]) -> None:
        if not group:
            return
        start = group[0].start_time
        end = group[-1].end_time
        compacts.append(
            Clip(
                clip_id=f"compact-{len(compacts) + 1:03d}",
                source_video_id=source_video_id,
                start_time=start,
                end_time=end,
                duration=round(end - start, 3),
                confidence=round(sum(c.confidence for c in group) / len(group), 2),
                boundary_evidence={"group_size": len(group)},
                child_point_clip_ids=[clip.clip_id for clip in group],
                aggregation_reason=f"gap<={compact_gap_seconds}s and total_duration<={compact_max_duration}s",
            )
        )

    for clip in point_clips:
        if not current:
            current = [clip]
            continue
        gap = clip.start_time - current[-1].end_time
        projected_duration = clip.end_time - current[0].start_time
        if gap <= compact_gap_seconds and projected_duration <= compact_max_duration and len(current) < compact_max_points:
            current.append(clip)
        else:
            flush(current)
            current = [clip]
    flush(current)
    return compacts


def build_activity_clusters(
    motion_windows: Sequence[Tuple[float, float]],
    activity_threshold: float,
    fps: float,
    cluster_gap_seconds: float,
) -> List[Interval]:
    intervals = [Interval(start, start + (1.0 / fps)) for start, value in motion_windows if value >= activity_threshold]
    return merge_intervals(intervals, cluster_gap_seconds)


def clip_copy(clip: Clip) -> Clip:
    return Clip(**asdict(clip))


def split_point_clips_on_motion_gaps(
    point_clips: Sequence[Clip],
    motion_clusters: Sequence[Interval],
    split_gap_seconds: float,
    tail_trim_gap_seconds: float,
    tail_cluster_max_seconds: float,
    buffer_seconds: float,
    min_point_duration: float,
) -> List[Clip]:
    refined: List[Clip] = []

    for clip in point_clips:
        clusters = [
            Interval(max(cluster.start, clip.start_time), min(cluster.end, clip.end_time))
            for cluster in motion_clusters
            if cluster.end >= clip.start_time and cluster.start <= clip.end_time
        ]
        clusters = [cluster for cluster in clusters if cluster.duration > 0]
        if not clusters:
            refined.append(clip_copy(clip))
            continue

        segment_ranges: List[Tuple[float, float]] = []
        current_start = clip.start_time
        current_cluster_index = 0

        while current_cluster_index < len(clusters) - 1:
            left = clusters[current_cluster_index]
            right = clusters[current_cluster_index + 1]
            gap = right.start - left.end
            if gap >= split_gap_seconds:
                segment_end = min(clip.end_time, left.end + buffer_seconds)
                if segment_end - current_start >= min_point_duration:
                    segment_ranges.append((current_start, segment_end))
                current_start = max(clip.start_time, right.start - buffer_seconds)
            current_cluster_index += 1

        final_end = clip.end_time
        final_clusters = [cluster for cluster in clusters if cluster.end >= current_start]
        if len(final_clusters) >= 2:
            prev_cluster = final_clusters[-2]
            last_cluster = final_clusters[-1]
            trailing_gap = last_cluster.start - prev_cluster.end
            trailing_cluster_duration = last_cluster.duration
            tail_room = clip.end_time - last_cluster.start
            if (
                trailing_gap >= tail_trim_gap_seconds
                and trailing_cluster_duration <= tail_cluster_max_seconds
                and tail_room <= tail_cluster_max_seconds + buffer_seconds
            ):
                final_end = min(final_end, prev_cluster.end + buffer_seconds)

        if final_end - current_start >= min_point_duration:
            segment_ranges.append((current_start, final_end))

        if not segment_ranges:
            refined.append(clip_copy(clip))
            continue

        if len(segment_ranges) == 1 and abs(segment_ranges[0][0] - clip.start_time) < 1e-6 and abs(segment_ranges[0][1] - clip.end_time) < 1e-6:
            refined.append(clip_copy(clip))
            continue

        inherited_sources = clip.boundary_evidence.get("merged_from") if isinstance(clip.boundary_evidence, dict) else None
        for index, (start_time, end_time) in enumerate(segment_ranges, start=1):
            new_clip = clip_copy(clip)
            new_clip.start_time = round(start_time, 3)
            new_clip.end_time = round(end_time, 3)
            new_clip.duration = round(end_time - start_time, 3)
            new_clip.boundary_evidence = {
                **new_clip.boundary_evidence,
                "motion_split": True,
                "motion_split_part": index,
            }
            if inherited_sources:
                new_clip.boundary_evidence["merged_from"] = inherited_sources
            refined.append(new_clip)

    for index, clip in enumerate(refined, start=1):
        clip.clip_id = f"point-{index:03d}"
        clip.point_index = index
    return refined


def hhmmss(seconds: float) -> str:
    total_ms = int(round(seconds * 1000))
    hours, remainder = divmod(total_ms, 3600 * 1000)
    minutes, remainder = divmod(remainder, 60 * 1000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def export_clip(source: Path, destination: Path, start_time: float, end_time: float, video_encoder: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    common = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        hhmmss(start_time),
        "-to",
        hhmmss(end_time),
        "-i",
        str(source),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-c:a",
        "aac",
        "-movflags",
        "+faststart",
    ]
    candidates = [common + ["-c:v", "libx264", "-preset", "veryfast", "-crf", "22", str(destination)]]
    if video_encoder == "h264_videotoolbox":
        candidates.insert(0, common + ["-c:v", "h264_videotoolbox", "-allow_sw", "1", "-b:v", "6M", str(destination)])

    last_error: Optional[subprocess.CalledProcessError] = None
    for cmd in candidates:
        try:
            run(cmd)
            return
        except subprocess.CalledProcessError as exc:
            last_error = exc
    if last_error is not None:
        raise last_error


def serialise_clips(clips: Sequence[Clip]) -> List[Dict[str, object]]:
    return [asdict(clip) for clip in clips]


def manifest_path_for(run_dir: Path) -> Path:
    return run_dir / "manifest.json"


def main() -> int:
    args = parse_args()
    input_path = Path(args.input).expanduser().resolve()
    if not input_path.exists():
        raise SystemExit(f"Input video not found: {input_path}")

    raw_dir, clips_dir = resolve_work_dirs(args)
    raw_dir = raw_dir.resolve()
    clips_dir = clips_dir.resolve()

    source_id = input_path.stem.lower()
    run_id = time.strftime("%Y%m%d-%H%M%S")
    run_dir = clips_dir / source_id / run_id
    logs_dir = run_dir / "logs"
    points_dir = run_dir / "point_clips"
    compact_dir = run_dir / "compact_clips"
    logs_dir.mkdir(parents=True, exist_ok=True)

    backup = backup_source(input_path, raw_dir, args.force_backup)
    backup_path = Path(backup["backup_path"])
    probe = probe_video(backup_path)
    format_info = probe.get("format", {})
    duration = float(format_info.get("duration", "0") or 0.0)
    has_audio = any(stream.get("codec_type") == "audio" for stream in probe.get("streams", []))
    if not has_audio:
        raise SystemExit("The input video does not have an audio stream; the current V1 segmenter cannot proceed.")

    with tempfile.TemporaryDirectory(prefix="toward-nadal-seg-") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        wav_path = extract_pcm_wav(backup_path, temp_dir)
        level_windows = extract_level_windows(wav_path, args.window_seconds)
        motion_windows = extract_motion_windows(backup_path, args.motion_fps)
        levels_only = sorted(level for _, level in level_windows)
        motion_only = sorted(value for _, value in motion_windows)
        noise_floor = quantile(levels_only, 0.20)
        high_activity = quantile(levels_only, 0.82)
        motion_activity_threshold = max(4.5, quantile(motion_only, 0.90))
        rms_threshold = args.rms_threshold_dbfs
        if rms_threshold is None:
            rms_threshold = max(-42.0, min(-18.0, noise_floor + (high_activity - noise_floor) * 0.38))

        silence_threshold = args.silence_threshold_dbfs
        if silence_threshold is None:
            silence_threshold = max(-55.0, min(-20.0, noise_floor + 0.5))
        silence_log_path = logs_dir / "ffmpeg-silencedetect.log"
        silences = detect_silences(backup_path, silence_log_path, args.min_silence_duration, silence_threshold)

    active_intervals = refine_long_intervals(
        filter_short_intervals(
            build_active_intervals(
        level_windows=level_windows,
        threshold_dbfs=rms_threshold,
        window_seconds=args.window_seconds,
        active_gap_seconds=args.active_gap_seconds,
            ),
            args.min_active_span_seconds,
        ),
        level_windows=level_windows,
        base_threshold_dbfs=rms_threshold,
        window_seconds=args.window_seconds,
        active_gap_seconds=args.active_gap_seconds,
        max_point_duration=args.max_point_duration,
    )
    point_intervals = extend_and_filter_intervals(
        intervals=active_intervals,
        duration=duration,
        pre_roll=args.pre_roll_seconds,
        post_roll=args.post_roll_seconds,
        min_duration=args.min_point_duration,
        merge_gap_seconds=args.active_gap_seconds,
    )
    point_clips = build_point_clips(
        intervals=point_intervals,
        silences=silences,
        source_video_id=source_id,
        min_point_duration=args.min_point_duration,
        max_point_duration=args.max_point_duration,
    )
    point_clips = merge_fragmented_point_clips(
        point_clips,
        fragment_gap_seconds=args.fragment_gap_seconds,
        fragment_short_point_seconds=args.fragment_short_point_seconds,
        fragment_max_combined_duration=args.fragment_max_combined_duration,
    )
    motion_clusters = build_activity_clusters(
        motion_windows=motion_windows,
        activity_threshold=motion_activity_threshold,
        fps=args.motion_fps,
        cluster_gap_seconds=args.motion_cluster_gap_seconds,
    )
    point_clips = split_point_clips_on_motion_gaps(
        point_clips,
        motion_clusters=motion_clusters,
        split_gap_seconds=args.motion_split_gap_seconds,
        tail_trim_gap_seconds=args.motion_tail_trim_gap_seconds,
        tail_cluster_max_seconds=args.motion_tail_cluster_max_seconds,
        buffer_seconds=args.motion_buffer_seconds,
        min_point_duration=args.min_point_duration,
    )
    compact_clips: List[Clip] = []
    if not args.skip_compact:
        compact_clips = build_compact_clips(
            point_clips=point_clips,
            source_video_id=source_id,
            compact_gap_seconds=args.compact_gap_seconds,
            compact_max_duration=args.compact_max_duration,
            compact_max_points=args.compact_max_points,
        )

    if not args.analysis_only:
        for clip in point_clips:
            destination = points_dir / f"{clip.clip_id}_{hhmmss(clip.start_time).replace(':', '-')}_{hhmmss(clip.end_time).replace(':', '-')}.mp4"
            export_clip(backup_path, destination, clip.start_time, clip.end_time, args.video_encoder)
            clip.export_path = str(destination)

        if not args.skip_compact:
            for clip in compact_clips:
                destination = compact_dir / f"{clip.clip_id}_{hhmmss(clip.start_time).replace(':', '-')}_{hhmmss(clip.end_time).replace(':', '-')}.mp4"
                export_clip(backup_path, destination, clip.start_time, clip.end_time, args.video_encoder)
                clip.export_path = str(destination)

    summary = {
        "input": str(input_path),
        "backup": backup,
        "probe": probe,
        "params": {
            "window_seconds": args.window_seconds,
            "active_gap_seconds": args.active_gap_seconds,
            "min_active_span_seconds": args.min_active_span_seconds,
            "pre_roll_seconds": args.pre_roll_seconds,
            "post_roll_seconds": args.post_roll_seconds,
            "min_point_duration": args.min_point_duration,
            "max_point_duration": args.max_point_duration,
            "compact_gap_seconds": args.compact_gap_seconds,
            "compact_max_duration": args.compact_max_duration,
            "compact_max_points": args.compact_max_points,
            "min_silence_duration": args.min_silence_duration,
            "fragment_gap_seconds": args.fragment_gap_seconds,
            "fragment_short_point_seconds": args.fragment_short_point_seconds,
            "fragment_max_combined_duration": args.fragment_max_combined_duration,
            "motion_fps": args.motion_fps,
            "motion_cluster_gap_seconds": args.motion_cluster_gap_seconds,
            "motion_activity_threshold": round(motion_activity_threshold, 3),
            "motion_split_gap_seconds": args.motion_split_gap_seconds,
            "motion_tail_trim_gap_seconds": args.motion_tail_trim_gap_seconds,
            "motion_tail_cluster_max_seconds": args.motion_tail_cluster_max_seconds,
            "motion_buffer_seconds": args.motion_buffer_seconds,
            "video_encoder": args.video_encoder,
            "skip_compact": args.skip_compact,
            "rms_threshold_dbfs": round(rms_threshold, 3),
            "silence_threshold_dbfs": round(silence_threshold, 3),
            "noise_floor_dbfs": round(noise_floor, 3),
            "high_activity_dbfs": round(high_activity, 3),
        },
        "counts": {
            "level_windows": len(level_windows),
            "motion_windows": len(motion_windows),
            "motion_clusters": len(motion_clusters),
            "silences": len(silences),
            "active_intervals": len(active_intervals),
            "point_clips": len(point_clips),
            "compact_clips": len(compact_clips),
        },
        "silences": [asdict(silence) for silence in silences],
        "point_clips": serialise_clips(point_clips),
        "compact_clips": serialise_clips(compact_clips),
        "logs": {"silencedetect": str(silence_log_path)},
        "analysis_only": args.analysis_only,
    }
    manifest = manifest_path_for(run_dir)
    manifest.write_text(json.dumps(summary, indent=2, ensure_ascii=True), encoding="utf-8")
    print(json.dumps({"run_dir": str(run_dir), "manifest": str(manifest), "counts": summary["counts"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
