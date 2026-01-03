"""片段（segments）读写功能"""

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class SegmentRecord:
    """片段记录数据类"""
    
    id: str
    start_sec: float
    end_sec: float
    duration_sec: float
    source_audio: str  # 绝对路径
    pre_silence_sec: float = 0.0
    post_silence_sec: float = 0.0
    is_speech: bool = True
    strategy: str = "silence"
    rms: Optional[float] = None  # RMS 值（归一化到 [0, 1]）
    energy_db: Optional[float] = None  # 能量 dB 值
    notes: Optional[dict] = None  # 额外信息（如 split_reason, merged_from 等）
    
    def to_dict(self) -> dict:
        """转换为字典（用于 JSON 序列化）
        
        注意：时间字段已 round(3)，rms 保留更高精度（round(6)），energy_db round(2)
        """
        data = asdict(self)
        # 确保时间字段都是 round(3)
        data["start_sec"] = round(data["start_sec"], 3)
        data["end_sec"] = round(data["end_sec"], 3)
        data["duration_sec"] = round(data["duration_sec"], 3)
        data["pre_silence_sec"] = round(data["pre_silence_sec"], 3)
        data["post_silence_sec"] = round(data["post_silence_sec"], 3)
        
        # rms 保留更高精度
        if data.get("rms") is not None:
            data["rms"] = round(data["rms"], 6)
        
        # energy_db 保留 2 位小数
        if data.get("energy_db") is not None:
            data["energy_db"] = round(data["energy_db"], 2)
        
        # 移除 None 值（可选，但为了 JSON 简洁性）
        # 这里保留 None 值，让调用方决定是否过滤
        
        return data


def write_segments_jsonl(
    path: Path,
    segments_records: list[SegmentRecord],
) -> Path:
    """写入 segments.jsonl 文件（JSONL 格式，一行一个片段）
    
    Args:
        path: 输出文件路径
        segments_records: 片段记录列表（必须按 start_sec 升序）
    
    Returns:
        写入的文件路径
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(path, "w", encoding="utf-8") as f:
        for record in segments_records:
            data = record.to_dict()
            json_line = json.dumps(data, ensure_ascii=False)
            f.write(json_line + "\n")
    
    logger.info(f"写入 {len(segments_records)} 个片段到 {path}")
    return path

