"""测试配置合并优先级（R11）"""

import json
import tempfile
from pathlib import Path

import pytest

from onepass_audioclean_seg.config import (
    get_default_config,
    load_config_file,
    merge_configs,
    set_nested_value,
)


def test_config_merge_precedence(tmp_path: Path):
    """测试配置合并优先级：defaults < config file < --set < CLI 显式参数"""
    # 创建配置文件
    config_file = tmp_path / "config.json"
    config_data = {
        "strategy": {
            "name": "energy",
        },
        "postprocess": {
            "min_seg_sec": 2.0,  # 覆盖默认值 1.0
        },
    }
    with open(config_file, "w", encoding="utf-8") as f:
        json.dump(config_data, f)
    
    # 创建 --set 覆盖
    set_overrides = {
        "postprocess.min_seg_sec": "3.0",  # 覆盖配置文件中的 2.0
    }
    
    # 合并配置
    defaults = get_default_config()
    file_config = load_config_file(config_file)
    merged = merge_configs(defaults, file_config, set_overrides)
    
    # 验证优先级：--set 覆盖应生效
    assert merged["postprocess"]["min_seg_sec"] == 3.0, (
        f"min_seg_sec 应为 3.0（--set 覆盖），实际为 {merged['postprocess']['min_seg_sec']}"
    )
    
    # 验证配置文件覆盖默认值
    assert merged["strategy"]["name"] == "energy", (
        f"strategy 应为 energy（配置文件），实际为 {merged['strategy']['name']}"
    )
    
    # 验证默认值保留（未被覆盖的字段）
    assert merged["postprocess"]["max_seg_sec"] == 25.0, (
        f"max_seg_sec 应为默认值 25.0，实际为 {merged['postprocess']['max_seg_sec']}"
    )


def test_set_nested_value():
    """测试点号路径设置嵌套值"""
    config = {
        "strategy": {
            "auto": {
                "enabled": False,
            },
        },
    }
    
    # 使用点号路径设置值
    set_nested_value(config, "strategy.auto.enabled", True)
    assert config["strategy"]["auto"]["enabled"] is True, "点号路径设置失败"
    
    # 测试字符串到 bool 的转换
    set_nested_value(config, "strategy.auto.enabled", "false")
    assert config["strategy"]["auto"]["enabled"] is False, "字符串到 bool 转换失败"
    
    # 测试字符串到 int 的转换
    set_nested_value(config, "postprocess.min_seg_sec", "5")
    assert "postprocess" in config, "应自动创建嵌套字典"
    assert config["postprocess"]["min_seg_sec"] == 5, "字符串到 int 转换失败"

