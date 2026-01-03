"""音频探测：获取音频时长等信息"""

import json
import logging
from pathlib import Path
from typing import Optional

from onepass_audioclean_seg.audio.ffmpeg import run_cmd, which

logger = logging.getLogger(__name__)


def get_audio_duration_sec(
    audio_path: Path,
    meta_path: Optional[Path] = None,
    ffprobe_path: Optional[str] = None,
) -> Optional[float]:
    """获取音频时长（秒）
    
    优先级：
    1. 从 meta_path 读取 duration_sec
    2. 使用 ffprobe 获取
    
    Args:
        audio_path: 音频文件路径
        meta_path: meta.json 路径（可选）
        ffprobe_path: ffprobe 可执行文件路径（可选，默认从 PATH 查找）
    
    Returns:
        音频时长（秒），若无法获取则返回 None
    """
    # 优先级 1: 从 meta_path 读取
    if meta_path and meta_path.exists():
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                obj = json.load(f)
            
            # 尝试多个可能的字段路径
            duration = None
            if "duration_sec" in obj:
                duration = obj["duration_sec"]
            elif "audio" in obj and isinstance(obj["audio"], dict):
                if "duration_sec" in obj["audio"]:
                    duration = obj["audio"]["duration_sec"]
            elif "output" in obj and isinstance(obj["output"], dict):
                if "duration_sec" in obj["output"]:
                    duration = obj["output"]["duration_sec"]
            
            if duration is not None:
                try:
                    return float(duration)
                except (ValueError, TypeError):
                    logger.warning(f"从 {meta_path} 读取的 duration_sec 无法转换为 float: {duration}")
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"读取 {meta_path} 失败: {e}")
    
    # 优先级 2: 使用 ffprobe
    if ffprobe_path is None:
        ffprobe_path = which("ffprobe")
    
    if ffprobe_path is None:
        logger.warning("ffprobe 未找到，无法获取音频时长")
        return None
    
    try:
        cmd = [
            ffprobe_path,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(audio_path),
        ]
        result = run_cmd(cmd, timeout_sec=30)
        
        if result.returncode != 0:
            logger.warning(f"ffprobe 执行失败（返回码 {result.returncode}）: {result.stderr}")
            return None
        
        # 解析输出（通常是单个浮点数）
        output = result.stdout.strip()
        if not output:
            logger.warning("ffprobe 输出为空")
            return None
        
        try:
            duration = float(output)
            if duration <= 0:
                logger.warning(f"ffprobe 返回的时长无效: {duration}")
                return None
            return duration
        except ValueError:
            logger.warning(f"无法解析 ffprobe 输出为 float: {output}")
            return None
    except Exception as e:
        logger.warning(f"使用 ffprobe 获取音频时长失败: {e}")
        return None

