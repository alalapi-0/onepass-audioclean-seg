"""测试 segments.jsonl 包含 strategy 字段"""

import json
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import pytest


def create_test_wav(path: Path, duration_sec: float = 2.0, amplitude: float = 0.5):
    """创建测试 WAV 文件"""
    import array
    
    sample_rate = 16000
    n_samples = int(duration_sec * sample_rate)
    sample_value = int(amplitude * 32767)
    audio_data = array.array("h", [sample_value] * n_samples)
    
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(audio_data.tobytes())


def test_segments_include_strategy_field_silence():
    """测试 silence 策略生成的 segments.jsonl 包含 strategy 字段"""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        workdir = tmpdir_path / "workdir"
        workdir.mkdir()
        out_root = tmpdir_path / "out_root"
        
        # 创建测试音频
        audio_path = workdir / "audio.wav"
        create_test_wav(audio_path, duration_sec=2.0, amplitude=0.5)
        
        # 运行 CLI 命令（silence 策略）
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "onepass_audioclean_seg",
                "segment",
                "--in",
                str(workdir),
                "--out",
                str(out_root),
                "--out-mode",
                "out_root",
                "--strategy",
                "silence",
                "--emit-segments",
            ],
            capture_output=True,
            text=True,
        )
        
        # 跳过如果 ffmpeg 不存在
        if result.returncode != 0 and "ffmpeg" in result.stderr.lower():
            pytest.skip("ffmpeg 不存在，跳过 silence 策略测试")
        
        assert result.returncode == 0, f"返回码应为 0，实际为 {result.returncode}，stderr: {result.stderr}"
        
        # 验证 segments.jsonl
        out_dir = out_root / workdir.name / "seg"
        segments_path = out_dir / "segments.jsonl"
        assert segments_path.exists(), f"segments.jsonl 应存在: {segments_path}"
        
        with open(segments_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    segment = json.loads(line)
                    assert "strategy" in segment, "每个 segment 应包含 strategy 字段"
                    assert segment["strategy"] == "silence", f"strategy 应为 'silence'，实际: {segment.get('strategy')}"


def test_segments_include_strategy_field_energy():
    """测试 energy 策略生成的 segments.jsonl 包含 strategy 字段"""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        workdir = tmpdir_path / "workdir"
        workdir.mkdir()
        out_root = tmpdir_path / "out_root"
        
        # 创建测试音频
        audio_path = workdir / "audio.wav"
        create_test_wav(audio_path, duration_sec=2.0, amplitude=0.5)
        
        # 运行 CLI 命令（energy 策略）
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "onepass_audioclean_seg",
                "segment",
                "--in",
                str(workdir),
                "--out",
                str(out_root),
                "--out-mode",
                "out_root",
                "--strategy",
                "energy",
                "--emit-segments",
            ],
            capture_output=True,
            text=True,
        )
        
        assert result.returncode == 0, f"返回码应为 0，实际为 {result.returncode}，stderr: {result.stderr}"
        
        # 验证 segments.jsonl
        out_dir = out_root / workdir.name / "seg"
        segments_path = out_dir / "segments.jsonl"
        assert segments_path.exists(), f"segments.jsonl 应存在: {segments_path}"
        
        with open(segments_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    segment = json.loads(line)
                    assert "strategy" in segment, "每个 segment 应包含 strategy 字段"
                    assert segment["strategy"] == "energy", f"strategy 应为 'energy'，实际: {segment.get('strategy')}"

