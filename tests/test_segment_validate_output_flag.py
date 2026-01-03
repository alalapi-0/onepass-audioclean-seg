"""测试 segment 命令的 --validate-output 选项"""

import json
import tempfile
import wave
from pathlib import Path

import pytest

from onepass_audioclean_seg.cli import main


def create_minimal_wav(file_path: Path, duration_sec: float = 0.1):
    """创建最小有效 WAV 文件"""
    sample_rate = 16000
    num_samples = int(sample_rate * duration_sec)
    
    with wave.open(str(file_path), "wb") as wav_file:
        wav_file.setnchannels(1)  # 单声道
        wav_file.setsampwidth(2)  # 16-bit
        wav_file.setframerate(sample_rate)
        
        # 写入静音数据（全零）
        silence_data = b"\x00\x00" * num_samples
        wav_file.writeframes(silence_data)


def test_segment_validate_output_flag(monkeypatch, tmp_path):
    """测试 segment --emit-segments --validate-output 生成 run_summary.json 并执行验证"""
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
    
    # 运行 CLI（带 --validate-output）
    argv = [
        "segment",
        "--in",
        str(workdir),
        "--out",
        str(out_root),
        "--out-mode",
        "out_root",
        "--emit-segments",
        "--validate-output",
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
    
    # 断言 run_summary.json 存在
    run_summary_path = out_root / "run_summary.json"
    assert run_summary_path.exists(), f"run_summary.json 不存在: {run_summary_path}"
    
    # 读取并验证 run_summary.json
    with open(run_summary_path, "r", encoding="utf-8") as f:
        summary = json.load(f)
    
    # 验证 run_summary 字段
    assert "run_id" in summary
    assert "started_at" in summary
    assert "finished_at" in summary
    assert "cli_args" in summary
    assert "counts" in summary
    assert "totals" in summary
    assert "failures" in summary
    assert "dry_run" in summary
    
    # 验证 counts
    counts = summary["counts"]
    assert "jobs_total" in counts
    assert "jobs_planned" in counts
    assert "jobs_analyzed" in counts
    assert "jobs_emitted" in counts
    assert "jobs_failed" in counts
    assert "jobs_skipped" in counts
    
    # 验证 totals
    totals = summary["totals"]
    assert "speech_total_sec" in totals
    assert "silences_total_sec" in totals
    
    # 验证 counts 合理
    assert counts["jobs_total"] >= 1
    assert counts["jobs_emitted"] >= 1
    
    # 验证 validate 行为在 stdout 有体现（需要通过 subprocess 运行才能看到）
    # 这里我们只验证文件存在和结构正确

