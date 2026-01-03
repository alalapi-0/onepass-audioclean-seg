"""R10: 片段 flags 生成辅助模块"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def track_postprocess_history(
    segments_before: list[tuple[float, float]],
    segments_after: list[tuple[float, float]],
    operation: str,
) -> dict[tuple[float, float], list[str]]:
    """跟踪后处理操作历史
    
    Args:
        segments_before: 操作前的段列表
        segments_after: 操作后的段列表
        operation: 操作名称（"split" 或 "merge"）
    
    Returns:
        字典：{(start, end): [flags]}，记录每个段对应的 flags
    """
    flags_map: dict[tuple[float, float], list[str]] = {}
    
    if operation == "split":
        # 对于 split：如果 after 中的段在 before 中找不到完全匹配的，且 before 中有更长的段包含它，则标记为 split_from_long
        for seg_after in segments_after:
            flags_map[seg_after] = []
            # 检查是否由 split 产生
            for seg_before in segments_before:
                # 如果 after 段完全在 before 段内，且 before 段更长，则可能是 split 产生的
                if (seg_before[0] <= seg_after[0] < seg_after[1] <= seg_before[1] and
                    (seg_before[1] - seg_before[0]) > (seg_after[1] - seg_after[0])):
                    flags_map[seg_after].append("split_from_long")
                    break
    elif operation == "merge":
        # 对于 merge：如果 after 中的段覆盖了多个 before 段，则标记为 merged_short
        for seg_after in segments_after:
            flags_map[seg_after] = []
            # 检查是否由 merge 产生
            covered_before = []
            for seg_before in segments_before:
                # 如果 before 段与 after 段有重叠
                if not (seg_before[1] <= seg_after[0] or seg_after[1] <= seg_before[0]):
                    covered_before.append(seg_before)
            
            if len(covered_before) > 1:
                flags_map[seg_after].append("merged_short")
    
    return flags_map


def compute_flags_for_segment(
    segment: tuple[float, float],
    duration_sec: float,
    rms: Optional[float],
    low_energy_rms_threshold: float,
    history_flags: Optional[list[str]] = None,
) -> list[str]:
    """计算单个段的 flags
    
    Args:
        segment: 段 (start, end)
        duration_sec: 音频总时长
        rms: RMS 值（可选）
        low_energy_rms_threshold: 低能量阈值
        history_flags: 从处理历史得到的 flags（可选）
    
    Returns:
        flags 列表
    """
    flags = []
    
    # 从处理历史添加 flags
    if history_flags:
        flags.extend(history_flags)
    
    # 检查 edge_clipped
    start, end = segment
    tolerance = 1e-3
    if abs(start - 0.0) < tolerance or abs(end - duration_sec) < tolerance:
        flags.append("edge_clipped")
    
    # 检查 low_energy
    if rms is not None and rms < low_energy_rms_threshold:
        flags.append("low_energy")
    
    return flags


def build_source_info(
    strategy: str,
    auto_chosen: bool,
    raw_index: Optional[int] = None,
    derived_from: Optional[list[tuple[float, float]]] = None,
) -> dict:
    """构建 source 信息
    
    Args:
        strategy: 策略名称
        auto_chosen: 是否由 auto-strategy 选择
        raw_index: 在 speech_segments_raw 中的序号（可选）
        derived_from: 若由多个 raw 合并，记录它们的边界（可选）
    
    Returns:
        source 字典
    """
    source = {
        "strategy": strategy,
        "auto_chosen": auto_chosen,
    }
    if raw_index is not None:
        source["raw_index"] = raw_index
    if derived_from is not None:
        source["derived_from"] = [[round(s, 3), round(e, 3)] for s, e in derived_from]
    return source


def build_quality_info(
    rms: Optional[float],
    energy_db: Optional[float],
    confidence_hint: Optional[float] = None,
) -> dict:
    """构建 quality 信息
    
    Args:
        rms: RMS 值
        energy_db: energy_db 值
        confidence_hint: 置信度提示（占位，后续 Repo7 可用）
    
    Returns:
        quality 字典
    """
    quality = {}
    if rms is not None:
        quality["rms"] = round(rms, 6)
    if energy_db is not None:
        quality["energy_db"] = round(energy_db, 2)
    if confidence_hint is not None:
        quality["confidence_hint"] = round(confidence_hint, 3)
    return quality if quality else None

