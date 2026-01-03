"""输出布局规划和执行计划"""

import json
import logging
import sys
from pathlib import Path
from typing import Any

from onepass_audioclean_seg.audio.ffmpeg import which
from onepass_audioclean_seg.audio.probe import get_audio_duration_sec
from onepass_audioclean_seg.io.report import update_seg_report_analysis, write_seg_report
from onepass_audioclean_seg.pipeline.jobs import SegJob
from onepass_audioclean_seg.strategies.silence_ffmpeg import (
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
        silence_threshold_db: float = -35.0,
    ):
        """
        Args:
            dry_run: 是否为 dry-run 模式（只打印计划，不写入文件）
            overwrite: 是否覆盖已存在的文件
            analyze: 是否运行静音分析
            silence_threshold_db: 静音检测阈值（dB）
        """
        self.dry_run = dry_run
        self.overwrite = overwrite
        self.analyze = analyze
        self.silence_threshold_db = silence_threshold_db
        self.has_analyze_error = False  # 记录是否有 analyze 错误
    
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
        
        for job in jobs:
            # 检查是否跳过（如果 overwrite=False 且输出已存在）
            segments_file = job.out_dir / "segments.jsonl"
            if not self.overwrite and segments_file.exists():
                warnings_str = f" warnings={len(job.warnings)}" if job.warnings else ""
                print(f"SKIP {job.job_id} audio={job.audio_path} out={job.out_dir}{warnings_str}", file=sys.stdout)
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
                    if self.analyze:
                        self._run_analyze(job, params)
                except Exception as e:
                    logger.error(f"写入报告失败 {job.job_id}: {e}", exc_info=True)
                    print(f"ERROR {job.job_id} failed to write report: {e}", file=sys.stderr)
            else:
                executed_count += 1
        
        return executed_count
    
    def get_exit_code(self) -> int:
        """获取退出码
        
        Returns:
            0 表示成功，1 表示有 analyze 错误
        """
        return 1 if self.has_analyze_error else 0
    
    def _run_analyze(self, job: SegJob, params: dict[str, Any]) -> None:
        """运行静音分析
        
        Args:
            job: 任务对象
            params: 参数字典
        """
        strategy = params.get("strategy", "silence")
        
        # 只支持 silence 策略
        if strategy != "silence":
            print(f"SKIP-ANALYZE {job.job_id} reason=strategy_not_supported", file=sys.stdout)
            return
        
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
            
        except Exception as e:
            # 记录错误
            self.has_analyze_error = True
            error_msg = str(e)[:100]  # 限制长度
            print(f"FAIL {job.job_id} error={error_msg}", file=sys.stdout)
            logger.error(f"分析失败 {job.job_id}: {e}", exc_info=True)
    
    def _print_plan(self, job: SegJob) -> None:
        """打印单个 job 的计划行"""
        meta_str = str(job.meta_path) if job.meta_path else "-"
        warnings_str = f" warnings={len(job.warnings)}" if job.warnings else ""
        
        print(
            f"PLAN {job.job_id} audio={job.audio_path} out={job.out_dir} meta={meta_str}{warnings_str}",
            file=sys.stdout
        )

