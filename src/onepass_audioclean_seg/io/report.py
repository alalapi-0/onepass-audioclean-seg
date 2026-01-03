"""报告读写功能"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from onepass_audioclean_seg import __version__


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

