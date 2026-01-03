"""测试 R10: timeline.json 导出"""

import json
import tempfile
from pathlib import Path

from onepass_audioclean_seg.io.exports import export_timeline_json
from onepass_audioclean_seg.io.segments import SegmentRecord


def test_export_timeline_json_structure():
    """测试 timeline.json 结构符合预期"""
    with tempfile.TemporaryDirectory() as tmpdir:
        out_dir = Path(tmpdir)
        audio_path = Path("/path/to/audio.wav")
        
        segments_records = [
            SegmentRecord(
                id="seg_000001",
                start_sec=1.0,
                end_sec=3.0,
                duration_sec=2.0,
                source_audio=str(audio_path),
                rms=0.05,
                flags=["split_from_long"],
            ),
            SegmentRecord(
                id="seg_000002",
                start_sec=5.0,
                end_sec=7.0,
                duration_sec=2.0,
                source_audio=str(audio_path),
                rms=0.03,
                flags=[],
            ),
        ]
        
        timeline_path = export_timeline_json(
            out_dir=out_dir,
            segments_records=segments_records,
            audio_path=audio_path,
            duration_sec=10.0,
            strategy="energy",
            auto_strategy=None,
            params={},
        )
        
        assert timeline_path.exists()
        
        # 读取并验证结构
        with open(timeline_path, "r", encoding="utf-8") as f:
            timeline = json.load(f)
        
        assert timeline["version"] == "timeline.v1"
        assert timeline["audio_path"] == str(audio_path.resolve())
        assert timeline["duration_sec"] == 10.0
        assert timeline["strategy"] == "energy"
        assert "tracks" in timeline
        assert len(timeline["tracks"]) == 2
        
        # 验证 segments track
        segments_track = timeline["tracks"][0]
        assert segments_track["name"] == "auto_segments"
        assert segments_track["type"] == "segments"
        assert len(segments_track["items"]) == 2
        
        # 验证 items 按 start_sec 排序
        items = segments_track["items"]
        assert items[0]["start_sec"] <= items[1]["start_sec"]
        
        # 验证第一个 item 的字段
        item1 = items[0]
        assert item1["id"] == "seg_000001"
        assert item1["start_sec"] == 1.0
        assert item1["end_sec"] == 3.0
        assert item1["duration_sec"] == 2.0
        assert item1["flags"] == ["split_from_long"]
        assert item1["rms"] == 0.05


def test_export_timeline_json_items_sorted():
    """测试 timeline.json 的 items 按 start_sec 排序"""
    with tempfile.TemporaryDirectory() as tmpdir:
        out_dir = Path(tmpdir)
        audio_path = Path("/path/to/audio.wav")
        
        # 故意打乱顺序
        segments_records = [
            SegmentRecord(
                id="seg_000002",
                start_sec=5.0,
                end_sec=7.0,
                duration_sec=2.0,
                source_audio=str(audio_path),
            ),
            SegmentRecord(
                id="seg_000001",
                start_sec=1.0,
                end_sec=3.0,
                duration_sec=2.0,
                source_audio=str(audio_path),
            ),
        ]
        
        timeline_path = export_timeline_json(
            out_dir=out_dir,
            segments_records=segments_records,
            audio_path=audio_path,
            duration_sec=10.0,
            strategy="silence",
            auto_strategy=None,
            params={},
        )
        
        with open(timeline_path, "r", encoding="utf-8") as f:
            timeline = json.load(f)
        
        items = timeline["tracks"][0]["items"]
        # 验证已排序
        for i in range(len(items) - 1):
            assert items[i]["start_sec"] <= items[i + 1]["start_sec"]

