# Project-local Codex execution policy.
#
# This repository runs local Python pipeline scripts frequently. The workspace is
# trusted, so project Python commands are allowed without repeated prompts.

prefix_rule(
    pattern = ["python3"],
    decision = "allow",
    justification = "Allow system python3 for this trusted project's video pipeline, validation, and maintenance commands.",
    match = [
        ["python3", "tools/segment_video.py", "--help"],
        ["python3", "tools/select_analysis_clips.py", "--help"],
        ["python3", "tools/analyse_session.py", "--help"],
        ["python3", "tools/rederive_video_segmentation.py", "--help"],
        ["python3", "-m", "py_compile", "tools/analyse_session.py"],
        ["python3", "-c", "print('inline validation checks are allowed')"],
    ],
    not_match = [
        ["python", "tools/analyse_session.py"],
        ["uv", "run", "python3", "tools/analyse_session.py"],
        ["bash", "-lc", "python3 tools/analyse_session.py --help"],
    ],
)

prefix_rule(
    pattern = [".venv/bin/python"],
    decision = "allow",
    justification = "Allow the project virtualenv Python for pipeline runs and local validation.",
    match = [
        [".venv/bin/python", "tools/segment_video.py", "--help"],
        [".venv/bin/python", "tools/select_analysis_clips.py", "--help"],
        [".venv/bin/python", "tools/analyse_session.py", "--help"],
        [".venv/bin/python", "tools/rederive_video_segmentation.py", "--help"],
        [".venv/bin/python", "-m", "py_compile", "tools/select_analysis_clips.py"],
        [".venv/bin/python", "-c", "print('inline validation checks are allowed')"],
    ],
    not_match = [
        ["python", "tools/analyse_session.py"],
        ["uv", "run", "python3", "tools/analyse_session.py"],
        ["bash", "-lc", ".venv/bin/python tools/analyse_session.py --help"],
    ],
)

prefix_rule(
    pattern = ["/Users/pataphaw/Projects/toward-nadal/.venv/bin/python"],
    decision = "allow",
    justification = "Allow the absolute path to this project's virtualenv Python for pipeline runs and local validation.",
    match = [
        ["/Users/pataphaw/Projects/toward-nadal/.venv/bin/python", "tools/segment_video.py", "--help"],
        ["/Users/pataphaw/Projects/toward-nadal/.venv/bin/python", "tools/select_analysis_clips.py", "--help"],
        ["/Users/pataphaw/Projects/toward-nadal/.venv/bin/python", "tools/analyse_session.py", "--help"],
        ["/Users/pataphaw/Projects/toward-nadal/.venv/bin/python", "tools/rederive_video_segmentation.py", "--help"],
        ["/Users/pataphaw/Projects/toward-nadal/.venv/bin/python", "-m", "py_compile", "tools/analyse_session.py"],
        ["/Users/pataphaw/Projects/toward-nadal/.venv/bin/python", "-c", "print('inline validation checks are allowed')"],
    ],
    not_match = [
        ["python", "tools/analyse_session.py"],
        ["uv", "run", "python3", "tools/analyse_session.py"],
        ["bash", "-lc", "/Users/pataphaw/Projects/toward-nadal/.venv/bin/python tools/analyse_session.py --help"],
    ],
)
