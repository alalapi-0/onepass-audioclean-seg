"""Energy 策略：基于 RMS 能量的语音/非语音检测"""

import array
import json
import logging
import math
import wave
from pathlib import Path
from typing import Any

from onepass_audioclean_seg.audio.probe import get_audio_duration_sec
from onepass_audioclean_seg.pipeline.jobs import SegJob
from onepass_audioclean_seg.strategies.base import AnalysisResult, SegmentStrategy
from typing import Optional

logger = logging.getLogger(__name__)


class EnergyStrategy(SegmentStrategy):
    """Energy 策略：基于短帧 RMS（能量）判定语音/非语音"""
    
    @property
    def name(self) -> str:
        return "energy"
    
    def analyze(
        self,
        job: SegJob,
        params: dict[str, Any],
    ) -> AnalysisResult:
        """分析音频并返回原始语音段
        
        Args:
            job: 分段任务对象
            params: 参数字典（包含 energy_frame_ms, energy_hop_ms, energy_smooth_ms, 
                              energy_threshold_rms, energy_min_speech_sec 等）
        
        Returns:
            AnalysisResult 对象
        """
        # 获取参数
        frame_ms = params.get("energy_frame_ms", 30.0)
        hop_ms = params.get("energy_hop_ms", 10.0)
        smooth_ms = params.get("energy_smooth_ms", 100.0)
        threshold_rms = params.get("energy_threshold_rms", 0.02)
        min_speech_sec = params.get("energy_min_speech_sec", 0.20)
        min_silence_sec = params.get("min_silence_sec", 0.35)  # 复用全局参数
        
        # 获取音频时长（优先 meta.json，其次 ffprobe，最后从 WAV 文件计算）
        duration_sec = get_audio_duration_sec(
            audio_path=job.audio_path,
            meta_path=job.meta_path,
        )
        if duration_sec is None:
            # 尝试从 WAV 文件直接计算（energy 策略的备用方案）
            duration_sec = self._get_duration_from_wav(job.audio_path)
            if duration_sec is None:
                raise RuntimeError("无法获取音频时长（需要 meta.json、ffprobe 或有效的 WAV 文件）")
        
        # A) 帧化并计算 RMS 序列（流式计算）
        rms_series, frame_times = self._compute_rms_series(
            audio_path=job.audio_path,
            frame_ms=frame_ms,
            hop_ms=hop_ms,
            duration_sec=duration_sec,
        )
        
        if not rms_series:
            # 如果没有任何帧，返回空结果
            logger.warning(f"音频时长过短，无法计算 RMS 序列")
            return AnalysisResult(
                strategy="energy",
                duration_sec=round(duration_sec, 3),
                speech_segments_raw=[],
                artifacts={},
                warnings=["音频时长过短，无法计算 RMS 序列"],
                stats={"frames": 0},
            )
        
        # B) 平滑与阈值判定
        smoothed_rms = self._smooth_rms(rms_series, smooth_ms, hop_ms)
        speech_mask = [rms >= threshold_rms for rms in smoothed_rms]
        
        # C) 形态学后处理
        speech_segments_raw = self._morphological_postprocess(
            speech_mask=speech_mask,
            frame_times=frame_times,
            frame_ms=frame_ms,
            hop_ms=hop_ms,
            min_speech_sec=min_speech_sec,
            min_silence_sec=min_silence_sec,
            duration_sec=duration_sec,
        )
        
        # D) 构建 artifacts（写入 energy.json）
        speech_frames = sum(speech_mask)
        energy_data = {
            "audio_path": str(job.audio_path.resolve()),
            "strategy": "energy",
            "params": {
                "frame_ms": frame_ms,
                "hop_ms": hop_ms,
                "smooth_ms": smooth_ms,
                "threshold_rms": threshold_rms,
                "min_speech_sec": min_speech_sec,
                "min_silence_sec": min_silence_sec,
            },
            "duration_sec": round(duration_sec, 3),
            "speech_segments_raw": [[round(s, 3), round(e, 3)] for s, e in speech_segments_raw],
            "stats": {
                "frames": len(rms_series),
                "speech_frames": speech_frames,
                "threshold_rms": threshold_rms,
            },
        }
        
        energy_path = self.write_artifact(job.out_dir, "energy.json", energy_data)
        
        # 构建 stats
        stats = {
            "frames": len(rms_series),
            "speech_frames": speech_frames,
            "threshold_rms": threshold_rms,
            "speech_raw_count": len(speech_segments_raw),
            "speech_raw_total_sec": round(sum(e - s for s, e in speech_segments_raw), 3),
        }
        
        return AnalysisResult(
            strategy="energy",
            duration_sec=round(duration_sec, 3),
            speech_segments_raw=speech_segments_raw,
            artifacts={"energy.json": energy_path},
            warnings=[],
            stats=stats,
        )
    
    def _compute_rms_series(
        self,
        audio_path: Path,
        frame_ms: float,
        hop_ms: float,
        duration_sec: float,
    ) -> tuple[list[float], list[float]]:
        """流式计算 RMS 序列
        
        Args:
            audio_path: 音频文件路径
            frame_ms: 帧长度（毫秒）
            hop_ms: 帧移（毫秒）
            duration_sec: 音频总时长（秒）
        
        Returns:
            (rms_series, frame_times) 元组
            - rms_series: 每帧的 RMS 值列表（归一化到 [0, 1]）
            - frame_times: 每帧的起始时间列表（秒）
        """
        rms_series = []
        frame_times = []
        
        try:
            with wave.open(str(audio_path), "rb") as wf:
                sample_rate = wf.getframerate()
                sample_width = wf.getsampwidth()
                n_channels = wf.getnchannels()
                
                # 只支持 16-bit PCM
                if sample_width != 2:
                    raise ValueError(f"不支持的样本宽度: {sample_width}（需要 2，即 16-bit PCM）")
                
                # 转换为样本数
                frame_samples = int(frame_ms * sample_rate / 1000.0)
                hop_samples = int(hop_ms * sample_rate / 1000.0)
                
                if frame_samples <= 0 or hop_samples <= 0:
                    logger.warning(f"帧长度或帧移过小: frame_samples={frame_samples}, hop_samples={hop_samples}")
                    return [], []
                
                # 流式读取并计算 RMS
                current_pos = 0
                total_samples = int(duration_sec * sample_rate)
                
                while current_pos < total_samples:
                    # 计算当前帧的结束位置
                    frame_end = min(current_pos + frame_samples, total_samples)
                    n_samples = frame_end - current_pos
                    
                    if n_samples <= 0:
                        break
                    
                    # 定位到当前帧
                    wf.setpos(current_pos)
                    
                    # 读取帧数据
                    frames = wf.readframes(n_samples)
                    
                    if len(frames) == 0:
                        break
                    
                    # 转换为 array（int16）
                    audio_data = array.array("h", frames)
                    
                    # 如果是多声道，取平均值
                    if n_channels > 1:
                        n_samples_mono = len(audio_data) // n_channels
                        mono_data = []
                        for i in range(n_samples_mono):
                            sample_sum = sum(audio_data[i * n_channels + ch] for ch in range(n_channels))
                            mono_data.append(sample_sum / n_channels)
                        audio_data = array.array("h", [int(x) for x in mono_data])
                    
                    # 计算 RMS（归一化到 [0, 1]）
                    if len(audio_data) > 0:
                        sum_squares = sum(float(x) ** 2 for x in audio_data)
                        mean_square = sum_squares / len(audio_data)
                        rms = math.sqrt(mean_square) / 32768.0
                        rms_series.append(float(rms))
                        
                        # 记录帧起始时间
                        frame_time = current_pos / sample_rate
                        frame_times.append(frame_time)
                    
                    # 移动到下一帧（hop）
                    current_pos += hop_samples
                
        except wave.Error as e:
            logger.warning(f"wave 库读取失败: {e}")
            raise
        except OSError as e:
            logger.warning(f"文件读取失败: {e}")
            raise
        except Exception as e:
            logger.warning(f"计算 RMS 序列时发生未预期错误: {e}", exc_info=True)
            raise
        
        return rms_series, frame_times
    
    def _smooth_rms(
        self,
        rms_series: list[float],
        smooth_ms: float,
        hop_ms: float,
    ) -> list[float]:
        """平滑 RMS 序列（简单滑动平均）
        
        Args:
            rms_series: 原始 RMS 序列
            smooth_ms: 平滑窗口长度（毫秒）
            hop_ms: 帧移（毫秒）
        
        Returns:
            平滑后的 RMS 序列
        """
        if not rms_series:
            return []
        
        # 计算窗口大小（帧数）
        window_frames = max(1, int(smooth_ms / hop_ms))
        
        smoothed = []
        n = len(rms_series)
        
        for i in range(n):
            # 计算窗口范围
            start_idx = max(0, i - window_frames // 2)
            end_idx = min(n, i + window_frames // 2 + 1)
            
            # 计算平均值
            window_values = rms_series[start_idx:end_idx]
            avg = sum(window_values) / len(window_values) if window_values else rms_series[i]
            smoothed.append(avg)
        
        return smoothed
    
    def _morphological_postprocess(
        self,
        speech_mask: list[bool],
        frame_times: list[float],
        frame_ms: float,
        hop_ms: float,
        min_speech_sec: float,
        min_silence_sec: float,
        duration_sec: float,
    ) -> list[tuple[float, float]]:
        """形态学后处理：减少碎片
        
        1. 最小语音长度过滤：删除短于 min_speech_sec 的 speech islands
        2. 最小静音长度填平：填平短于 min_silence_sec 的 silence gaps
        
        Args:
            speech_mask: 语音掩码（True=语音，False=非语音）
            frame_times: 每帧的起始时间列表
            frame_ms: 帧长度（毫秒）
            hop_ms: 帧移（毫秒）
            min_speech_sec: 最小语音长度（秒）
            min_silence_sec: 最小静音长度（秒）
            duration_sec: 音频总时长（秒）
        
        Returns:
            语音段列表，每个元素为 (start, end) 元组
        """
        if not speech_mask or not frame_times:
            return []
        
        # 将 mask 转为区间列表（runs）
        runs = []  # [(start_idx, end_idx, is_speech), ...]
        current_run_start = 0
        current_value = speech_mask[0]
        
        for i in range(1, len(speech_mask)):
            if speech_mask[i] != current_value:
                # 结束当前 run
                runs.append((current_run_start, i - 1, current_value))
                current_run_start = i
                current_value = speech_mask[i]
        
        # 添加最后一个 run
        runs.append((current_run_start, len(speech_mask) - 1, current_value))
        
        # 步骤 1: 删除极短 speech runs（< min_speech_sec）
        frame_sec = frame_ms / 1000.0
        hop_sec = hop_ms / 1000.0
        
        filtered_runs = []
        for start_idx, end_idx, is_speech in runs:
            if is_speech:
                # 计算 run 的时长
                run_start_time = frame_times[start_idx]
                run_end_time = frame_times[end_idx] + frame_sec
                run_duration = run_end_time - run_start_time
                
                if run_duration >= min_speech_sec:
                    filtered_runs.append((start_idx, end_idx, is_speech))
                # 否则丢弃（标记为非语音）
            else:
                filtered_runs.append((start_idx, end_idx, is_speech))
        
        # 步骤 2: 填平短 silence gaps（< min_silence_sec）
        filled_runs = []
        for i, (start_idx, end_idx, is_speech) in enumerate(filtered_runs):
            if not is_speech:
                # 计算 silence run 的时长
                run_start_time = frame_times[start_idx]
                run_end_time = frame_times[end_idx] + frame_sec
                run_duration = run_end_time - run_start_time
                
                if run_duration < min_silence_sec:
                    # 填平：翻转为 speech
                    filled_runs.append((start_idx, end_idx, True))
                else:
                    filled_runs.append((start_idx, end_idx, False))
            else:
                filled_runs.append((start_idx, end_idx, is_speech))
        
        # 合并连续的相同类型 runs
        merged_runs = []
        for start_idx, end_idx, is_speech in filled_runs:
            if not merged_runs:
                merged_runs.append((start_idx, end_idx, is_speech))
            else:
                last_start, last_end, last_is_speech = merged_runs[-1]
                if is_speech == last_is_speech:
                    # 合并
                    merged_runs[-1] = (last_start, end_idx, is_speech)
                else:
                    merged_runs.append((start_idx, end_idx, is_speech))
        
        # 提取 speech segments
        segments = []
        for start_idx, end_idx, is_speech in merged_runs:
            if is_speech:
                seg_start = frame_times[start_idx]
                seg_end = min(frame_times[end_idx] + frame_sec, duration_sec)
                if seg_end > seg_start:
                    segments.append((round(seg_start, 3), round(seg_end, 3)))
        
        # 按 start 排序
        segments.sort(key=lambda x: x[0])
        
        return segments
    
    def _get_duration_from_wav(self, audio_path: Path) -> Optional[float]:
        """从 WAV 文件直接计算时长（备用方案）
        
        Args:
            audio_path: WAV 文件路径
        
        Returns:
            时长（秒），若无法计算则返回 None
        """
        try:
            with wave.open(str(audio_path), "rb") as wf:
                n_frames = wf.getnframes()
                sample_rate = wf.getframerate()
                if sample_rate > 0:
                    duration = n_frames / sample_rate
                    return float(duration)
        except Exception as e:
            logger.debug(f"从 WAV 文件计算时长失败: {e}")
        return None

