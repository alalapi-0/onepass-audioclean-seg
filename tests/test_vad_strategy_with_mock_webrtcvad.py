"""测试 VAD 策略（使用 mock webrtcvad）"""

import sys
import tempfile
import wave
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from onepass_audioclean_seg.pipeline.jobs import SegJob
from onepass_audioclean_seg.strategies.vad_webrtc import VadStrategy


@pytest.fixture
def temp_wav_file():
    """创建一个临时 WAV 文件（1秒 PCM16 mono 16000Hz，全 0）"""
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        wav_path = Path(f.name)
    
    # 写入 1 秒的静音（全 0）
    sample_rate = 16000
    duration_sec = 1.0
    n_samples = int(sample_rate * duration_sec)
    
    with wave.open(str(wav_path), "wb") as wf:
        wf.setnchannels(1)  # mono
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00\x00" * n_samples)  # 全 0（静音）
    
    yield wav_path
    
    # 清理
    if wav_path.exists():
        wav_path.unlink()


@pytest.fixture
def mock_webrtcvad():
    """Mock webrtcvad 模块"""
    fake_module = Mock()
    
    class FakeVad:
        def __init__(self, aggressiveness):
            self.aggressiveness = aggressiveness
            self.call_count = 0
        
        def is_speech(self, frame, sample_rate):
            """返回固定模式：前 10 帧 True，中间 10 帧 False，后 10 帧 True"""
            self.call_count += 1
            frame_idx = self.call_count - 1
            if frame_idx < 10:
                return True
            elif frame_idx < 20:
                return False
            else:
                return True
    
    fake_module.Vad = FakeVad
    return fake_module


def test_vad_strategy_with_mock_webrtcvad(temp_wav_file, mock_webrtcvad, monkeypatch):
    """测试 VAD 策略：mock webrtcvad，验证 speech_segments_raw 输出"""
    # Mock sys.modules 中的 webrtcvad
    monkeypatch.setitem(sys.modules, "webrtcvad", mock_webrtcvad)
    
    # Mock get_pcm16_mono_frames 以避免需要真实音频或 ffmpeg
    frame_ms = 30
    sample_rate = 16000
    frame_bytes = int(sample_rate * frame_ms / 1000 * 2)  # 16-bit = 2 bytes per sample
    
    def mock_get_frames(audio_path, target_sr, frame_ms, ffmpeg_path=None):
        """生成固定数量的帧（30 帧，每帧 frame_bytes 字节）"""
        n_frames = 30
        for _ in range(n_frames):
            yield b"\x00\x00" * (frame_bytes // 2)  # 全 0 帧
    
    with patch("onepass_audioclean_seg.strategies.vad_webrtc.get_pcm16_mono_frames", mock_get_frames):
        # Mock get_audio_duration_sec
        with patch("onepass_audioclean_seg.strategies.vad_webrtc.get_audio_duration_sec", return_value=1.0):
            # 创建 job
            out_dir = Path(tempfile.mkdtemp())
            job = SegJob(
                job_id="test_job",
                input_type="file",
                workdir=None,
                audio_path=temp_wav_file,
                meta_path=None,
                out_dir=out_dir,
                rel_key="test",
            )
            
            # 创建策略并运行
            strategy = VadStrategy()
            params = {
                "vad_aggressiveness": 2,
                "vad_frame_ms": 30,
                "vad_sample_rate": 16000,
                "vad_min_speech_sec": 0.20,
                "min_silence_sec": 0.35,
            }
            
            result = strategy.analyze(job, params)
            
            # 验证结果
            assert result.strategy == "vad"
            assert result.duration_sec == 1.0
            assert len(result.speech_segments_raw) == 2, f"应输出 2 段语音，实际: {len(result.speech_segments_raw)}"
            
            # 验证时间边界（前 10 帧和后 10 帧为语音）
            frame_sec = 30 / 1000.0
            seg1 = result.speech_segments_raw[0]
            seg2 = result.speech_segments_raw[1]
            
            # 第一段：前 10 帧（0-10帧，约 0.0-0.3 秒）
            assert seg1[0] == pytest.approx(0.0, abs=0.01)
            assert seg1[1] == pytest.approx(10 * frame_sec, abs=0.05)
            
            # 第二段：后 10 帧（20-30帧，约 0.6-0.9 秒）
            assert seg2[0] == pytest.approx(20 * frame_sec, abs=0.05)
            assert seg2[1] == pytest.approx(30 * frame_sec, abs=0.05)
            
            # 验证 artifact 已创建
            assert "vad.json" in result.artifacts
            vad_json_path = result.artifacts["vad.json"]
            assert vad_json_path.exists()
            
            # 清理
            import shutil
            shutil.rmtree(out_dir, ignore_errors=True)

