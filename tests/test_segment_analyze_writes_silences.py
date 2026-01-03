"""测试 segment analyze 功能：写入 silences.json"""

import json
import tempfile
import wave
from pathlib import Path

import pytest

from onepass_audioclean_seg.cli import main


def create_minimal_wav(file_path: Path, duration_sec: float = 0.1):
    """创建最小有效 WAV 文件
    
    Args:
        file_path: 输出文件路径
        duration_sec: 音频时长（秒）
    """
    sample_rate = 16000
    num_samples = int(sample_rate * duration_sec)
    
    with wave.open(str(file_path), "wb") as wav_file:
        wav_file.setnchannels(1)  # 单声道
        wav_file.setsampwidth(2)  # 16-bit
        wav_file.setframerate(sample_rate)
        
        # 写入静音数据（全零）
        silence_data = b"\x00\x00" * num_samples
        wav_file.writeframes(silence_data)


def test_segment_analyze_writes_silences(monkeypatch, tmp_path):
    """测试 segment analyze 写入 silences.json"""
    # 创建临时目录结构
    workdir = tmp_path / "job1"
    workdir.mkdir()
    
    # 创建最小 WAV 文件
    audio_path = workdir / "audio.wav"
    create_minimal_wav(audio_path, duration_sec=0.1)
    
    # 创建 meta.json（包含 duration_sec）
    meta_path = workdir / "meta.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump({"duration_sec": 10.0}, f, ensure_ascii=False)
    
    # 创建输出目录
    out_root = tmp_path / "out"
    
    # Mock run_silencedetect 返回固定输出
    def mock_run_silencedetect(*args, **kwargs):
        return """
        [silencedetect @ 0x123456] silence_start: 0.000
        [silencedetect @ 0x123456] silence_end: 0.120 | silence_duration: 0.120
        [silencedetect @ 0x123456] silence_start: 8.500
        [silencedetect @ 0x123456] silence_end: 9.000 | silence_duration: 0.500
        """
    
    # Mock which 返回假路径（表示 ffmpeg 存在）
    def mock_which(exe_name: str):
        if exe_name == "ffmpeg":
            return "/usr/bin/ffmpeg"
        return None
    
    # 应用 monkeypatch
    monkeypatch.setattr(
        "onepass_audioclean_seg.strategies.silence_ffmpeg.run_silencedetect",
        mock_run_silencedetect,
    )
    monkeypatch.setattr(
        "onepass_audioclean_seg.audio.ffmpeg.which",
        mock_which,
    )
    # 同时 patch planner 中使用的 which
    monkeypatch.setattr(
        "onepass_audioclean_seg.pipeline.planner.which",
        mock_which,
    )
    
    # 运行 CLI
    argv = [
        "segment",
        "--in",
        str(workdir),
        "--out",
        str(out_root),
        "--out-mode",
        "out_root",
        "--analyze",
        "--strategy",
        "silence",
    ]
    
    exit_code = main(argv)
    
    # 断言返回码为 0
    assert exit_code == 0
    
    # 确定输出目录（out_root 模式下）
    out_dir = out_root / "job1" / "seg"
    
    # 断言 silences.json 存在
    silences_path = out_dir / "silences.json"
    assert silences_path.exists(), f"silences.json 不存在: {silences_path}"
    
    # 读取并验证 silences.json
    with open(silences_path, "r", encoding="utf-8") as f:
        silences_data = json.load(f)
    
    assert "silences" in silences_data
    assert len(silences_data["silences"]) == 2
    assert silences_data["strategy"] == "silence"
    assert "params" in silences_data
    assert silences_data["params"]["silence_threshold_db"] == -35.0
    
    # 断言 seg_report.json 包含 analysis.silence.silences_count
    report_path = out_dir / "seg_report.json"
    assert report_path.exists(), f"seg_report.json 不存在: {report_path}"
    
    with open(report_path, "r", encoding="utf-8") as f:
        report_data = json.load(f)
    
    assert "analysis" in report_data
    assert "silence" in report_data["analysis"]
    assert "silences_count" in report_data["analysis"]["silence"]
    assert report_data["analysis"]["silence"]["silences_count"] == 2

