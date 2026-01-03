"""测试 R10: mask.json 导出（bin 数量验证）"""

import json
import math
import tempfile
from pathlib import Path

from onepass_audioclean_seg.io.exports import export_mask_json
from onepass_audioclean_seg.io.segments import SegmentRecord


def test_export_mask_json_bins_count():
    """测试 mask.json 的 series 长度 = ceil(duration/bin)"""
    with tempfile.TemporaryDirectory() as tmpdir:
        out_dir = Path(tmpdir)
        
        duration_sec = 1.0
        bin_ms = 100.0
        bin_sec = bin_ms / 1000.0
        expected_bins = int(math.ceil(duration_sec / bin_sec))  # ceil(1.0/0.1) = 10
        
        segments_records = [
            SegmentRecord(
                id="seg_000001",
                start_sec=0.0,
                end_sec=0.5,
                duration_sec=0.5,
                source_audio="/path/to/audio.wav",
                rms=0.05,
            ),
            SegmentRecord(
                id="seg_000002",
                start_sec=0.6,
                end_sec=1.0,
                duration_sec=0.4,
                source_audio="/path/to/audio.wav",
                rms=0.03,
            ),
        ]
        
        mask_path = export_mask_json(
            out_dir=out_dir,
            duration_sec=duration_sec,
            strategy="silence",
            bin_ms=bin_ms,
            segments_records=segments_records,
        )
        
        assert mask_path is not None
        assert mask_path.exists()
        
        # 读取并验证
        with open(mask_path, "r", encoding="utf-8") as f:
            mask = json.load(f)
        
        assert mask["version"] == "mask.v1"
        assert mask["bin_ms"] == 100.0
        assert mask["duration_sec"] == 1.0
        assert "series" in mask
        
        # 验证 series 长度
        assert len(mask["series"]) == expected_bins


def test_export_mask_json_t_sec_increments():
    """测试 mask.json 的 t_sec 从 0.0 开始递增，最后一个 < duration"""
    with tempfile.TemporaryDirectory() as tmpdir:
        out_dir = Path(tmpdir)
        
        duration_sec = 1.0
        bin_ms = 100.0
        
        segments_records = [
            SegmentRecord(
                id="seg_000001",
                start_sec=0.0,
                end_sec=1.0,
                duration_sec=1.0,
                source_audio="/path/to/audio.wav",
            ),
        ]
        
        mask_path = export_mask_json(
            out_dir=out_dir,
            duration_sec=duration_sec,
            strategy="silence",
            bin_ms=bin_ms,
            segments_records=segments_records,
        )
        
        assert mask_path is not None
        
        with open(mask_path, "r", encoding="utf-8") as f:
            mask = json.load(f)
        
        series = mask["series"]
        
        # 验证第一个 t_sec = 0.0
        assert series[0]["t_sec"] == 0.0
        
        # 验证 t_sec 递增
        for i in range(len(series) - 1):
            assert series[i]["t_sec"] < series[i + 1]["t_sec"]
        
        # 验证最后一个 t_sec < duration
        assert series[-1]["t_sec"] < duration_sec

