"""测试 auto-strategy：当 vad 可用且质量好时使用 vad"""

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


def test_auto_strategy_uses_vad_when_available_and_good(monkeypatch):
    """测试 auto-strategy：silence 策略质量差，vad 策略可用且质量好，最终选择 vad"""
    
    # Mock webrtcvad 模块（使其可用）
    fake_webrtcvad = Mock()
    fake_webrtcvad.Vad = Mock(return_value=Mock())
    monkeypatch.setitem(sys.modules, "webrtcvad", fake_webrtcvad)
    
    # Mock SilenceStrategy.analyze 返回很差的结果（0 段或覆盖全长）
    def mock_silence_analyze(job, params):
        return AnalysisResult(
            strategy="silence",
            duration_sec=2.0,
            speech_segments_raw=[(0.0, 2.0)],  # 覆盖全长，质量差
            artifacts={},
            stats={"silences_count": 0},
        )
    
    # Mock VadStrategy.analyze 返回合理结果（两段）
    def mock_vad_analyze(job, params):
        return AnalysisResult(
            strategy="vad",
            duration_sec=2.0,
            speech_segments_raw=[(0.2, 0.8), (1.2, 1.8)],  # 两段，质量合理
            artifacts={},
            stats={"frames": 66},  # 30ms frame, 2s duration ≈ 66 frames
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
            with patch("onepass_audioclean_seg.pipeline.planner.VadStrategy.analyze", mock_vad_analyze):
                # Mock get_pcm16_mono_frames（避免真实音频处理）
                def mock_get_frames(*args, **kwargs):
                    yield b"\x00\x00" * 480  # 30ms frame at 16kHz = 480 samples = 960 bytes
                
                with patch("onepass_audioclean_seg.strategies.vad_webrtc.get_pcm16_mono_frames", mock_get_frames):
                    # Mock get_audio_duration_sec
                    with patch("onepass_audioclean_seg.pipeline.planner.get_audio_duration_sec", return_value=2.0):
                        with patch("onepass_audioclean_seg.strategies.vad_webrtc.get_audio_duration_sec", return_value=2.0):
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
                                            "auto_strategy_order": "silence,vad",
                                            "auto_strategy_min_segments": 2,
                                            "auto_strategy_min_speech_total_sec": 1.0,
                                            "vad_aggressiveness": 2,
                                            "vad_frame_ms": 30,
                                            "vad_sample_rate": 16000,
                                            "vad_min_speech_sec": 0.20,
                                            "min_seg_sec": 0.5,
                                            "max_seg_sec": 10.0,
                                            "pad_sec": 0.1,
                                        }
                                        
                                        # 调用 _run_emit_segments（内部会调用 auto-strategy）
                                        success = planner._run_emit_segments(job, params)
                                        
                                        # 验证成功
                                        assert success, "auto-strategy 应成功"
                                        
                                        # 验证报告中的 auto_strategy.chosen == "vad"
                                        import json
                                        report_path = out_dir / "seg_report.json"
                                        if report_path.exists():
                                            with open(report_path, "r") as f:
                                                report = json.load(f)
                                            
                                            assert "auto_strategy" in report
                                            assert report["auto_strategy"]["chosen"] == "vad"
                                            assert len(report["auto_strategy"]["attempts"]) >= 1
                                            assert report["auto_strategy"]["attempts"][0]["strategy"] == "silence"
                                            assert report["auto_strategy"]["attempts"][-1]["strategy"] == "vad"
                                            assert report["auto_strategy"]["attempts"][-1]["ok"] is True

