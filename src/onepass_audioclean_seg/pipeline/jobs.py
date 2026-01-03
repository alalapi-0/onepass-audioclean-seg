"""任务数据结构定义"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class SegJob:
    """分段任务数据"""
    
    job_id: str
    input_type: str  # file|workdir|root|manifest
    workdir: Optional[Path]
    audio_path: Path
    meta_path: Optional[Path]
    out_dir: Path
    rel_key: str  # 相对键，用于在 out_root 下创建镜像目录
    warnings: list[str] = field(default_factory=list)
    
    def __post_init__(self):
        """验证字段"""
        if self.input_type not in ["file", "workdir", "root", "manifest"]:
            raise ValueError(f"无效的 input_type: {self.input_type}")
        if not self.audio_path:
            raise ValueError("audio_path 不能为空")
        if not self.out_dir:
            raise ValueError("out_dir 不能为空")

