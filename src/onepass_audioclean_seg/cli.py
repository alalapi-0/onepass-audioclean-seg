"""CLI 主入口"""

import argparse
import json
import sys
from pathlib import Path

from onepass_audioclean_seg import __version__
from onepass_audioclean_seg.constants import (
    DEFAULT_AUTO_STRATEGY_MIN_SEGMENTS,
    DEFAULT_AUTO_STRATEGY_MIN_SPEECH_TOTAL_SEC,
    DEFAULT_AUTO_STRATEGY_ORDER,
    DEFAULT_JOBS,
    DEFAULT_LOG_LEVEL,
    DEFAULT_MAX_SEG_SEC,
    DEFAULT_MIN_SEG_SEC,
    DEFAULT_MIN_SILENCE_SEC,
    DEFAULT_PAD_SEC,
    DEFAULT_STRATEGY,
    DEFAULT_SILENCE_THRESHOLD_DB,
    DEFAULT_VAD_AGGRESSIVENESS,
    DEFAULT_VAD_FRAME_MS,
    DEFAULT_VAD_MIN_SPEECH_SEC,
    DEFAULT_VAD_SAMPLE_RATE,
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
    check_deps_parser.add_argument(
        "--strict",
        action="store_true",
        default=False,
        help="严格模式：webrtcvad 缺失也视为失败（默认: False，webrtcvad 为可选依赖）",
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
        "--silence-threshold-db",
        type=float,
        default=DEFAULT_SILENCE_THRESHOLD_DB,
        help=f"静音检测阈值（dB，默认: {DEFAULT_SILENCE_THRESHOLD_DB}，仅 silence 策略）",
    )
    segment_parser.add_argument(
        "--energy-frame-ms",
        type=float,
        default=30.0,
        help="Energy 策略：帧长度（毫秒，默认: 30）",
    )
    segment_parser.add_argument(
        "--energy-hop-ms",
        type=float,
        default=10.0,
        help="Energy 策略：帧移（毫秒，默认: 10）",
    )
    segment_parser.add_argument(
        "--energy-smooth-ms",
        type=float,
        default=100.0,
        help="Energy 策略：平滑窗口长度（毫秒，默认: 100）",
    )
    segment_parser.add_argument(
        "--energy-threshold-rms",
        type=float,
        default=0.02,
        help="Energy 策略：RMS 阈值（归一化到 [0, 1]，默认: 0.02）",
    )
    segment_parser.add_argument(
        "--energy-min-speech-sec",
        type=float,
        default=0.20,
        help="Energy 策略：最小语音长度（秒，用于硬过滤极短语音岛，默认: 0.20）",
    )
    segment_parser.add_argument(
        "--vad-aggressiveness",
        type=int,
        default=DEFAULT_VAD_AGGRESSIVENESS,
        choices=[0, 1, 2, 3],
        help=f"VAD 策略：攻击性级别 0..3（默认: {DEFAULT_VAD_AGGRESSIVENESS}）",
    )
    segment_parser.add_argument(
        "--vad-frame-ms",
        type=int,
        default=DEFAULT_VAD_FRAME_MS,
        choices=[10, 20, 30],
        help=f"VAD 策略：帧长度（毫秒，10/20/30，默认: {DEFAULT_VAD_FRAME_MS}）",
    )
    segment_parser.add_argument(
        "--vad-sample-rate",
        type=int,
        default=DEFAULT_VAD_SAMPLE_RATE,
        choices=[8000, 16000, 32000, 48000],
        help=f"VAD 策略：采样率（8000/16000/32000/48000，默认: {DEFAULT_VAD_SAMPLE_RATE}）",
    )
    segment_parser.add_argument(
        "--vad-min-speech-sec",
        type=float,
        default=DEFAULT_VAD_MIN_SPEECH_SEC,
        help=f"VAD 策略：最小语音长度（秒，用于硬过滤极短语音岛，默认: {DEFAULT_VAD_MIN_SPEECH_SEC}）",
    )
    segment_parser.add_argument(
        "--auto-strategy",
        action="store_true",
        default=False,
        help="启用自动策略选择（按顺序尝试策略直到找到满足质量门槛的，默认: False）",
    )
    segment_parser.add_argument(
        "--auto-strategy-order",
        type=str,
        default=DEFAULT_AUTO_STRATEGY_ORDER,
        help=f"Auto-strategy 策略尝试顺序（逗号分隔，默认: {DEFAULT_AUTO_STRATEGY_ORDER}）",
    )
    segment_parser.add_argument(
        "--auto-strategy-min-segments",
        type=int,
        default=DEFAULT_AUTO_STRATEGY_MIN_SEGMENTS,
        help=f"Auto-strategy 最小片段数（默认: {DEFAULT_AUTO_STRATEGY_MIN_SEGMENTS}）",
    )
    segment_parser.add_argument(
        "--auto-strategy-min-speech-total-sec",
        type=float,
        default=DEFAULT_AUTO_STRATEGY_MIN_SPEECH_TOTAL_SEC,
        help=f"Auto-strategy 最小总语音时长（秒，默认: {DEFAULT_AUTO_STRATEGY_MIN_SPEECH_TOTAL_SEC}）",
    )
    segment_parser.add_argument(
        "--analyze",
        action="store_true",
        default=False,
        help="运行分析并输出策略 artifact（silences.json 或 energy.json 或 vad.json，默认: False）",
    )
    segment_parser.add_argument(
        "--emit-segments",
        action="store_true",
        default=False,
        help="生成语音片段并输出 segments.jsonl（默认: False）",
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
    segment_parser.add_argument(
        "--validate-output",
        action="store_true",
        default=False,
        help="生成 segments.jsonl 后立即验证输出（默认: False）",
    )
    
    # validate 子命令
    validate_parser = subparsers.add_parser(
        "validate",
        help="验证输出文件（segments.jsonl / silences.json / seg_report.json）",
    )
    validate_parser.add_argument(
        "--in",
        dest="input_path",
        required=True,
        help="输入路径：segments.jsonl 文件、目录或 workdir/out_root（必填）",
    )
    validate_parser.add_argument(
        "--strict",
        action="store_true",
        default=False,
        help="严格模式：将 warnings 视为 errors（默认: False）",
    )
    validate_parser.add_argument(
        "--max-errors",
        type=int,
        default=20,
        help="最大错误数（达到后停止，默认: 20）",
    )
    validate_parser.add_argument(
        "--pattern",
        default="segments.jsonl",
        help="目录扫描时的文件名模式（默认: segments.jsonl）",
    )
    validate_parser.add_argument(
        "--json",
        action="store_true",
        help="以 JSON 格式输出汇总（默认: False）",
    )
    validate_parser.add_argument(
        "--log-level",
        default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help=f"日志级别（默认: {DEFAULT_LOG_LEVEL}）",
    )
    validate_parser.add_argument(
        "--log-file",
        default=None,
        help="日志文件路径（可选）",
    )
    
    return parser


def cmd_check_deps(args: argparse.Namespace) -> int:
    """执行 check-deps 子命令"""
    try:
        checker = DepsChecker()
        report = checker.check(verbose=args.verbose, strict=args.strict)
        
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


def cmd_validate(args: argparse.Namespace) -> int:
    """执行 validate 子命令"""
    from onepass_audioclean_seg.validate import validate_file_or_dir
    
    input_path = Path(args.input_path)
    
    try:
        summary = validate_file_or_dir(
            input_path=input_path,
            pattern=args.pattern,
            strict=args.strict,
            max_errors=args.max_errors,
        )
        
        if args.json:
            # JSON 模式：只输出 JSON，不混入日志
            print(json.dumps(summary, ensure_ascii=False, indent=2))
        else:
            # 文本模式：逐个文件输出 OK/FAIL，并在末尾输出汇总
            for result in summary["results"]:
                status = "OK" if result["ok"] else "FAIL"
                path = result["path"]
                errors_count = len(result["errors"])
                warnings_count = len(result["warnings"])
                
                print(f"{status} {path} errors={errors_count} warnings={warnings_count}")
                
                # 输出错误和警告（限制数量）
                if result["errors"]:
                    for error in result["errors"][:5]:  # 最多显示 5 个错误
                        print(f"  ERROR: {error}", file=sys.stderr)
                    if len(result["errors"]) > 5:
                        print(f"  ... 还有 {len(result['errors']) - 5} 个错误", file=sys.stderr)
                
                if result["warnings"]:
                    for warning in result["warnings"][:5]:  # 最多显示 5 个警告
                        print(f"  WARNING: {warning}", file=sys.stderr)
                    if len(result["warnings"]) > 5:
                        print(f"  ... 还有 {len(result['warnings']) - 5} 个警告", file=sys.stderr)
            
            # 输出汇总
            print(f"\n汇总: checked={summary['checked_files']} "
                  f"failed={summary['failed_files']} "
                  f"errors={summary['errors']} "
                  f"warnings={summary['warnings']}")
        
        # 根据结果返回退出码
        if summary["ok"]:
            return 0
        elif summary["error_code"] == "violations":
            return 2
        else:
            return 1
    except FileNotFoundError as e:
        if args.json:
            error_report = {
                "ok": False,
                "error_code": "unexpected_error",
                "checked_files": 0,
                "failed_files": 0,
                "warnings": 0,
                "errors": 0,
                "error": str(e),
                "results": [],
            }
            print(json.dumps(error_report, ensure_ascii=False, indent=2))
        else:
            print(f"错误: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        if args.json:
            error_report = {
                "ok": False,
                "error_code": "unexpected_error",
                "checked_files": 0,
                "failed_files": 0,
                "warnings": 0,
                "errors": 0,
                "error": str(e),
                "results": [],
            }
            print(json.dumps(error_report, ensure_ascii=False, indent=2))
        else:
            print(f"错误: {e}", file=sys.stderr)
        return 1


def cmd_segment(args: argparse.Namespace) -> int:
    """执行 segment 子命令（R3：输入解析与计划；R4：静音分析；R5：生成片段）"""
    from onepass_audioclean_seg.pipeline.resolver import InputResolver
    from onepass_audioclean_seg.pipeline.planner import SegmentPlanner
    
    input_path = Path(args.input_path)
    output_dir = Path(args.output_dir)
    
    # 检查 --analyze 和 --dry-run 的冲突
    if args.analyze and args.dry_run:
        print("错误: --analyze 需要关闭 --dry-run", file=sys.stderr)
        return 2
    
    # 检查 --emit-segments 和 --dry-run 的冲突
    if args.emit_segments and args.dry_run:
        print("错误: --emit-segments 需要关闭 --dry-run", file=sys.stderr)
        return 2
    
    # 参数校验
    if args.pad_sec < 0:
        print(f"错误: --pad-sec 必须 >= 0，当前值: {args.pad_sec}", file=sys.stderr)
        return 2
    
    if args.min_seg_sec <= 0:
        print(f"错误: --min-seg-sec 必须 > 0，当前值: {args.min_seg_sec}", file=sys.stderr)
        return 2
    
    if args.min_silence_sec <= 0:
        print(f"错误: --min-silence-sec 必须 > 0，当前值: {args.min_silence_sec}", file=sys.stderr)
        return 2
    
    if args.max_seg_sec < args.min_seg_sec:
        print(f"错误: --max-seg-sec ({args.max_seg_sec}) 必须 >= --min-seg-sec ({args.min_seg_sec})", file=sys.stderr)
        return 2
    
    # 检查 ffmpeg 是否存在（如果使用 silence 策略）
    if args.strategy == "silence":
        from onepass_audioclean_seg.audio.ffmpeg import which
        ffmpeg_path = which("ffmpeg")
        if ffmpeg_path is None:
            print("错误: --strategy silence 需要 ffmpeg，但未找到", file=sys.stderr)
            return 1
    
    # 检查 webrtcvad 是否存在（如果使用 vad 策略）
    if args.strategy == "vad":
        try:
            import webrtcvad
        except ImportError:
            print("错误: --strategy vad 需要 webrtcvad，但未安装", file=sys.stderr)
            print("提示: 请运行 pip install -e \".[vad]\" 或 pip install webrtcvad>=2.0.10", file=sys.stderr)
            return 2
    
    # 构建参数字典（用于写入报告）
    params = {
        "strategy": args.strategy,
        "min_silence_sec": args.min_silence_sec,
        "silence_threshold_db": args.silence_threshold_db,
        "energy_frame_ms": args.energy_frame_ms,
        "energy_hop_ms": args.energy_hop_ms,
        "energy_smooth_ms": args.energy_smooth_ms,
        "energy_threshold_rms": args.energy_threshold_rms,
        "energy_min_speech_sec": args.energy_min_speech_sec,
        "vad_aggressiveness": args.vad_aggressiveness,
        "vad_frame_ms": args.vad_frame_ms,
        "vad_sample_rate": args.vad_sample_rate,
        "vad_min_speech_sec": args.vad_min_speech_sec,
        "auto_strategy": args.auto_strategy,
        "auto_strategy_order": args.auto_strategy_order,
        "auto_strategy_min_segments": args.auto_strategy_min_segments,
        "auto_strategy_min_speech_total_sec": args.auto_strategy_min_speech_total_sec,
        "min_seg_sec": args.min_seg_sec,
        "max_seg_sec": args.max_seg_sec,
        "pad_sec": args.pad_sec,
        "emit_wav": args.emit_wav,
        "jobs": args.jobs,
        "overwrite": args.overwrite,
        "pattern": args.pattern,
        "out_mode": args.out_mode,
        "dry_run": args.dry_run,
        "analyze": args.analyze,
        "emit_segments": args.emit_segments,
        "validate_output": getattr(args, "validate_output", False),
    }
    
    # 如果使用 energy 策略，忽略 silence 相关参数（但写 warning）
    if args.strategy == "energy" and args.silence_threshold_db != DEFAULT_SILENCE_THRESHOLD_DB:
        print(f"警告: --strategy energy 时忽略 --silence-threshold-db 参数", file=sys.stderr)
    
    try:
        # 解析输入
        resolver = InputResolver(pattern=args.pattern)
        jobs = resolver.resolve(input_path, output_dir, args.out_mode)
        
        # 规划并执行（或 dry-run）
        planner = SegmentPlanner(
            dry_run=args.dry_run,
            overwrite=args.overwrite,
            analyze=args.analyze,
            emit_segments=args.emit_segments,
            silence_threshold_db=args.silence_threshold_db,
            validate_output=getattr(args, "validate_output", False),
        )
        executed_count = planner.plan_and_execute(jobs, params)
        
        return planner.get_exit_code()
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
        elif args.command == "validate":
            return cmd_validate(args)
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

