#!/usr/bin/env python3

from __future__ import annotations

import argparse
import base64
import http.client
import json
import os
import pathlib
import subprocess
import sys
import time
import urllib.error
import urllib.request
from typing import Any

import tomllib


DEFAULTS = {
    "config_path": "config.toml",
    "frames_per_clip": 6,
    "image_detail": "low",
    "primary_model": "google/gemini-2.5-flash",
    "fallback_model": "google/gemini-2.5-pro",
    "timeout_seconds": 180,
    "api_base": "https://openrouter.ai/api/v1/chat/completions",
    "api_key_env_var": "OPENROUTER_API_KEY",
    "max_memory_chars": 32000,
}

SYSTEM_PROMPT = """你是网球技术分析教练。

你会收到：
1. 一组按时间顺序排列的训练视频关键帧。
2. 每个片段的基础元数据与 selection 证据。
3. 用户现有的网球长期/近期记忆文档。

请输出结构化 JSON，用于训练复盘。

分析规则：
- 只根据提供的视频证据和上下文做判断。
- 明确区分 observed、inferred、uncertain。
- selection 阶段的 model_judgement 和 cv_evidence 只是辅助证据，不是最终技术结论。
- 不要输出泛泛鼓励，不要空泛鸡汤。
- 如果证据不足，明确写 uncertain 或放入 open_questions。
"""

ANALYSIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "session_summary",
        "goal_assessment",
        "state_assessment",
        "top_findings",
        "priority_actions",
        "keep_doing",
        "clip_notes",
        "open_questions",
        "next_session_focus",
    ],
    "properties": {
        "session_summary": {"type": "string"},
        "goal_assessment": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "current_technique",
                "current_training_focus",
                "core_goal",
                "attainment_status",
                "attainment_score",
                "evidence",
            ],
            "properties": {
                "current_technique": {"type": "string"},
                "current_training_focus": {"type": "string"},
                "core_goal": {"type": "string"},
                "attainment_status": {"type": "string"},
                "attainment_score": {"type": "number"},
                "evidence": {"type": "array", "items": {"type": "string"}},
            },
        },
        "state_assessment": {
            "type": "object",
            "additionalProperties": False,
            "required": ["overall_state", "strengths", "weaknesses", "confidence", "evidence"],
            "properties": {
                "overall_state": {"type": "string"},
                "strengths": {"type": "array", "items": {"type": "string"}},
                "weaknesses": {"type": "array", "items": {"type": "string"}},
                "confidence": {"type": "number"},
                "evidence": {"type": "array", "items": {"type": "string"}},
            },
        },
        "top_findings": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["title", "detail", "status", "confidence", "evidence", "related_clip_ids"],
                "properties": {
                    "title": {"type": "string"},
                    "detail": {"type": "string"},
                    "status": {"type": "string"},
                    "confidence": {"type": "number"},
                    "evidence": {"type": "array", "items": {"type": "string"}},
                    "related_clip_ids": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "priority_actions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["action", "detail", "status", "confidence", "evidence", "related_clip_ids"],
                "properties": {
                    "action": {"type": "string"},
                    "detail": {"type": "string"},
                    "status": {"type": "string"},
                    "confidence": {"type": "number"},
                    "evidence": {"type": "array", "items": {"type": "string"}},
                    "related_clip_ids": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "keep_doing": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["item", "detail", "status", "confidence", "evidence", "related_clip_ids"],
                "properties": {
                    "item": {"type": "string"},
                    "detail": {"type": "string"},
                    "status": {"type": "string"},
                    "confidence": {"type": "number"},
                    "evidence": {"type": "array", "items": {"type": "string"}},
                    "related_clip_ids": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "clip_notes": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "selection_id",
                    "observed",
                    "inferred",
                    "uncertain",
                    "key_strengths",
                    "key_issues",
                ],
                "properties": {
                    "selection_id": {"type": "string"},
                    "observed": {"type": "array", "items": {"type": "string"}},
                    "inferred": {"type": "array", "items": {"type": "string"}},
                    "uncertain": {"type": "array", "items": {"type": "string"}},
                    "key_strengths": {"type": "array", "items": {"type": "string"}},
                    "key_issues": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "open_questions": {"type": "array", "items": {"type": "string"}},
        "next_session_focus": {"type": "array", "items": {"type": "string"}},
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run minimal tennis analysis from a selection package.")
    parser.add_argument("--selection-package", required=True, help="Path to a selection-package.json file.")
    parser.add_argument("--config", default=DEFAULTS["config_path"], help="Path to config.toml.")
    return parser.parse_args()


def run_command(args: list[str], *, capture_stdout: bool = False) -> str:
    result = subprocess.run(
        args,
        check=False,
        text=True,
        stdout=subprocess.PIPE if capture_stdout else subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(args)}\n{result.stderr[-1200:]}")
    return result.stdout if capture_stdout else result.stderr


def load_toml(path: pathlib.Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"Missing config file: {path}")
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise SystemExit(f"Invalid TOML in {path}: {exc}") from exc


def nested_get(config: dict[str, Any], *keys: str, default: Any = None) -> Any:
    current: Any = config
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def ffprobe_duration(video_path: pathlib.Path) -> float:
    data = json.loads(
        run_command(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(video_path),
            ],
            capture_stdout=True,
        )
    )
    return float(data["format"]["duration"])


def build_frame_timestamps(duration: float, frame_count: int) -> list[float]:
    if duration <= 0:
        return [0.0]
    if frame_count <= 1:
        return [round(duration / 2.0, 3)]
    margin = min(max(duration * 0.08, 0.15), 1.0)
    start = margin if duration > margin * 2 else 0.0
    end = duration - margin if duration > margin * 2 else duration
    if end <= start:
        start = 0.0
        end = duration
    step = (end - start) / (frame_count - 1)
    return [round(start + step * index, 3) for index in range(frame_count)]


def extract_frame_bytes(video_path: pathlib.Path, timestamp: float) -> bytes:
    result = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-ss",
            f"{timestamp:.3f}",
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            "-vf",
            "scale='min(1024,iw)':-2",
            "-f",
            "image2pipe",
            "-vcodec",
            "mjpeg",
            "-",
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0 or not result.stdout:
        raise RuntimeError(f"Failed to extract frame from {video_path} at {timestamp:.3f}s\n{result.stderr.decode()[-1200:]}")
    return result.stdout


def load_selection_package(path: pathlib.Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"Missing selection package: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON in selection package {path}: {exc}") from exc
    selected = payload.get("selected_clips", [])
    if not selected:
        raise SystemExit("selection package has no selected_clips")
    for item in selected:
        video_path = pathlib.Path(item.get("exported_clip_path", ""))
        if not item.get("exported_clip_path"):
            raise SystemExit(f"selected clip {item.get('selection_id', '<unknown>')} is missing exported_clip_path")
        if not video_path.exists():
            raise SystemExit(f"selected clip video does not exist: {video_path}")
    return payload


def load_memory_documents(memory_root: pathlib.Path, max_memory_chars: int) -> list[dict[str, str]]:
    if not memory_root.exists():
        raise SystemExit(f"Obsidian memory directory does not exist: {memory_root}")
    docs: list[dict[str, str]] = []
    for path in sorted(memory_root.rglob("*.md")):
        rel = str(path.relative_to(memory_root))
        text = path.read_text(encoding="utf-8")
        title = path.stem
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("# "):
                title = stripped[2:].strip()
                break
        docs.append({"relative_path": rel, "title": title, "content": text})

    profile_docs = [doc for doc in docs if doc["relative_path"].startswith("00_Profile/")]
    other_docs = [doc for doc in docs if not doc["relative_path"].startswith("00_Profile/")]
    ordered = profile_docs + other_docs
    kept: list[dict[str, str]] = []
    used = 0
    for doc in ordered:
        block = f"PATH: {doc['relative_path']}\nTITLE: {doc['title']}\n\n{doc['content']}\n\n"
        if kept and used + len(block) > max_memory_chars:
            break
        kept.append(doc)
        used += len(block)
    return kept


def build_user_text(selected_clips: list[dict[str, Any]], memory_docs: list[dict[str, str]]) -> str:
    parts: list[str] = []
    parts.append("任务：请基于以下训练片段，输出当天网球技术复盘。")
    parts.append("必须覆盖：")
    parts.append("1. 当前网球技术、训练和核心目标，以及当天达成度。")
    parts.append("2. 当天状态的整体判断，包括发挥好的技术特点和差的技术特点。")
    parts.append("3. 当天的主要问题，以及后续改进方案。")
    parts.append("4. 当天发挥好的方面，以及后续如何继续保持。")
    parts.append("")
    parts.append("历史记忆文档如下：")
    for doc in memory_docs:
        parts.append(f"## {doc['relative_path']}")
        parts.append(doc["content"])
        parts.append("")
    parts.append("视频片段元数据如下：")
    for item in selected_clips:
        parts.append(f"### {item['selection_id']}")
        parts.append(
            json.dumps(
                {
                    "selection_id": item.get("selection_id"),
                    "clip_id": item.get("clip_id"),
                    "source_video_id": item.get("source_video_id"),
                    "focus_window": item.get("focus_window"),
                    "export_window": item.get("export_window"),
                    "coverage_roles": item.get("coverage_roles"),
                    "model_judgement": item.get("model_judgement"),
                    "cv_evidence": item.get("cv_evidence"),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        parts.append("")
    return "\n".join(parts)


def build_user_content(
    selected_clips: list[dict[str, Any]],
    *,
    frames_per_clip: int,
    image_detail: str,
    user_text: str,
) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = [{"type": "text", "text": user_text}]
    for item in selected_clips:
        video_path = pathlib.Path(item["exported_clip_path"])
        duration = ffprobe_duration(video_path)
        timestamps = build_frame_timestamps(duration, frames_per_clip)
        content.append(
            {
                "type": "text",
                "text": (
                    f"片段 {item['selection_id']}，视频文件 {video_path.name}，"
                    f"focus_window={json.dumps(item.get('focus_window'), ensure_ascii=False)}，"
                    f"export_window={json.dumps(item.get('export_window'), ensure_ascii=False)}"
                ),
            }
        )
        for timestamp in timestamps:
            image_bytes = extract_frame_bytes(video_path, timestamp)
            encoded = base64.b64encode(image_bytes).decode("ascii")
            content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{encoded}",
                        "detail": image_detail,
                    },
                }
            )
    return content


def call_openrouter(
    *,
    api_base: str,
    api_key: str,
    model: str,
    timeout_seconds: int,
    user_content: list[dict[str, Any]],
) -> dict[str, Any]:
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "tennis_analysis",
                "strict": True,
                "schema": ANALYSIS_SCHEMA,
            },
        },
        "plugins": [{"id": "response-healing"}],
        "stream": False,
    }
    req = urllib.request.Request(
        api_base,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/pataphaw/toward-nadal",
            "X-OpenRouter-Title": "toward-nadal",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", errors="replace")
        except http.client.IncompleteRead as read_exc:
            detail = read_exc.partial.decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenRouter request failed with {exc.code}\n{detail[-2000:]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"OpenRouter request failed: {exc}") from exc


def call_openrouter_with_fallback(
    *,
    api_base: str,
    api_key: str,
    primary_model: str,
    fallback_model: str | None,
    timeout_seconds: int,
    user_content: list[dict[str, Any]],
) -> tuple[dict[str, Any], str]:
    try:
        return (
            call_openrouter(
                api_base=api_base,
                api_key=api_key,
                model=primary_model,
                timeout_seconds=timeout_seconds,
                user_content=user_content,
            ),
            primary_model,
        )
    except RuntimeError:
        if not fallback_model or fallback_model == primary_model:
            raise
        return (
            call_openrouter(
                api_base=api_base,
                api_key=api_key,
                model=fallback_model,
                timeout_seconds=timeout_seconds,
                user_content=user_content,
            ),
            fallback_model,
        )


def parse_openrouter_response(payload: dict[str, Any]) -> dict[str, Any]:
    choices = payload.get("choices", [])
    if not choices:
        raise RuntimeError("OpenRouter response has no choices")
    message = choices[0].get("message", {})
    content = message.get("content")
    if isinstance(content, str):
        return json.loads(content)
    if isinstance(content, list):
        text_parts = [item.get("text", "") for item in content if isinstance(item, dict) and item.get("text")]
        if text_parts:
            return json.loads("".join(text_parts))
    raise RuntimeError("Unable to parse structured JSON content from OpenRouter response")


def ensure_analysis_shape(payload: dict[str, Any]) -> None:
    for key in ANALYSIS_SCHEMA["required"]:
        if key not in payload:
            raise RuntimeError(f"analysis result is missing required key: {key}")


def render_markdown(result: dict[str, Any], *, model_name: str) -> str:
    lines: list[str] = []
    lines.append("# 网球训练分析报告")
    lines.append("")
    lines.append(f"- 模型：`{model_name}`")
    lines.append("")
    lines.append("## Session Summary")
    lines.append(result["session_summary"])
    lines.append("")
    goal = result["goal_assessment"]
    lines.append("## Goal Assessment")
    lines.append(f"- 当前技术：{goal['current_technique']}")
    lines.append(f"- 当前训练重点：{goal['current_training_focus']}")
    lines.append(f"- 核心目标：{goal['core_goal']}")
    lines.append(f"- 当天达成度：{goal['attainment_status']} ({goal['attainment_score']})")
    lines.append("")
    state = result["state_assessment"]
    lines.append("## State Assessment")
    lines.append(f"- 整体状态：{state['overall_state']}")
    if state["strengths"]:
        lines.append(f"- 发挥好的特点：{'；'.join(state['strengths'])}")
    if state["weaknesses"]:
        lines.append(f"- 发挥差的特点：{'；'.join(state['weaknesses'])}")
    lines.append("")
    lines.append("## Top Findings")
    for item in result["top_findings"]:
        lines.append(f"- {item['title']}：{item['detail']}")
    lines.append("")
    lines.append("## Priority Actions")
    for item in result["priority_actions"]:
        lines.append(f"- {item['action']}：{item['detail']}")
    lines.append("")
    lines.append("## Keep Doing")
    for item in result["keep_doing"]:
        lines.append(f"- {item['item']}：{item['detail']}")
    lines.append("")
    lines.append("## Next Session Focus")
    for item in result["next_session_focus"]:
        lines.append(f"- {item}")
    return "\n".join(lines) + "\n"


def derive_output_dir(selection_package_path: pathlib.Path) -> pathlib.Path:
    run_id = time.strftime("%Y%m%d-%H%M%S")
    return selection_package_path.parent / "analysis_runs" / run_id


def main() -> None:
    args = parse_args()
    config = load_toml(pathlib.Path(args.config).expanduser())
    memory_root_value = nested_get(config, "memory", "obsidian_vault_dir", default="")
    if not memory_root_value:
        raise SystemExit("config.toml is missing memory.obsidian_vault_dir")
    memory_root = pathlib.Path(str(memory_root_value)).expanduser()

    selection_package_path = pathlib.Path(args.selection_package).expanduser().resolve()
    selection_package = load_selection_package(selection_package_path)

    analysis_cfg = nested_get(config, "analysis", default={}) or {}
    openrouter_cfg = nested_get(config, "analysis", "openrouter", default={}) or {}
    frames_per_clip = int(analysis_cfg.get("frames_per_clip", DEFAULTS["frames_per_clip"]))
    image_detail = str(openrouter_cfg.get("image_detail", DEFAULTS["image_detail"]))
    primary_model = str(openrouter_cfg.get("model", DEFAULTS["primary_model"]))
    fallback_model = str(openrouter_cfg.get("fallback_model", DEFAULTS["fallback_model"]))
    timeout_seconds = int(openrouter_cfg.get("timeout_seconds", DEFAULTS["timeout_seconds"]))
    api_base = str(openrouter_cfg.get("api_base", DEFAULTS["api_base"]))
    api_key_env_var = str(openrouter_cfg.get("api_key_env_var", DEFAULTS["api_key_env_var"]))
    max_memory_chars = int(analysis_cfg.get("max_memory_chars", DEFAULTS["max_memory_chars"]))

    api_key = os.environ.get(api_key_env_var, "")
    if not api_key:
        raise SystemExit(f"Missing API key in environment variable: {api_key_env_var}")

    selected_clips = selection_package["selected_clips"]
    memory_docs = load_memory_documents(memory_root, max_memory_chars=max_memory_chars)
    user_text = build_user_text(selected_clips, memory_docs)
    user_content = build_user_content(
        selected_clips,
        frames_per_clip=frames_per_clip,
        image_detail=image_detail,
        user_text=user_text,
    )
    raw_response, used_model = call_openrouter_with_fallback(
        api_base=api_base,
        api_key=api_key,
        primary_model=primary_model,
        fallback_model=fallback_model,
        timeout_seconds=timeout_seconds,
        user_content=user_content,
    )
    result = parse_openrouter_response(raw_response)
    ensure_analysis_shape(result)

    output_dir = derive_output_dir(selection_package_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    result_with_trace = {
        **result,
        "trace": {
            "provider": "openrouter",
            "model": used_model,
        },
    }
    (output_dir / "analysis-result.json").write_text(
        json.dumps(result_with_trace, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "analysis-report.md").write_text(
        render_markdown(result, model_name=used_model),
        encoding="utf-8",
    )
    print(str(output_dir / "analysis-result.json"))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
