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
) -> Path:
    """写入最小 seg_report.json 文件
    
    Args:
        out_dir: 输出目录
        params: 参数字典（包含 strategy、min_seg_sec 等）
        audio_path: 音频文件路径
        meta_path: meta.json 路径（可选）
    
    Returns:
        seg_report.json 的路径
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    
    report = {
        "version": "R3",
        "created_at": datetime.now().isoformat(),
        "versions": {
            "onepass_audioclean_seg": __version__,
        },
        "planned": True,  # R3 阶段只做计划
        "params": params,
        "audio_path": str(audio_path.resolve()),
        "meta_path": str(meta_path.resolve()) if meta_path else None,
        "segments": [],  # R3 阶段为空列表
    }
    
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
            "version": "R4",
            "created_at": datetime.now().isoformat(),
            "versions": {
                "onepass_audioclean_seg": __version__,
            },
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
) -> Path:
    """更新 seg_report.json 的 segments 字段（读旧 -> 合并 -> 写新）
    
    Args:
        out_dir: 输出目录
        segments_data: 要添加的 segments 数据（例如 {"count": N, "speech_total_sec": ...}）
    
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
            "version": "R5",
            "created_at": datetime.now().isoformat(),
            "versions": {
                "onepass_audioclean_seg": __version__,
            },
        }
    
    # 合并 segments 字段（覆盖）
    existing_report["segments"] = segments_data
    existing_report["updated_at"] = datetime.now().isoformat()
    
    # 写回
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(existing_report, f, ensure_ascii=False, indent=2)
    
    return report_path

