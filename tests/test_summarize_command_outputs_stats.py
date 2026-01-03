"""测试 R10: summarize 命令输出统计信息"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from onepass_audioclean_seg.io.segments import SegmentRecord, write_segments_jsonl


def test_summarize_command_outputs_stats():
    """测试 summarize 命令输出包含统计信息"""
    with tempfile.TemporaryDirectory() as tmpdir:
        out_dir = Path(tmpdir)
        segments_file = out_dir / "segments.jsonl"
        
        # 创建测试 segments.jsonl
        segments_records = [
            SegmentRecord(
                id="seg_000001",
                start_sec=1.0,
                end_sec=3.0,
                duration_sec=2.0,
                source_audio="/path/to/audio.wav",
                strategy="energy",
                flags=["split_from_long"],
                rms=0.05,
            ),
            SegmentRecord(
                id="seg_000002",
                start_sec=5.0,
                end_sec=7.0,
                duration_sec=2.0,
                source_audio="/path/to/audio.wav",
                strategy="energy",
                flags=["low_energy"],
                rms=0.005,
            ),
        ]
        
        write_segments_jsonl(segments_file, segments_records)
        
        # 运行 summarize 命令
        result = subprocess.run(
            [sys.executable, "-m", "onepass_audioclean_seg", "summarize", "--in", str(segments_file)],
            capture_output=True,
            text=True,
            cwd=out_dir,
        )
        
        # 验证返回码为 0
        assert result.returncode == 0
        
        # 验证输出包含统计信息
        output = result.stdout
        assert "segments=" in output or "speech_total_sec=" in output


def test_summarize_command_json_output():
    """测试 summarize --json 输出合法 JSON 并包含必要字段"""
    with tempfile.TemporaryDirectory() as tmpdir:
        out_dir = Path(tmpdir)
        segments_file = out_dir / "segments.jsonl"
        
        # 创建测试 segments.jsonl
        segments_records = [
            SegmentRecord(
                id="seg_000001",
                start_sec=1.0,
                end_sec=3.0,
                duration_sec=2.0,
                source_audio="/path/to/audio.wav",
                strategy="energy",
                flags=["split_from_long"],
            ),
        ]
        
        write_segments_jsonl(segments_file, segments_records)
        
        # 运行 summarize --json 命令
        result = subprocess.run(
            [sys.executable, "-m", "onepass_audioclean_seg", "summarize", "--in", str(segments_file), "--json"],
            capture_output=True,
            text=True,
            cwd=out_dir,
        )
        
        # 验证返回码为 0
        assert result.returncode == 0
        
        # 验证输出是合法 JSON
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            pytest.fail("输出不是合法 JSON")
        
        # 验证包含必要字段
        assert "ok" in data
        assert "checked_files" in data
        assert "items" in data
        
        if data["items"]:
            item = data["items"][0]
            assert "path" in item
            assert "stats" in item
            stats = item["stats"]
            assert "count" in stats
            assert "speech_total_sec" in stats


def test_summarize_command_directory_input():
    """测试 summarize 命令对目录输入的处理"""
    with tempfile.TemporaryDirectory() as tmpdir:
        out_dir = Path(tmpdir)
        subdir = out_dir / "subdir"
        subdir.mkdir()
        segments_file = subdir / "segments.jsonl"
        
        # 创建测试 segments.jsonl
        segments_records = [
            SegmentRecord(
                id="seg_000001",
                start_sec=1.0,
                end_sec=3.0,
                duration_sec=2.0,
                source_audio="/path/to/audio.wav",
            ),
        ]
        
        write_segments_jsonl(segments_file, segments_records)
        
        # 运行 summarize 命令（输入目录）
        result = subprocess.run(
            [sys.executable, "-m", "onepass_audioclean_seg", "summarize", "--in", str(out_dir)],
            capture_output=True,
            text=True,
            cwd=out_dir,
        )
        
        # 验证返回码为 0
        assert result.returncode == 0

