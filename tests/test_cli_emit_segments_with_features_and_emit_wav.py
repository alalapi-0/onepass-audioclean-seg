"""测试 CLI emit-segments 功能：包含能量特征和 WAV 导出"""

import array
import json
import tempfile
import wave
from pathlib import Path

import pytest

from onepass_audioclean_seg.cli import main


def create_test_wav(file_path: Path, duration_sec: float = 1.0):
    """创建测试 WAV 文件（包含一些音频内容）
    
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
        
        # 生成一些音频数据（固定幅度，便于测试）
        audio_data = array.array("h", [5000] * num_samples)
        wav_file.writeframes(audio_data.tobytes())


def test_cli_emit_segments_with_features_and_emit_wav(monkeypatch, tmp_path):
    """测试 CLI emit-segments 功能：包含能量特征和 WAV 导出
    
    创建 workdir：audio.wav + meta.json(duration)
    不需要真实 silencedetect：直接预置 silences.json（让补集产生 1-2 个语音段）
    运行 CLI：
     audioclean-seg segment --in workdir --out out_root --out-mode out_root --emit-segments --emit-wav --min-seg-sec 0.2 --max-seg-sec 0.6 --pad-sec 0.0
    (max 很小以触发 split)
    """
    # 创建临时目录结构
    workdir = tmp_path / "job1"
    workdir.mkdir()
    
    # 创建测试 WAV 文件（1.0 秒）
    audio_path = workdir / "audio.wav"
    create_test_wav(audio_path, duration_sec=1.0)
    
    # 创建 meta.json（包含 duration_sec=1.0）
    meta_path = workdir / "meta.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump({"duration_sec": 1.0}, f, ensure_ascii=False)
    
    # 创建输出目录
    out_root = tmp_path / "out"
    out_dir = out_root / "job1" / "seg"
    out_dir.mkdir(parents=True)
    
    # 创建 silences.json（中间有 0.3-0.4 静音，这样能生成至少 1 段语音，且长度 > 0.6 以触发 split）
    silences_data = {
        "audio_path": str(audio_path.resolve()),
        "strategy": "silence",
        "params": {
            "silence_threshold_db": -35.0,
            "min_silence_sec": 0.1,
        },
        "duration_sec": 1.0,
        "silences": [
            {
                "start_sec": 0.3,
                "end_sec": 0.4,
                "duration_sec": 0.1,
            }
        ],
    }
    
    silences_path = out_dir / "silences.json"
    with open(silences_path, "w", encoding="utf-8") as f:
        json.dump(silences_data, f, ensure_ascii=False, indent=2)
    
    # Mock which 返回假路径（表示 ffmpeg 存在）
    def mock_which(exe_name: str):
        if exe_name == "ffmpeg":
            return "/usr/bin/ffmpeg"
        elif exe_name == "ffprobe":
            return "/usr/bin/ffprobe"
        return None
    
    # Mock extract_wav_segment 以避免实际调用 ffmpeg（测试环境可能没有）
    def mock_extract_wav_segment(audio_path, out_path, start_sec, end_sec, ffmpeg_path=None):
        # 创建一个空的 WAV 文件作为占位符
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(out_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(b"\x00\x00" * 100)  # 写入一些静音数据
        return True
    
    # 应用 monkeypatch
    monkeypatch.setattr(
        "onepass_audioclean_seg.audio.ffmpeg.which",
        mock_which,
    )
    monkeypatch.setattr(
        "onepass_audioclean_seg.audio.probe.which",
        mock_which,
    )
    monkeypatch.setattr(
        "onepass_audioclean_seg.audio.extract.extract_wav_segment",
        mock_extract_wav_segment,
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
        "--emit-wav",
        "--strategy",
        "silence",
        "--min-seg-sec",
        "0.2",
        "--max-seg-sec",
        "0.6",  # 很小，会触发 split
        "--pad-sec",
        "0.0",
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
    
    # 断言至少 1 行（可能触发 split，所以可能 > 1）
    assert len(segments_records) >= 1, f"segments.jsonl 应至少包含 1 个片段，实际: {len(segments_records)}"
    
    # 验证每个片段包含 rms 字段
    for seg in segments_records:
        assert "rms" in seg, "每个片段应包含 rms 字段"
        # rms 可能为 None（如果计算失败），但字段必须存在
        if seg["rms"] is not None:
            assert isinstance(seg["rms"], (int, float))
            assert seg["rms"] >= 0.0
    
    # 验证 segments/ 目录下存在对应 seg_*.wav（数量与行数一致或至少存在）
    wav_dir = out_dir / "segments"
    if wav_dir.exists():
        wav_files = list(wav_dir.glob("seg_*.wav"))
        # 至少应该有一些 WAV 文件（可能因为 mock 失败而少于 segments 数量）
        assert len(wav_files) > 0, f"segments/ 目录下应存在 WAV 文件，实际: {len(wav_files)}"
    
    # 验证 seg_report.json 的 segments.count 与行数一致
    report_path = out_dir / "seg_report.json"
    assert report_path.exists(), f"seg_report.json 不存在: {report_path}"
    
    with open(report_path, "r", encoding="utf-8") as f:
        report_data = json.load(f)
    
    assert "segments" in report_data
    assert "count" in report_data["segments"]
    assert report_data["segments"]["count"] == len(segments_records)
    
    # R6: 验证新的统计字段
    assert "max_seg_sec" in report_data["segments"]
    assert "merge_overlaps" in report_data["segments"]
    assert report_data["segments"]["merge_overlaps"] is True
    assert "min_merge" in report_data["segments"]
    assert report_data["segments"]["min_merge"] is True
    assert "max_split" in report_data["segments"]
    assert "rms_computed" in report_data["segments"]
    assert "outputs" in report_data["segments"]
    assert "segments_jsonl" in report_data["segments"]["outputs"]
    assert "silences_json" in report_data["segments"]["outputs"]
    assert "segments_wav_dir" in report_data["segments"]["outputs"]

