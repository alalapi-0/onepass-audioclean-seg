"""R10: summarize 命令实现"""

import json
import logging
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

from onepass_audioclean_seg.io.report import read_seg_report

logger = logging.getLogger(__name__)


def summarize_segments(
    input_path: Path,
    top_n: int = 5,
    json_output: bool = False,
) -> dict[str, Any]:
    """汇总 segments.jsonl 文件
    
    Args:
        input_path: 输入路径（文件、目录或 out_root）
        top_n: 显示 flags 计数 Top N
        json_output: 是否输出 JSON 格式
    
    Returns:
        汇总结果字典
    """
    input_path = Path(input_path).resolve()
    
    # 查找 segments.jsonl 文件
    segments_files = []
    
    if input_path.is_file():
        if input_path.name == "segments.jsonl":
            segments_files.append(input_path)
    elif input_path.is_dir():
        # 递归查找所有 segments.jsonl
        segments_files = sorted(input_path.rglob("segments.jsonl"))
    
    if not segments_files:
        return {
            "ok": False,
            "error_code": "no_files",
            "checked_files": 0,
            "items": [],
        }
    
    items = []
    
    for segments_file in segments_files:
        try:
            stats = _summarize_single_file(segments_file, top_n)
            items.append({
                "path": str(segments_file),
                "stats": stats,
            })
        except Exception as e:
            logger.warning(f"汇总文件失败 {segments_file}: {e}")
            items.append({
                "path": str(segments_file),
                "stats": {},
                "error": str(e),
            })
    
    return {
        "ok": True,
        "checked_files": len(segments_files),
        "items": items,
    }


def _summarize_single_file(
    segments_file: Path,
    top_n: int,
) -> dict[str, Any]:
    """汇总单个 segments.jsonl 文件
    
    Args:
        segments_file: segments.jsonl 文件路径
        top_n: 显示 flags 计数 Top N
    
    Returns:
        统计信息字典
    """
    segments = []
    
    # 读取 segments.jsonl
    with open(segments_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                seg = json.loads(line)
                segments.append(seg)
            except json.JSONDecodeError as e:
                logger.warning(f"解析 JSON 失败 {segments_file}: {e}")
                continue
    
    if not segments:
        return {
            "count": 0,
            "speech_total_sec": 0.0,
            "avg_duration": 0.0,
            "median_duration": 0.0,
            "min_duration": 0.0,
            "max_duration": 0.0,
            "flags_count": {},
            "strategy_info": {},
        }
    
    # 计算统计信息
    durations = [seg.get("duration_sec", 0.0) for seg in segments]
    speech_total_sec = sum(durations)
    avg_duration = statistics.mean(durations) if durations else 0.0
    median_duration = statistics.median(durations) if durations else 0.0
    min_duration = min(durations) if durations else 0.0
    max_duration = max(durations) if durations else 0.0
    
    # 统计 flags
    flags_counter = Counter()
    for seg in segments:
        flags = seg.get("flags", [])
        for flag in flags:
            flags_counter[flag] += 1
    
    # 获取 Top N flags
    flags_count = dict(flags_counter.most_common(top_n))
    
    # 获取策略信息
    strategy_info = {}
    if segments:
        first_seg = segments[0]
        strategy = first_seg.get("strategy", "unknown")
        strategy_info["strategy"] = strategy
        
        # 尝试从 source 获取 auto_chosen
        source = first_seg.get("source", {})
        if source:
            strategy_info["auto_chosen"] = source.get("auto_chosen", False)
        
        # 尝试从 seg_report.json 获取 auto_strategy 信息
        report_path = segments_file.parent / "seg_report.json"
        if report_path.exists():
            report = read_seg_report(report_path)
            if report:
                auto_strategy = report.get("auto_strategy")
                if auto_strategy:
                    strategy_info["auto_strategy"] = auto_strategy
    
    return {
        "count": len(segments),
        "speech_total_sec": round(speech_total_sec, 3),
        "avg_duration": round(avg_duration, 3),
        "median_duration": round(median_duration, 3),
        "min_duration": round(min_duration, 3),
        "max_duration": round(max_duration, 3),
        "flags_count": flags_count,
        "strategy_info": strategy_info,
    }

