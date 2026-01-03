"""测试 Energy 策略检测两个语音岛"""

import array
import tempfile
import wave
from pathlib import Path

import pytest

from onepass_audioclean_seg.pipeline.jobs import SegJob
from onepass_audioclean_seg.strategies.energy_rms import EnergyStrategy


def create_test_wav(path: Path, segments: list[tuple[float, float, float]]):
    """创建测试 WAV 文件
    
    Args:
        path: 输出文件路径
        segments: [(start_sec, end_sec, amplitude), ...] 列表
                  amplitude 为归一化幅度（0~1），将转换为 int16 范围
    """
    sample_rate = 16000
    duration_sec = max(seg[1] for seg in segments)
    n_samples = int(duration_sec * sample_rate)
    
    # 创建音频数据（初始为静音）
    audio_data = array.array("h", [0] * n_samples)
    
    # 填充各段
    for start_sec, end_sec, amplitude in segments:
        start_sample = int(start_sec * sample_rate)
        end_sample = int(end_sec * sample_rate)
        # 转换为 int16 范围（-32768 到 32767）
        sample_value = int(amplitude * 32767)
        for i in range(start_sample, min(end_sample, n_samples)):
            audio_data[i] = sample_value
    
    # 写入 WAV 文件
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)  # 单声道
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        wf.writeframes(audio_data.tobytes())


def test_energy_strategy_detects_two_speech_islands():
    """测试 Energy 策略检测两个语音岛
    
    构造：
    - 0.0-0.5s: 静音（幅度 0）
    - 0.5-1.0s: 语音（幅度 0.5，RMS 约 0.5）
    - 1.0-1.5s: 静音（幅度 0）
    - 1.5-2.0s: 语音（幅度 0.5，RMS 约 0.5）
    
    设置 threshold_rms=0.02，应能检测到两个语音段。
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        audio_path = tmpdir_path / "test.wav"
        out_dir = tmpdir_path / "out"
        
        # 创建测试音频
        create_test_wav(
            audio_path,
            [
                (0.0, 0.5, 0.0),  # 静音
                (0.5, 1.0, 0.5),  # 语音（幅度 0.5）
                (1.0, 1.5, 0.0),  # 静音
                (1.5, 2.0, 0.5),  # 语音（幅度 0.5）
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
            "energy_threshold_rms": 0.02,  # 阈值应低于 0.5 的 RMS
            "energy_min_speech_sec": 0.20,
            "min_silence_sec": 0.35,
        }
        
        result = strategy.analyze(job, params)
        
        # 断言：应检测到 2 个语音段
        assert len(result.speech_segments_raw) == 2, f"应检测到 2 个语音段，实际: {len(result.speech_segments_raw)}"
        
        # 检查边界（允许 1 帧误差，约 0.01s）
        seg1 = result.speech_segments_raw[0]
        seg2 = result.speech_segments_raw[1]
        
        # 第一个段应该在 0.5s 附近开始，1.0s 附近结束
        assert abs(seg1[0] - 0.5) < 0.05, f"第一个段开始时间应为 ~0.5s，实际: {seg1[0]}"
        assert abs(seg1[1] - 1.0) < 0.05, f"第一个段结束时间应为 ~1.0s，实际: {seg1[1]}"
        
        # 第二个段应该在 1.5s 附近开始，2.0s 附近结束
        assert abs(seg2[0] - 1.5) < 0.05, f"第二个段开始时间应为 ~1.5s，实际: {seg2[0]}"
        assert abs(seg2[1] - 2.0) < 0.05, f"第二个段结束时间应为 ~2.0s，实际: {seg2[1]}"
        
        # 验证 strategy 字段
        assert result.strategy == "energy"
        
        # 验证 stats
        assert "frames" in result.stats
        assert result.stats["frames"] > 0

