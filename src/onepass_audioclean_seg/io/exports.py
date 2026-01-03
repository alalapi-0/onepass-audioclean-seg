"""R10: 可视化友好导出功能"""

import csv
import json
import logging
import math
from pathlib import Path
from typing import Any, Optional

from onepass_audioclean_seg.io.segments import SegmentRecord

logger = logging.getLogger(__name__)


def export_timeline_json(
    out_dir: Path,
    segments_records: list[SegmentRecord],
    audio_path: Path,
    duration_sec: float,
    strategy: str,
    auto_strategy: Optional[dict] = None,
    params: Optional[dict] = None,
) -> Path:
    """导出 timeline.json（单文件，供前端直接加载）
    
    Args:
        out_dir: 输出目录
        segments_records: 片段记录列表
        audio_path: 音频文件路径
        duration_sec: 音频总时长
        strategy: 策略名称
        auto_strategy: auto-strategy 信息（可选）
        params: 参数字典（可选）
    
    Returns:
        写入的文件路径
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    timeline_path = out_dir / "timeline.json"
    
    # 构建 timeline 结构
    timeline = {
        "version": "timeline.v1",
        "audio_path": str(audio_path.resolve()),
        "duration_sec": round(duration_sec, 3),
        "strategy": strategy,
        "auto_strategy": auto_strategy,
        "params": params or {},
        "tracks": [
            {
                "name": "auto_segments",
                "type": "segments",
                "items": [],
            },
            {
                "name": "analysis",
                "type": "intervals",
                "items": [],
            },
        ],
    }
    
    # 填充 segments track
    for record in segments_records:
        item = {
            "id": record.id,
            "start_sec": round(record.start_sec, 3),
            "end_sec": round(record.end_sec, 3),
            "duration_sec": round(record.duration_sec, 3),
            "flags": record.flags,
        }
        if record.rms is not None:
            item["rms"] = round(record.rms, 6)
        timeline["tracks"][0]["items"].append(item)
    
    # items 必须按 start_sec 排序
    timeline["tracks"][0]["items"].sort(key=lambda x: x["start_sec"])
    
    # 写入文件
    with open(timeline_path, "w", encoding="utf-8") as f:
        json.dump(timeline, f, ensure_ascii=False, indent=2)
    
    logger.info(f"导出 timeline.json: {timeline_path}")
    return timeline_path


def export_segments_csv(
    out_dir: Path,
    segments_records: list[SegmentRecord],
) -> Path:
    """导出 segments.csv（表格友好）
    
    Args:
        out_dir: 输出目录
        segments_records: 片段记录列表
    
    Returns:
        写入的文件路径
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "segments.csv"
    
    # 列固定
    fieldnames = [
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
    
    # 按 start_sec 排序
    sorted_records = sorted(segments_records, key=lambda r: r.start_sec)
    
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        
        for record in sorted_records:
            row = {
                "id": record.id,
                "start_sec": round(record.start_sec, 3),
                "end_sec": round(record.end_sec, 3),
                "duration_sec": round(record.duration_sec, 3),
                "rms": round(record.rms, 6) if record.rms is not None else "",
                "strategy": record.strategy,
                "flags": "|".join(record.flags) if record.flags else "",
                "pre_silence_sec": round(record.pre_silence_sec, 3),
                "post_silence_sec": round(record.post_silence_sec, 3),
                "source_audio": record.source_audio,
            }
            writer.writerow(row)
    
    logger.info(f"导出 segments.csv: {csv_path}")
    return csv_path


def export_mask_json(
    out_dir: Path,
    duration_sec: float,
    strategy: str,
    bin_ms: float,
    analysis_result: Optional[Any] = None,
    segments_records: Optional[list[SegmentRecord]] = None,
) -> Optional[Path]:
    """导出 mask.json（降采样帧级信息）
    
    Args:
        out_dir: 输出目录
        duration_sec: 音频总时长
        strategy: 策略名称
        bin_ms: bin 大小（毫秒）
        analysis_result: 分析结果（可选，用于 energy/vad 策略）
        segments_records: 片段记录列表（可选，用于 silence 策略）
    
    Returns:
        写入的文件路径，若无法生成则返回 None
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    mask_path = out_dir / "mask.json"
    
    bin_sec = bin_ms / 1000.0
    n_bins = int(math.ceil(duration_sec / bin_sec))
    
    series = []
    
    if strategy == "energy" and analysis_result is not None:
        # 从 energy 策略获取 rms_series
        # 注意：需要从 analysis_result 或 artifact 中获取
        # 这里假设可以从 artifact 读取
        energy_path = out_dir / "energy.json"
        if energy_path.exists():
            try:
                with open(energy_path, "r", encoding="utf-8") as f:
                    energy_data = json.load(f)
                # 需要从 energy_data 中提取 rms_series 和 frame_times
                # 但 energy.json 可能不包含这些，需要策略在 analyze 时保存
                # 这里先实现一个简化版本：从 segments 反推
                logger.warning("energy 策略的 mask 导出需要策略保存 rms_series，当前使用简化实现")
            except Exception as e:
                logger.warning(f"读取 energy.json 失败: {e}")
        
        # 简化实现：从 segments 反推
        if segments_records:
            for i in range(n_bins):
                t_sec = i * bin_sec
                bin_end = min((i + 1) * bin_sec, duration_sec)
                
                # 计算该 bin 内的 speech_ratio 和 avg_rms
                speech_samples = 0
                total_samples = 0
                rms_sum = 0.0
                rms_count = 0
                
                for record in segments_records:
                    # 计算重叠
                    overlap_start = max(t_sec, record.start_sec)
                    overlap_end = min(bin_end, record.end_sec)
                    if overlap_end > overlap_start:
                        overlap_duration = overlap_end - overlap_start
                        speech_samples += overlap_duration
                        if record.rms is not None:
                            rms_sum += record.rms * overlap_duration
                            rms_count += overlap_duration
                
                total_samples = bin_end - t_sec
                speech_ratio = speech_samples / total_samples if total_samples > 0 else 0.0
                avg_rms = rms_sum / rms_count if rms_count > 0 else 0.0
                
                series.append({
                    "t_sec": round(t_sec, 3),
                    "speech_ratio": round(speech_ratio, 3),
                    "avg_rms": round(avg_rms, 6),
                })
    
    elif strategy == "vad" and analysis_result is not None:
        # 从 vad 策略获取 frame-level mask
        vad_path = out_dir / "vad.json"
        if vad_path.exists():
            try:
                with open(vad_path, "r", encoding="utf-8") as f:
                    vad_data = json.load(f)
                # 需要从 vad_data 中提取 frame-level mask
                # 但 vad.json 可能不包含这些，需要策略在 analyze 时保存
                logger.warning("vad 策略的 mask 导出需要策略保存 frame-level mask，当前使用简化实现")
            except Exception as e:
                logger.warning(f"读取 vad.json 失败: {e}")
        
        # 简化实现：从 segments 反推
        if segments_records:
            for i in range(n_bins):
                t_sec = i * bin_sec
                bin_end = min((i + 1) * bin_sec, duration_sec)
                
                speech_samples = 0
                total_samples = bin_end - t_sec
                
                for record in segments_records:
                    overlap_start = max(t_sec, record.start_sec)
                    overlap_end = min(bin_end, record.end_sec)
                    if overlap_end > overlap_start:
                        speech_samples += overlap_end - overlap_start
                
                speech_ratio = speech_samples / total_samples if total_samples > 0 else 0.0
                
                series.append({
                    "t_sec": round(t_sec, 3),
                    "speech_ratio": round(speech_ratio, 3),
                })
    
    elif strategy == "silence" and segments_records:
        # 从 segments 反推
        for i in range(n_bins):
            t_sec = i * bin_sec
            bin_end = min((i + 1) * bin_sec, duration_sec)
            
            speech_samples = 0
            total_samples = bin_end - t_sec
            
            for record in segments_records:
                overlap_start = max(t_sec, record.start_sec)
                overlap_end = min(bin_end, record.end_sec)
                if overlap_end > overlap_start:
                    speech_samples += overlap_end - overlap_start
            
            speech_ratio = speech_samples / total_samples if total_samples > 0 else 0.0
            
            series.append({
                "t_sec": round(t_sec, 3),
                "speech_ratio": round(speech_ratio, 3),
            })
    
    else:
        logger.warning(f"无法为策略 {strategy} 生成 mask.json")
        return None
    
    # 构建 mask 结构
    mask = {
        "version": "mask.v1",
        "bin_ms": round(bin_ms, 1),
        "duration_sec": round(duration_sec, 3),
        "series": series,
        "source": {
            "strategy": strategy,
            "frame_ms": None,  # 需要从策略获取
            "hop_ms": None,  # 需要从策略获取
        },
    }
    
    # 写入文件
    with open(mask_path, "w", encoding="utf-8") as f:
        json.dump(mask, f, ensure_ascii=False, indent=2)
    
    logger.info(f"导出 mask.json: {mask_path}")
    return mask_path

