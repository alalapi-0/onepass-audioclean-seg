"""VAD 策略：基于 webrtcvad 的语音活动检测"""

import json
import logging
from pathlib import Path
from typing import Any

from onepass_audioclean_seg.audio.ffmpeg import which
from onepass_audioclean_seg.audio.probe import get_audio_duration_sec
from onepass_audioclean_seg.audio.vad_io import get_pcm16_mono_frames
from onepass_audioclean_seg.pipeline.jobs import SegJob
from onepass_audioclean_seg.strategies.base import AnalysisResult, SegmentStrategy

logger = logging.getLogger(__name__)


def _import_webrtcvad():
    """动态导入 webrtcvad
    
    Returns:
        webrtcvad 模块
    
    Raises:
        ImportError: 如果 webrtcvad 未安装，给出清晰的错误信息
    """
    try:
        import webrtcvad
        return webrtcvad
    except ImportError as e:
        raise ImportError(
            "webrtcvad 未安装。请运行: pip install -e \".[vad]\" 或 pip install webrtcvad>=2.0.10"
        ) from e


class VadStrategy(SegmentStrategy):
    """VAD 策略：基于 webrtcvad 的语音活动检测"""
    
    @property
    def name(self) -> str:
        return "vad"
    
    def analyze(
        self,
        job: SegJob,
        params: dict[str, Any],
    ) -> AnalysisResult:
        """分析音频并返回原始语音段
        
        Args:
            job: 分段任务对象
            params: 参数字典（包含 vad_aggressiveness, vad_frame_ms, vad_sample_rate 等）
        
        Returns:
            AnalysisResult 对象
        
        Raises:
            ImportError: webrtcvad 未安装
            RuntimeError: 音频格式不符合要求且 ffmpeg 不可用
        """
        # 动态导入 webrtcvad（检查依赖）
        webrtcvad = _import_webrtcvad()
        
        # 获取参数
        aggressiveness = params.get("vad_aggressiveness", 2)
        frame_ms = params.get("vad_frame_ms", 30)
        sample_rate = params.get("vad_sample_rate", 16000)
        min_speech_sec = params.get("vad_min_speech_sec", 0.20)
        min_silence_sec = params.get("min_silence_sec", 0.35)  # 复用全局参数
        
        # 参数验证
        if aggressiveness not in [0, 1, 2, 3]:
            raise ValueError(f"vad_aggressiveness 必须在 0..3 范围内，当前值: {aggressiveness}")
        if frame_ms not in [10, 20, 30]:
            raise ValueError(f"vad_frame_ms 必须是 10/20/30，当前值: {frame_ms}")
        if sample_rate not in [8000, 16000, 32000, 48000]:
            raise ValueError(f"vad_sample_rate 必须是 8000/16000/32000/48000，当前值: {sample_rate}")
        
        # 获取音频时长
        duration_sec = get_audio_duration_sec(
            audio_path=job.audio_path,
            meta_path=job.meta_path,
        )
        if duration_sec is None:
            raise RuntimeError("无法获取音频时长（需要 meta.json 或 ffprobe）")
        
        # 获取 ffmpeg 路径（用于音频转换）
        ffmpeg_path = which("ffmpeg")
        
        # 获取 PCM16 mono frames
        try:
            frames_iter = get_pcm16_mono_frames(
                audio_path=job.audio_path,
                target_sr=sample_rate,
                frame_ms=frame_ms,
                ffmpeg_path=ffmpeg_path,
            )
        except RuntimeError as e:
            # 如果错误信息已经很清楚，直接抛出
            raise RuntimeError(f"无法获取 PCM16 mono frames: {e}") from e
        
        # 初始化 webrtcvad.Vad
        vad = webrtcvad.Vad(aggressiveness)
        
        # 逐帧判定
        speech_mask = []  # 每帧一个 boolean
        frame_sec = frame_ms / 1000.0
        frame_count = 0
        
        try:
            for frame_bytes in frames_iter:
                is_speech = vad.is_speech(frame_bytes, sample_rate)
                speech_mask.append(is_speech)
                frame_count += 1
        except Exception as e:
            raise RuntimeError(f"webrtcvad 处理失败: {e}") from e
        
        if frame_count == 0:
            logger.warning("音频未产生任何帧，返回空结果")
            return AnalysisResult(
                strategy="vad",
                duration_sec=round(duration_sec, 3),
                speech_segments_raw=[],
                artifacts={},
                warnings=["音频未产生任何帧"],
                stats={
                    "frames": 0,
                    "speech_frames": 0,
                    "aggressiveness": aggressiveness,
                    "frame_ms": frame_ms,
                    "sample_rate": sample_rate,
                },
            )
        
        # 将 frame-level mask 转为 speech runs（区间）
        speech_segments_raw = self._mask_to_segments(
            speech_mask=speech_mask,
            frame_sec=frame_sec,
            min_speech_sec=min_speech_sec,
            min_silence_sec=min_silence_sec,
            duration_sec=duration_sec,
        )
        
        # 构建 artifacts（写入 vad.json）
        speech_frames = sum(speech_mask)
        vad_data = {
            "audio_path": str(job.audio_path.resolve()),
            "strategy": "vad",
            "params": {
                "vad_aggressiveness": aggressiveness,
                "vad_frame_ms": frame_ms,
                "vad_sample_rate": sample_rate,
                "vad_min_speech_sec": min_speech_sec,
                "min_silence_sec": min_silence_sec,
            },
            "duration_sec": round(duration_sec, 3),
            "frame_ms": frame_ms,
            "frames": frame_count,
            "speech_frames": speech_frames,
            "speech_segments_raw": [[round(s, 3), round(e, 3)] for s, e in speech_segments_raw],
        }
        
        vad_path = self.write_artifact(job.out_dir, "vad.json", vad_data)
        
        # 构建 stats
        stats = {
            "frames": frame_count,
            "speech_frames": speech_frames,
            "aggressiveness": aggressiveness,
            "frame_ms": frame_ms,
            "sample_rate": sample_rate,
            "speech_raw_count": len(speech_segments_raw),
            "speech_raw_total_sec": round(sum(e - s for s, e in speech_segments_raw), 3),
        }
        
        return AnalysisResult(
            strategy="vad",
            duration_sec=round(duration_sec, 3),
            speech_segments_raw=speech_segments_raw,
            artifacts={"vad.json": vad_path},
            warnings=[],
            stats=stats,
        )
    
    def _mask_to_segments(
        self,
        speech_mask: list[bool],
        frame_sec: float,
        min_speech_sec: float,
        min_silence_sec: float,
        duration_sec: float,
    ) -> list[tuple[float, float]]:
        """将 frame-level mask 转为语音段（带形态学后处理）
        
        Args:
            speech_mask: 每帧的语音掩码（True=语音，False=非语音）
            frame_sec: 每帧的时长（秒）
            min_speech_sec: 最小语音长度（秒，删除极短语音岛）
            min_silence_sec: 最小静音长度（秒，填平短静音）
            duration_sec: 音频总时长（秒）
        
        Returns:
            语音段列表，每个元素为 (start, end) 元组，已排序且 round(3)
        """
        if not speech_mask:
            return []
        
        # 将 mask 转为 runs
        runs = []  # [(start_idx, end_idx, is_speech), ...]
        current_run_start = 0
        current_value = speech_mask[0]
        
        for i in range(1, len(speech_mask)):
            if speech_mask[i] != current_value:
                runs.append((current_run_start, i - 1, current_value))
                current_run_start = i
                current_value = speech_mask[i]
        
        # 添加最后一个 run
        runs.append((current_run_start, len(speech_mask) - 1, current_value))
        
        # 步骤 1: 删除极短 speech runs（< min_speech_sec）
        filtered_runs = []
        for start_idx, end_idx, is_speech in runs:
            if is_speech:
                run_start_time = start_idx * frame_sec
                run_end_time = (end_idx + 1) * frame_sec
                run_duration = run_end_time - run_start_time
                
                if run_duration >= min_speech_sec:
                    filtered_runs.append((start_idx, end_idx, is_speech))
                # 否则丢弃（标记为非语音）
            else:
                filtered_runs.append((start_idx, end_idx, is_speech))
        
        # 步骤 2: 填平短 silence gaps（< min_silence_sec）
        filled_runs = []
        for start_idx, end_idx, is_speech in filtered_runs:
            if not is_speech:
                run_start_time = start_idx * frame_sec
                run_end_time = (end_idx + 1) * frame_sec
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
                seg_start = start_idx * frame_sec
                seg_end = min((end_idx + 1) * frame_sec, duration_sec)
                if seg_end > seg_start:
                    segments.append((round(seg_start, 3), round(seg_end, 3)))
        
        # 按 start 排序
        segments.sort(key=lambda x: x[0])
        
        return segments

