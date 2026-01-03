"""测试通过等长切分来强制最大时长"""

import pytest

from onepass_audioclean_seg.pipeline.segments_from_silence import (
    enforce_max_duration_by_split,
)


def test_max_duration_split_equal():
    """测试等长切分超长段
    
    一个段 (0.0, 10.0) max=3.0
    应切为 ceil(10/3)=4 段，每段约 2.5s
    """
    segments = [(0.0, 10.0)]
    max_seg_sec = 3.0
    min_seg_sec = 0.5
    
    result = enforce_max_duration_by_split(segments, max_seg_sec, min_seg_sec, "equal")
    
    # 验证段数=4
    assert len(result) == 4
    
    # 验证首段 start=0.0
    assert result[0][0] == 0.0
    
    # 验证末段 end=10.0
    assert result[-1][1] == 10.0
    
    # 验证每段 <= 3.0（考虑 round 容差）
    for start, end in result:
        duration = end - start
        assert duration <= 3.0 + 0.01  # 容差 0.01
    
    # 验证所有时间都是 round(3)
    for start, end in result:
        assert start == round(start, 3)
        assert end == round(end, 3)


def test_max_duration_split_no_split_needed():
    """测试不需要切分的情况（所有段都 <= max）"""
    segments = [(0.0, 2.0), (3.0, 5.0)]
    max_seg_sec = 3.0
    min_seg_sec = 0.5
    
    result = enforce_max_duration_by_split(segments, max_seg_sec, min_seg_sec, "equal")
    
    # 所有段都满足，不应切分
    assert len(result) == 2
    assert result[0] == (0.0, 2.0)
    assert result[1] == (3.0, 5.0)


def test_max_duration_split_multiple_segments():
    """测试多个段，部分需要切分"""
    segments = [(0.0, 2.0), (3.0, 10.0)]  # 第二段超长
    max_seg_sec = 3.0
    min_seg_sec = 0.5
    
    result = enforce_max_duration_by_split(segments, max_seg_sec, min_seg_sec, "equal")
    
    # 第一段保留，第二段切分
    assert len(result) > 2
    assert result[0] == (0.0, 2.0)  # 第一段保留
    # 第二段应被切分


def test_max_duration_split_validation():
    """测试参数校验（max_seg_sec < min_seg_sec 应报错）"""
    segments = [(0.0, 10.0)]
    max_seg_sec = 1.0
    min_seg_sec = 2.0
    
    with pytest.raises(ValueError, match="max_seg_sec.*必须.*>=.*min_seg_sec"):
        enforce_max_duration_by_split(segments, max_seg_sec, min_seg_sec, "equal")

