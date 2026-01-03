"""测试 check-deps --json 在 ffmpeg 缺失时返回正确结果"""

import json
import sys
from unittest.mock import Mock

import pytest


def test_check_deps_missing_ffmpeg(monkeypatch, capsys):
    """测试 ffmpeg 缺失：返回码 2，json.ok=false，json.error_code="deps_missing"，missing 包含 "ffmpeg" """
    # Mock shutil.which 返回 None（找不到 ffmpeg）
    fake_ffprobe_path = "/usr/bin/ffprobe"
    
    def mock_which(name):
        if name == "ffmpeg":
            return None  # ffmpeg 缺失
        elif name == "ffprobe":
            return fake_ffprobe_path
        return None
    
    # Mock subprocess.run（ffprobe 可用，但 ffmpeg 不存在所以不会调用相关命令）
    def mock_run(cmd, **kwargs):
        result = Mock()
        result.returncode = 0
        
        cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
        if "ffprobe" in cmd_str:
            if "-version" in cmd:
                result.stdout = f"{cmd[0]} version 6.0.1\nbuilt with gcc..."
                result.stderr = ""
        
        return result
    
    # 使用 monkeypatch 替换 shutil.which 和 subprocess.run
    monkeypatch.setattr("onepass_audioclean_seg.audio.ffmpeg.shutil.which", mock_which)
    monkeypatch.setattr("onepass_audioclean_seg.audio.ffmpeg.subprocess.run", mock_run)
    
    # 直接调用 CLI 函数
    from onepass_audioclean_seg.cli import cmd_check_deps, create_parser
    
    parser = create_parser()
    args = parser.parse_args(["check-deps", "--json"])
    return_code = cmd_check_deps(args)
    
    # 验证返回码（应该是 2，表示 deps_missing）
    assert return_code == 2, f"返回码应为 2（deps_missing），实际为 {return_code}"
    
    # 获取输出
    captured = capsys.readouterr()
    output = captured.out
    
    # 验证 JSON 输出
    try:
        report = json.loads(output)
    except json.JSONDecodeError as e:
        assert False, f"输出不是有效的 JSON: {e}\n输出: {output}"
    
    # 验证关键字段
    assert report["ok"] is False, "报告应显示依赖缺失"
    assert report["error_code"] == "deps_missing", f'error_code 应为 "deps_missing"，实际为 {report.get("error_code")}'
    assert "missing" in report, "报告应包含 missing 字段"
    assert "ffmpeg" in report["missing"], "missing 列表应包含 'ffmpeg'"
    # 由于 ffmpeg 缺失，silencedetect 也应该在 missing 中（因为它依赖 ffmpeg）
    assert "silencedetect" in report["missing"], "missing 列表应包含 'silencedetect'（因为依赖 ffmpeg）"
    
    # 验证 deps 字段
    assert "deps" in report, "报告应包含 deps 字段"
    assert "ffmpeg" in report["deps"], "deps 应包含 ffmpeg"
    
    # 验证 ffmpeg 信息（应标记为不可用）
    ffmpeg_info = report["deps"]["ffmpeg"]
    assert ffmpeg_info["ok"] is False, "ffmpeg 应标记为不可用"
    assert ffmpeg_info["path"] == "", "ffmpeg path 应为空字符串"

