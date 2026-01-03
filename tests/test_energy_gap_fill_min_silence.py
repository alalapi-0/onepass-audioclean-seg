"""测试 Energy 策略的最小静音填平功能"""

import array
import tempfile
import wave
from pathlib import Path

import pytest

from onepass_audioclean_seg.pipeline.jobs import SegJob
from onepass_audioclean_seg.strategies.energy_rms import EnergyStrategy


def create_test_wav(path: Path, segments: list[tuple[float, float, float]]):
    """创建测试 WAV 文件"""
    sample_rate = 16000
    duration_sec = max(seg[1] for seg in segments)
    n_samples = int(duration_sec * sample_rate)
    
    audio_data = array.array("h", [0] * n_samples)
    
    for start_sec, end_sec, amplitude in segments:
        start_sample = int(start_sec * sample_rate)
        end_sample = int(end_sec * sample_rate)
        sample_value = int(amplitude * 32767)
        for i in range(start_sample, min(end_sample, n_samples)):
            audio_data[i] = sample_value
    
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(audio_data.tobytes())


def test_energy_gap_fill_min_silence():
    """测试 Energy 策略填平短静音间隙
    
    构造：
    - 0.0-0.5s: 语音（幅度 0.5）
    - 0.5-0.6s: 短静音（0.1s，小于 min_silence_sec=0.35）
    - 0.6-1.0s: 语音（幅度 0.5）
    
    期望：短静音被填平，输出 1 个连续语音段。
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        audio_path = tmpdir_path / "test.wav"
        out_dir = tmpdir_path / "out"
        
        # 创建测试音频
        create_test_wav(
            audio_path,
            [
                (0.0, 0.5, 0.5),  # 语音
                (0.5, 0.6, 0.0),  # 短静音（0.1s）
                (0.6, 1.0, 0.5),  # 语音
            ],
        )
        
        # 创建 job
        job = SegJob(
            job_id="test_job",
            input_type="file",
            workdir=None,
            audio_path=audio_path,
            meta_path=None,
            out_dir=out_dir,
            rel_key="test",
        )
        
        # 创建策略并运行分析
        strategy = EnergyStrategy()
        params = {
            "energy_frame_ms": 30.0,
            "energy_hop_ms": 10.0,
            "energy_smooth_ms": 100.0,
            "energy_threshold_rms": 0.02,
            "energy_min_speech_sec": 0.20,
            "min_silence_sec": 0.35,  # 短静音 0.1s < 0.35s，应被填平
        }
        
        result = strategy.analyze(job, params)
        
        # 断言：应输出 1 个连续语音段（短静音被填平）
        assert len(result.speech_segments_raw) == 1, f"应输出 1 个语音段（短静音被填平），实际: {len(result.speech_segments_raw)}"
        
        seg = result.speech_segments_raw[0]
        # 段应该从接近 0.0 开始，到接近 1.0 结束
        assert seg[0] < 0.1, f"段开始时间应接近 0.0，实际: {seg[0]}"
        assert seg[1] > 0.9, f"段结束时间应接近 1.0，实际: {seg[1]}"
        
        # 验证 duration 接近 1.0s（允许误差）
        duration = seg[1] - seg[0]
        assert duration > 0.8, f"段时长应接近 1.0s，实际: {duration}"

