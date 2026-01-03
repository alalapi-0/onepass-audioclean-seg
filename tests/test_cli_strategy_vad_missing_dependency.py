"""测试 CLI --strategy vad 在 webrtcvad 缺失时返回错误"""

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


def test_cli_strategy_vad_missing_dependency(monkeypatch):
    """测试 --strategy vad 在 webrtcvad 缺失时返回退出码 2 并提示安装"""
    # 确保 sys.modules 中不含 webrtcvad
    if "webrtcvad" in sys.modules:
        monkeypatch.delitem(sys.modules, "webrtcvad", raising=False)
    
    # Mock import webrtcvad 抛出 ImportError
    original_import = __import__
    
    def mock_import(name, *args, **kwargs):
        if name == "webrtcvad":
            raise ImportError("No module named 'webrtcvad'")
        return original_import(name, *args, **kwargs)
    
    monkeypatch.setattr("builtins.__import__", mock_import)
    
    # 创建临时音频文件
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        audio_path = Path(f.name)
    
    try:
        # 创建最小 WAV 文件
        import wave
        with wave.open(str(audio_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(b"\x00\x00" * 100)
        
        # 创建输出目录
        with tempfile.TemporaryDirectory() as out_dir:
            # 运行命令
            from onepass_audioclean_seg.cli import cmd_segment, create_parser
            
            parser = create_parser()
            args = parser.parse_args([
                "segment",
                "--in", str(audio_path),
                "--out", out_dir,
                "--strategy", "vad",
                "--emit-segments",
            ])
            
            return_code = cmd_segment(args)
            
            # 验证返回码
            assert return_code == 2, f"返回码应为 2（deps_missing），实际为 {return_code}"
    
    finally:
        # 清理
        if audio_path.exists():
            audio_path.unlink()

