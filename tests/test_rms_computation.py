"""测试 RMS 计算功能"""

import array
import tempfile
import wave
from pathlib import Path

import pytest

from onepass_audioclean_seg.audio.features import compute_rms, rms_to_db


def create_test_wav(path: Path, duration_sec: float, sample_rate: int = 16000, silent_first_half: bool = True):
    """创建测试 WAV 文件
    
    Args:
        path: 输出文件路径
        duration_sec: 音频时长（秒）
        sample_rate: 采样率（默认 16000）
        silent_first_half: 如果 True，前一半为静音（全 0），后一半为常量幅度
    """
    n_frames = int(duration_sec * sample_rate)
    
    # 生成音频数据
    if silent_first_half:
        # 前一半全 0（静音），后一半固定幅度（如 10000）
        half = n_frames // 2
        audio_data = array.array("h", [0] * half + [10000] * (n_frames - half))
    else:
        # 全部固定幅度
        audio_data = array.array("h", [10000] * n_frames)
    
    # 写入 WAV 文件
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)  # 单声道
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        wf.writeframes(audio_data.tobytes())


def test_rms_computation_silent_segment():
    """测试静音段的 RMS 计算"""
    with tempfile.TemporaryDirectory() as tmpdir:
        wav_path = Path(tmpdir) / "test.wav"
        create_test_wav(wav_path, duration_sec=1.0, silent_first_half=True)
        
        # 计算前 0.5s（静音段）的 RMS
        rms = compute_rms(wav_path, start_sec=0.0, end_sec=0.5)
        
        assert rms is not None
        assert rms >= 0.0
        assert rms < 0.01  # 静音段 RMS 应该接近 0


def test_rms_computation_non_silent_segment():
    """测试非静音段的 RMS 计算"""
    with tempfile.TemporaryDirectory() as tmpdir:
        wav_path = Path(tmpdir) / "test.wav"
        create_test_wav(wav_path, duration_sec=1.0, silent_first_half=True)
        
        # 计算后 0.5s（非静音段）的 RMS
        rms = compute_rms(wav_path, start_sec=0.5, end_sec=1.0)
        
        assert rms is not None
        assert rms > 0.0
        # 常量幅度 10000 的 RMS 约为 10000/32768 ≈ 0.305
        assert 0.2 < rms < 0.4


def test_rms_computation_full_segment():
    """测试完整段的 RMS 计算"""
    with tempfile.TemporaryDirectory() as tmpdir:
        wav_path = Path(tmpdir) / "test.wav"
        create_test_wav(wav_path, duration_sec=1.0, silent_first_half=False)
        
        # 计算完整段的 RMS
        rms = compute_rms(wav_path, start_sec=0.0, end_sec=1.0)
        
        assert rms is not None
        assert rms > 0.0


def test_rms_to_db():
    """测试 RMS 转 dB"""
    # 测试正常值
    rms = 0.1
    db = rms_to_db(rms)
    assert db < 0  # dB 通常为负值
    
    # 测试很小的值
    rms = 1e-6
    db = rms_to_db(rms)
    assert db < -100  # 很小的 RMS 对应很小的 dB
    
    # 测试接近 0 的值
    rms = 0.0
    db = rms_to_db(rms)
    assert db < -200  # 0 对应非常小的 dB


def test_rms_computation_invalid_range():
    """测试无效时间范围"""
    with tempfile.TemporaryDirectory() as tmpdir:
        wav_path = Path(tmpdir) / "test.wav"
        create_test_wav(wav_path, duration_sec=1.0)
        
        # 无效范围：end <= start
        rms = compute_rms(wav_path, start_sec=0.5, end_sec=0.3)
        assert rms is None
        
        # 无效范围：start < 0
        rms = compute_rms(wav_path, start_sec=-0.1, end_sec=0.5)
        assert rms is None

