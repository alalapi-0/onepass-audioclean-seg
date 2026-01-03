"""FFmpeg silencedetect 运行器与解析器"""

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from onepass_audioclean_seg.audio.ffmpeg import run_cmd, which
from onepass_audioclean_seg.audio.probe import get_audio_duration_sec
from onepass_audioclean_seg.pipeline.jobs import SegJob
from onepass_audioclean_seg.pipeline.segments_from_silence import complement_to_speech_segments, normalize_intervals
from onepass_audioclean_seg.strategies.base import AnalysisResult, SegmentStrategy

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SilenceInterval:
    """静音区间"""
    
    start_sec: float
    end_sec: float
    duration_sec: float


def build_silencedetect_cmd(
    ffmpeg_path: str,
    audio_path: Path,
    threshold_db: float,
    min_silence_sec: float,
) -> list[str]:
    """构建 silencedetect 命令
    
    Args:
        ffmpeg_path: ffmpeg 可执行文件路径
        audio_path: 音频文件路径
        threshold_db: 静音阈值（dB，如 -35）
        min_silence_sec: 最小静音时长（秒）
    
    Returns:
        命令列表
    """
    return [
        ffmpeg_path,
        "-hide_banner",
        "-nostats",
        "-i",
        str(audio_path),
        "-af",
        f"silencedetect=noise={threshold_db}dB:d={min_silence_sec}",
        "-f",
        "null",
        "-",
    ]


def run_silencedetect(
    ffmpeg_path: str,
    audio_path: Path,
    threshold_db: float,
    min_silence_sec: float,
    timeout_sec: int = 300,
) -> str:
    """运行 silencedetect 并返回输出文本
    
    Args:
        ffmpeg_path: ffmpeg 可执行文件路径
        audio_path: 音频文件路径
        threshold_db: 静音阈值（dB）
        min_silence_sec: 最小静音时长（秒）
        timeout_sec: 超时时间（秒，默认 300）
    
    Returns:
        用于解析的完整文本（stdout + stderr 合并）
    
    Raises:
        TimeoutError: 命令执行超时
        OSError: 无法执行命令
        RuntimeError: ffmpeg 返回非 0 退出码
    """
    cmd = build_silencedetect_cmd(ffmpeg_path, audio_path, threshold_db, min_silence_sec)
    
    try:
        result = run_cmd(cmd, timeout_sec=timeout_sec)
        
        # 合并 stdout 和 stderr（silencedetect 输出通常在 stderr）
        output = result.stdout + result.stderr
        
        # 如果返回码非 0，抛出异常
        if result.returncode != 0:
            error_msg = result.stderr or result.stdout or "未知错误"
            raise RuntimeError(f"ffmpeg silencedetect 执行失败（返回码 {result.returncode}）: {error_msg}")
        
        return output
    except TimeoutError:
        raise
    except OSError:
        raise
    except Exception as e:
        if isinstance(e, (TimeoutError, OSError, RuntimeError)):
            raise
        raise RuntimeError(f"运行 silencedetect 时发生未预期错误: {e}") from e


def parse_silencedetect_output(
    text: str,
    audio_duration_sec: Optional[float] = None,
) -> list[SilenceInterval]:
    """解析 silencedetect 输出文本
    
    Args:
        text: silencedetect 输出文本（stdout + stderr 合并）
        audio_duration_sec: 音频总时长（秒，可选，用于闭合未结束的区间）
    
    Returns:
        静音区间列表（已排序、已清理）
    """
    intervals = []
    pending_start: Optional[float] = None
    
    # 按行解析
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        
        # 匹配 silence_start
        start_match = re.search(r"silence_start:\s*([\d.]+)", line)
        if start_match:
            start_sec = float(start_match.group(1))
            # 如果已有 pending_start，记录警告但继续
            if pending_start is not None:
                logger.warning(f"发现新的 silence_start ({start_sec}) 但已有 pending_start ({pending_start})，丢弃未闭合区间")
            pending_start = start_sec
            continue
        
        # 匹配 silence_end
        end_match = re.search(r"silence_end:\s*([\d.]+)", line)
        if end_match:
            end_sec = float(end_match.group(1))
            if pending_start is not None:
                # 尝试从同一行提取 duration（如果有）
                duration_match = re.search(r"silence_duration:\s*([\d.]+)", line)
                if duration_match:
                    duration_sec = float(duration_match.group(1))
                else:
                    duration_sec = end_sec - pending_start
                
                # 创建区间
                intervals.append(SilenceInterval(
                    start_sec=round(pending_start, 3),
                    end_sec=round(end_sec, 3),
                    duration_sec=round(duration_sec, 3),
                ))
                pending_start = None
            else:
                logger.warning(f"发现 silence_end ({end_sec}) 但没有对应的 silence_start，跳过")
            continue
    
    # 处理未闭合的区间（只有 start 没有 end）
    if pending_start is not None:
        if audio_duration_sec is not None:
            end_sec = audio_duration_sec
            duration_sec = end_sec - pending_start
            intervals.append(SilenceInterval(
                start_sec=round(pending_start, 3),
                end_sec=round(audio_duration_sec, 3),
                duration_sec=round(duration_sec, 3),
            ))
            logger.info(f"闭合未结束的静音区间: {pending_start} -> {audio_duration_sec}")
        else:
            logger.warning(f"发现未闭合的静音区间（start={pending_start}），但 audio_duration_sec 不可用，丢弃该区间")
    
    # 排序（按 start_sec）
    intervals.sort(key=lambda x: x.start_sec)
    
    # 清理：clip 到 [0, audio_duration_sec] 并过滤异常区间
    cleaned_intervals = []
    for interval in intervals:
        # clip 到有效范围
        start_sec = max(0.0, interval.start_sec)
        if audio_duration_sec is not None:
            start_sec = min(start_sec, audio_duration_sec)
            end_sec = min(interval.end_sec, audio_duration_sec)
        else:
            end_sec = interval.end_sec
        
        # 过滤掉 end <= start 的异常区间
        if end_sec <= start_sec:
            logger.warning(f"过滤异常区间: start={start_sec}, end={end_sec}")
            continue
        
        # 重新计算 duration
        duration_sec = end_sec - start_sec
        
        cleaned_intervals.append(SilenceInterval(
            start_sec=round(start_sec, 3),
            end_sec=round(end_sec, 3),
            duration_sec=round(duration_sec, 3),
        ))
    
    return cleaned_intervals


class SilenceStrategy(SegmentStrategy):
    """Silence 策略：基于 ffmpeg silencedetect 的静音检测"""
    
    @property
    def name(self) -> str:
        return "silence"
    
    def analyze(
        self,
        job: SegJob,
        params: dict[str, Any],
    ) -> AnalysisResult:
        """运行 silencedetect 分析并返回语音段
        
        Args:
            job: 分段任务对象
            params: 参数字典（包含 silence_threshold_db, min_silence_sec 等）
        
        Returns:
            AnalysisResult 对象
        """
        # 获取参数
        threshold_db = params.get("silence_threshold_db", -35.0)
        min_silence_sec = params.get("min_silence_sec", 0.35)
        
        # 获取 ffmpeg 路径
        ffmpeg_path = which("ffmpeg")
        if ffmpeg_path is None:
            raise RuntimeError("ffmpeg 未找到，无法运行 silence 策略")
        
        # 获取音频时长
        duration_sec = get_audio_duration_sec(
            audio_path=job.audio_path,
            meta_path=job.meta_path,
        )
        if duration_sec is None:
            raise RuntimeError("无法获取音频时长（需要 meta.json 或 ffprobe）")
        
        # 运行 silencedetect
        output_text = run_silencedetect(
            ffmpeg_path=ffmpeg_path,
            audio_path=job.audio_path,
            threshold_db=threshold_db,
            min_silence_sec=min_silence_sec,
        )
        
        # 解析输出
        silence_intervals = parse_silencedetect_output(output_text, duration_sec)
        
        # 规范化静音区间
        normalized_silences = normalize_intervals(silence_intervals, duration_sec)
        
        # 生成语音段（补集）
        speech_segments_raw = complement_to_speech_segments(normalized_silences, duration_sec)
        
        # 构建 artifacts（写入 silences.json）
        silences_data = {
            "audio_path": str(job.audio_path.resolve()),
            "strategy": "silence",
            "params": {
                "silence_threshold_db": threshold_db,
                "min_silence_sec": min_silence_sec,
            },
            "duration_sec": round(duration_sec, 3),
            "silences": [
                {
                    "start_sec": interval.start_sec,
                    "end_sec": interval.end_sec,
                    "duration_sec": interval.duration_sec,
                }
                for interval in normalized_silences
            ],
        }
        
        silences_path = self.write_artifact(job.out_dir, "silences.json", silences_data)
        
        # 构建 stats
        silences_total_sec = sum(interval.duration_sec for interval in normalized_silences)
        stats = {
            "silences_count": len(normalized_silences),
            "silences_total_sec": round(silences_total_sec, 3),
            "threshold_db": threshold_db,
            "min_silence_sec": min_silence_sec,
        }
        
        return AnalysisResult(
            strategy="silence",
            duration_sec=round(duration_sec, 3),
            speech_segments_raw=speech_segments_raw,
            nonspeech_segments_raw=[(s.start_sec, s.end_sec) for s in normalized_silences],
            artifacts={"silences.json": silences_path},
            warnings=[],
            stats=stats,
        )

