"""测试 run_manifest.json 是否被正确写入（R11）"""

import json
import tempfile
import wave
from pathlib import Path

import pytest


def generate_test_wav(output_path: Path, duration_sec: float = 1.0) -> None:
    """生成测试 WAV 文件"""
    sample_rate = 16000
    n_channels = 1
    sample_width = 2
    
    n_frames = int(duration_sec * sample_rate)
    frames_data = []
    for i in range(n_frames):
        sample_value = 5000  # 中等音量
        frames_data.append(sample_value.to_bytes(2, byteorder="little", signed=True))
    
    with wave.open(str(output_path), "wb") as wf:
        wf.setnchannels(n_channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.writeframes(b"".join(frames_data))


def test_run_manifest_written(tmp_path: Path):
    """测试 run_manifest.json 是否被正确写入"""
    # 生成测试音频
    test_audio = tmp_path / "test.wav"
    generate_test_wav(test_audio)
    
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
            "--in",
            str(test_audio),
            "--out",
            str(out_dir),
            "--strategy",
            "energy",
            "--emit-segments",
        ],
        capture_output=True,
        text=True,
    )
    
    assert result.returncode == 0, f"segment 命令失败: {result.stderr}"
    
    # 查找 run_manifest.json（可能在 out_dir 或其子目录中）
    manifest_path = None
    for path in out_dir.rglob("run_manifest.json"):
        manifest_path = path
        break
    
    assert manifest_path is not None, f"run_manifest.json 未找到，搜索目录: {out_dir}"
    assert manifest_path.exists(), f"run_manifest.json 不存在: {manifest_path}"
    
    # 读取并验证内容
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    
    # 验证必需字段
    assert manifest["tool"] == "onepass-audioclean-seg", "tool 字段不正确"
    assert "version" in manifest, "缺少 version 字段"
    assert "started_at" in manifest, "缺少 started_at 字段"
    assert "finished_at" in manifest, "缺少 finished_at 字段"
    assert "command" in manifest, "缺少 command 字段"
    assert "effective_config" in manifest, "缺少 effective_config 字段"
    assert "environment" in manifest, "缺少 environment 字段"
    assert "jobs" in manifest, "缺少 jobs 字段"
    
    # 验证 environment 字段
    env = manifest["environment"]
    assert "python_version" in env, "environment 缺少 python_version"
    assert "platform" in env, "environment 缺少 platform"
    assert "deps" in env, "environment 缺少 deps"
    
    # 验证 jobs 数组
    jobs = manifest["jobs"]
    assert isinstance(jobs, list), "jobs 应为列表"
    assert len(jobs) > 0, "jobs 不应为空"
    
    # 验证第一个 job
    job = jobs[0]
    assert "job_id" in job, "job 缺少 job_id"
    assert "audio_path" in job, "job 缺少 audio_path"
    assert "out_dir" in job, "job 缺少 out_dir"
    assert "status" in job, "job 缺少 status"

