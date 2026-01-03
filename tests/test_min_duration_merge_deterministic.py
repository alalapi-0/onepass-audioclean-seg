"""测试通过合并短段来强制最小时长的确定性策略"""

import pytest

from onepass_audioclean_seg.pipeline.segments_from_silence import (
    enforce_min_duration_by_merge,
)


def test_min_duration_merge_deterministic():
    """测试短段确定性合并
    
    segments [(0.0,0.4),(0.6,2.0)] min=1.0
    第一段短（0.4 < 1.0），只有右邻，合并后变 (0.0,2.0)
    """
    segments = [(0.0, 0.4), (0.6, 2.0)]
    min_seg_sec = 1.0
    
    result = enforce_min_duration_by_merge(segments, min_seg_sec)
    
    # 验证输出 1 段且 start/end 正确
    assert len(result) == 1
    assert result[0] == (0.0, 2.0)
    
    # 验证所有时间都是 round(3)
    for start, end in result:
        assert start == round(start, 3)
        assert end == round(end, 3)


def test_min_duration_merge_both_neighbors():
    """测试左右邻都存在的情况（优先与 gap 更小的合并）"""
    segments = [(0.0, 0.3), (0.5, 0.8), (1.0, 2.0)]  # 中间段短
    min_seg_sec = 1.0
    
    result = enforce_min_duration_by_merge(segments, min_seg_sec)
    
    # 中间段应该与 gap 更小的邻段合并
    # gap_left = 0.5 - 0.3 = 0.2
    # gap_right = 1.0 - 0.8 = 0.2
    # gap 相等，与右邻合并（按规则）
    assert len(result) == 2
    assert result[0] == (0.0, 0.3)  # 第一段保留
    assert result[1] == (0.5, 2.0)  # 中间段与右邻合并


def test_min_duration_merge_no_neighbors():
    """测试孤立短段（无邻可合并，应丢弃）"""
    segments = [(0.0, 0.3)]  # 只有一个短段
    min_seg_sec = 1.0
    
    result = enforce_min_duration_by_merge(segments, min_seg_sec)
    
    # 孤立短段应被丢弃
    assert len(result) == 0


def test_min_duration_merge_all_satisfy():
    """测试所有段都满足最小时长（不应合并）"""
    segments = [(0.0, 1.5), (2.0, 3.5)]
    min_seg_sec = 1.0
    
    result = enforce_min_duration_by_merge(segments, min_seg_sec)
    
    # 所有段都满足，不应合并
    assert len(result) == 2
    assert result[0] == (0.0, 1.5)
    assert result[1] == (2.0, 3.5)

