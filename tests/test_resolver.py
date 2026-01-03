"""测试输入解析器（R3）"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path


def test_resolve_single_file():
    """测试解析单个音频文件"""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        audio_file = tmp_path / "a.wav"
        audio_file.touch()  # 创建空文件
        
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "onepass_audioclean_seg",
                "segment",
                "--in",
                str(audio_file),
                "--out",
                str(tmp_path / "out"),
                "--dry-run",
            ],
            capture_output=True,
            text=True,
        )
        
        assert result.returncode == 0, f"返回码应为 0，实际为 {result.returncode}，stderr: {result.stderr}"
        assert "PLAN" in result.stdout, "输出应包含 'PLAN' 关键字"
        assert "a.wav" in result.stdout, "输出应包含输入文件路径"
        assert "audio=" in result.stdout, "输出应包含 audio= 前缀"


def test_resolve_workdir_in_place():
    """测试解析 workdir 并使用 in_place 模式"""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        workdir = tmp_path / "job1"
        workdir.mkdir()
        audio_file = workdir / "audio.wav"
        audio_file.touch()
        meta_file = workdir / "meta.json"
        meta_file.write_text(json.dumps({"test": "data"}))
        
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "onepass_audioclean_seg",
                "segment",
                "--in",
                str(workdir),
                "--out",
                str(tmp_path / "out"),
                "--dry-run",
                "--out-mode",
                "in_place",
            ],
            capture_output=True,
            text=True,
        )
        
        assert result.returncode == 0, f"返回码应为 0，实际为 {result.returncode}，stderr: {result.stderr}"
        assert "PLAN" in result.stdout, "输出应包含 'PLAN' 关键字"
        # 检查 out 路径包含 job1/seg
        assert "job1/seg" in result.stdout or "job1\\seg" in result.stdout, "输出路径应包含 job1/seg"


def test_resolve_root_mirror_out_root():
    """测试解析根目录并使用 out_root 模式"""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        root = tmp_path / "root"
        root.mkdir()
        
        # 创建两个子目录，每个包含 audio.wav
        subdir_a = root / "a"
        subdir_a.mkdir()
        (subdir_a / "audio.wav").touch()
        
        subdir_b = root / "b"
        subdir_b.mkdir()
        (subdir_b / "audio.wav").touch()
        
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "onepass_audioclean_seg",
                "segment",
                "--in",
                str(root),
                "--out",
                str(tmp_path / "out"),
                "--dry-run",
                "--out-mode",
                "out_root",
            ],
            capture_output=True,
            text=True,
        )
        
        assert result.returncode == 0, f"返回码应为 0，实际为 {result.returncode}，stderr: {result.stderr}"
        # 检查有两个 PLAN 行
        plan_count = result.stdout.count("PLAN")
        assert plan_count == 2, f"应有两个 PLAN 行，实际有 {plan_count} 个"
        # 检查输出路径包含 a/seg 和 b/seg
        assert ("a/seg" in result.stdout or "a\\seg" in result.stdout), "输出路径应包含 a/seg"
        assert ("b/seg" in result.stdout or "b\\seg" in result.stdout), "输出路径应包含 b/seg"


def test_resolve_manifest():
    """测试解析 manifest.jsonl"""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        
        # 创建两个 workdir
        workdir1 = tmp_path / "job1"
        workdir1.mkdir()
        (workdir1 / "audio.wav").touch()
        (workdir1 / "meta.json").write_text(json.dumps({"test": "data1"}))
        
        workdir2 = tmp_path / "job2"
        workdir2.mkdir()
        (workdir2 / "audio.wav").touch()
        
        # 创建 manifest.jsonl：一行成功，一行失败
        manifest_file = tmp_path / "manifest.jsonl"
        with open(manifest_file, "w", encoding="utf-8") as f:
            # 成功行
            json.dump({
                "status": "success",
                "output": {
                    "workdir": str(workdir1),
                    "audio_wav": str(workdir1 / "audio.wav"),
                }
            }, f)
            f.write("\n")
            # 失败行（有 error）
            json.dump({
                "status": "failed",
                "error": "some error",
                "output": {
                    "workdir": str(workdir2),
                }
            }, f)
            f.write("\n")
        
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "onepass_audioclean_seg",
                "segment",
                "--in",
                str(manifest_file),
                "--out",
                str(tmp_path / "out"),
                "--dry-run",
            ],
            capture_output=True,
            text=True,
        )
        
        assert result.returncode == 0, f"返回码应为 0，实际为 {result.returncode}，stderr: {result.stderr}"
        # 应该只解析成功的那一行
        plan_count = result.stdout.count("PLAN")
        assert plan_count == 1, f"应有一个 PLAN 行（只解析成功项），实际有 {plan_count} 个"
        assert "job1" in result.stdout, "输出应包含 job1"

