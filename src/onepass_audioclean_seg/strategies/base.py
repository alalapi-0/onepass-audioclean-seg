"""策略基类：统一策略接口定义"""

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from onepass_audioclean_seg.pipeline.jobs import SegJob


@dataclass
class StrategyParams:
    """策略参数（可以是简单 dict，或 dataclass）"""
    pass


@dataclass
class AnalysisResult:
    """分析结果数据类
    
    包含策略分析后的原始语音段、非语音段、中间产物等信息。
    """
    strategy: str  # "silence"|"energy"|...
    duration_sec: float
    speech_segments_raw: list[tuple[float, float]]  # 未 pad/merge/min/max 之前的候选语音段
    nonspeech_segments_raw: Optional[list[tuple[float, float]]] = None  # 可选（R8 可以不输出）
    artifacts: dict[str, Path] = field(default_factory=dict)  # 写出的中间文件路径，如 silences.json / energy.json
    warnings: list[str] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)  # 如 {"frames":..., "speech_frames":..., "threshold":...}


class SegmentStrategy(ABC):
    """分段策略抽象基类
    
    所有策略必须实现 analyze 方法，返回 AnalysisResult。
    """
    
    @property
    @abstractmethod
    def name(self) -> str:
        """策略名称（如 "silence", "energy"）"""
        pass
    
    @abstractmethod
    def analyze(
        self,
        job: SegJob,
        params: dict[str, Any],
    ) -> AnalysisResult:
        """分析音频并返回原始语音段
        
        Args:
            job: 分段任务对象
            params: 参数字典（包含策略相关参数）
        
        Returns:
            AnalysisResult 对象，包含 speech_segments_raw 等信息
        """
        pass
    
    def write_artifact(
        self,
        out_dir: Path,
        artifact_name: str,
        data: dict[str, Any],
    ) -> Path:
        """写入策略中间产物文件（辅助方法）
        
        Args:
            out_dir: 输出目录
            artifact_name: 文件名（如 "silences.json", "energy.json"）
            data: 要写入的数据（字典）
        
        Returns:
            写入的文件路径
        """
        out_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = out_dir / artifact_name
        
        with open(artifact_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        return artifact_path

