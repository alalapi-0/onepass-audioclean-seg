"""输出布局规划和执行计划"""

import json
import logging
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from onepass_audioclean_seg.audio.ffmpeg import which
from onepass_audioclean_seg.audio.probe import get_audio_duration_sec
from onepass_audioclean_seg.io.report import (
    read_seg_report,
    update_seg_report_analysis,
    update_seg_report_segments,
    write_seg_report,
)
from onepass_audioclean_seg.io.segments import SegmentRecord, write_segments_jsonl
from onepass_audioclean_seg.pipeline.jobs import SegJob
from onepass_audioclean_seg.pipeline.segments_from_silence import (
    apply_padding_and_clip,
    complement_to_speech_segments,
    enforce_max_duration_by_split,
    enforce_min_duration_by_merge,
    merge_overlaps,
    normalize_intervals,
)
from onepass_audioclean_seg.constants import DEFAULT_AUTO_STRATEGY_MAX_SPEECH_RATIO
from onepass_audioclean_seg.strategies.base import AnalysisResult, SegmentStrategy
from onepass_audioclean_seg.strategies.energy_rms import EnergyStrategy
from onepass_audioclean_seg.strategies.silence_ffmpeg import (
    SilenceInterval,
    SilenceStrategy,
)
from onepass_audioclean_seg.strategies.vad_webrtc import VadStrategy

logger = logging.getLogger(__name__)


class SegmentPlanner:
    """分段计划器：处理输出布局、dry-run 输出、写入报告、静音分析"""
    
    def __init__(
        self,
        dry_run: bool = False,
        overwrite: bool = False,
        analyze: bool = False,
        emit_segments: bool = False,
        silence_threshold_db: float = -35.0,
        validate_output: bool = False,
        export_timeline: bool = False,
        export_csv: bool = False,
        export_mask: str = "none",
        mask_bin_ms: float = 50.0,
    ):
        """
        Args:
            dry_run: 是否为 dry-run 模式（只打印计划，不写入文件）
            overwrite: 是否覆盖已存在的文件
            analyze: 是否运行静音分析
            emit_segments: 是否生成语音片段
            silence_threshold_db: 静音检测阈值（dB）
            validate_output: 是否在生成 segments.jsonl 后立即验证
            export_timeline: 是否导出 timeline.json（R10）
            export_csv: 是否导出 segments.csv（R10）
            export_mask: 导出 mask.json 的模式（none|energy|vad|auto，R10）
            mask_bin_ms: mask 降采样 bin 大小（毫秒，R10）
        """
        self.dry_run = dry_run
        self.overwrite = overwrite
        self.analyze = analyze
        self.emit_segments = emit_segments
        self.silence_threshold_db = silence_threshold_db
        self.validate_output = validate_output
        self.export_timeline = export_timeline
        self.export_csv = export_csv
        self.export_mask = export_mask
        self.mask_bin_ms = mask_bin_ms
        self.job_stats: list[dict[str, Any]] = []  # 记录每个 job 的统计信息
        self.started_at = datetime.now().isoformat()
        self.has_any_error = False  # 记录是否有任何错误
        self._current_config_hash: Optional[str] = None  # R11: 当前配置哈希
    
    def plan_and_execute(
        self,
        jobs: list[SegJob],
        params: dict[str, Any],
        effective_config: Optional[dict[str, Any]] = None,
        config_hash: Optional[str] = None,
    ) -> int:
        """规划并执行（或 dry-run）任务列表
        
        Args:
            jobs: 任务列表
            params: 参数字典（用于写入报告）
            effective_config: 合并后的最终配置（R11，可选）
            config_hash: 配置哈希值（R11，可选）
        
        Returns:
            处理的 job 数量
        """
        if not jobs:
            print("0 job(s)", file=sys.stdout)
            return 0
        
        executed_count = 0
        jobs_planned = len(jobs)
        jobs_analyzed = 0
        jobs_emitted = 0
        jobs_failed: list[dict[str, Any]] = []
        jobs_skipped = 0
        
        for job in jobs:
            job_stat = {
                "job_id": job.job_id,
                "status": "pending",
                "error": None,
            }
            
            # 检查是否跳过（如果 overwrite=False 且输出已存在）
            # 对于 emit_segments，检查 segments.jsonl；对于 analyze，检查 silences.json
            skip_file = None
            if self.emit_segments:
                skip_file = job.out_dir / "segments.jsonl"
            elif self.analyze:
                skip_file = job.out_dir / "silences.json"
            
            if skip_file and not self.overwrite and skip_file.exists():
                warnings_str = f" warnings={len(job.warnings)}" if job.warnings else ""
                print(f"SKIP {job.job_id} audio={job.audio_path} out={job.out_dir}{warnings_str}", file=sys.stdout)
                jobs_skipped += 1
                job_stat["status"] = "skipped"
                self.job_stats.append(job_stat)
                continue
            
            # 打印计划
            self._print_plan(job)
            
            # 如果不是 dry-run，创建目录并写入最小报告
            if not self.dry_run:
                try:
                    # R11: 从 plan_and_execute 的参数中获取 config_hash
                    config_hash = getattr(self, "_current_config_hash", None)
                    write_seg_report(
                        out_dir=job.out_dir,
                        params=params,
                        audio_path=job.audio_path,
                        meta_path=job.meta_path,
                        config_hash=config_hash,
                    )
                    executed_count += 1
                    
                    # 如果启用 analyze，运行静音分析
                    analyze_success = True
                    if self.analyze:
                        analyze_success = self._run_analyze(job, params)
                        if analyze_success:
                            jobs_analyzed += 1
                            job_stat["status"] = "analyzed"
                    
                    # 如果启用 emit_segments，生成语音片段
                    emit_success = True
                    if self.emit_segments:
                        emit_success = self._run_emit_segments(job, params)
                        if emit_success:
                            jobs_emitted += 1
                            if job_stat["status"] == "pending":
                                job_stat["status"] = "emitted"
                    
                    # 如果失败，记录错误
                    if not analyze_success or not emit_success:
                        job_stat["status"] = "failed"
                        reasons = []
                        if not analyze_success:
                            reasons.append("analyze 失败")
                        if not emit_success:
                            reasons.append("emit_segments 失败")
                        job_stat["error"] = "; ".join(reasons)
                        jobs_failed.append({
                            "job_id": job.job_id,
                            "reason": job_stat["error"],
                        })
                        self.has_any_error = True
                except Exception as e:
                    logger.error(f"写入报告失败 {job.job_id}: {e}", exc_info=True)
                    print(f"ERROR {job.job_id} failed to write report: {e}", file=sys.stderr)
                    job_stat["status"] = "failed"
                    job_stat["error"] = str(e)[:100]
                    jobs_failed.append({
                        "job_id": job.job_id,
                        "reason": job_stat["error"],
                    })
            else:
                executed_count += 1
                job_stat["status"] = "planned"
            
            self.job_stats.append(job_stat)
        
        # 生成 run_summary.json
        self._write_run_summary(
            jobs=jobs,
            params=params,
            jobs_planned=jobs_planned,
            jobs_analyzed=jobs_analyzed,
            jobs_emitted=jobs_emitted,
            jobs_failed=jobs_failed,
            jobs_skipped=jobs_skipped,
        )
        
        # R11: 生成 run_manifest.json
        if not self.dry_run:
            self._write_run_manifest(
                jobs=jobs,
                params=params,
                effective_config=effective_config,
                config_hash=config_hash,
            )
        
        return executed_count
    
    def get_exit_code(self) -> int:
        """获取退出码
        
        Returns:
            0 表示成功，1 表示有错误（analyze 或 emit_segments）
        """
        return 1 if self.has_any_error else 0
    
    def _get_strategy(self, strategy_name: str) -> SegmentStrategy:
        """获取策略实例
        
        Args:
            strategy_name: 策略名称（"silence"、"energy" 或 "vad"）
        
        Returns:
            策略实例
        
        Raises:
            ValueError: 不支持的策略名称
        """
        if strategy_name == "silence":
            return SilenceStrategy()
        elif strategy_name == "energy":
            return EnergyStrategy()
        elif strategy_name == "vad":
            return VadStrategy()
        else:
            raise ValueError(f"不支持的策略: {strategy_name}")
    
    def _run_analyze(self, job: SegJob, params: dict[str, Any]) -> bool:
        """运行分析（使用策略接口）
        
        Args:
            job: 任务对象
            params: 参数字典
        """
        strategy_name = params.get("strategy", "silence")
        
        try:
            # 确保 out_dir 存在
            job.out_dir.mkdir(parents=True, exist_ok=True)
            
            # 获取策略实例
            strategy = self._get_strategy(strategy_name)
            
            # 运行分析
            result = strategy.analyze(job, params)
            
            # 更新 seg_report.json（按策略区分）
            analysis_data = {strategy_name: result.stats}
            update_seg_report_analysis(job.out_dir, analysis_data)
            
            # 打印成功信息
            if strategy_name == "silence":
                count = result.stats.get("silences_count", 0)
                print(f"ANALYZE {job.job_id} strategy={strategy_name} silences={count} out={job.out_dir}", file=sys.stdout)
            elif strategy_name == "energy":
                frames = result.stats.get("frames", 0)
                segments = result.stats.get("speech_raw_count", 0)
                print(f"ANALYZE {job.job_id} strategy={strategy_name} frames={frames} segments={segments} out={job.out_dir}", file=sys.stdout)
            elif strategy_name == "vad":
                frames = result.stats.get("frames", 0)
                segments = result.stats.get("speech_raw_count", 0)
                print(f"ANALYZE {job.job_id} strategy={strategy_name} frames={frames} segments={segments} out={job.out_dir}", file=sys.stdout)
            else:
                print(f"ANALYZE {job.job_id} strategy={strategy_name} out={job.out_dir}", file=sys.stdout)
            
            return True
            
        except Exception as e:
            # 记录错误
            error_msg = str(e)[:100]  # 限制长度
            print(f"FAIL {job.job_id} error={error_msg}", file=sys.stdout)
            logger.error(f"分析失败 {job.job_id}: {e}", exc_info=True)
            return False
    
    def _run_emit_segments(self, job: SegJob, params: dict[str, Any]) -> bool:
        """生成语音片段并写入 segments.jsonl（使用策略接口）
        
        Args:
            job: 任务对象
            params: 参数字典
        """
        # 检查是否启用 auto-strategy
        auto_strategy = params.get("auto_strategy", False)
        if auto_strategy:
            return self._run_auto_strategy_emit_segments(job, params)
        
        strategy_name = params.get("strategy", "silence")
        
        try:
            # 确保 out_dir 存在
            job.out_dir.mkdir(parents=True, exist_ok=True)
            
            # 1. 获取策略实例并运行分析（如果 artifact 不存在则自动触发）
            strategy = self._get_strategy(strategy_name)
            analysis_result: Optional[AnalysisResult] = None
            
            # 尝试读取现有 artifact（兼容性）
            artifact_path = None
            if strategy_name == "silence":
                artifact_path = job.out_dir / "silences.json"
            elif strategy_name == "energy":
                artifact_path = job.out_dir / "energy.json"
            elif strategy_name == "vad":
                artifact_path = job.out_dir / "vad.json"
            
            if artifact_path and artifact_path.exists():
                # 尝试从 artifact 重建 AnalysisResult（仅 silence 策略支持）
                if strategy_name == "silence":
                    try:
                        with open(artifact_path, "r", encoding="utf-8") as f:
                            silences_data = json.load(f)
                        duration_sec = silences_data.get("duration_sec")
                        if duration_sec:
                            silence_intervals = [
                                SilenceInterval(
                                    start_sec=item["start_sec"],
                                    end_sec=item["end_sec"],
                                    duration_sec=item["duration_sec"],
                                )
                                for item in silences_data.get("silences", [])
                            ]
                            normalized_silences = normalize_intervals(silence_intervals, duration_sec)
                            speech_segments_raw = complement_to_speech_segments(normalized_silences, duration_sec)
                            analysis_result = AnalysisResult(
                                strategy="silence",
                                duration_sec=duration_sec,
                                speech_segments_raw=speech_segments_raw,
                                artifacts={"silences.json": artifact_path},
                                stats=silences_data.get("params", {}),
                            )
                            logger.info(f"使用现有的 {artifact_path.name}")
                    except Exception as e:
                        logger.warning(f"读取现有 artifact 失败: {e}，将重新分析")
            
            # 如果无法从 artifact 重建，运行分析
            if analysis_result is None:
                logger.info(f"运行策略分析: {strategy_name}")
                analysis_result = strategy.analyze(job, params)
            
            # 2. 获取 duration_sec
            duration_sec = analysis_result.duration_sec
            
            # 3. 使用 speech_segments_raw
            speech_segments = analysis_result.speech_segments_raw
            
            # 6. 应用填充和裁剪
            pad_sec = params.get("pad_sec", 0.1)
            padded_segments = apply_padding_and_clip(speech_segments, pad_sec, duration_sec)
            
            # 7. R6: 合并重叠/粘连的段
            merged_segments = merge_overlaps(padded_segments, gap_merge_sec=0.0, overlap_tolerance=1e-3)
            
            # 8. R6: 通过合并短段来强制最小时长
            min_seg_sec = params.get("min_seg_sec", 1.0)
            max_seg_sec = params.get("max_seg_sec", 25.0)
            # R10: 跟踪 merge 操作
            segments_before_merge = merged_segments.copy()
            merged_segments = enforce_min_duration_by_merge(merged_segments, min_seg_sec, max_seg_sec)
            from onepass_audioclean_seg.pipeline.segment_flags import track_postprocess_history
            merge_flags_map = track_postprocess_history(segments_before_merge, merged_segments, "merge")
            
            # 9. R6: 通过切分超长段来强制最大时长
            split_strategy = params.get("split_strategy", "equal")
            # R10: 跟踪 split 操作
            segments_before_split = merged_segments.copy()
            final_segments = enforce_max_duration_by_split(merged_segments, max_seg_sec, min_seg_sec, split_strategy)
            split_flags_map = track_postprocess_history(segments_before_split, final_segments, "split")
            
            # 最终排序和 round(3)
            final_segments = sorted(final_segments, key=lambda x: x[0])
            final_segments = [(round(s, 3), round(e, 3)) for s, e in final_segments]
            
            # R10: 合并所有 flags
            all_flags_map: dict[tuple[float, float], list[str]] = {}
            for seg in final_segments:
                flags = []
                if seg in split_flags_map:
                    flags.extend(split_flags_map[seg])
                if seg in merge_flags_map:
                    flags.extend(merge_flags_map[seg])
                all_flags_map[seg] = flags
            
            # 10. R6: 构建 SegmentRecord 列表（计算 pre_silence_sec、post_silence_sec、rms、energy_db）
            segments_records = []
            audio_path_abs = str(job.audio_path.resolve())
            emit_wav = params.get("emit_wav", False)
            overwrite = params.get("overwrite", False)
            warnings_list = []
            
            # 如果启用 WAV 导出，创建输出目录
            wav_dir = None
            if emit_wav:
                wav_dir = job.out_dir / "segments"
                wav_dir.mkdir(parents=True, exist_ok=True)
            
            if not final_segments:
                logger.warning(f"规整后没有剩余片段")
                # 仍然写入空的 segments.jsonl 和更新报告
            else:
                
                # 获取 ffmpeg 路径（用于 WAV 导出）
                ffmpeg_path = None
                if emit_wav:
                    from onepass_audioclean_seg.audio.ffmpeg import which
                    ffmpeg_path = which("ffmpeg")
                    if ffmpeg_path is None:
                        warnings_list.append("ffmpeg 未找到，无法导出 WAV 文件")
                        emit_wav = False
                
                for idx, (start, end) in enumerate(final_segments, start=1):
                    seg_id = f"seg_{idx:06d}"
                    duration = end - start
                    
                    # 计算 pre_silence_sec 和 post_silence_sec（仅 silence 策略支持）
                    pre_silence_sec = 0.0
                    post_silence_sec = 0.0
                    
                    if strategy_name == "silence" and analysis_result.nonspeech_segments_raw:
                        # 查找前一个静音区间
                        for silence_start, silence_end in analysis_result.nonspeech_segments_raw:
                            if abs(silence_end - start) <= 0.001:
                                pre_silence_sec = silence_end - silence_start
                                break
                        
                        # 查找后一个静音区间
                        for silence_start, silence_end in analysis_result.nonspeech_segments_raw:
                            if abs(silence_start - end) <= 0.001:
                                post_silence_sec = silence_end - silence_start
                                break
                    
                    # R6: 计算 RMS 和 energy_db
                    rms = None
                    energy_db = None
                    try:
                        from onepass_audioclean_seg.audio.features import compute_rms, rms_to_db
                        rms = compute_rms(job.audio_path, start, end)
                        if rms is not None:
                            energy_db = rms_to_db(rms)
                    except Exception as e:
                        logger.warning(f"计算 RMS 失败 {seg_id}: {e}")
                        warnings_list.append(f"计算 RMS 失败 {seg_id}: {str(e)[:100]}")
                    
                    # R10: 计算 flags
                    low_energy_rms_threshold = params.get("low_energy_rms_threshold", 0.01)
                    history_flags = all_flags_map.get((start, end), [])
                    from onepass_audioclean_seg.pipeline.segment_flags import (
                        compute_flags_for_segment,
                        build_source_info,
                        build_quality_info,
                    )
                    flags = compute_flags_for_segment(
                        segment=(start, end),
                        duration_sec=duration_sec,
                        rms=rms,
                        low_energy_rms_threshold=low_energy_rms_threshold,
                        history_flags=history_flags,
                    )
                    
                    # R10: 构建 source 信息
                    # 尝试找到在 speech_segments_raw 中的原始索引
                    raw_index = None
                    for idx, (raw_start, raw_end) in enumerate(speech_segments):
                        if abs(raw_start - start) < 0.01 and abs(raw_end - end) < 0.01:
                            raw_index = idx
                            break
                    source = build_source_info(
                        strategy=strategy_name,
                        auto_chosen=False,
                        raw_index=raw_index,
                    )
                    
                    # R10: 构建 quality 信息
                    quality = build_quality_info(rms=rms, energy_db=energy_db)
                    
                    # R6: 导出 WAV 文件（如果启用）
                    notes = None
                    if emit_wav and wav_dir:
                        wav_path = wav_dir / f"{seg_id}.wav"
                        
                        # 检查是否已存在且不需要覆盖
                        if not overwrite and wav_path.exists():
                            logger.debug(f"跳过已存在的 WAV 文件: {wav_path}")
                        else:
                            try:
                                from onepass_audioclean_seg.audio.extract import extract_wav_segment
                                success = extract_wav_segment(
                                    job.audio_path,
                                    wav_path,
                                    start,
                                    end,
                                    ffmpeg_path,
                                )
                                if not success:
                                    warnings_list.append(f"导出 WAV 失败 {seg_id}")
                            except Exception as e:
                                logger.warning(f"导出 WAV 失败 {seg_id}: {e}")
                                warnings_list.append(f"导出 WAV 失败 {seg_id}: {str(e)[:100]}")
                    
                    record = SegmentRecord(
                        id=seg_id,
                        start_sec=round(start, 3),
                        end_sec=round(end, 3),
                        duration_sec=round(duration, 3),
                        source_audio=audio_path_abs,
                        pre_silence_sec=round(pre_silence_sec, 3),
                        post_silence_sec=round(post_silence_sec, 3),
                        is_speech=True,
                        strategy=strategy_name,
                        rms=rms,
                        energy_db=energy_db,
                        notes=notes,
                        flags=flags,
                        source=source,
                        quality=quality,
                    )
                    segments_records.append(record)
            
            # 9. 写入 segments.jsonl
            segments_path = job.out_dir / "segments.jsonl"
            write_segments_jsonl(segments_path, segments_records)
            
            # R10: 导出可视化友好文件
            exports = {}
            if self.export_timeline:
                from onepass_audioclean_seg.io.exports import export_timeline_json
                from onepass_audioclean_seg.io.report import read_seg_report
                report = read_seg_report(job.out_dir / "seg_report.json")
                auto_strategy = report.get("auto_strategy") if report else None
                timeline_path = export_timeline_json(
                    out_dir=job.out_dir,
                    segments_records=segments_records,
                    audio_path=job.audio_path,
                    duration_sec=duration_sec,
                    strategy=strategy_name,
                    auto_strategy=auto_strategy,
                    params=params,
                )
                exports["timeline_json"] = str(timeline_path.resolve())
            
            if self.export_csv:
                from onepass_audioclean_seg.io.exports import export_segments_csv
                csv_path = export_segments_csv(
                    out_dir=job.out_dir,
                    segments_records=segments_records,
                )
                exports["segments_csv"] = str(csv_path.resolve())
            
            if self.export_mask != "none":
                from onepass_audioclean_seg.io.exports import export_mask_json
                mask_strategy = self.export_mask
                if mask_strategy == "auto":
                    mask_strategy = strategy_name
                mask_path = export_mask_json(
                    out_dir=job.out_dir,
                    duration_sec=duration_sec,
                    strategy=mask_strategy,
                    bin_ms=self.mask_bin_ms,
                    analysis_result=analysis_result,
                    segments_records=segments_records,
                )
                if mask_path:
                    exports["mask_json"] = str(mask_path.resolve())
            
            # 10. 如果启用 validate_output，立即验证
            if self.validate_output:
                self._validate_job_output(job, segments_path)
            
            # 11. R6: 更新 seg_report.json（包含新的统计信息）
            speech_total_sec = sum(record.duration_sec for record in segments_records)
            min_duration = min((r.duration_sec for r in segments_records), default=0.0)
            max_duration = max((r.duration_sec for r in segments_records), default=0.0)
            
            segments_report_data = {
                "count": len(segments_records),
                "speech_total_sec": round(speech_total_sec, 3),
                "min_seg_sec": min_seg_sec,
                "max_seg_sec": max_seg_sec,
                "pad_sec": pad_sec,
                "merge_overlaps": True,
                "min_merge": True,
                "max_split": split_strategy,
                "rms_computed": any(r.rms is not None for r in segments_records),
                "strategy": strategy_name,
            }
            
            # 添加 warnings 和 outputs
            if warnings_list:
                segments_report_data["warnings"] = warnings_list
            
            outputs = {
                "segments_jsonl": str((job.out_dir / "segments.jsonl").resolve()),
            }
            # 根据策略添加 artifact
            if strategy_name == "silence":
                silences_path = job.out_dir / "silences.json"
                if silences_path.exists():
                    outputs["silences_json"] = str(silences_path.resolve())
            elif strategy_name == "energy":
                energy_path = job.out_dir / "energy.json"
                if energy_path.exists():
                    outputs["energy_json"] = str(energy_path.resolve())
            elif strategy_name == "vad":
                vad_path = job.out_dir / "vad.json"
                if vad_path.exists():
                    outputs["vad_json"] = str(vad_path.resolve())
            if wav_dir and wav_dir.exists():
                outputs["segments_wav_dir"] = str(wav_dir.resolve())
            # R10: 添加 exports
            if exports:
                outputs["exports"] = exports
            segments_report_data["outputs"] = outputs
            
            update_seg_report_segments(job.out_dir, segments_report_data, audio_path=job.audio_path)
            
            # 11. 打印成功信息
            print(f"EMIT {job.job_id} segments={len(segments_records)} out={job.out_dir}", file=sys.stdout)
            return True
            
        except Exception as e:
            # 记录错误
            error_msg = str(e)[:100]  # 限制长度
            print(f"FAIL {job.job_id} error={error_msg}", file=sys.stdout)
            logger.error(f"生成片段失败 {job.job_id}: {e}", exc_info=True)
            return False
    
    def _run_auto_strategy_emit_segments(self, job: SegJob, params: dict[str, Any]) -> bool:
        """使用 auto-strategy 生成语音片段（自动降级）
        
        Args:
            job: 任务对象
            params: 参数字典
        """
        # 获取参数
        strategy_order_str = params.get("auto_strategy_order", "silence,vad,energy")
        strategy_order = [s.strip() for s in strategy_order_str.split(",")]
        min_segments = params.get("auto_strategy_min_segments", 2)
        min_speech_total_sec = params.get("auto_strategy_min_speech_total_sec", 3.0)
        max_speech_ratio = params.get("auto_strategy_max_speech_ratio", DEFAULT_AUTO_STRATEGY_MAX_SPEECH_RATIO)
        
        attempts = []
        chosen_strategy = None
        chosen_result = None
        
        # 依次尝试每个策略
        for strategy_name in strategy_order:
            attempt_info = {
                "strategy": strategy_name,
                "ok": False,
                "reason": None,
                "stats": {},
            }
            
            try:
                # 尝试运行策略
                strategy = self._get_strategy(strategy_name)
                analysis_result = strategy.analyze(job, params)
                
                # 运行 postprocess 得到最终 segments
                final_segments = self._postprocess_segments(
                    analysis_result.speech_segments_raw,
                    analysis_result.duration_sec,
                    params,
                )
                
                # 评估质量
                speech_total_sec = sum(e - s for s, e in final_segments)
                segments_count = len(final_segments)
                speech_ratio = speech_total_sec / analysis_result.duration_sec if analysis_result.duration_sec > 0 else 0.0
                
                # 质量门槛判断
                reason = None
                if segments_count < min_segments:
                    reason = "too_few_segments"
                elif speech_total_sec < min_speech_total_sec:
                    reason = "too_short_speech"
                elif speech_ratio >= max_speech_ratio:
                    reason = "full_span"
                
                if reason is None:
                    # 通过质量门槛，使用该策略
                    chosen_strategy = strategy_name
                    chosen_result = analysis_result
                    attempt_info["ok"] = True
                    attempt_info["stats"] = {
                        "segments_count": segments_count,
                        "speech_total_sec": round(speech_total_sec, 3),
                        "speech_ratio": round(speech_ratio, 3),
                    }
                    attempts.append(attempt_info)
                    break
                else:
                    # 未通过质量门槛
                    attempt_info["reason"] = reason
                    attempt_info["stats"] = {
                        "segments_count": segments_count,
                        "speech_total_sec": round(speech_total_sec, 3),
                        "speech_ratio": round(speech_ratio, 3),
                    }
                    attempts.append(attempt_info)
                    
            except ImportError as e:
                # 依赖缺失（如 webrtcvad）
                attempt_info["reason"] = "missing_dependency"
                attempt_info["error"] = str(e)[:100]
                attempts.append(attempt_info)
            except Exception as e:
                # 其他错误
                attempt_info["reason"] = "error"
                attempt_info["error"] = str(e)[:100]
                attempts.append(attempt_info)
                logger.warning(f"策略 {strategy_name} 尝试失败: {e}")
        
        # 如果所有策略都失败
        if chosen_strategy is None:
            # 写入报告（记录尝试信息）
            auto_strategy_data = {
                "enabled": True,
                "order": strategy_order,
                "chosen": None,
                "attempts": attempts,
            }
            self._update_seg_report_auto_strategy(job.out_dir, auto_strategy_data)
            
            error_msg = "所有策略都未通过质量门槛"
            print(f"FAIL {job.job_id} error={error_msg}", file=sys.stdout)
            logger.error(f"Auto-strategy 失败 {job.job_id}: {error_msg}")
            return False
        
        # 使用选中的策略生成最终输出
        params_with_chosen_strategy = params.copy()
        params_with_chosen_strategy["strategy"] = chosen_strategy
        
        # 调用单策略版本的 _run_emit_segments（但跳过 auto-strategy 检查）
        try:
            job.out_dir.mkdir(parents=True, exist_ok=True)
            strategy = self._get_strategy(chosen_strategy)
            analysis_result = chosen_result
            
            # 运行 postprocess 并生成输出（复用现有逻辑）
            duration_sec = analysis_result.duration_sec
            speech_segments = analysis_result.speech_segments_raw
            
            pad_sec = params.get("pad_sec", 0.1)
            padded_segments = apply_padding_and_clip(speech_segments, pad_sec, duration_sec)
            merged_segments = merge_overlaps(padded_segments, gap_merge_sec=0.0, overlap_tolerance=1e-3)
            
            min_seg_sec = params.get("min_seg_sec", 1.0)
            max_seg_sec = params.get("max_seg_sec", 25.0)
            # R10: 跟踪 merge 操作
            segments_before_merge = merged_segments.copy()
            merged_segments = enforce_min_duration_by_merge(merged_segments, min_seg_sec, max_seg_sec)
            from onepass_audioclean_seg.pipeline.segment_flags import track_postprocess_history
            merge_flags_map = track_postprocess_history(segments_before_merge, merged_segments, "merge")
            
            split_strategy = params.get("split_strategy", "equal")
            # R10: 跟踪 split 操作
            segments_before_split = merged_segments.copy()
            final_segments = enforce_max_duration_by_split(merged_segments, max_seg_sec, min_seg_sec, split_strategy)
            split_flags_map = track_postprocess_history(segments_before_split, final_segments, "split")
            
            final_segments = sorted(final_segments, key=lambda x: x[0])
            final_segments = [(round(s, 3), round(e, 3)) for s, e in final_segments]
            
            # R10: 合并所有 flags
            all_flags_map: dict[tuple[float, float], list[str]] = {}
            for seg in final_segments:
                flags = []
                if seg in split_flags_map:
                    flags.extend(split_flags_map[seg])
                if seg in merge_flags_map:
                    flags.extend(merge_flags_map[seg])
                all_flags_map[seg] = flags
            
            # 构建 SegmentRecord 列表（复用现有逻辑）
            segments_records = []
            audio_path_abs = str(job.audio_path.resolve())
            emit_wav = params.get("emit_wav", False)
            overwrite = params.get("overwrite", False)
            warnings_list = []
            
            wav_dir = None
            if emit_wav:
                wav_dir = job.out_dir / "segments"
                wav_dir.mkdir(parents=True, exist_ok=True)
            
            if not final_segments:
                logger.warning(f"规整后没有剩余片段")
            else:
                ffmpeg_path = None
                if emit_wav:
                    from onepass_audioclean_seg.audio.ffmpeg import which
                    ffmpeg_path = which("ffmpeg")
                    if ffmpeg_path is None:
                        warnings_list.append("ffmpeg 未找到，无法导出 WAV 文件")
                        emit_wav = False
                
                for idx, (start, end) in enumerate(final_segments, start=1):
                    seg_id = f"seg_{idx:06d}"
                    duration = end - start
                    
                    pre_silence_sec = 0.0
                    post_silence_sec = 0.0
                    if chosen_strategy == "silence" and analysis_result.nonspeech_segments_raw:
                        for silence_start, silence_end in analysis_result.nonspeech_segments_raw:
                            if abs(silence_end - start) <= 0.001:
                                pre_silence_sec = silence_end - silence_start
                                break
                        for silence_start, silence_end in analysis_result.nonspeech_segments_raw:
                            if abs(silence_start - end) <= 0.001:
                                post_silence_sec = silence_end - silence_start
                                break
                    
                    rms = None
                    energy_db = None
                    try:
                        from onepass_audioclean_seg.audio.features import compute_rms, rms_to_db
                        rms = compute_rms(job.audio_path, start, end)
                        if rms is not None:
                            energy_db = rms_to_db(rms)
                    except Exception as e:
                        logger.warning(f"计算 RMS 失败 {seg_id}: {e}")
                        warnings_list.append(f"计算 RMS 失败 {seg_id}: {str(e)[:100]}")
                    
                    # R10: 计算 flags
                    low_energy_rms_threshold = params.get("low_energy_rms_threshold", 0.01)
                    history_flags = all_flags_map.get((start, end), [])
                    from onepass_audioclean_seg.pipeline.segment_flags import (
                        compute_flags_for_segment,
                        build_source_info,
                        build_quality_info,
                    )
                    flags = compute_flags_for_segment(
                        segment=(start, end),
                        duration_sec=duration_sec,
                        rms=rms,
                        low_energy_rms_threshold=low_energy_rms_threshold,
                        history_flags=history_flags,
                    )
                    
                    # R10: 构建 source 信息
                    raw_index = None
                    for idx, (raw_start, raw_end) in enumerate(speech_segments):
                        if abs(raw_start - start) < 0.01 and abs(raw_end - end) < 0.01:
                            raw_index = idx
                            break
                    source = build_source_info(
                        strategy=chosen_strategy,
                        auto_chosen=True,
                        raw_index=raw_index,
                    )
                    
                    # R10: 构建 quality 信息
                    quality = build_quality_info(rms=rms, energy_db=energy_db)
                    
                    notes = None
                    if emit_wav and wav_dir:
                        wav_path = wav_dir / f"{seg_id}.wav"
                        if not overwrite and wav_path.exists():
                            logger.debug(f"跳过已存在的 WAV 文件: {wav_path}")
                        else:
                            try:
                                from onepass_audioclean_seg.audio.extract import extract_wav_segment
                                success = extract_wav_segment(
                                    job.audio_path,
                                    wav_path,
                                    start,
                                    end,
                                    ffmpeg_path,
                                )
                                if not success:
                                    warnings_list.append(f"导出 WAV 失败 {seg_id}")
                            except Exception as e:
                                logger.warning(f"导出 WAV 失败 {seg_id}: {e}")
                                warnings_list.append(f"导出 WAV 失败 {seg_id}: {str(e)[:100]}")
                    
                    record = SegmentRecord(
                        id=seg_id,
                        start_sec=round(start, 3),
                        end_sec=round(end, 3),
                        duration_sec=round(duration, 3),
                        source_audio=audio_path_abs,
                        pre_silence_sec=round(pre_silence_sec, 3),
                        post_silence_sec=round(post_silence_sec, 3),
                        is_speech=True,
                        strategy=chosen_strategy,
                        rms=rms,
                        energy_db=energy_db,
                        notes=notes,
                        flags=flags,
                        source=source,
                        quality=quality,
                    )
                    segments_records.append(record)
            
            # 写入 segments.jsonl
            segments_path = job.out_dir / "segments.jsonl"
            write_segments_jsonl(segments_path, segments_records)
            
            # R10: 导出可视化友好文件
            exports = {}
            if self.export_timeline:
                from onepass_audioclean_seg.io.exports import export_timeline_json
                from onepass_audioclean_seg.io.report import read_seg_report
                report = read_seg_report(job.out_dir / "seg_report.json")
                auto_strategy = report.get("auto_strategy") if report else None
                timeline_path = export_timeline_json(
                    out_dir=job.out_dir,
                    segments_records=segments_records,
                    audio_path=job.audio_path,
                    duration_sec=duration_sec,
                    strategy=chosen_strategy,
                    auto_strategy=auto_strategy,
                    params=params,
                )
                exports["timeline_json"] = str(timeline_path.resolve())
            
            if self.export_csv:
                from onepass_audioclean_seg.io.exports import export_segments_csv
                csv_path = export_segments_csv(
                    out_dir=job.out_dir,
                    segments_records=segments_records,
                )
                exports["segments_csv"] = str(csv_path.resolve())
            
            if self.export_mask != "none":
                from onepass_audioclean_seg.io.exports import export_mask_json
                mask_strategy = self.export_mask
                if mask_strategy == "auto":
                    mask_strategy = chosen_strategy
                mask_path = export_mask_json(
                    out_dir=job.out_dir,
                    duration_sec=duration_sec,
                    strategy=mask_strategy,
                    bin_ms=self.mask_bin_ms,
                    analysis_result=chosen_result,
                    segments_records=segments_records,
                )
                if mask_path:
                    exports["mask_json"] = str(mask_path.resolve())
            
            # 验证输出
            if self.validate_output:
                self._validate_job_output(job, segments_path)
            
            # 更新报告
            speech_total_sec = sum(record.duration_sec for record in segments_records)
            min_duration = min((r.duration_sec for r in segments_records), default=0.0)
            max_duration = max((r.duration_sec for r in segments_records), default=0.0)
            
            segments_report_data = {
                "count": len(segments_records),
                "speech_total_sec": round(speech_total_sec, 3),
                "min_seg_sec": min_seg_sec,
                "max_seg_sec": max_seg_sec,
                "pad_sec": pad_sec,
                "merge_overlaps": True,
                "min_merge": True,
                "max_split": split_strategy,
                "rms_computed": any(r.rms is not None for r in segments_records),
                "strategy": chosen_strategy,
            }
            
            if warnings_list:
                segments_report_data["warnings"] = warnings_list
            
            outputs = {
                "segments_jsonl": str(segments_path.resolve()),
            }
            if chosen_strategy == "silence":
                silences_path = job.out_dir / "silences.json"
                if silences_path.exists():
                    outputs["silences_json"] = str(silences_path.resolve())
            elif chosen_strategy == "energy":
                energy_path = job.out_dir / "energy.json"
                if energy_path.exists():
                    outputs["energy_json"] = str(energy_path.resolve())
            elif chosen_strategy == "vad":
                vad_path = job.out_dir / "vad.json"
                if vad_path.exists():
                    outputs["vad_json"] = str(vad_path.resolve())
            if wav_dir and wav_dir.exists():
                outputs["segments_wav_dir"] = str(wav_dir.resolve())
            # R10: 添加 exports
            if exports:
                outputs["exports"] = exports
            segments_report_data["outputs"] = outputs
            
            update_seg_report_segments(job.out_dir, segments_report_data, audio_path=job.audio_path)
            
            # 写入 auto-strategy 信息
            auto_strategy_data = {
                "enabled": True,
                "order": strategy_order,
                "chosen": chosen_strategy,
                "attempts": attempts,
            }
            self._update_seg_report_auto_strategy(job.out_dir, auto_strategy_data)
            
            # 打印成功信息
            print(f"EMIT {job.job_id} segments={len(segments_records)} strategy={chosen_strategy} out={job.out_dir}", file=sys.stdout)
            return True
            
        except Exception as e:
            error_msg = str(e)[:100]
            print(f"FAIL {job.job_id} error={error_msg}", file=sys.stdout)
            logger.error(f"Auto-strategy 生成片段失败 {job.job_id}: {e}", exc_info=True)
            return False
    
    def _postprocess_segments(
        self,
        speech_segments_raw: list[tuple[float, float]],
        duration_sec: float,
        params: dict[str, Any],
    ) -> list[tuple[float, float]]:
        """对 speech_segments_raw 进行后处理（复用现有逻辑）
        
        Args:
            speech_segments_raw: 原始语音段列表
            duration_sec: 音频总时长
            params: 参数字典
        
        Returns:
            后处理后的片段列表
        """
        pad_sec = params.get("pad_sec", 0.1)
        min_seg_sec = params.get("min_seg_sec", 1.0)
        max_seg_sec = params.get("max_seg_sec", 25.0)
        
        padded_segments = apply_padding_and_clip(speech_segments_raw, pad_sec, duration_sec)
        merged_segments = merge_overlaps(padded_segments, gap_merge_sec=0.0, overlap_tolerance=1e-3)
        merged_segments = enforce_min_duration_by_merge(merged_segments, min_seg_sec, max_seg_sec)
        split_strategy = params.get("split_strategy", "equal")
        final_segments = enforce_max_duration_by_split(merged_segments, max_seg_sec, min_seg_sec, split_strategy)
        final_segments = sorted(final_segments, key=lambda x: x[0])
        final_segments = [(round(s, 3), round(e, 3)) for s, e in final_segments]
        return final_segments
    
    def _update_seg_report_auto_strategy(self, out_dir: Path, auto_strategy_data: dict[str, Any]) -> None:
        """更新 seg_report.json 的 auto_strategy 字段"""
        report_path = out_dir / "seg_report.json"
        existing_report = read_seg_report(report_path)
        
        if existing_report is None:
            existing_report = {
                "version": "R9",
                "created_at": datetime.now().isoformat(),
            }
        
        existing_report["auto_strategy"] = auto_strategy_data
        
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(existing_report, f, ensure_ascii=False, indent=2)
    
    def _print_plan(self, job: SegJob) -> None:
        """打印单个 job 的计划行"""
        meta_str = str(job.meta_path) if job.meta_path else "-"
        warnings_str = f" warnings={len(job.warnings)}" if job.warnings else ""
        
        print(
            f"PLAN {job.job_id} audio={job.audio_path} out={job.out_dir} meta={meta_str}{warnings_str}",
            file=sys.stdout
        )
    
    def _validate_job_output(self, job: SegJob, segments_path: Path) -> None:
        """验证 job 的输出
        
        Args:
            job: 任务对象
            segments_path: segments.jsonl 文件路径
        """
        try:
            from onepass_audioclean_seg.validate import validate_segments_jsonl
            
            result = validate_segments_jsonl(segments_path, strict=False)
            
            errors_count = len(result.errors)
            warnings_count = len(result.warnings)
            ok = result.ok
            
            print(
                f"VALIDATE {job.job_id} ok={ok} errors={errors_count} warnings={warnings_count}",
                file=sys.stdout
            )
            
            if not ok:
                # 验证失败，标记为失败
                self.has_any_error = True
                # 输出前几个错误
                for error in result.errors[:3]:
                    print(f"  VALIDATE ERROR: {error}", file=sys.stderr)
        except Exception as e:
            logger.warning(f"验证输出失败 {job.job_id}: {e}", exc_info=True)
            print(f"VALIDATE {job.job_id} ok=false errors=1 warnings=0 (验证过程异常: {str(e)[:50]})", file=sys.stdout)
            self.has_any_error = True
    
    def _write_run_summary(
        self,
        jobs: list[SegJob],
        params: dict[str, Any],
        jobs_planned: int,
        jobs_analyzed: int,
        jobs_emitted: int,
        jobs_failed: list[dict[str, Any]],
        jobs_skipped: int,
    ) -> None:
        """写入 run_summary.json
        
        Args:
            jobs: 任务列表
            params: 参数字典
            jobs_planned: 计划的任务数
            jobs_analyzed: 分析的任务数
            jobs_emitted: 生成片段的任务数
            jobs_failed: 失败的任务列表
            jobs_skipped: 跳过的任务数
        """
        if not jobs:
            return
        
        # 确定输出目录
        # 找到所有 jobs 的 out_dir 的共同父目录
        out_dirs = [job.out_dir for job in jobs]
        common_parent = out_dirs[0].parent
        
        # 如果所有 out_dir 都在同一个父目录下，使用该父目录
        # 否则使用第一个 job 的 out_dir 的父目录
        for out_dir in out_dirs[1:]:
            try:
                # 尝试找到共同父目录
                if out_dir.parent != common_parent:
                    # 如果不在同一个父目录，尝试找到更上层的共同目录
                    common_parts = []
                    parts1 = common_parent.parts
                    parts2 = out_dir.parent.parts
                    for p1, p2 in zip(parts1, parts2):
                        if p1 == p2:
                            common_parts.append(p1)
                        else:
                            break
                    if common_parts:
                        common_parent = Path(*common_parts)
                    else:
                        # 如果找不到共同目录，使用第一个 job 的 out_dir 的父目录
                        common_parent = out_dirs[0].parent
                        break
            except Exception:
                common_parent = out_dirs[0].parent
                break
        
        # 如果 out_mode=out_root，且 out_dir 名称是 "seg"，则使用父目录的父目录
        out_mode = params.get("out_mode", "in_place")
        if out_mode == "out_root" and out_dirs[0].name == "seg":
            summary_dir = common_parent.parent if common_parent.name != "seg" else common_parent
        else:
            summary_dir = common_parent
        
        # 计算 totals
        speech_total_sec = 0.0
        silences_total_sec = 0.0
        exports_written_total = 0
        per_strategy_exports_count: dict[str, int] = {}
        
        for job in jobs:
            # 读取 seg_report.json 获取统计信息
            report_path = job.out_dir / "seg_report.json"
            if report_path.exists():
                try:
                    with open(report_path, "r", encoding="utf-8") as f:
                        report_data = json.load(f)
                    
                    # 累加 speech_total_sec
                    segments_data = report_data.get("segments", {})
                    if isinstance(segments_data, dict):
                        speech_total_sec += segments_data.get("speech_total_sec", 0.0)
                    
                    # 累加 silences_total_sec（从 silence 或 energy 策略）
                    analysis_data = report_data.get("analysis", {})
                    # 尝试从 silence 策略获取
                    silence_data = analysis_data.get("silence", {})
                    if isinstance(silence_data, dict):
                        silences_total_sec += silence_data.get("silences_total_sec", 0.0)
                    # 尝试从 energy 策略获取（energy 策略不直接提供 silences_total_sec，跳过）
                    
                    # R10: 统计 exports
                    outputs = segments_data.get("outputs", {})
                    exports = outputs.get("exports", {})
                    if exports:
                        exports_written_total += len(exports)
                        strategy = segments_data.get("strategy", "unknown")
                        per_strategy_exports_count[strategy] = per_strategy_exports_count.get(strategy, 0) + len(exports)
                except Exception:
                    pass  # 读取失败，跳过
        
        # 构建 run_summary
        finished_at = datetime.now().isoformat()
        run_id = str(uuid.uuid4())
        
        summary = {
            "run_id": run_id,
            "started_at": self.started_at,
            "finished_at": finished_at,
            "cli_args": params,
            "counts": {
                "jobs_total": len(jobs),
                "jobs_planned": jobs_planned,
                "jobs_analyzed": jobs_analyzed,
                "jobs_emitted": jobs_emitted,
                "jobs_failed": len(jobs_failed),
                "jobs_skipped": jobs_skipped,
            },
            "totals": {
                "speech_total_sec": round(speech_total_sec, 3),
                "silences_total_sec": round(silences_total_sec, 3),
            },
            "failures": jobs_failed,
            "dry_run": self.dry_run,
        }
        
        # R10: 添加 exports 统计
        if exports_written_total > 0:
            summary["exports"] = {
                "exports_written_total": exports_written_total,
                "per_strategy_exports_count": per_strategy_exports_count,
            }
        
        # 写入文件
        summary_path = summary_dir / "run_summary.json"
        try:
            summary_dir.mkdir(parents=True, exist_ok=True)
            with open(summary_path, "w", encoding="utf-8") as f:
                json.dump(summary, f, ensure_ascii=False, indent=2)
            logger.info(f"写入 run_summary.json: {summary_path}")
        except Exception as e:
            logger.warning(f"写入 run_summary.json 失败: {e}", exc_info=True)
    
    def _write_run_manifest(
        self,
        jobs: list[SegJob],
        params: dict[str, Any],
        effective_config: Optional[dict[str, Any]] = None,
        config_hash: Optional[str] = None,
    ) -> None:
        """写入 run_manifest.json（R11：可复现实验快照）
        
        Args:
            jobs: 任务列表
            params: 参数字典
            effective_config: 合并后的最终配置（可选）
            config_hash: 配置哈希值（可选）
        """
        if not jobs:
            return
        
        # 确定输出目录（与 run_summary.json 相同）
        out_dirs = [job.out_dir for job in jobs]
        common_parent = out_dirs[0].parent
        
        for out_dir in out_dirs[1:]:
            try:
                if out_dir.parent != common_parent:
                    common_parts = []
                    parts1 = common_parent.parts
                    parts2 = out_dir.parent.parts
                    for p1, p2 in zip(parts1, parts2):
                        if p1 == p2:
                            common_parts.append(p1)
                        else:
                            break
                    if common_parts:
                        common_parent = Path(*common_parts)
                    else:
                        common_parent = out_dirs[0].parent
                        break
            except Exception:
                common_parent = out_dirs[0].parent
                break
        
        out_mode = params.get("out_mode", "in_place")
        if out_mode == "out_root" and out_dirs[0].name == "seg":
            manifest_dir = common_parent.parent if common_parent.name != "seg" else common_parent
        else:
            manifest_dir = common_parent
        
        # 获取工具版本
        from onepass_audioclean_seg import __version__
        
        # 获取 git commit（可选）
        git_commit = None
        import os
        git_commit_env = os.environ.get("GIT_COMMIT")
        if git_commit_env:
            git_commit = git_commit_env
        else:
            # 尝试从 .git 读取（简化实现，不依赖 gitpython）
            try:
                git_dir = Path.cwd() / ".git"
                if git_dir.exists():
                    # 尝试读取 HEAD
                    head_file = git_dir / "HEAD"
                    if head_file.exists():
                        with open(head_file, "r") as f:
                            head_content = f.read().strip()
                            if head_content.startswith("ref: "):
                                ref_path = git_dir / head_content[5:]
                                if ref_path.exists():
                                    with open(ref_path, "r") as rf:
                                        git_commit = rf.read().strip()[:40]  # 取前40字符
            except Exception:
                pass  # 忽略错误
        
        # 获取环境信息
        import platform
        import sys
        
        environment = {
            "python_version": sys.version.split()[0],
            "platform": platform.platform(),
            "deps": {},
        }
        
        # 获取依赖版本
        from onepass_audioclean_seg.audio.ffmpeg import get_ffmpeg_version, get_ffprobe_version, which
        
        ffmpeg_path = which("ffmpeg")
        if ffmpeg_path:
            ffmpeg_version = get_ffmpeg_version(ffmpeg_path)
            if ffmpeg_version:
                environment["deps"]["ffmpeg_version"] = ffmpeg_version
        
        ffprobe_path = which("ffprobe")
        if ffprobe_path:
            ffprobe_version = get_ffprobe_version(ffprobe_path)
            if ffprobe_version:
                environment["deps"]["ffprobe_version"] = ffprobe_version
        
        try:
            import webrtcvad
            environment["deps"]["webrtcvad_version"] = "available"  # webrtcvad 没有版本 API
        except ImportError:
            pass
        
        try:
            import yaml
            environment["deps"]["pyyaml_version"] = getattr(yaml, "__version__", "unknown")
        except ImportError:
            pass
        
        # 构建 jobs 列表
        manifest_jobs = []
        for job, job_stat in zip(jobs, self.job_stats):
            job_info = {
                "job_id": job.job_id,
                "audio_path": str(job.audio_path.resolve()),
                "out_dir": str(job.out_dir.resolve()),
                "status": job_stat["status"],
            }
            
            # 读取 seg_report.json 获取额外信息
            report_path = job.out_dir / "seg_report.json"
            if report_path.exists():
                try:
                    with open(report_path, "r", encoding="utf-8") as f:
                        report_data = json.load(f)
                    
                    # 获取 chosen_strategy
                    segments_data = report_data.get("segments", {})
                    if isinstance(segments_data, dict):
                        job_info["chosen_strategy"] = segments_data.get("strategy")
                        job_info["segments_count"] = segments_data.get("count", 0)
                        job_info["speech_total_sec"] = segments_data.get("speech_total_sec", 0.0)
                    
                    # 统计 errors/warnings
                    errors_count = 0
                    warnings_count = 0
                    if "warnings" in segments_data:
                        warnings_count = len(segments_data["warnings"]) if isinstance(segments_data["warnings"], list) else 0
                    if job_stat.get("error"):
                        errors_count = 1
                    job_info["errors_count"] = errors_count
                    job_info["warnings_count"] = warnings_count
                except Exception:
                    pass
            
            manifest_jobs.append(job_info)
        
        # 构建 run_manifest
        finished_at = datetime.now().isoformat()
        
        manifest = {
            "tool": "onepass-audioclean-seg",
            "version": __version__,
            "git": git_commit,
            "started_at": self.started_at,
            "finished_at": finished_at,
            "command": sys.argv,
            "effective_config": effective_config or {},
            "environment": environment,
            "jobs": manifest_jobs,
        }
        
        # 写入文件
        manifest_path = manifest_dir / "run_manifest.json"
        try:
            manifest_dir.mkdir(parents=True, exist_ok=True)
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, ensure_ascii=False, indent=2)
            logger.info(f"写入 run_manifest.json: {manifest_path}")
        except Exception as e:
            logger.warning(f"写入 run_manifest.json 失败: {e}", exc_info=True)

