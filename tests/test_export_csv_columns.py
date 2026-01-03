"""测试 R10: segments.csv 导出（列名验证）"""

import csv
import tempfile
from pathlib import Path

from onepass_audioclean_seg.io.exports import export_segments_csv
from onepass_audioclean_seg.io.segments import SegmentRecord


def test_export_csv_columns():
    """测试 segments.csv 的列名完全匹配预期"""
    with tempfile.TemporaryDirectory() as tmpdir:
        out_dir = Path(tmpdir)
        
        segments_records = [
            SegmentRecord(
                id="seg_000001",
                start_sec=1.0,
                end_sec=3.0,
                duration_sec=2.0,
                source_audio="/path/to/audio.wav",
                rms=0.05,
                strategy="energy",
                flags=["split_from_long"],
                pre_silence_sec=0.5,
                post_silence_sec=0.3,
            ),
        ]
        
        csv_path = export_segments_csv(out_dir, segments_records)
        
        assert csv_path.exists()
        
        # 读取并验证列名
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
        
        expected_columns = [
            "id",
            "start_sec",
            "end_sec",
            "duration_sec",
            "rms",
            "strategy",
            "flags",
            "pre_silence_sec",
            "post_silence_sec",
            "source_audio",
        ]
        
        assert fieldnames == expected_columns


def test_export_csv_flags_format():
    """测试 segments.csv 的 flags 格式（用 | 拼接）"""
    with tempfile.TemporaryDirectory() as tmpdir:
        out_dir = Path(tmpdir)
        
        segments_records = [
            SegmentRecord(
                id="seg_000001",
                start_sec=1.0,
                end_sec=3.0,
                duration_sec=2.0,
                source_audio="/path/to/audio.wav",
                flags=["split_from_long", "low_energy"],
            ),
            SegmentRecord(
                id="seg_000002",
                start_sec=5.0,
                end_sec=7.0,
                duration_sec=2.0,
                source_audio="/path/to/audio.wav",
                flags=[],  # 无 flags
            ),
        ]
        
        csv_path = export_segments_csv(out_dir, segments_records)
        
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        
        # 验证 flags 格式
        assert rows[0]["flags"] == "split_from_long|low_energy"
        assert rows[1]["flags"] == ""  # 无 flags 为空字符串


def test_export_csv_sorted():
    """测试 segments.csv 按 start_sec 排序"""
    with tempfile.TemporaryDirectory() as tmpdir:
        out_dir = Path(tmpdir)
        
        # 故意打乱顺序
        segments_records = [
            SegmentRecord(
                id="seg_000002",
                start_sec=5.0,
                end_sec=7.0,
                duration_sec=2.0,
                source_audio="/path/to/audio.wav",
            ),
            SegmentRecord(
                id="seg_000001",
                start_sec=1.0,
                end_sec=3.0,
                duration_sec=2.0,
                source_audio="/path/to/audio.wav",
            ),
        ]
        
        csv_path = export_segments_csv(out_dir, segments_records)
        
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        
        # 验证已排序
        assert float(rows[0]["start_sec"]) <= float(rows[1]["start_sec"])

