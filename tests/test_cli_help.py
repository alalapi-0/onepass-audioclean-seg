"""测试 CLI help 命令"""

import subprocess
import sys


def test_cli_help():
    """测试 audioclean-seg --help 返回码 0，输出包含子命令名"""
    result = subprocess.run(
        [sys.executable, "-m", "onepass_audioclean_seg", "--help"],
        capture_output=True,
        text=True,
    )
    
    assert result.returncode == 0, f"返回码应为 0，实际为 {result.returncode}"
    assert "check-deps" in result.stdout, "输出应包含子命令 'check-deps'"
    assert "segment" in result.stdout, "输出应包含子命令 'segment'"

