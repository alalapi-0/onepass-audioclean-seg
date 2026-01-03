"""音频指纹模块（R11）：轻量级、离线、可复现的音频标识"""

import hashlib
import logging
import wave
from pathlib import Path
from typing import Optional

from onepass_audioclean_seg.config import FINGERPRINT_READ_SECONDS

logger = logging.getLogger(__name__)


def fingerprint_audio_wav(audio_path: Path) -> Optional[str]:
    """计算音频文件的指纹
    
    只对 WAV 文件计算：
    - 读取前 N 秒（FINGERPRINT_READ_SECONDS）的 PCM16 数据，计算 sha256
    - 读取 WAV header（sr/channels/sample_width/frames）
    - 输出短指纹：sha256[:16] + ":" + sr + "x" + ch + ":" + frames
    
    Args:
        audio_path: 音频文件路径（WAV 格式）
    
    Returns:
        指纹字符串（格式：sha256[:16]:sr x ch:frames），若无法计算则返回 None
    """
    if not audio_path.exists():
        logger.warning(f"音频文件不存在: {audio_path}")
        return None
    
    try:
        with wave.open(str(audio_path), "rb") as wf:
            sample_rate = wf.getframerate()
            n_channels = wf.getnchannels()
            sample_width = wf.getsampwidth()
            n_frames_total = wf.getnframes()
            
            # 计算要读取的帧数（限制在前 N 秒）
            frames_to_read = int(FINGERPRINT_READ_SECONDS * sample_rate)
            frames_to_read = min(frames_to_read, n_frames_total)
            
            # 读取 PCM 数据
            wf.setpos(0)
            frames_data = wf.readframes(frames_to_read)
            
            if len(frames_data) == 0:
                logger.warning(f"读取到空数据: {audio_path}")
                return None
            
            # 计算 SHA256 哈希
            hash_obj = hashlib.sha256(frames_data)
            hash_hex = hash_obj.hexdigest()
            hash_short = hash_hex[:16]  # 前16个字符
            
            # 构建指纹字符串
            fingerprint = f"{hash_short}:{sample_rate}x{n_channels}:{n_frames_total}"
            
            return fingerprint
    
    except wave.Error as e:
        logger.warning(f"wave 库读取失败: {e}")
        return None
    except OSError as e:
        logger.warning(f"文件读取失败: {e}")
        return None
    except Exception as e:
        logger.warning(f"计算音频指纹时发生未预期错误: {e}", exc_info=True)
        return None

