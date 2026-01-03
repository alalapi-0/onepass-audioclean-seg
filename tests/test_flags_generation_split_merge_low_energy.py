"""测试 R10: flags 生成（split/merge/low_energy）"""

import tempfile
from pathlib import Path

import pytest

from onepass_audioclean_seg.io.segments import SegmentRecord, write_segments_jsonl
from onepass_audioclean_seg.pipeline.segment_flags import (
    compute_flags_for_segment,
    track_postprocess_history,
)


def test_flags_split_from_long():
    """测试 split 产生的段包含 split_from_long flag"""
    segments_before = [(0.0, 10.0)]
    segments_after = [(0.0, 3.0), (3.0, 6.0), (6.0, 9.0), (9.0, 10.0)]
    
    flags_map = track_postprocess_history(segments_before, segments_after, "split")
    
    # 所有 after 段都应该有 split_from_long flag
    for seg in segments_after:
        assert seg in flags_map
        assert "split_from_long" in flags_map[seg]


def test_flags_merged_short():
    """测试 merge 产生的段包含 merged_short flag"""
    segments_before = [(0.0, 0.3), (0.5, 2.0)]
    segments_after = [(0.0, 2.0)]
    
    flags_map = track_postprocess_history(segments_before, segments_after, "merge")
    
    # after 段应该由多个 before 段合并，有 merged_short flag
    assert (0.0, 2.0) in flags_map
    assert "merged_short" in flags_map[(0.0, 2.0)]


def test_flags_edge_clipped():
    """测试 edge_clipped flag（start==0 或 end==duration）"""
    duration_sec = 10.0
    
    # start == 0
    seg1 = (0.0, 5.0)
    flags1 = compute_flags_for_segment(seg1, duration_sec, rms=None, low_energy_rms_threshold=0.01)
    assert "edge_clipped" in flags1
    
    # end == duration
    seg2 = (5.0, 10.0)
    flags2 = compute_flags_for_segment(seg2, duration_sec, rms=None, low_energy_rms_threshold=0.01)
    assert "edge_clipped" in flags2
    
    # 中间段不应有 edge_clipped
    seg3 = (2.0, 8.0)
    flags3 = compute_flags_for_segment(seg3, duration_sec, rms=None, low_energy_rms_threshold=0.01)
    assert "edge_clipped" not in flags3


def test_flags_low_energy():
    """测试 low_energy flag（rms < threshold）"""
    duration_sec = 10.0
    threshold = 0.01
    
    # rms < threshold
    seg1 = (0.0, 5.0)
    flags1 = compute_flags_for_segment(seg1, duration_sec, rms=0.005, low_energy_rms_threshold=threshold)
    assert "low_energy" in flags1
    
    # rms >= threshold
    seg2 = (5.0, 10.0)
    flags2 = compute_flags_for_segment(seg2, duration_sec, rms=0.02, low_energy_rms_threshold=threshold)
    assert "low_energy" not in flags2
    
    # rms is None
    seg3 = (0.0, 5.0)
    flags3 = compute_flags_for_segment(seg3, duration_sec, rms=None, low_energy_rms_threshold=threshold)
    assert "low_energy" not in flags3


def test_flags_combined():
    """测试多个 flags 的组合"""
    duration_sec = 10.0
    threshold = 0.01
    
    # split + edge_clipped + low_energy
    history_flags = ["split_from_long"]
    seg = (0.0, 3.0)
    flags = compute_flags_for_segment(
        seg, duration_sec, rms=0.005, low_energy_rms_threshold=threshold, history_flags=history_flags
    )
    
    assert "split_from_long" in flags
    assert "edge_clipped" in flags
    assert "low_energy" in flags


def test_segment_record_flags_serialization():
    """测试 SegmentRecord 的 flags 序列化（按固定顺序排序）"""
    with tempfile.TemporaryDirectory() as tmpdir:
        out_dir = Path(tmpdir)
        
        # 创建带 flags 的 SegmentRecord
        record = SegmentRecord(
            id="seg_000001",
            start_sec=0.0,
            end_sec=5.0,
            duration_sec=5.0,
            source_audio="/path/to/audio.wav",
            flags=["low_energy", "split_from_long", "edge_clipped", "merged_short"],
        )
        
        # 写入并读取
        write_segments_jsonl(out_dir / "segments.jsonl", [record])
        
        import json
        with open(out_dir / "segments.jsonl", "r", encoding="utf-8") as f:
            line = f.readline()
            data = json.loads(line)
        
        # flags 应该按固定顺序排序
        expected_order = ["split_from_long", "merged_short", "edge_clipped", "low_energy"]
        assert data["flags"] == expected_order

