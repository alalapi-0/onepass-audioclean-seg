"""测试 CLI emit-segments 功能：从已有的 silences.json 生成 segments.jsonl"""

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


def test_cli_emit_segments_from_existing_silences(monkeypatch, tmp_path):
    """测试从已有的 silences.json 生成 segments.jsonl"""
    # 创建临时目录结构
    workdir = tmp_path / "job1"
    workdir.mkdir()
    
    # 创建最小 WAV 文件
    audio_path = workdir / "audio.wav"
    create_minimal_wav(audio_path, duration_sec=0.1)
    
    # 创建 meta.json（包含 duration_sec=1.0）
    meta_path = workdir / "meta.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump({"duration_sec": 1.0}, f, ensure_ascii=False)
    
    # 创建输出目录
    out_root = tmp_path / "out"
    out_dir = out_root / "job1" / "seg"
    out_dir.mkdir(parents=True)
    
    # 创建 silences.json（中间有 0.2-0.3 静音，这样能生成至少 1 段语音）
    silences_data = {
        "audio_path": str(audio_path.resolve()),
        "strategy": "silence",
        "params": {
            "silence_threshold_db": -35.0,
            "min_silence_sec": 0.5,
        },
        "duration_sec": 1.0,
        "silences": [
            {
                "start_sec": 0.2,
                "end_sec": 0.3,
                "duration_sec": 0.1,
            }
        ],
    }
    
    silences_path = out_dir / "silences.json"
    with open(silences_path, "w", encoding="utf-8") as f:
        json.dump(silences_data, f, ensure_ascii=False, indent=2)
    
    # Mock which 返回假路径（表示 ffmpeg 存在，但实际不会用到）
    def mock_which(exe_name: str):
        if exe_name == "ffmpeg":
            return "/usr/bin/ffmpeg"
        elif exe_name == "ffprobe":
            return "/usr/bin/ffprobe"
        return None
    
    # 应用 monkeypatch
    monkeypatch.setattr(
        "onepass_audioclean_seg.audio.ffmpeg.which",
        mock_which,
    )
    monkeypatch.setattr(
        "onepass_audioclean_seg.audio.probe.which",
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
        "--emit-segments",
        "--strategy",
        "silence",
        "--pad-sec",
        "0.0",
        "--min-seg-sec",
        "0.1",
    ]
    
    exit_code = main(argv)
    
    # 断言返回码为 0
    assert exit_code == 0, f"退出码应为 0，实际为 {exit_code}"
    
    # 断言 segments.jsonl 存在
    segments_path = out_dir / "segments.jsonl"
    assert segments_path.exists(), f"segments.jsonl 不存在: {segments_path}"
    
    # 读取并验证 segments.jsonl
    segments_records = []
    with open(segments_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                segments_records.append(json.loads(line))
    
    # 断言至少 1 行
    assert len(segments_records) >= 1, f"segments.jsonl 应至少包含 1 个片段，实际: {len(segments_records)}"
    
    # 验证第一个片段的字段
    first_seg = segments_records[0]
    assert "id" in first_seg
    assert "start_sec" in first_seg
    assert "end_sec" in first_seg
    assert "duration_sec" in first_seg
    assert "source_audio" in first_seg
    assert "is_speech" in first_seg
    assert first_seg["is_speech"] is True
    assert first_seg["strategy"] == "silence"
    
    # 验证 source_audio 是绝对路径
    assert Path(first_seg["source_audio"]).is_absolute()
    
    # 验证 id 格式
    assert first_seg["id"].startswith("seg_")
    
    # 验证时间字段都是数字且合理
    assert isinstance(first_seg["start_sec"], (int, float))
    assert isinstance(first_seg["end_sec"], (int, float))
    assert isinstance(first_seg["duration_sec"], (int, float))
    assert first_seg["start_sec"] >= 0
    assert first_seg["end_sec"] > first_seg["start_sec"]
    assert first_seg["duration_sec"] > 0
    
    # 验证 seg_report.json 包含 segments 字段
    report_path = out_dir / "seg_report.json"
    assert report_path.exists(), f"seg_report.json 不存在: {report_path}"
    
    with open(report_path, "r", encoding="utf-8") as f:
        report_data = json.load(f)
    
    assert "segments" in report_data
    assert "count" in report_data["segments"]
    assert report_data["segments"]["count"] == len(segments_records)
    assert "speech_total_sec" in report_data["segments"]
    assert "min_seg_sec" in report_data["segments"]
    assert "pad_sec" in report_data["segments"]
    assert "strategy" in report_data["segments"]
    assert report_data["segments"]["strategy"] == "silence"

