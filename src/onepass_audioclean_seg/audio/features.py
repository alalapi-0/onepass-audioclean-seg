"""音频能量特征计算：RMS、energy_db 等"""

import array
import logging
import math
import wave
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def compute_rms(
    audio_path: Path,
    start_sec: float,
    end_sec: float,
    sample_rate_hint: Optional[int] = None,
) -> Optional[float]:
    """计算音频片段的 RMS（Root Mean Square）值
    
    使用 Python wave 库读取 PCM 数据，计算 RMS。
    要求音频为 16-bit PCM WAV 格式（Repo1 标准输出）。
    
    Args:
        audio_path: 音频文件路径（WAV 格式）
        start_sec: 片段开始时间（秒）
        end_sec: 片段结束时间（秒）
        sample_rate_hint: 采样率提示（可选，用于验证）
    
    Returns:
        RMS 值（归一化到 [0, 1]），若无法计算则返回 None
    """
    if start_sec < 0 or end_sec <= start_sec:
        logger.warning(f"无效的时间范围: start={start_sec}, end={end_sec}")
        return None
    
    try:
        with wave.open(str(audio_path), "rb") as wf:
            sample_rate = wf.getframerate()
            sample_width = wf.getsampwidth()
            n_channels = wf.getnchannels()
            
            # 验证采样率（如果提供了 hint）
            if sample_rate_hint is not None and sample_rate != sample_rate_hint:
                logger.debug(f"采样率不匹配: 文件={sample_rate}, 提示={sample_rate_hint}")
            
            # 只支持 16-bit PCM（sample_width=2）
            if sample_width != 2:
                logger.warning(f"不支持的样本宽度: {sample_width}（需要 2，即 16-bit PCM）")
                return None
            
            # 计算帧范围
            start_frame = int(start_sec * sample_rate)
            end_frame = int(end_sec * sample_rate)
            n_frames = end_frame - start_frame
            
            if n_frames <= 0:
                logger.warning(f"无效的帧范围: start_frame={start_frame}, end_frame={end_frame}")
                return None
            
            # 定位到起始帧
            wf.setpos(start_frame)
            
            # 读取帧数据
            frames = wf.readframes(n_frames)
            
            if len(frames) == 0:
                logger.warning(f"读取到空数据: start_frame={start_frame}, end_frame={end_frame}")
                return None
            
            # 转换为 array（int16）
            audio_data = array.array("h", frames)  # 'h' 表示 signed short (int16)
            
            # 如果是多声道，取平均值
            if n_channels > 1:
                # 重塑为 (n_frames, n_channels) 并取平均值
                n_samples = len(audio_data) // n_channels
                reshaped = []
                for i in range(n_samples):
                    sample_sum = sum(audio_data[i * n_channels + ch] for ch in range(n_channels))
                    reshaped.append(sample_sum / n_channels)
                audio_data = array.array("h", [int(x) for x in reshaped])
            
            # 计算 RMS
            # RMS = sqrt(mean(x^2)) / 32768.0（归一化到 [0, 1]）
            sum_squares = sum(float(x) ** 2 for x in audio_data)
            mean_square = sum_squares / len(audio_data) if len(audio_data) > 0 else 0.0
            rms = math.sqrt(mean_square) / 32768.0
            
            return float(rms)
    
    except wave.Error as e:
        logger.warning(f"wave 库读取失败: {e}")
        return None
    except OSError as e:
        logger.warning(f"文件读取失败: {e}")
        return None
    except Exception as e:
        logger.warning(f"计算 RMS 时发生未预期错误: {e}", exc_info=True)
        return None


def rms_to_db(rms: float, eps: float = 1e-12) -> float:
    """将 RMS 值转换为 dB（分贝）
    
    Args:
        rms: RMS 值（归一化到 [0, 1]）
        eps: 防止 log(0) 的小值（默认 1e-12）
    
    Returns:
        dB 值（通常为负值，如 -35.0）
    """
    if rms <= 0:
        # 如果 RMS 为 0 或负值，返回一个很小的 dB 值
        rms = eps
    
    # dB = 20 * log10(rms)
    db = 20.0 * math.log10(max(rms, eps))
    return float(db)

