"""测试 YAML 配置文件缺失依赖时的错误处理（R11）"""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from onepass_audioclean_seg.config import load_config_file
from onepass_audioclean_seg.errors import DependencyMissingError


def test_yaml_config_missing_dependency(tmp_path: Path):
    """测试 YAML 配置文件但 pyyaml 未安装时返回退出码 2"""
    # 创建 YAML 配置文件
    yaml_config = tmp_path / "config.yaml"
    yaml_config.write_text("strategy:\n  name: energy\n")
    
    # Mock ImportError（模拟 pyyaml 未安装）
    with patch("builtins.__import__", side_effect=ImportError("No module named 'yaml'")):
        with pytest.raises(DependencyMissingError) as exc_info:
            load_config_file(yaml_config)
        
        assert "pyyaml" in str(exc_info.value).lower(), "错误消息应提及 pyyaml"
        assert "pip install" in str(exc_info.value).lower(), "错误消息应包含安装提示"

