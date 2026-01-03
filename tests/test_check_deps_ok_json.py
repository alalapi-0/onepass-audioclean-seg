"""测试 check-deps --json 在依赖齐全时返回正确结果"""

import json
from unittest.mock import Mock

import pytest


def test_check_deps_ok_json(monkeypatch, capsys):
    """测试 ffmpeg/ffprobe 都存在，silencedetect 可用：check-deps --json 返回码 0，json.ok=true，包含 version/path"""
    # Mock shutil.which 返回假路径
    fake_ffmpeg_path = "/usr/bin/ffmpeg"
    fake_ffprobe_path = "/usr/bin/ffprobe"
    
    def mock_which(name):
        if name == "ffmpeg":
            return fake_ffmpeg_path
        elif name == "ffprobe":
            return fake_ffprobe_path
        return None
    
    # Mock subprocess.run 返回成功的 CompletedProcess
    def mock_run(cmd, **kwargs):
        result = Mock()
        result.returncode = 0
        
        cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
        if "ffmpeg" in cmd_str or "ffprobe" in cmd_str:
            if "-version" in cmd:
                result.stdout = f"{cmd[0]} version 6.0.1\nbuilt with gcc..."
                result.stderr = ""
            elif "-h" in cmd and "filter=silencedetect" in cmd_str:
                result.stdout = "silencedetect filter\nDetect silence in audio stream..."
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
    
    # 验证返回码
    assert return_code == 0, f"返回码应为 0，实际为 {return_code}"
    
    # 获取输出
    captured = capsys.readouterr()
    output = captured.out
    
    # 验证 JSON 输出
    try:
        report = json.loads(output)
    except json.JSONDecodeError as e:
        assert False, f"输出不是有效的 JSON: {e}\n输出: {output}"
    
    # 验证关键字段
    assert report["ok"] is True, "报告应显示所有依赖正常"
    assert report["error_code"] is None, "error_code 应为 None"
    assert "missing" in report, "报告应包含 missing 字段"
    assert len(report["missing"]) == 0, "missing 列表应为空"
    
    # 验证 deps 字段
    assert "deps" in report, "报告应包含 deps 字段"
    assert "ffmpeg" in report["deps"], "deps 应包含 ffmpeg"
    assert "ffprobe" in report["deps"], "deps 应包含 ffprobe"
    assert "silencedetect" in report["deps"], "deps 应包含 silencedetect"
    
    # 验证 ffmpeg 信息
    ffmpeg_info = report["deps"]["ffmpeg"]
    assert ffmpeg_info["ok"] is True, "ffmpeg 应标记为 OK"
    assert "path" in ffmpeg_info, "ffmpeg 应包含 path"
    assert "version" in ffmpeg_info, "ffmpeg 应包含 version"
    assert ffmpeg_info["path"] == fake_ffmpeg_path, "ffmpeg path 应正确"
    assert ffmpeg_info["version"] != "", "ffmpeg version 不应为空"
    
    # 验证 ffprobe 信息
    ffprobe_info = report["deps"]["ffprobe"]
    assert ffprobe_info["ok"] is True, "ffprobe 应标记为 OK"
    assert "path" in ffprobe_info, "ffprobe 应包含 path"
    assert "version" in ffprobe_info, "ffprobe 应包含 version"
    assert ffprobe_info["path"] == fake_ffprobe_path, "ffprobe path 应正确"
    assert ffprobe_info["version"] != "", "ffprobe version 不应为空"
    
    # 验证 silencedetect 信息
    silencedetect_info = report["deps"]["silencedetect"]
    assert silencedetect_info["ok"] is True, "silencedetect 应标记为 OK"

