"""测试 --dump-effective-config 功能（R11）"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest


def test_dump_effective_config(tmp_path: Path):
    """测试 --dump-effective-config 输出 JSON 并退出码 0，且不写 segments"""
    # 创建配置文件
    config_file = tmp_path / "config.json"
    config_data = {
        "strategy": {
            "name": "energy",
        },
        "postprocess": {
            "min_seg_sec": 2.0,
        },
    }
    with open(config_file, "w", encoding="utf-8") as f:
        json.dump(config_data, f)
    
    # 运行 --dump-effective-config
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "onepass_audioclean_seg",
            "segment",
            "--config",
            str(config_file),
            "--in",
            "dummy.wav",  # 不需要真实文件
            "--out",
            str(tmp_path / "output"),
            "--dump-effective-config",
        ],
        capture_output=True,
        text=True,
    )
    
    # 验证退出码为 0
    assert result.returncode == 0, f"退出码应为 0，实际为 {result.returncode}，stderr: {result.stderr}"
    
    # 验证输出是有效的 JSON
    try:
        effective_config = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        pytest.fail(f"输出不是有效的 JSON: {e}\n输出: {result.stdout}")
    
    # 验证配置包含合并后的值
    assert effective_config["strategy"]["name"] == "energy", "配置应包含文件中的 strategy"
    assert effective_config["postprocess"]["min_seg_sec"] == 2.0, "配置应包含文件中的 min_seg_sec"
    
    # 验证没有写入 segments（输出目录不应存在或为空）
    output_dir = tmp_path / "output"
    if output_dir.exists():
        # 如果目录存在，应该没有 segments.jsonl
        segments_files = list(output_dir.rglob("segments.jsonl"))
        assert len(segments_files) == 0, f"不应写入 segments.jsonl，但找到: {segments_files}"

