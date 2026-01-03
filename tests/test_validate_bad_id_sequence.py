"""测试 validate 命令：验证 ID 跳号或重复的情况"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path


def test_validate_bad_id_sequence(tmp_path):
    """测试 validate 命令检测 ID 跳号"""
    # 创建临时 segments.jsonl 文件（第二行 ID 跳号）
    segments_path = tmp_path / "segments.jsonl"
    
    segments = [
        {
            "id": "seg_000001",
            "start_sec": 0.0,
            "end_sec": 1.5,
            "duration_sec": 1.5,
            "source_audio": str(tmp_path / "audio.wav"),
        },
        {
            "id": "seg_000003",  # 跳号：应该是 seg_000002
            "start_sec": 1.7,
            "end_sec": 3.2,
            "duration_sec": 1.5,
            "source_audio": str(tmp_path / "audio.wav"),
        },
    ]
    
    with open(segments_path, "w", encoding="utf-8") as f:
        for seg in segments:
            f.write(json.dumps(seg, ensure_ascii=False) + "\n")
    
    # 运行 validate 命令
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "onepass_audioclean_seg",
            "validate",
            "--in",
            str(segments_path),
        ],
        capture_output=True,
        text=True,
    )
    
    # 断言返回码为 2（violations）
    assert result.returncode == 2, f"返回码应为 2，实际为 {result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
    
    # 断言输出包含 FAIL
    assert "FAIL" in result.stdout, f"输出应包含 'FAIL'，实际输出: {result.stdout}"
    
    # 断言输出包含错误信息（跳号）
    assert "跳号" in result.stdout or "id" in result.stdout.lower(), f"输出应包含跳号错误，实际输出: {result.stdout}"


def test_validate_bad_id_first_not_one(tmp_path):
    """测试 validate 命令检测第一个 ID 不是 seg_000001"""
    # 创建临时 segments.jsonl 文件（第一个 ID 不是 seg_000001）
    segments_path = tmp_path / "segments.jsonl"
    
    segments = [
        {
            "id": "seg_000002",  # 第一个 ID 应该是 seg_000001
            "start_sec": 0.0,
            "end_sec": 1.5,
            "duration_sec": 1.5,
            "source_audio": str(tmp_path / "audio.wav"),
        },
    ]
    
    with open(segments_path, "w", encoding="utf-8") as f:
        for seg in segments:
            f.write(json.dumps(seg, ensure_ascii=False) + "\n")
    
    # 运行 validate 命令
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "onepass_audioclean_seg",
            "validate",
            "--in",
            str(segments_path),
        ],
        capture_output=True,
        text=True,
    )
    
    # 断言返回码为 2
    assert result.returncode == 2, f"返回码应为 2，实际为 {result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
    
    # 断言输出包含 FAIL
    assert "FAIL" in result.stdout, f"输出应包含 'FAIL'，实际输出: {result.stdout}"

