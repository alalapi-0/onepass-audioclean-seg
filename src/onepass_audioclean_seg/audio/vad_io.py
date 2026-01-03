"""VAD 输入/输出处理：将音频转换为 webrtcvad 可用的 PCM16 mono frames"""

import logging
import subprocess
import wave
from pathlib import Path
from typing import Iterator, Optional

from onepass_audioclean_seg.audio.ffmpeg import run_cmd, which

logger = logging.getLogger(__name__)


def get_pcm16_mono_frames(
    audio_path: Path,
    target_sr: int,
    frame_ms: int,
    ffmpeg_path: Optional[str] = None,
) -> Iterator[bytes]:
    """获取 PCM16 mono frames 迭代器（供 webrtcvad 使用）
    
    Args:
        audio_path: 音频文件路径
        target_sr: 目标采样率（8000/16000/32000/48000）
        frame_ms: 帧长度（毫秒，10/20/30）
        ffmpeg_path: ffmpeg 可执行文件路径（可选，默认从 PATH 查找）
    
    Yields:
        bytes: 每个帧的 PCM16 数据，长度为 frame_bytes = target_sr * frame_ms / 1000 * 2
    
    Raises:
        RuntimeError: 如果无法获取 frames（ffmpeg 不可用且音频格式不匹配）
    """
    frame_bytes = int(target_sr * frame_ms / 1000 * 2)  # 16-bit = 2 bytes per sample
    
    # 尝试使用 ffmpeg（推荐方式）
    if ffmpeg_path is None:
        ffmpeg_path = which("ffmpeg")
    
    if ffmpeg_path:
        try:
            yield from _get_frames_via_ffmpeg(
                audio_path=audio_path,
                target_sr=target_sr,
                frame_bytes=frame_bytes,
                ffmpeg_path=ffmpeg_path,
            )
            return
        except Exception as e:
            logger.warning(f"使用 ffmpeg 转换失败: {e}，尝试直接读取 WAV")
    
    # 备用方案：直接读取 WAV（要求 PCM16 mono 且采样率匹配）
    try:
        yield from _get_frames_from_wav(
            audio_path=audio_path,
            target_sr=target_sr,
            frame_bytes=frame_bytes,
        )
    except Exception as e:
        error_msg = (
            f"vad 策略需要 PCM16 mono + 采样率 {target_sr}Hz，"
            f"但音频格式不符合且 ffmpeg 不可用。"
            f"请在 Repo1 ingest 阶段设定 sample_rate={target_sr} channels=1，或安装 ffmpeg。"
            f"原始错误: {e}"
        )
        raise RuntimeError(error_msg) from e


def _get_frames_via_ffmpeg(
    audio_path: Path,
    target_sr: int,
    frame_bytes: int,
    ffmpeg_path: str,
) -> Iterator[bytes]:
    """使用 ffmpeg 转换音频为 PCM16 mono 并逐帧读取
    
    Args:
        audio_path: 音频文件路径
        target_sr: 目标采样率
        frame_bytes: 每帧的字节数
        ffmpeg_path: ffmpeg 可执行文件路径
    
    Yields:
        bytes: 每个帧的 PCM16 数据
    
    Raises:
        RuntimeError: ffmpeg 执行失败
    """
    cmd = [
        ffmpeg_path,
        "-hide_banner",
        "-nostats",
        "-i",
        str(audio_path),
        "-ac",
        "1",  # 单声道
        "-ar",
        str(target_sr),  # 采样率
        "-f",
        "s16le",  # 16-bit little-endian PCM
        "-",  # 输出到 stdout
    ]
    
    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=frame_bytes * 2,  # 设置缓冲区大小为 2 帧
        )
        
        # 逐帧读取
        while True:
            frame = process.stdout.read(frame_bytes)
            if len(frame) == 0:
                break  # EOF
            if len(frame) < frame_bytes:
                # 尾部不足一帧，直接丢弃（保证确定性）
                logger.debug(f"丢弃尾部不足一帧的数据（{len(frame)}/{frame_bytes} 字节）")
                break
            yield frame
        
        # 等待进程结束
        process.wait(timeout=30)
        if process.returncode != 0:
            stderr = process.stderr.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"ffmpeg 执行失败（返回码 {process.returncode}）: {stderr[:200]}")
        
    except subprocess.TimeoutExpired:
        process.kill()
        raise RuntimeError("ffmpeg 执行超时")
    except Exception as e:
        if isinstance(e, RuntimeError):
            raise
        raise RuntimeError(f"使用 ffmpeg 转换音频失败: {e}") from e
    finally:
        if process.poll() is None:
            process.kill()


def _get_frames_from_wav(
    audio_path: Path,
    target_sr: int,
    frame_bytes: int,
) -> Iterator[bytes]:
    """直接从 WAV 文件读取 PCM16 mono frames（备用方案）
    
    Args:
        audio_path: WAV 文件路径
        target_sr: 目标采样率（必须匹配）
        frame_bytes: 每帧的字节数
    
    Yields:
        bytes: 每个帧的 PCM16 数据
    
    Raises:
        ValueError: 音频格式不符合要求（非 PCM16、非 mono、采样率不匹配）
    """
    try:
        with wave.open(str(audio_path), "rb") as wf:
            sample_rate = wf.getframerate()
            sample_width = wf.getsampwidth()
            n_channels = wf.getnchannels()
            
            # 检查格式
            if sample_width != 2:
                raise ValueError(f"不支持的样本宽度: {sample_width}（需要 2，即 16-bit PCM）")
            if n_channels != 1:
                raise ValueError(f"不支持的声道数: {n_channels}（需要 1，即 mono）")
            if sample_rate != target_sr:
                raise ValueError(f"采样率不匹配: {sample_rate}（需要 {target_sr}）")
            
            # 逐帧读取
            while True:
                # 计算需要读取的帧数
                frame_samples = frame_bytes // 2  # 16-bit = 2 bytes per sample
                frames = wf.readframes(frame_samples)
                
                if len(frames) == 0:
                    break  # EOF
                if len(frames) < frame_bytes:
                    # 尾部不足一帧，直接丢弃（保证确定性）
                    logger.debug(f"丢弃尾部不足一帧的数据（{len(frames)}/{frame_bytes} 字节）")
                    break
                yield frames
                
    except wave.Error as e:
        raise ValueError(f"无法读取 WAV 文件: {e}") from e
    except OSError as e:
        raise ValueError(f"文件读取失败: {e}") from e

