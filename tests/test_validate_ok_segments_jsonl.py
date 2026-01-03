"""测试 validate 命令：验证正确的 segments.jsonl"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path


def test_validate_ok_segments_jsonl(tmp_path):
    """测试 validate 命令验证正确的 segments.jsonl 文件"""
    # 创建临时 segments.jsonl 文件
    segments_path = tmp_path / "segments.jsonl"
    
    # 创建 2 行正确的 segments.jsonl
    segments = [
        {
            "id": "seg_000001",
            "start_sec": 0.0,
            "end_sec": 1.5,
            "duration_sec": 1.5,
            "source_audio": str(tmp_path / "audio.wav"),
            "pre_silence_sec": 0.0,
            "post_silence_sec": 0.2,
            "is_speech": True,
            "strategy": "silence",
        },
        {
            "id": "seg_000002",
            "start_sec": 1.7,
            "end_sec": 3.2,
            "duration_sec": 1.5,
            "source_audio": str(tmp_path / "audio.wav"),
            "pre_silence_sec": 0.2,
            "post_silence_sec": 0.0,
            "is_speech": True,
            "strategy": "silence",
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
    
    # 断言返回码为 0
    assert result.returncode == 0, f"返回码应为 0，实际为 {result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
    
    # 断言输出包含 OK
    assert "OK" in result.stdout, f"输出应包含 'OK'，实际输出: {result.stdout}"
    
    # 断言输出包含文件路径
    assert str(segments_path) in result.stdout, f"输出应包含文件路径，实际输出: {result.stdout}"

