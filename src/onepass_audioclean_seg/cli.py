"""CLI 主入口"""

import argparse
import json
import sys
from pathlib import Path

from onepass_audioclean_seg import __version__
from onepass_audioclean_seg.constants import (
    DEFAULT_JOBS,
    DEFAULT_LOG_LEVEL,
    DEFAULT_MAX_SEG_SEC,
    DEFAULT_MIN_SEG_SEC,
    DEFAULT_MIN_SILENCE_SEC,
    DEFAULT_PAD_SEC,
    DEFAULT_STRATEGY,
    STRATEGY_CHOICES,
)
from onepass_audioclean_seg.deps import DepsChecker, format_text_output
from onepass_audioclean_seg.logging_utils import setup_logging


def create_parser() -> argparse.ArgumentParser:
    """创建命令行参数解析器"""
    parser = argparse.ArgumentParser(
        prog="audioclean-seg",
        description="Repo2 分段模块：将长音频切成候选片段（segments）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    
    # 全局日志选项
    parser.add_argument(
        "--log-level",
        default=DEFAULT_LOG_LEVEL,
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help=f"日志级别（默认: {DEFAULT_LOG_LEVEL}）",
    )
    parser.add_argument(
        "--log-file",
        help="日志文件路径（可选）",
    )
    
    # 子命令
    subparsers = parser.add_subparsers(
        dest="command",
        help="可用子命令",
        required=True,
    )
    
    # check-deps 子命令
    check_deps_parser = subparsers.add_parser(
        "check-deps",
        help="检查依赖（ffmpeg/ffprobe/silencedetect）",
    )
    check_deps_parser.add_argument(
        "--json",
        action="store_true",
        help="以 JSON 格式输出",
    )
    check_deps_parser.add_argument(
        "--verbose",
        action="store_true",
        help="详细输出",
    )
    
    # segment 子命令
    segment_parser = subparsers.add_parser(
        "segment",
        help="将音频分段（R3：输入解析与计划）",
    )
    segment_parser.add_argument(
        "--in",
        dest="input_path",
        required=True,
        help="输入路径：单个音频文件、workdir、批处理根目录或 manifest.jsonl（必填）",
    )
    segment_parser.add_argument(
        "--out",
        dest="output_dir",
        required=True,
        help="输出根目录路径（必填）",
    )
    segment_parser.add_argument(
        "--pattern",
        default="audio.wav",
        help="扫描根目录时使用的文件名模式（默认: audio.wav）",
    )
    segment_parser.add_argument(
        "--out-mode",
        choices=["in_place", "out_root"],
        default="in_place",
        help="输出模式：in_place（输出到 workdir/seg）或 out_root（输出到 out_root 下镜像目录，默认: in_place）",
    )
    segment_parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="dry-run 模式：只打印计划，不写入文件（默认: False）",
    )
    segment_parser.add_argument(
        "--strategy",
        default=DEFAULT_STRATEGY,
        choices=STRATEGY_CHOICES,
        help=f"分段策略（默认: {DEFAULT_STRATEGY}）",
    )
    segment_parser.add_argument(
        "--min-silence-sec",
        type=float,
        default=DEFAULT_MIN_SILENCE_SEC,
        help=f"最小静音时长（秒，默认: {DEFAULT_MIN_SILENCE_SEC}）",
    )
    segment_parser.add_argument(
        "--min-seg-sec",
        type=float,
        default=DEFAULT_MIN_SEG_SEC,
        help=f"最小片段时长（秒，默认: {DEFAULT_MIN_SEG_SEC}）",
    )
    segment_parser.add_argument(
        "--max-seg-sec",
        type=float,
        default=DEFAULT_MAX_SEG_SEC,
        help=f"最大片段时长（秒，默认: {DEFAULT_MAX_SEG_SEC}）",
    )
    segment_parser.add_argument(
        "--pad-sec",
        type=float,
        default=DEFAULT_PAD_SEC,
        help=f"片段前后填充时长（秒，默认: {DEFAULT_PAD_SEC}）",
    )
    segment_parser.add_argument(
        "--emit-wav",
        action="store_true",
        help="输出 WAV 文件（flag）",
    )
    segment_parser.add_argument(
        "--jobs",
        type=int,
        default=DEFAULT_JOBS,
        help=f"并行任务数（默认: {DEFAULT_JOBS}）",
    )
    segment_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="覆盖已存在文件（flag）",
    )
    # 日志选项也可以在子命令中使用
    segment_parser.add_argument(
        "--log-level",
        default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help=f"日志级别（默认: {DEFAULT_LOG_LEVEL}）",
    )
    segment_parser.add_argument(
        "--log-file",
        default=None,
        help="日志文件路径（可选）",
    )
    
    return parser


def cmd_check_deps(args: argparse.Namespace) -> int:
    """执行 check-deps 子命令"""
    try:
        checker = DepsChecker()
        report = checker.check(verbose=args.verbose)
        
        if args.json:
            # JSON 模式：只输出 JSON，不混入日志
            print(json.dumps(report, ensure_ascii=False))
        else:
            # 文本模式：输出格式化文本
            output = format_text_output(report, verbose=args.verbose)
            print(output)
        
        # 根据报告结果返回退出码
        if report["ok"]:
            return 0
        elif report["error_code"] == "deps_missing":
            return 2
        else:
            # unexpected_error 或其他错误
            return 1
    except Exception as e:
        # 捕获未预期的异常
        if args.json:
            error_report = {
                "ok": False,
                "error_code": "unexpected_error",
                "missing": [],
                "error": str(e),
            }
            print(json.dumps(error_report, ensure_ascii=False))
        else:
            print(f"错误: {e}", file=sys.stderr)
        return 1


def cmd_segment(args: argparse.Namespace) -> int:
    """执行 segment 子命令（R3：输入解析与计划）"""
    from onepass_audioclean_seg.pipeline.resolver import InputResolver
    from onepass_audioclean_seg.pipeline.planner import SegmentPlanner
    
    input_path = Path(args.input_path)
    output_dir = Path(args.output_dir)
    
    # 构建参数字典（用于写入报告）
    params = {
        "strategy": args.strategy,
        "min_silence_sec": args.min_silence_sec,
        "min_seg_sec": args.min_seg_sec,
        "max_seg_sec": args.max_seg_sec,
        "pad_sec": args.pad_sec,
        "emit_wav": args.emit_wav,
        "jobs": args.jobs,
        "overwrite": args.overwrite,
        "pattern": args.pattern,
        "out_mode": args.out_mode,
        "dry_run": args.dry_run,
    }
    
    try:
        # 解析输入
        resolver = InputResolver(pattern=args.pattern)
        jobs = resolver.resolve(input_path, output_dir, args.out_mode)
        
        # 规划并执行（或 dry-run）
        planner = SegmentPlanner(dry_run=args.dry_run, overwrite=args.overwrite)
        executed_count = planner.plan_and_execute(jobs, params)
        
        return 0
    except FileNotFoundError as e:
        print(f"错误: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


def main(argv: list[str] | None = None) -> int:
    """CLI 主函数
    
    Args:
        argv: 命令行参数列表，默认为 None（使用 sys.argv）
    """
    parser = create_parser()
    args = parser.parse_args(argv)
    
    # 设置日志（子命令中的日志选项优先于全局选项）
    log_level = getattr(args, "log_level", DEFAULT_LOG_LEVEL)
    if log_level is None:  # 如果子命令中没有指定，使用全局默认值
        log_level = DEFAULT_LOG_LEVEL
    log_file = getattr(args, "log_file", None)
    setup_logging(level=log_level, log_file=log_file)
    
    # 根据子命令分发
    try:
        if args.command == "check-deps":
            return cmd_check_deps(args)
        elif args.command == "segment":
            return cmd_segment(args)
        else:
            parser.print_help()
            return 2
    except KeyboardInterrupt:
        print("\n操作已取消", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())

