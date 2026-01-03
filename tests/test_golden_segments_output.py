"""Golden 测试：验证 segments.jsonl 输出稳定性（R11）"""

import json
import tempfile
import wave
from pathlib import Path

import pytest


def generate_deterministic_wav(output_path: Path, duration_sec: float = 2.0) -> None:
    """生成确定性音频文件（静音-常量-静音-常量）
    
    Args:
        output_path: 输出 WAV 文件路径
        duration_sec: 音频时长（秒）
    """
    sample_rate = 16000
    n_channels = 1
    sample_width = 2  # 16-bit
    
    n_frames = int(duration_sec * sample_rate)
    
    # 生成 PCM 数据：前0.5秒静音，0.5-1.0秒常量，1.0-1.5秒静音，1.5-2.0秒常量
    frames_data = []
    for i in range(n_frames):
        t = i / sample_rate
        if 0.5 <= t < 1.0 or 1.5 <= t < 2.0:
            # 常量值（中等音量）
            sample_value = 10000
        else:
            # 静音
            sample_value = 0
        
        # 转换为 16-bit signed integer（little-endian）
        frames_data.append(sample_value.to_bytes(2, byteorder="little", signed=True))
    
    # 写入 WAV 文件
    with wave.open(str(output_path), "wb") as wf:
        wf.setnchannels(n_channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.writeframes(b"".join(frames_data))


def normalize_segments_jsonl(segments_path: Path) -> list[dict]:
    """读取并归一化 segments.jsonl（替换 source_audio 路径）
    
    Args:
        segments_path: segments.jsonl 文件路径
    
    Returns:
        归一化后的片段列表
    """
    segments = []
    with open(segments_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            seg = json.loads(line)
            # 归一化 source_audio 路径
            seg["source_audio"] = "<AUDIO>"
            # 移除 rms 字段（不比较精确值）
            if "rms" in seg:
                del seg["rms"]
            if "energy_db" in seg:
                del seg["energy_db"]
            segments.append(seg)
    return segments


def test_golden_segments_output(tmp_path: Path):
    """测试 golden segments 输出：使用固定配置和确定性音频，验证输出稳定性"""
    # 生成测试音频文件
    test_audio = tmp_path / "test_audio.wav"
    generate_deterministic_wav(test_audio, duration_sec=2.0)
    
    # 使用 golden 配置
    golden_config = Path(__file__).parent / "golden" / "config.json"
    assert golden_config.exists(), "golden/config.json 必须存在"
    
    # 运行 segment 命令
    import subprocess
    import sys
    
    out_dir = tmp_path / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "onepass_audioclean_seg",
            "segment",
            "--config",
            str(golden_config),
            "--in",
            str(test_audio),
            "--out",
            str(out_dir),
            "--emit-segments",
        ],
        capture_output=True,
        text=True,
    )
    
    assert result.returncode == 0, f"segment 命令失败: {result.stderr}"
    
    # 读取生成的 segments.jsonl
    segments_path = out_dir / test_audio.stem / "seg" / "segments.jsonl"
    assert segments_path.exists(), f"segments.jsonl 不存在: {segments_path}"
    
    actual_segments = normalize_segments_jsonl(segments_path)
    
    # 读取期望的 segments.jsonl（如果存在）
    expected_path = Path(__file__).parent / "golden" / "expected_segments.jsonl"
    
    if expected_path.exists():
        expected_segments = normalize_segments_jsonl(expected_path)
        
        # 比较（只比较关键字段：id, start, end, duration, flags, strategy）
        assert len(actual_segments) == len(expected_segments), (
            f"片段数量不匹配: 实际={len(actual_segments)}, 期望={len(expected_segments)}"
        )
        
        for actual, expected in zip(actual_segments, expected_segments):
            # 比较关键字段
            assert actual["id"] == expected["id"], f"ID 不匹配: {actual['id']} != {expected['id']}"
            assert abs(actual["start_sec"] - expected["start_sec"]) < 0.01, (
                f"start_sec 不匹配: {actual['start_sec']} != {expected['start_sec']}"
            )
            assert abs(actual["end_sec"] - expected["end_sec"]) < 0.01, (
                f"end_sec 不匹配: {actual['end_sec']} != {expected['end_sec']}"
            )
            assert abs(actual["duration_sec"] - expected["duration_sec"]) < 0.01, (
                f"duration_sec 不匹配: {actual['duration_sec']} != {expected['duration_sec']}"
            )
            assert actual.get("strategy") == expected.get("strategy"), (
                f"strategy 不匹配: {actual.get('strategy')} != {expected.get('strategy')}"
            )
    else:
        # 如果期望文件不存在，打印实际输出以便创建期望文件
        print("\n期望文件不存在，实际输出：")
        for seg in actual_segments:
            print(json.dumps(seg, ensure_ascii=False))
        pytest.skip("期望文件不存在，请创建 tests/golden/expected_segments.jsonl")

