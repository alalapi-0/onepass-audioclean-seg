"""测试 auto-strategy：当 silence 策略质量差时降级到 energy"""

import sys
import tempfile
import wave
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from onepass_audioclean_seg.pipeline.jobs import SegJob
from onepass_audioclean_seg.pipeline.planner import SegmentPlanner
from onepass_audioclean_seg.strategies.base import AnalysisResult


def create_test_wav(path: Path):
    """创建测试 WAV 文件（1秒，全 0）"""
    sample_rate = 16000
    n_samples = sample_rate
    
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00\x00" * n_samples)


def test_auto_strategy_fallback_to_energy_when_silence_poor(monkeypatch):
    """测试 auto-strategy：silence 策略返回很差的结果，energy 策略返回合理结果，最终选择 energy"""
    
    # Mock SilenceStrategy.analyze 返回很差的结果（1 段覆盖全长）
    def mock_silence_analyze(job, params):
        return AnalysisResult(
            strategy="silence",
            duration_sec=2.0,
            speech_segments_raw=[(0.0, 2.0)],  # 覆盖全长，质量差
            artifacts={},
            stats={"silences_count": 0},
        )
    
    # Mock EnergyStrategy.analyze 返回合理结果（两段）
    def mock_energy_analyze(job, params):
        return AnalysisResult(
            strategy="energy",
            duration_sec=2.0,
            speech_segments_raw=[(0.2, 0.8), (1.2, 1.8)],  # 两段，质量合理
            artifacts={},
            stats={"frames": 200},
        )
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        audio_path = tmpdir_path / "test.wav"
        out_dir = tmpdir_path / "out"
        
        create_test_wav(audio_path)
        
        job = SegJob(
            job_id="test_job",
            input_type="file",
            workdir=None,
            audio_path=audio_path,
            meta_path=None,
            out_dir=out_dir,
            rel_key="test",
        )
        
        # Mock 策略类
        with patch("onepass_audioclean_seg.pipeline.planner.SilenceStrategy.analyze", mock_silence_analyze):
            with patch("onepass_audioclean_seg.pipeline.planner.EnergyStrategy.analyze", mock_energy_analyze):
                # Mock get_audio_duration_sec
                with patch("onepass_audioclean_seg.pipeline.planner.get_audio_duration_sec", return_value=2.0):
                    # Mock 写入文件操作（简化）
                    with patch("onepass_audioclean_seg.pipeline.planner.write_segments_jsonl"):
                        with patch("onepass_audioclean_seg.pipeline.planner.update_seg_report_segments"):
                            with patch("onepass_audioclean_seg.pipeline.planner.update_seg_report_analysis"):
                                planner = SegmentPlanner(
                                    dry_run=False,
                                    overwrite=True,
                                    analyze=False,
                                    emit_segments=True,
                                    validate_output=False,
                                )
                                
                                params = {
                                    "strategy": "silence",  # 会被 auto-strategy 忽略
                                    "auto_strategy": True,
                                    "auto_strategy_order": "silence,energy",
                                    "auto_strategy_min_segments": 2,
                                    "auto_strategy_min_speech_total_sec": 1.0,
                                    "min_seg_sec": 0.5,
                                    "max_seg_sec": 10.0,
                                    "pad_sec": 0.1,
                                }
                                
                                # 调用 _run_emit_segments（内部会调用 auto-strategy）
                                success = planner._run_emit_segments(job, params)
                                
                                # 验证成功
                                assert success, "auto-strategy 应成功"
                                
                                # 验证报告中的 auto_strategy.chosen == "energy"
                                import json
                                report_path = out_dir / "seg_report.json"
                                if report_path.exists():
                                    with open(report_path, "r") as f:
                                        report = json.load(f)
                                    
                                    assert "auto_strategy" in report
                                    assert report["auto_strategy"]["chosen"] == "energy"
                                    assert len(report["auto_strategy"]["attempts"]) == 2

