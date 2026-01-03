"""测试补集生成语音片段的基本功能"""

import pytest

from onepass_audioclean_seg.pipeline.segments_from_silence import (
    complement_to_speech_segments,
    normalize_intervals,
)
from onepass_audioclean_seg.strategies.silence_ffmpeg import SilenceInterval


def test_complement_segments_basic():
    """测试基本补集生成
    
    duration=10.0
    silences=[(0.0,0.5),(2.0,2.5),(9.0,10.0)]
    补集应为 [(0.5,2.0),(2.5,9.0)]
    """
    duration = 10.0
    silences = [
        SilenceInterval(start_sec=0.0, end_sec=0.5, duration_sec=0.5),
        SilenceInterval(start_sec=2.0, end_sec=2.5, duration_sec=0.5),
        SilenceInterval(start_sec=9.0, end_sec=10.0, duration_sec=1.0),
    ]
    
    # 规范化（虽然这里已经排序且不重叠，但保险起见）
    normalized = normalize_intervals(silences, duration)
    
    # 生成补集
    segments = complement_to_speech_segments(normalized, duration)
    
    # 断言结果
    assert len(segments) == 2
    assert segments[0] == (0.5, 2.0)
    assert segments[1] == (2.5, 9.0)
    
    # 验证所有时间都是 round(3)
    for start, end in segments:
        assert start == round(start, 3)
        assert end == round(end, 3)


def test_complement_segments_no_silences():
    """测试没有静音的情况（整个音频都是语音）"""
    duration = 10.0
    silences = []
    
    normalized = normalize_intervals(silences, duration)
    segments = complement_to_speech_segments(normalized, duration)
    
    assert len(segments) == 1
    assert segments[0] == (0.0, 10.0)


def test_complement_segments_all_silence():
    """测试整个音频都是静音的情况（没有语音段）"""
    duration = 10.0
    silences = [
        SilenceInterval(start_sec=0.0, end_sec=10.0, duration_sec=10.0),
    ]
    
    normalized = normalize_intervals(silences, duration)
    segments = complement_to_speech_segments(normalized, duration)
    
    assert len(segments) == 0


def test_complement_segments_start_with_silence():
    """测试开头是静音的情况"""
    duration = 10.0
    silences = [
        SilenceInterval(start_sec=0.0, end_sec=1.0, duration_sec=1.0),
        SilenceInterval(start_sec=5.0, end_sec=6.0, duration_sec=1.0),
    ]
    
    normalized = normalize_intervals(silences, duration)
    segments = complement_to_speech_segments(normalized, duration)
    
    assert len(segments) == 2
    assert segments[0] == (1.0, 5.0)
    assert segments[1] == (6.0, 10.0)

