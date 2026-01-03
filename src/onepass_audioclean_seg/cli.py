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
        help="将音频分段（R1 占位实现，仅打印计划）",
    )
    segment_parser.add_argument(
        "--in",
        dest="input_path",
        required=True,
        help="输入音频文件路径（必填）",
    )
    segment_parser.add_argument(
        "--out",
        dest="output_dir",
        required=True,
        help="输出目录路径（必填）",
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
    """执行 segment 子命令（R1 仅打印计划）"""
    input_path = Path(args.input_path)
    output_dir = Path(args.output_dir)
    
    # 打印计划（dry-run 风格）
    print("=" * 60)
    print("PLAN: 音频分段计划（R1 占位实现，不会实际处理）")
    print("=" * 60)
    print(f"输入文件: {input_path}")
    print(f"输出目录: {output_dir}")
    print(f"分段策略: {args.strategy}")
    print(f"参数配置:")
    print(f"  - 最小静音时长: {args.min_silence_sec} 秒")
    print(f"  - 最小片段时长: {args.min_seg_sec} 秒")
    print(f"  - 最大片段时长: {args.max_seg_sec} 秒")
    print(f"  - 片段填充时长: {args.pad_sec} 秒")
    print(f"  - 输出 WAV: {args.emit_wav}")
    print(f"  - 并行任务数: {args.jobs}")
    print(f"  - 覆盖已存在: {args.overwrite}")
    print("=" * 60)
    print("注意: R1 版本仅进行参数解析和计划打印，不会实际执行分段操作。")
    print("=" * 60)
    
    return 0


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

