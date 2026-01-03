"""测试 CLI emit-segments 使用 energy 策略时不需要 ffmpeg"""

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


def test_cli_emit_segments_energy_no_ffmpeg(monkeypatch):
    """测试使用 energy 策略时，即使 ffmpeg 缺失也能运行
    
    通过 monkeypatch 让 which("ffmpeg") 返回 None，但 energy 策略不应受影响。
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        workdir = tmpdir_path / "workdir"
        workdir.mkdir()
        out_root = tmpdir_path / "out_root"
        
        # 创建测试音频
        audio_path = workdir / "audio.wav"
        create_test_wav(audio_path, duration_sec=2.0, amplitude=0.5)
        
        # monkeypatch which("ffmpeg") 和 which("ffprobe") 返回 None
        # energy 策略不需要 ffmpeg/ffprobe（duration 可以从 WAV 文件直接计算）
        def mock_which(name):
            if name in ("ffmpeg", "ffprobe"):
                return None
            # 对于其他命令，使用真实路径查找
            import shutil
            return shutil.which(name)
        
        import onepass_audioclean_seg.audio.ffmpeg
        monkeypatch.setattr(onepass_audioclean_seg.audio.ffmpeg, "which", mock_which)
        
        # 同时 monkeypatch probe 模块中的 which
        import onepass_audioclean_seg.audio.probe
        monkeypatch.setattr(onepass_audioclean_seg.audio.probe, "which", mock_which)
        
        # 运行 CLI 命令
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
        
        # 断言：应成功（返回码 0）
        assert result.returncode == 0, f"返回码应为 0，实际为 {result.returncode}，stderr: {result.stderr}"
        
        # 断言：应生成 segments.jsonl
        out_dir = out_root / workdir.name / "seg"
        segments_path = out_dir / "segments.jsonl"
        assert segments_path.exists(), f"segments.jsonl 应存在: {segments_path}"
        
        # 验证 segments.jsonl 内容
        with open(segments_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            assert len(lines) > 0, "segments.jsonl 应至少包含 1 行"
            
            # 验证第一行包含 strategy 字段
            first_line = json.loads(lines[0])
            assert "strategy" in first_line, "segments.jsonl 应包含 strategy 字段"
            assert first_line["strategy"] == "energy", f"strategy 应为 'energy'，实际: {first_line['strategy']}"
        
        # 断言：应生成 energy.json
        energy_path = out_dir / "energy.json"
        assert energy_path.exists(), f"energy.json 应存在: {energy_path}"

