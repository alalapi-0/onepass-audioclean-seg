"""输出布局规划和执行计划"""

import json
import logging
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from onepass_audioclean_seg.audio.ffmpeg import which
from onepass_audioclean_seg.audio.probe import get_audio_duration_sec
from onepass_audioclean_seg.io.report import (
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
from onepass_audioclean_seg.strategies.silence_ffmpeg import (
    SilenceInterval,
    parse_silencedetect_output,
    run_silencedetect,
)

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
    ):
        """
        Args:
            dry_run: 是否为 dry-run 模式（只打印计划，不写入文件）
            overwrite: 是否覆盖已存在的文件
            analyze: 是否运行静音分析
            emit_segments: 是否生成语音片段
            silence_threshold_db: 静音检测阈值（dB）
            validate_output: 是否在生成 segments.jsonl 后立即验证
        """
        self.dry_run = dry_run
        self.overwrite = overwrite
        self.analyze = analyze
        self.emit_segments = emit_segments
        self.silence_threshold_db = silence_threshold_db
        self.validate_output = validate_output
        self.job_stats: list[dict[str, Any]] = []  # 记录每个 job 的统计信息
        self.started_at = datetime.now().isoformat()
        self.has_any_error = False  # 记录是否有任何错误
    
    def plan_and_execute(
        self,
        jobs: list[SegJob],
        params: dict[str, Any],
    ) -> int:
        """规划并执行（或 dry-run）任务列表
        
        Args:
            jobs: 任务列表
            params: 参数字典（用于写入报告）
        
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
                    write_seg_report(
                        out_dir=job.out_dir,
                        params=params,
                        audio_path=job.audio_path,
                        meta_path=job.meta_path,
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
        
        return executed_count
    
    def get_exit_code(self) -> int:
        """获取退出码
        
        Returns:
            0 表示成功，1 表示有错误（analyze 或 emit_segments）
        """
        return 1 if self.has_any_error else 0
    
    def _run_analyze(self, job: SegJob, params: dict[str, Any]) -> bool:
        """运行静音分析
        
        Args:
            job: 任务对象
            params: 参数字典
        """
        strategy = params.get("strategy", "silence")
        
        # 只支持 silence 策略
        if strategy != "silence":
            print(f"SKIP-ANALYZE {job.job_id} reason=strategy_not_supported", file=sys.stdout)
            return True
        
        try:
            # 确保 out_dir 存在
            job.out_dir.mkdir(parents=True, exist_ok=True)
            
            # 获取 ffmpeg 路径
            ffmpeg_path = which("ffmpeg")
            if ffmpeg_path is None:
                raise RuntimeError("ffmpeg 未找到")
            
            # 获取音频时长
            duration_sec = get_audio_duration_sec(
                audio_path=job.audio_path,
                meta_path=job.meta_path,
            )
            
            # 运行 silencedetect
            min_silence_sec = params.get("min_silence_sec", 0.5)
            output_text = run_silencedetect(
                ffmpeg_path=ffmpeg_path,
                audio_path=job.audio_path,
                threshold_db=self.silence_threshold_db,
                min_silence_sec=min_silence_sec,
            )
            
            # 解析输出
            intervals = parse_silencedetect_output(output_text, duration_sec)
            
            # 写入 silences.json
            silences_data = {
                "audio_path": str(job.audio_path.resolve()),
                "strategy": "silence",
                "params": {
                    "silence_threshold_db": self.silence_threshold_db,
                    "min_silence_sec": min_silence_sec,
                },
                "duration_sec": round(duration_sec, 3) if duration_sec is not None else None,
                "silences": [
                    {
                        "start_sec": interval.start_sec,
                        "end_sec": interval.end_sec,
                        "duration_sec": interval.duration_sec,
                    }
                    for interval in intervals
                ],
            }
            
            silences_path = job.out_dir / "silences.json"
            with open(silences_path, "w", encoding="utf-8") as f:
                json.dump(silences_data, f, ensure_ascii=False, indent=2)
            
            # 更新 seg_report.json
            silences_total_sec = sum(interval.duration_sec for interval in intervals)
            analysis_data = {
                "silence": {
                    "silences_count": len(intervals),
                    "silences_total_sec": round(silences_total_sec, 3),
                    "threshold_db": self.silence_threshold_db,
                    "min_silence_sec": min_silence_sec,
                    "duration_sec": round(duration_sec, 3) if duration_sec is not None else None,
                }
            }
            update_seg_report_analysis(job.out_dir, analysis_data)
            
            # 打印成功信息
            print(f"ANALYZE {job.job_id} silences={len(intervals)} out={job.out_dir}", file=sys.stdout)
            return True
            
        except Exception as e:
            # 记录错误
            error_msg = str(e)[:100]  # 限制长度
            print(f"FAIL {job.job_id} error={error_msg}", file=sys.stdout)
            logger.error(f"分析失败 {job.job_id}: {e}", exc_info=True)
            return False
    
    def _run_emit_segments(self, job: SegJob, params: dict[str, Any]) -> bool:
        """生成语音片段并写入 segments.jsonl
        
        Args:
            job: 任务对象
            params: 参数字典
        """
        strategy = params.get("strategy", "silence")
        
        # 只支持 silence 策略
        if strategy != "silence":
            print(f"SKIP-EMIT {job.job_id} reason=strategy_not_supported", file=sys.stdout)
            return True
        
        try:
            # 确保 out_dir 存在
            job.out_dir.mkdir(parents=True, exist_ok=True)
            
            # 1. 读取或生成 silences.json
            silences_path = job.out_dir / "silences.json"
            silences_data = None
            
            if silences_path.exists():
                # 读取现有的 silences.json
                with open(silences_path, "r", encoding="utf-8") as f:
                    silences_data = json.load(f)
                logger.info(f"使用现有的 silences.json: {silences_path}")
            else:
                # 方案1（推荐）：自动触发分析
                # 如果 analyze=True，_run_analyze 应该在 _run_emit_segments 之前执行
                # 但如果 silences.json 仍不存在，说明 analyze 失败或未执行，我们尝试再次运行
                logger.info(f"silences.json 不存在，自动触发分析")
                self._run_analyze(job, params)
                
                # 重新读取 silences.json
                if silences_path.exists():
                    with open(silences_path, "r", encoding="utf-8") as f:
                        silences_data = json.load(f)
                else:
                    raise RuntimeError("自动分析后 silences.json 仍不存在（分析可能失败）")
            
            # 2. 获取 duration_sec（从 silences_data 或 meta.json 或 ffprobe）
            duration_sec = None
            if silences_data and "duration_sec" in silences_data:
                duration_sec = silences_data.get("duration_sec")
            
            if duration_sec is None:
                duration_sec = get_audio_duration_sec(
                    audio_path=job.audio_path,
                    meta_path=job.meta_path,
                )
            
            if duration_sec is None:
                raise RuntimeError("无法获取音频时长（需要 meta.json 或 ffprobe）")
            
            # 3. 解析静音区间
            silence_intervals = [
                SilenceInterval(
                    start_sec=item["start_sec"],
                    end_sec=item["end_sec"],
                    duration_sec=item["duration_sec"],
                )
                for item in silences_data.get("silences", [])
            ]
            
            # 4. 规范化静音区间
            normalized_silences = normalize_intervals(silence_intervals, duration_sec)
            
            # 5. 生成语音段（补集）
            speech_segments = complement_to_speech_segments(normalized_silences, duration_sec)
            
            # 6. 应用填充和裁剪
            pad_sec = params.get("pad_sec", 0.1)
            padded_segments = apply_padding_and_clip(speech_segments, pad_sec, duration_sec)
            
            # 7. R6: 合并重叠/粘连的段
            merged_segments = merge_overlaps(padded_segments, gap_merge_sec=0.0, overlap_tolerance=1e-3)
            
            # 8. R6: 通过合并短段来强制最小时长
            min_seg_sec = params.get("min_seg_sec", 1.0)
            max_seg_sec = params.get("max_seg_sec", 25.0)
            merged_segments = enforce_min_duration_by_merge(merged_segments, min_seg_sec, max_seg_sec)
            
            # 9. R6: 通过切分超长段来强制最大时长
            split_strategy = params.get("split_strategy", "equal")
            final_segments = enforce_max_duration_by_split(merged_segments, max_seg_sec, min_seg_sec, split_strategy)
            
            # 最终排序和 round(3)
            final_segments = sorted(final_segments, key=lambda x: x[0])
            final_segments = [(round(s, 3), round(e, 3)) for s, e in final_segments]
            
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
                    
                    # 计算 pre_silence_sec 和 post_silence_sec
                    pre_silence_sec = 0.0
                    post_silence_sec = 0.0
                    
                    # 查找前一个静音区间（end == start，考虑容差 1e-3）
                    for silence in normalized_silences:
                        if abs(silence.end_sec - start) <= 0.001:
                            pre_silence_sec = silence.duration_sec
                            break
                    
                    # 查找后一个静音区间（start == end，考虑容差 1e-3）
                    for silence in normalized_silences:
                        if abs(silence.start_sec - end) <= 0.001:
                            post_silence_sec = silence.duration_sec
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
                        strategy="silence",
                        rms=rms,
                        energy_db=energy_db,
                        notes=notes,
                    )
                    segments_records.append(record)
            
            # 9. 写入 segments.jsonl
            segments_path = job.out_dir / "segments.jsonl"
            write_segments_jsonl(segments_path, segments_records)
            
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
                "strategy": "silence",
            }
            
            # 添加 warnings 和 outputs
            if warnings_list:
                segments_report_data["warnings"] = warnings_list
            
            outputs = {
                "segments_jsonl": str((job.out_dir / "segments.jsonl").resolve()),
                "silences_json": str((job.out_dir / "silences.json").resolve()),
                "segments_wav_dir": str(wav_dir.resolve()) if wav_dir and wav_dir.exists() else None,
            }
            segments_report_data["outputs"] = outputs
            
            update_seg_report_segments(job.out_dir, segments_report_data)
            
            # 11. 打印成功信息
            print(f"EMIT {job.job_id} segments={len(segments_records)} out={job.out_dir}", file=sys.stdout)
            return True
            
        except Exception as e:
            # 记录错误
            error_msg = str(e)[:100]  # 限制长度
            print(f"FAIL {job.job_id} error={error_msg}", file=sys.stdout)
            logger.error(f"生成片段失败 {job.job_id}: {e}", exc_info=True)
            return False
    
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
                    
                    # 累加 silences_total_sec
                    analysis_data = report_data.get("analysis", {})
                    silence_data = analysis_data.get("silence", {})
                    if isinstance(silence_data, dict):
                        silences_total_sec += silence_data.get("silences_total_sec", 0.0)
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
        
        # 写入文件
        summary_path = summary_dir / "run_summary.json"
        try:
            summary_dir.mkdir(parents=True, exist_ok=True)
            with open(summary_path, "w", encoding="utf-8") as f:
                json.dump(summary, f, ensure_ascii=False, indent=2)
            logger.info(f"写入 run_summary.json: {summary_path}")
        except Exception as e:
            logger.warning(f"写入 run_summary.json 失败: {e}", exc_info=True)

