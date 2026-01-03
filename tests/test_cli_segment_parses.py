"""测试 CLI segment 命令参数解析"""

import subprocess
import sys


def test_cli_segment_parses():
    """测试 audioclean-seg segment --in a.wav --out outdir 返回码 0，输出包含 'PLAN'"""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "onepass_audioclean_seg",
            "segment",
            "--in",
            "a.wav",
            "--out",
            "outdir",
        ],
        capture_output=True,
        text=True,
    )
    
    assert result.returncode == 0, f"返回码应为 0，实际为 {result.returncode}"
    assert "PLAN" in result.stdout, "输出应包含 'PLAN' 关键字"
    assert "a.wav" in result.stdout, "输出应包含输入文件路径"
    assert "outdir" in result.stdout, "输出应包含输出目录路径"

