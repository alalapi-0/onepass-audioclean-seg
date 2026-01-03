"""测试 segment --dry-run 时仍写 run_summary.json"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path


def test_run_summary_written_on_dry_run(tmp_path):
    """测试 segment --dry-run 时仍写 run_summary.json，并且 dry_run=true"""
    # 创建临时音频文件（不需要真实内容，因为 dry-run）
    audio_path = tmp_path / "audio.wav"
    audio_path.touch()
    
    out_root = tmp_path / "out"
    
    # 运行 CLI（dry-run 模式）
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "onepass_audioclean_seg",
            "segment",
            "--in",
            str(audio_path),
            "--out",
            str(out_root),
            "--dry-run",
        ],
        capture_output=True,
        text=True,
    )
    
    # 断言返回码为 0
    assert result.returncode == 0, f"返回码应为 0，实际为 {result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
    
    # 断言 run_summary.json 存在
    # 注意：dry-run 时，out_root 可能不存在，但 run_summary.json 应该写到某个位置
    # 简化：检查 out_root 或其父目录下是否有 run_summary.json
    possible_locations = [
        out_root / "run_summary.json",
        tmp_path / "run_summary.json",
    ]
    
    run_summary_path = None
    for loc in possible_locations:
        if loc.exists():
            run_summary_path = loc
            break
    
    # 如果都不存在，尝试查找
    if run_summary_path is None:
        for path in tmp_path.rglob("run_summary.json"):
            run_summary_path = path
            break
    
    assert run_summary_path is not None and run_summary_path.exists(), (
        f"run_summary.json 不存在，查找位置: {possible_locations}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    
    # 读取并验证 run_summary.json
    with open(run_summary_path, "r", encoding="utf-8") as f:
        summary = json.load(f)
    
    # 验证 dry_run=true
    assert summary.get("dry_run") is True, f"dry_run 应为 True，实际: {summary.get('dry_run')}"
    
    # 验证 counts
    assert "counts" in summary
    counts = summary["counts"]
    assert "jobs_total" in counts
    assert "jobs_planned" in counts

