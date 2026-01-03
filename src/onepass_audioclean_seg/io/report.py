"""报告读写功能"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from onepass_audioclean_seg import __version__


def read_seg_report(report_path: Path) -> Optional[dict[str, Any]]:
    """读取 seg_report.json 文件
    
    Args:
        report_path: 报告文件路径
    
    Returns:
        报告字典，若文件不存在或解析失败则返回 None
    """
    if not report_path.exists():
        return None
    
    try:
        with open(report_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def write_seg_report(
    out_dir: Path,
    params: dict[str, Any],
    audio_path: Path,
    meta_path: Optional[Path] = None,
    config_hash: Optional[str] = None,
) -> Path:
    """写入最小 seg_report.json 文件
    
    Args:
        out_dir: 输出目录
        params: 参数字典（包含 strategy、min_seg_sec 等）
        audio_path: 音频文件路径
        meta_path: meta.json 路径（可选）
        config_hash: 配置哈希值（R11，可选）
    
    Returns:
        seg_report.json 的路径
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    
    # R11: 计算音频指纹
    audio_fingerprint = None
    try:
        from onepass_audioclean_seg.audio.fingerprint import fingerprint_audio_wav
        audio_fingerprint = fingerprint_audio_wav(audio_path)
    except Exception:
        pass  # 忽略错误
    
    report = {
        "version": "R11",
        "created_at": datetime.now().isoformat(),
        "tool": {
            "name": "onepass-audioclean-seg",
            "version": __version__,
        },
        "planned": True,  # R3 阶段只做计划
        "params": params,
        "audio_path": str(audio_path.resolve()),
        "meta_path": str(meta_path.resolve()) if meta_path else None,
        "segments": [],  # R3 阶段为空列表
    }
    
    # R11: 添加 config_hash 和 audio_fingerprint
    if config_hash:
        report["config_hash"] = config_hash
    if audio_fingerprint:
        report["audio_fingerprint"] = audio_fingerprint
    
    report_path = out_dir / "seg_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    
    return report_path


def update_seg_report_analysis(
    out_dir: Path,
    analysis_data: dict[str, Any],
) -> Path:
    """更新 seg_report.json 的 analysis 字段（读旧 -> 合并 -> 写新）
    
    Args:
        out_dir: 输出目录
        analysis_data: 要添加的 analysis 数据（例如 {"silence": {...}}）
    
    Returns:
        seg_report.json 的路径
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "seg_report.json"
    
    # 读取现有报告（如果存在）
    existing_report = read_seg_report(report_path)
    
    if existing_report is None:
        # 如果报告不存在，创建一个最小报告
        existing_report = {
            "version": "R11",
            "created_at": datetime.now().isoformat(),
            "tool": {
                "name": "onepass-audioclean-seg",
                "version": __version__,
            },
        }
    
    # R11: 确保 tool 字段存在
    if "tool" not in existing_report:
        existing_report["tool"] = {
            "name": "onepass-audioclean-seg",
            "version": __version__,
        }
    
    # 合并 analysis 字段
    if "analysis" not in existing_report:
        existing_report["analysis"] = {}
    
    existing_report["analysis"].update(analysis_data)
    existing_report["updated_at"] = datetime.now().isoformat()
    
    # 写回
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(existing_report, f, ensure_ascii=False, indent=2)
    
    return report_path


def update_seg_report_segments(
    out_dir: Path,
    segments_data: dict[str, Any],
    audio_path: Optional[Path] = None,
) -> Path:
    """更新 seg_report.json 的 segments 字段（读旧 -> 合并 -> 写新）
    
    Args:
        out_dir: 输出目录
        segments_data: 要添加的 segments 数据（例如 {"count": N, "speech_total_sec": ...}）
        audio_path: 音频文件路径（R11，用于计算指纹，可选）
    
    Returns:
        seg_report.json 的路径
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "seg_report.json"
    
    # 读取现有报告（如果存在）
    existing_report = read_seg_report(report_path)
    
    if existing_report is None:
        # 如果报告不存在，创建一个最小报告
        existing_report = {
            "version": "R11",
            "created_at": datetime.now().isoformat(),
            "tool": {
                "name": "onepass-audioclean-seg",
                "version": __version__,
            },
        }
    
    # R11: 确保 tool 字段存在
    if "tool" not in existing_report:
        existing_report["tool"] = {
            "name": "onepass-audioclean-seg",
            "version": __version__,
        }
    
    # R11: 如果 audio_path 提供且 audio_fingerprint 不存在，计算指纹
    if audio_path and "audio_fingerprint" not in existing_report:
        try:
            from onepass_audioclean_seg.audio.fingerprint import fingerprint_audio_wav
            audio_fingerprint = fingerprint_audio_wav(audio_path)
            if audio_fingerprint:
                existing_report["audio_fingerprint"] = audio_fingerprint
        except Exception:
            pass  # 忽略错误
    
    # 合并 segments 字段（覆盖）
    existing_report["segments"] = segments_data
    existing_report["updated_at"] = datetime.now().isoformat()
    
    # 写回
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(existing_report, f, ensure_ascii=False, indent=2)
    
    return report_path

