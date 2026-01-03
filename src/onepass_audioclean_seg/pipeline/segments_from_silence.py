"""从静音区间生成语音片段的核心算法模块"""

import logging
from typing import Optional

from onepass_audioclean_seg.strategies.silence_ffmpeg import SilenceInterval

logger = logging.getLogger(__name__)


def normalize_intervals(
    silences: list[SilenceInterval],
    duration_sec: Optional[float] = None,
) -> list[SilenceInterval]:
    """规范化静音区间列表
    
    - 按 start 排序
    - 合并重叠或相邻（gap <= 0.001）静音区间
    - clip 到 [0, duration_sec]（若 duration 可用）
    - 过滤异常区间 end <= start
    - 输出 start/end/duration 统一 round(3)
    
    Args:
        silences: 静音区间列表
        duration_sec: 音频总时长（秒，可选）
    
    Returns:
        规范化后的静音区间列表（按 start 升序）
    """
    if not silences:
        return []
    
    # 1. 按 start 排序
    sorted_silences = sorted(silences, key=lambda x: x.start_sec)
    
    # 2. 合并重叠或相邻区间（gap <= 0.001）
    merged: list[SilenceInterval] = []
    for interval in sorted_silences:
        if not merged:
            merged.append(interval)
            continue
        
        last = merged[-1]
        gap = interval.start_sec - last.end_sec
        
        # 如果重叠（gap < 0）或相邻（gap <= 0.001），合并
        if gap <= 0.001:
            # 合并：取 start 的最小值和 end 的最大值
            new_start = min(last.start_sec, interval.start_sec)
            new_end = max(last.end_sec, interval.end_sec)
            new_duration = new_end - new_start
            merged[-1] = SilenceInterval(
                start_sec=round(new_start, 3),
                end_sec=round(new_end, 3),
                duration_sec=round(new_duration, 3),
            )
        else:
            merged.append(interval)
    
    # 3. clip 到 [0, duration_sec] 并过滤异常区间
    result: list[SilenceInterval] = []
    for interval in merged:
        start_sec = max(0.0, interval.start_sec)
        if duration_sec is not None:
            start_sec = min(start_sec, duration_sec)
            end_sec = min(interval.end_sec, duration_sec)
        else:
            end_sec = interval.end_sec
        
        # 过滤 end <= start 的异常区间
        if end_sec <= start_sec:
            logger.warning(f"过滤异常静音区间: start={start_sec}, end={end_sec}")
            continue
        
        duration = end_sec - start_sec
        result.append(SilenceInterval(
            start_sec=round(start_sec, 3),
            end_sec=round(end_sec, 3),
            duration_sec=round(duration, 3),
        ))
    
    return result


def complement_to_speech_segments(
    silences: list[SilenceInterval],
    duration_sec: float,
) -> list[tuple[float, float]]:
    """从静音区间生成语音段（补集）
    
    输入假设：silences 已 normalize 且在 [0, duration]
    
    补集规则：
    - 如果开头不是静音，从 0.0 到 first_silence.start 为语音段
    - 两个静音之间的 gap 为语音段：prev.end -> next.start
    - 结尾若 last_silence.end < duration，则 last_silence.end -> duration 为语音段
    
    Args:
        silences: 已规范化的静音区间列表（按 start 升序）
        duration_sec: 音频总时长（秒）
    
    Returns:
        语音段列表，每个元素为 (start, end) 元组（按 start 升序）
    """
    segments: list[tuple[float, float]] = []
    
    if not silences:
        # 如果没有静音，整个音频都是语音段
        if duration_sec > 0:
            segments.append((round(0.0, 3), round(duration_sec, 3)))
        return segments
    
    # 开头：如果第一个静音区间不在 0，则 0 -> first.start 是语音段
    first_silence = silences[0]
    if first_silence.start_sec > 0:
        segments.append((round(0.0, 3), round(first_silence.start_sec, 3)))
    
    # 中间：两个静音之间的 gap
    for i in range(len(silences) - 1):
        prev_end = silences[i].end_sec
        next_start = silences[i + 1].start_sec
        gap = next_start - prev_end
        if gap > 0:
            segments.append((round(prev_end, 3), round(next_start, 3)))
    
    # 结尾：如果最后一个静音区间结束时间 < duration，则 last.end -> duration 是语音段
    last_silence = silences[-1]
    if last_silence.end_sec < duration_sec:
        segments.append((round(last_silence.end_sec, 3), round(duration_sec, 3)))
    
    # 过滤掉 duration <= 0 的段（理论上不应该出现，但保险起见）
    segments = [(s, e) for s, e in segments if e > s]
    
    return segments


def apply_padding_and_clip(
    segments: list[tuple[float, float]],
    pad_sec: float,
    duration_sec: float,
) -> list[tuple[float, float]]:
    """对语音段应用填充并裁剪到有效范围
    
    对每段：start = max(0, start - pad), end = min(duration, end + pad)
    
    Args:
        segments: 语音段列表，每个元素为 (start, end)
        pad_sec: 填充时长（秒，>= 0）
        duration_sec: 音频总时长（秒）
    
    Returns:
        填充并裁剪后的语音段列表（按 start 升序，保证 start < end）
    """
    result: list[tuple[float, float]] = []
    
    for start, end in segments:
        new_start = max(0.0, start - pad_sec)
        new_end = min(duration_sec, end + pad_sec)
        
        # 确保 start < end（如果 pad 后导致重叠，仍保留，但不合并）
        if new_end > new_start:
            result.append((round(new_start, 3), round(new_end, 3)))
        else:
            logger.warning(f"填充后段无效（start >= end）: start={new_start}, end={new_end}")
    
    # 按 start 排序（虽然输入应该已排序，但保险起见）
    result.sort(key=lambda x: x[0])
    
    return result


def filter_min_duration(
    segments: list[tuple[float, float]],
    min_seg_sec: float,
) -> list[tuple[float, float]]:
    """过滤掉时长小于 min_seg_sec 的语音段（R5：直接丢弃，不合并）
    
    Args:
        segments: 语音段列表，每个元素为 (start, end)
        min_seg_sec: 最小片段时长（秒，> 0）
    
    Returns:
        过滤后的语音段列表（按 start 升序）
    """
    result: list[tuple[float, float]] = []
    
    for start, end in segments:
        duration = end - start
        if duration >= min_seg_sec:
            result.append((round(start, 3), round(end, 3)))
        else:
            logger.debug(f"过滤短段: start={start}, end={end}, duration={duration:.3f} < {min_seg_sec}")
    
    return result

