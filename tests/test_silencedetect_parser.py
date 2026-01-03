"""测试 silencedetect 解析器"""

import pytest

from onepass_audioclean_seg.strategies.silence_ffmpeg import (
    SilenceInterval,
    parse_silencedetect_output,
)


def test_parse_silencedetect_output():
    """测试解析 silencedetect 输出"""
    # 构造示例输出文本
    output_text = """
    [silencedetect @ 0x123456] silence_start: 0.000
    [silencedetect @ 0x123456] silence_end: 0.120 | silence_duration: 0.120
    [silencedetect @ 0x123456] silence_start: 8.500
    [silencedetect @ 0x123456] silence_end: 9.000 | silence_duration: 0.500
    """
    
    audio_duration_sec = 10.0
    
    intervals = parse_silencedetect_output(output_text, audio_duration_sec)
    
    # 断言解析到 2 个区间
    assert len(intervals) == 2
    
    # 断言第一个区间
    assert intervals[0].start_sec == 0.000
    assert intervals[0].end_sec == pytest.approx(0.120, abs=0.001)
    assert intervals[0].duration_sec == pytest.approx(0.120, abs=0.001)
    
    # 断言第二个区间
    assert intervals[1].start_sec == 8.500
    assert intervals[1].end_sec == 9.000
    assert intervals[1].duration_sec == pytest.approx(0.500, abs=0.001)
    
    # 断言所有值都经过 round(3)
    for interval in intervals:
        assert interval.start_sec == round(interval.start_sec, 3)
        assert interval.end_sec == round(interval.end_sec, 3)
        assert interval.duration_sec == round(interval.duration_sec, 3)


def test_parse_silencedetect_output_unclosed_interval():
    """测试未闭合区间的处理"""
    # 只有 start 没有 end
    output_text = """
    [silencedetect @ 0x123456] silence_start: 8.500
    """
    
    audio_duration_sec = 10.0
    
    intervals = parse_silencedetect_output(output_text, audio_duration_sec)
    
    # 应该闭合到 audio_duration_sec
    assert len(intervals) == 1
    assert intervals[0].start_sec == 8.500
    assert intervals[0].end_sec == 10.0
    assert intervals[0].duration_sec == pytest.approx(1.5, abs=0.001)


def test_parse_silencedetect_output_unclosed_no_duration():
    """测试未闭合区间且无 duration 的情况"""
    output_text = """
    [silencedetect @ 0x123456] silence_start: 8.500
    """
    
    intervals = parse_silencedetect_output(output_text, audio_duration_sec=None)
    
    # 应该丢弃未闭合区间
    assert len(intervals) == 0


def test_parse_silencedetect_output_sorted():
    """测试区间排序"""
    output_text = """
    [silencedetect @ 0x123456] silence_start: 8.500
    [silencedetect @ 0x123456] silence_end: 9.000 | silence_duration: 0.500
    [silencedetect @ 0x123456] silence_start: 0.000
    [silencedetect @ 0x123456] silence_end: 0.120 | silence_duration: 0.120
    """
    
    intervals = parse_silencedetect_output(output_text, audio_duration_sec=10.0)
    
    # 应该按 start_sec 排序
    assert len(intervals) == 2
    assert intervals[0].start_sec < intervals[1].start_sec
    assert intervals[0].start_sec == 0.000
    assert intervals[1].start_sec == 8.500

