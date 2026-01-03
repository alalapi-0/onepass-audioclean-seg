"""测试 pad 后合并重叠/粘连的段"""

import pytest

from onepass_audioclean_seg.pipeline.segments_from_silence import (
    apply_padding_and_clip,
    merge_overlaps,
)


def test_merge_overlaps_after_padding():
    """测试 pad 后相邻段重叠/粘连合并
    
    segments 初始 [(0.5, 1.0), (1.0, 1.5)] pad=0.1
    pad 后会重叠/粘连: [(0.4, 1.1), (0.9, 1.6)]
    merge_overlaps 后应为单段 (0.4, 1.6)（按 round(3)）
    """
    segments = [(0.5, 1.0), (1.0, 1.5)]
    pad_sec = 0.1
    duration_sec = 10.0
    
    # 应用填充
    padded = apply_padding_and_clip(segments, pad_sec, duration_sec)
    
    # 验证填充后的结果
    assert len(padded) == 2
    assert padded[0] == (0.4, 1.1)  # 0.5-0.1, 1.0+0.1
    assert padded[1] == (0.9, 1.6)  # 1.0-0.1, 1.5+0.1
    
    # 合并重叠
    merged = merge_overlaps(padded, gap_merge_sec=0.0, overlap_tolerance=1e-3)
    
    # 验证合并后的结果
    assert len(merged) == 1
    assert merged[0] == (0.4, 1.6)  # 合并后应为 (min(0.4,0.9), max(1.1,1.6))
    
    # 验证所有时间都是 round(3)
    for start, end in merged:
        assert start == round(start, 3)
        assert end == round(end, 3)


def test_merge_overlaps_no_overlap():
    """测试没有重叠的情况（不应合并）"""
    segments = [(0.0, 1.0), (2.0, 3.0)]
    merged = merge_overlaps(segments, gap_merge_sec=0.0, overlap_tolerance=1e-3)
    
    assert len(merged) == 2
    assert merged[0] == (0.0, 1.0)
    assert merged[1] == (2.0, 3.0)


def test_merge_overlaps_with_gap_merge():
    """测试 gap_merge_sec > 0 的情况"""
    segments = [(0.0, 1.0), (1.1, 2.0)]  # gap = 0.1
    merged = merge_overlaps(segments, gap_merge_sec=0.15, overlap_tolerance=1e-3)
    
    # gap=0.1 <= gap_merge_sec=0.15，应该合并
    assert len(merged) == 1
    assert merged[0] == (0.0, 2.0)

