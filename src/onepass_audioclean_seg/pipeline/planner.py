"""输出布局规划和执行计划"""

import logging
import sys
from pathlib import Path
from typing import Any

from onepass_audioclean_seg.io.report import write_seg_report
from onepass_audioclean_seg.pipeline.jobs import SegJob

logger = logging.getLogger(__name__)


class SegmentPlanner:
    """分段计划器：处理输出布局、dry-run 输出、写入报告"""
    
    def __init__(self, dry_run: bool = False, overwrite: bool = False):
        """
        Args:
            dry_run: 是否为 dry-run 模式（只打印计划，不写入文件）
            overwrite: 是否覆盖已存在的文件
        """
        self.dry_run = dry_run
        self.overwrite = overwrite
    
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
                except Exception as e:
                    logger.error(f"写入报告失败 {job.job_id}: {e}", exc_info=True)
                    print(f"ERROR {job.job_id} failed to write report: {e}", file=sys.stderr)
            else:
                executed_count += 1
        
        return executed_count
    
    def _print_plan(self, job: SegJob) -> None:
        """打印单个 job 的计划行"""
        meta_str = str(job.meta_path) if job.meta_path else "-"
        warnings_str = f" warnings={len(job.warnings)}" if job.warnings else ""
        
        print(
            f"PLAN {job.job_id} audio={job.audio_path} out={job.out_dir} meta={meta_str}{warnings_str}",
            file=sys.stdout
        )

