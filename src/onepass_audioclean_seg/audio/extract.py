"""音频片段提取：从长音频中提取指定时间段的 WAV 文件"""

import logging
import subprocess
from pathlib import Path
from typing import Optional

from onepass_audioclean_seg.audio.ffmpeg import run_cmd, which

logger = logging.getLogger(__name__)


def extract_wav_segment(
    audio_path: Path,
    out_path: Path,
    start_sec: float,
    end_sec: float,
    ffmpeg_path: Optional[str] = None,
) -> bool:
    """使用 ffmpeg 提取音频片段并保存为 WAV 文件
    
    Args:
        audio_path: 输入音频文件路径
        out_path: 输出 WAV 文件路径
        start_sec: 片段开始时间（秒）
        end_sec: 片段结束时间（秒）
        ffmpeg_path: ffmpeg 可执行文件路径（可选，默认从 PATH 查找）
    
    Returns:
        是否成功提取
    """
    if start_sec < 0 or end_sec <= start_sec:
        logger.warning(f"无效的时间范围: start={start_sec}, end={end_sec}")
        return False
    
    if ffmpeg_path is None:
        ffmpeg_path = which("ffmpeg")
        if ffmpeg_path is None:
            logger.error("ffmpeg 未找到，无法提取音频片段")
            return False
    
    # 确保输出目录存在
    out_path.parent.mkdir(parents=True, exist_ok=True)
    
    # 构建 ffmpeg 命令
    # 使用 -ss 和 -to 指定时间范围，-acodec pcm_s16le 重新编码为 PCM16
    cmd = [
        ffmpeg_path,
        "-hide_banner",
        "-y",  # 覆盖输出文件
        "-ss",
        str(start_sec),
        "-to",
        str(end_sec),
        "-i",
        str(audio_path),
        "-acodec",
        "pcm_s16le",  # 16-bit PCM
        str(out_path),
    ]
    
    try:
        result = run_cmd(cmd, timeout_sec=60)
        
        if result.returncode != 0:
            error_msg = result.stderr or result.stdout or "未知错误"
            logger.warning(f"ffmpeg 提取失败（返回码 {result.returncode}）: {error_msg[:200]}")
            return False
        
        # 检查输出文件是否存在
        if not out_path.exists():
            logger.warning(f"提取完成但输出文件不存在: {out_path}")
            return False
        
        return True
    
    except Exception as e:
        logger.warning(f"提取音频片段时发生错误: {e}", exc_info=True)
        return False

