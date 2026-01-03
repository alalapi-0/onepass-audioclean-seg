"""路径处理工具函数"""

import hashlib
from pathlib import Path
from typing import Optional


def safe_join(base: Path, *parts: str) -> Path:
    """安全地拼接路径，防止路径遍历攻击"""
    result = base.resolve()
    for part in parts:
        part_path = Path(part)
        if part_path.is_absolute():
            raise ValueError(f"路径部分不能是绝对路径: {part}")
        # 移除 .. 和 . 并规范化
        normalized = part_path.resolve()
        result = result / normalized
    return result.resolve()


def stable_hash(text: str, length: int = 10) -> str:
    """生成稳定的哈希值（前 length 位）"""
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:length]


def get_rel_key(path: Path, base: Optional[Path] = None) -> str:
    """获取路径的相对键（用于输出路径映射）
    
    Args:
        path: 目标路径
        base: 基准路径（如果提供，返回相对路径；否则返回路径的规范化字符串）
    
    Returns:
        相对键字符串
    """
    if base:
        try:
            return str(path.relative_to(base))
        except ValueError:
            # 如果不在 base 下，使用路径的规范化形式
            return str(path.resolve())
    return str(path.resolve())


def sanitize_path_component(component: str) -> str:
    """清理路径组件，移除不安全字符"""
    # 移除或替换不安全字符
    unsafe_chars = ["/", "\\", ":", "*", "?", '"', "<", ">", "|"]
    for char in unsafe_chars:
        component = component.replace(char, "_")
    return component

