"""测试填充和最小时长过滤功能"""

import pytest

from onepass_audioclean_seg.pipeline.segments_from_silence import (
    apply_padding_and_clip,
    filter_min_duration,
)


def test_padding_and_min_filter():
    """测试填充和最小过滤的组合
    
    segments=[(1.0,1.4),(3.0,5.0)] pad=0.2 duration=10.0
    pad 后第一段变 (0.8,1.6) duration=0.8
    若 min_seg_sec=1.0，则第一段被过滤掉，只剩第二段（pad 后 (2.8,5.2)）
    """
    segments = [(1.0, 1.4), (3.0, 5.0)]
    pad_sec = 0.2
    duration_sec = 10.0
    min_seg_sec = 1.0
    
    # 应用填充
    padded = apply_padding_and_clip(segments, pad_sec, duration_sec)
    
    # 验证填充后的结果
    assert len(padded) == 2
    assert padded[0] == (0.8, 1.6)  # 1.0-0.2=0.8, 1.4+0.2=1.6
    assert padded[1] == (2.8, 5.2)  # 3.0-0.2=2.8, 5.0+0.2=5.2
    
    # 应用最小时长过滤
    filtered = filter_min_duration(padded, min_seg_sec)
    
    # 第一段 duration=0.8 < 1.0，应被过滤
    # 第二段 duration=2.4 >= 1.0，应保留
    assert len(filtered) == 1
    assert filtered[0] == (2.8, 5.2)
    
    # 验证所有时间都是 round(3)
    for start, end in filtered:
        assert start == round(start, 3)
        assert end == round(end, 3)


def test_padding_clip_to_boundary():
    """测试填充时裁剪到边界（0 和 duration）"""
    segments = [(0.5, 1.0), (9.5, 10.0)]
    pad_sec = 1.0
    duration_sec = 10.0
    
    padded = apply_padding_and_clip(segments, pad_sec, duration_sec)
    
    assert len(padded) == 2
    assert padded[0] == (0.0, 2.0)  # 0.5-1.0 被 clip 到 0.0
    assert padded[1] == (8.5, 10.0)  # 9.5+1.0 被 clip 到 10.0


def test_filter_min_duration_edge_case():
    """测试最小时长过滤的边界情况"""
    segments = [(1.0, 1.5), (2.0, 3.0), (4.0, 4.5)]
    min_seg_sec = 1.0
    
    filtered = filter_min_duration(segments, min_seg_sec)
    
    # 第一段 0.5 < 1.0，过滤
    # 第二段 1.0 >= 1.0，保留
    # 第三段 0.5 < 1.0，过滤
    assert len(filtered) == 1
    assert filtered[0] == (2.0, 3.0)


def test_padding_zero():
    """测试 pad_sec=0 的情况（不填充）"""
    segments = [(1.0, 2.0), (3.0, 4.0)]
    pad_sec = 0.0
    duration_sec = 10.0
    
    padded = apply_padding_and_clip(segments, pad_sec, duration_sec)
    
    assert len(padded) == 2
    assert padded[0] == (1.0, 2.0)
    assert padded[1] == (3.0, 4.0)

