"""测试错误退出码（R11）"""

import subprocess
import sys

import pytest

from onepass_audioclean_seg.errors import (
    ArgError,
    ConfigError,
    DependencyMissingError,
    InputNotFoundError,
)


def test_error_exit_code_input_not_found():
    """测试输入文件不存在时退出码为 2"""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "onepass_audioclean_seg",
            "segment",
            "--in",
            "/nonexistent/path/audio.wav",
            "--out",
            "/tmp/output",
        ],
        capture_output=True,
        text=True,
    )
    
    # 验证退出码为 2（InputNotFoundError）
    assert result.returncode == 2, (
        f"输入文件不存在时应返回退出码 2，实际为 {result.returncode}\n"
        f"stderr: {result.stderr}"
    )


def test_error_exit_code_config_not_found():
    """测试配置文件不存在时退出码为 2"""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "onepass_audioclean_seg",
            "segment",
            "--config",
            "/nonexistent/config.json",
            "--in",
            "dummy.wav",
            "--out",
            "/tmp/output",
        ],
        capture_output=True,
        text=True,
    )
    
    # 验证退出码为 2（ConfigError）
    assert result.returncode == 2, (
        f"配置文件不存在时应返回退出码 2，实际为 {result.returncode}\n"
        f"stderr: {result.stderr}"
    )


def test_error_exit_code_invalid_set_format():
    """测试 --set 格式错误时退出码为 2"""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "onepass_audioclean_seg",
            "segment",
            "--set",
            "invalid_format",  # 缺少 = 号
            "--in",
            "dummy.wav",
            "--out",
            "/tmp/output",
        ],
        capture_output=True,
        text=True,
    )
    
    # 验证退出码为 2（ArgError）
    assert result.returncode == 2, (
        f"--set 格式错误时应返回退出码 2，实际为 {result.returncode}\n"
        f"stderr: {result.stderr}"
    )

