"""测试 validate 命令：验证 duration_sec 与 end-start 不一致的情况"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path


def test_validate_duration_mismatch_strict(tmp_path):
    """测试 validate 命令检测 duration_sec 与 end-start 明显不一致"""
    # 创建临时 segments.jsonl 文件（duration_sec 与 end-start 不一致）
    segments_path = tmp_path / "segments.jsonl"
    
    segments = [
        {
            "id": "seg_000001",
            "start_sec": 0.0,
            "end_sec": 1.5,
            "duration_sec": 2.0,  # 明显不一致：应该是 1.5
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
    
    # 断言输出包含错误信息（duration_sec 不一致）
    assert "duration_sec" in result.stdout.lower() or "不一致" in result.stdout, f"输出应包含 duration_sec 错误，实际输出: {result.stdout}"

