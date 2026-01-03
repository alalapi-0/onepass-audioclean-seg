"""输出验证模块：验证 segments.jsonl、silences.json、seg_report.json 的格式和一致性"""

import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ValidationError(Exception):
    """验证错误异常"""
    pass


class ValidationResult:
    """验证结果"""
    
    def __init__(self, path: Path):
        self.path = path
        self.ok = True
        self.warnings: list[str] = []
        self.errors: list[str] = []
        self.stats: dict[str, Any] = {}
    
    def add_warning(self, message: str):
        """添加警告"""
        self.warnings.append(message)
    
    def add_error(self, message: str):
        """添加错误"""
        self.errors.append(message)
        self.ok = False
    
    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "path": str(self.path),
            "ok": self.ok,
            "warnings": self.warnings,
            "errors": self.errors,
            "stats": self.stats,
        }


def validate_segments_jsonl(
    segments_path: Path,
    strict: bool = False,
) -> ValidationResult:
    """验证 segments.jsonl 文件
    
    Args:
        segments_path: segments.jsonl 文件路径
        strict: 是否严格模式（overlap 等作为 error 而非 warning）
    
    Returns:
        验证结果
    """
    result = ValidationResult(segments_path)
    
    if not segments_path.exists():
        result.add_error("文件不存在")
        return result
    
    # 读取并解析 JSONL
    segments = []
    try:
        with open(segments_path, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                
                try:
                    obj = json.loads(line)
                    segments.append((line_num, obj))
                except json.JSONDecodeError as e:
                    result.add_error(f"line {line_num}: JSON 解析失败: {e}")
    except OSError as e:
        result.add_error(f"读取文件失败: {e}")
        return result
    
    if not segments:
        result.add_warning("文件为空（没有片段）")
        result.stats = {"segments": 0, "speech_total_sec": 0.0}
        return result
    
    # 验证每个片段
    prev_start = None
    prev_id_num = None
    
    for line_num, seg in segments:
        # 必填字段检查
        required_fields = ["id", "start_sec", "end_sec", "duration_sec", "source_audio"]
        for field in required_fields:
            if field not in seg:
                result.add_error(f"line {line_num}: 缺少必填字段 '{field}'")
        
        if not result.ok:  # 如果已有错误，跳过后续检查
            continue
        
        # 类型检查
        if not isinstance(seg["id"], str):
            result.add_error(f"line {line_num}: id 必须是字符串")
        if not isinstance(seg["start_sec"], (int, float)):
            result.add_error(f"line {line_num}: start_sec 必须是数字")
        if not isinstance(seg["end_sec"], (int, float)):
            result.add_error(f"line {line_num}: end_sec 必须是数字")
        if not isinstance(seg["duration_sec"], (int, float)):
            result.add_error(f"line {line_num}: duration_sec 必须是数字")
        if not isinstance(seg["source_audio"], str):
            result.add_error(f"line {line_num}: source_audio 必须是字符串")
        
        if not result.ok:
            continue
        
        # 数值约束
        start_sec = seg["start_sec"]
        end_sec = seg["end_sec"]
        duration_sec = seg["duration_sec"]
        
        if start_sec < 0:
            result.add_error(f"line {line_num}: start_sec 必须 >= 0，当前值: {start_sec}")
        
        if end_sec <= start_sec:
            result.add_error(f"line {line_num}: end_sec 必须 > start_sec，当前值: end={end_sec}, start={start_sec}")
        
        # duration_sec 约等于 (end_sec - start_sec)，允许误差 <= 0.002
        expected_duration = end_sec - start_sec
        duration_diff = abs(duration_sec - expected_duration)
        if duration_diff > 0.002:
            result.add_error(
                f"line {line_num}: duration_sec 与 (end_sec - start_sec) 不一致，"
                f"差值: {duration_diff:.6f}，允许误差: 0.002"
            )
        
        # round(3) 约束：检查 (value * 1000) 接近整数（误差 <= 1e-6）
        for field in ["start_sec", "end_sec", "duration_sec"]:
            value = seg[field]
            if isinstance(value, (int, float)):
                scaled = value * 1000
                diff = abs(scaled - round(scaled))
                if diff > 1e-6:
                    result.add_warning(
                        f"line {line_num}: {field} 可能不是 round(3) 格式，"
                        f"值: {value}, scaled: {scaled}, diff: {diff}"
                    )
        
        # ID 格式检查
        seg_id = seg["id"]
        id_match = re.match(r"^seg_(\d{6})$", seg_id)
        if not id_match:
            result.add_error(f"line {line_num}: id 格式错误，应为 seg_000001 格式，当前: {seg_id}")
        else:
            id_num = int(id_match.group(1))
            
            # ID 连续性检查
            if prev_id_num is not None:
                if id_num != prev_id_num + 1:
                    result.add_error(
                        f"line {line_num}: id 跳号，期望 seg_{prev_id_num + 1:06d}，实际 {seg_id}"
                    )
            elif id_num != 1:
                result.add_error(f"line {line_num}: 第一个 id 应为 seg_000001，实际 {seg_id}")
            
            prev_id_num = id_num
        
        # 排序检查：start_sec 单调非递减
        if prev_start is not None:
            if start_sec < prev_start - 1e-6:  # 允许小的浮点误差
                result.add_error(
                    f"line {line_num}: start_sec 不满足单调非递减，"
                    f"前一个: {prev_start}, 当前: {start_sec}"
                )
        
        prev_start = start_sec
        
        # 片段非重叠约束（默认作为 warning，strict=true 时变 error）
        if prev_start is not None and len(segments) > 1:
            prev_seg = segments[segments.index((line_num, seg)) - 1][1]
            prev_end = prev_seg.get("end_sec")
            if prev_end is not None:
                overlap = prev_end - start_sec
                if overlap > 0.001:  # 超过容差
                    msg = (
                        f"line {line_num}: 片段重叠，前一个 end_sec={prev_end}, "
                        f"当前 start_sec={start_sec}, overlap={overlap:.6f}"
                    )
                    if strict:
                        result.add_error(msg)
                    else:
                        result.add_warning(msg)
        
        # 建议字段类型检查
        if "is_speech" in seg and not isinstance(seg["is_speech"], bool):
            result.add_warning(f"line {line_num}: is_speech 应为布尔值")
        
        if "strategy" in seg and not isinstance(seg["strategy"], str):
            result.add_warning(f"line {line_num}: strategy 应为字符串")
        
        if "pre_silence_sec" in seg:
            if not isinstance(seg["pre_silence_sec"], (int, float)):
                result.add_warning(f"line {line_num}: pre_silence_sec 应为数字")
            elif seg["pre_silence_sec"] < 0:
                result.add_warning(f"line {line_num}: pre_silence_sec 应 >= 0")
        
        if "post_silence_sec" in seg:
            if not isinstance(seg["post_silence_sec"], (int, float)):
                result.add_warning(f"line {line_num}: post_silence_sec 应为数字")
            elif seg["post_silence_sec"] < 0:
                result.add_warning(f"line {line_num}: post_silence_sec 应 >= 0")
        
        if "rms" in seg and seg["rms"] is not None:
            if not isinstance(seg["rms"], (int, float)):
                result.add_warning(f"line {line_num}: rms 应为数字")
            elif not (0 <= seg["rms"] <= 1):
                result.add_warning(f"line {line_num}: rms 应在 [0, 1] 范围内")
        
        if "energy_db" in seg and seg["energy_db"] is not None:
            if not isinstance(seg["energy_db"], (int, float)):
                result.add_warning(f"line {line_num}: energy_db 应为数字")
        
        if "notes" in seg and seg["notes"] is not None:
            if not isinstance(seg["notes"], dict):
                result.add_warning(f"line {line_num}: notes 应为对象")
    
    # 统计信息
    speech_total_sec = sum(seg[1].get("duration_sec", 0) for seg in segments)
    result.stats = {
        "segments": len(segments),
        "speech_total_sec": round(speech_total_sec, 3),
    }
    
    return result


def validate_silences_json(silences_path: Path) -> ValidationResult:
    """验证 silences.json 文件
    
    Args:
        silences_path: silences.json 文件路径
    
    Returns:
        验证结果
    """
    result = ValidationResult(silences_path)
    
    if not silences_path.exists():
        result.add_error("文件不存在")
        return result
    
    try:
        with open(silences_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        result.add_error(f"JSON 解析失败: {e}")
        return result
    except OSError as e:
        result.add_error(f"读取文件失败: {e}")
        return result
    
    # 必填字段检查
    required_fields = ["audio_path", "strategy", "params", "silences"]
    for field in required_fields:
        if field not in data:
            result.add_error(f"缺少必填字段 '{field}'")
    
    if not result.ok:
        return result
    
    # 类型检查
    if not isinstance(data["audio_path"], str):
        result.add_error("audio_path 必须是字符串")
    
    if not isinstance(data["strategy"], str):
        result.add_error("strategy 必须是字符串")
    
    if not isinstance(data["params"], dict):
        result.add_error("params 必须是对象")
    
    if not isinstance(data["silences"], list):
        result.add_error("silences 必须是数组")
    
    if not result.ok:
        return result
    
    # 验证 silences 数组
    silences = data["silences"]
    for idx, silence in enumerate(silences):
        if not isinstance(silence, dict):
            result.add_error(f"silences[{idx}] 必须是对象")
            continue
        
        required = ["start_sec", "end_sec", "duration_sec"]
        for field in required:
            if field not in silence:
                result.add_error(f"silences[{idx}] 缺少必填字段 '{field}'")
        
        if not result.ok:
            continue
        
        # 数值约束
        start_sec = silence["start_sec"]
        end_sec = silence["end_sec"]
        duration_sec = silence["duration_sec"]
        
        if not isinstance(start_sec, (int, float)) or start_sec < 0:
            result.add_error(f"silences[{idx}]: start_sec 必须 >= 0")
        
        if not isinstance(end_sec, (int, float)) or end_sec <= start_sec:
            result.add_error(f"silences[{idx}]: end_sec 必须 > start_sec")
        
        if not isinstance(duration_sec, (int, float)) or duration_sec < 0:
            result.add_error(f"silences[{idx}]: duration_sec 必须 >= 0")
    
    # 统计信息
    silences_total_sec = sum(
        s.get("duration_sec", 0) for s in silences
        if isinstance(s, dict) and isinstance(s.get("duration_sec"), (int, float))
    )
    result.stats = {
        "silences_count": len(silences),
        "silences_total_sec": round(silences_total_sec, 3),
    }
    
    return result


def validate_seg_report_json(report_path: Path) -> ValidationResult:
    """验证 seg_report.json 文件
    
    Args:
        report_path: seg_report.json 文件路径
    
    Returns:
        验证结果
    """
    result = ValidationResult(report_path)
    
    if not report_path.exists():
        result.add_error("文件不存在")
        return result
    
    try:
        with open(report_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        result.add_error(f"JSON 解析失败: {e}")
        return result
    except OSError as e:
        result.add_error(f"读取文件失败: {e}")
        return result
    
    # 必填字段检查
    required_fields = ["version", "created_at", "versions", "params", "audio_path"]
    for field in required_fields:
        if field not in data:
            result.add_error(f"缺少必填字段 '{field}'")
    
    if not result.ok:
        return result
    
    # 类型检查
    if not isinstance(data["version"], str):
        result.add_error("version 必须是字符串")
    
    if not isinstance(data["created_at"], str):
        result.add_error("created_at 必须是字符串")
    
    if not isinstance(data["versions"], dict):
        result.add_error("versions 必须是对象")
    
    if not isinstance(data["params"], dict):
        result.add_error("params 必须是对象")
    
    if not isinstance(data["audio_path"], str):
        result.add_error("audio_path 必须是字符串")
    
    # 统计信息
    segments_count = 0
    speech_total_sec = 0.0
    
    if "segments" in data and isinstance(data["segments"], dict):
        segments_count = data["segments"].get("count", 0)
        speech_total_sec = data["segments"].get("speech_total_sec", 0.0)
    
    result.stats = {
        "segments_count": segments_count,
        "speech_total_sec": speech_total_sec,
    }
    
    return result


def validate_consistency(
    segments_result: ValidationResult,
    report_result: ValidationResult | None,
    silences_result: ValidationResult | None,
    strict: bool = False,
) -> None:
    """进行一致性检查
    
    Args:
        segments_result: segments.jsonl 验证结果
        report_result: seg_report.json 验证结果（可选）
        silences_result: silences.json 验证结果（可选）
        strict: 是否严格模式
    """
    segments_path = segments_result.path
    segments_dir = segments_path.parent
    
    # 检查 seg_report.json
    if report_result and report_result.ok:
        report_path = report_result.path
        try:
            with open(report_path, "r", encoding="utf-8") as f:
                report_data = json.load(f)
        except Exception:
            return  # 如果读取失败，跳过一致性检查
        
        # segments.count == segments.jsonl 行数
        segments_count = segments_result.stats.get("segments", 0)
        report_segments_count = report_data.get("segments", {}).get("count", 0)
        
        if segments_count != report_segments_count:
            msg = (
                f"seg_report.json segments.count ({report_segments_count}) "
                f"与 segments.jsonl 行数 ({segments_count}) 不一致"
            )
            if strict:
                segments_result.add_error(msg)
            else:
                segments_result.add_warning(msg)
        
        # segments.speech_total_sec 与 jsonl 求和接近（误差 <= 0.1）
        segments_speech_total = segments_result.stats.get("speech_total_sec", 0.0)
        report_speech_total = report_data.get("segments", {}).get("speech_total_sec", 0.0)
        
        if abs(segments_speech_total - report_speech_total) > 0.1:
            msg = (
                f"seg_report.json segments.speech_total_sec ({report_speech_total}) "
                f"与 segments.jsonl 求和 ({segments_speech_total}) 差异超过 0.1"
            )
            if strict:
                segments_result.add_error(msg)
            else:
                segments_result.add_warning(msg)
        
        # outputs.segments_jsonl 指向的路径若存在，必须指向当前文件（strict=true）
        if strict:
            outputs = report_data.get("segments", {}).get("outputs", {})
            report_segments_path = outputs.get("segments_jsonl")
            if report_segments_path:
                try:
                    report_segments_path_resolved = Path(report_segments_path).resolve()
                    segments_path_resolved = segments_path.resolve()
                    if report_segments_path_resolved != segments_path_resolved:
                        segments_result.add_error(
                            f"seg_report.json outputs.segments_jsonl ({report_segments_path}) "
                            f"与当前文件路径不一致"
                        )
                except Exception:
                    pass  # 路径解析失败，跳过
    
    # 检查 silences.json
    if silences_result and silences_result.ok:
        silences_path = silences_result.path
        try:
            with open(silences_path, "r", encoding="utf-8") as f:
                silences_data = json.load(f)
        except Exception:
            return  # 如果读取失败，跳过一致性检查
        
        # silences.duration_sec 与 seg_report.analysis.silence.duration_sec（若都有）接近
        if report_result and report_result.ok:
            try:
                with open(report_result.path, "r", encoding="utf-8") as f:
                    report_data = json.load(f)
                
                silences_total = silences_data.get("duration_sec")
                report_silences_total = (
                    report_data.get("analysis", {})
                    .get("silence", {})
                    .get("silences_total_sec")
                )
                
                if silences_total is not None and report_silences_total is not None:
                    if abs(silences_total - report_silences_total) > 0.1:
                        msg = (
                            f"silences.json duration_sec ({silences_total}) "
                            f"与 seg_report.json analysis.silence.silences_total_sec "
                            f"({report_silences_total}) 差异超过 0.1"
                        )
                        if strict:
                            silences_result.add_error(msg)
                        else:
                            silences_result.add_warning(msg)
            except Exception:
                pass  # 读取失败，跳过
        
        # 检查 segments.jsonl 中的 strategy
        try:
            with open(segments_path, "r", encoding="utf-8") as f:
                first_line = f.readline().strip()
                if first_line:
                    first_seg = json.loads(first_line)
                    strategy = first_seg.get("strategy", "silence")
                    
                    if strategy == "silence" and not silences_path.exists():
                        msg = (
                            f"segments.jsonl strategy 为 'silence'，但 silences.json 不存在"
                        )
                        if strict:
                            segments_result.add_error(msg)
                        else:
                            segments_result.add_warning(msg)
        except Exception:
            pass  # 读取失败，跳过


def validate_file_or_dir(
    input_path: Path,
    pattern: str = "segments.jsonl",
    strict: bool = False,
    max_errors: int = 20,
) -> dict[str, Any]:
    """验证文件或目录
    
    Args:
        input_path: 输入路径（文件或目录）
        pattern: 目录扫描时的文件名模式（默认: segments.jsonl）
        strict: 是否严格模式
        max_errors: 最大错误数（达到后停止）
    
    Returns:
        验证汇总结果
    """
    input_path = input_path.resolve()
    
    if not input_path.exists():
        raise FileNotFoundError(f"输入路径不存在: {input_path}")
    
    results: list[ValidationResult] = []
    
    # 收集要验证的文件
    files_to_validate: list[Path] = []
    
    if input_path.is_file():
        if input_path.name == "segments.jsonl":
            files_to_validate.append(input_path)
        else:
            raise ValueError(f"输入文件必须是 segments.jsonl，当前: {input_path.name}")
    else:
        # 递归扫描目录
        for file_path in sorted(input_path.rglob(pattern)):
            if file_path.is_file() and file_path.name == "segments.jsonl":
                files_to_validate.append(file_path)
    
    if not files_to_validate:
        return {
            "ok": True,
            "error_code": None,
            "checked_files": 0,
            "failed_files": 0,
            "warnings": 0,
            "errors": 0,
            "results": [],
        }
    
    # 验证每个文件
    for segments_path in files_to_validate:
        if len([r for r in results if not r.ok]) >= max_errors:
            break
        
        segments_dir = segments_path.parent
        
        # 验证 segments.jsonl
        segments_result = validate_segments_jsonl(segments_path, strict=strict)
        
        # 验证同目录下的其他文件
        report_path = segments_dir / "seg_report.json"
        silences_path = segments_dir / "silences.json"
        
        report_result = None
        if report_path.exists():
            report_result = validate_seg_report_json(report_path)
        
        silences_result = None
        if silences_path.exists():
            silences_result = validate_silences_json(silences_path)
        
        # 一致性检查
        validate_consistency(segments_result, report_result, silences_result, strict=strict)
        
        results.append(segments_result)
        if report_result:
            results.append(report_result)
        if silences_result:
            results.append(silences_result)
    
    # 汇总
    total_warnings = sum(len(r.warnings) for r in results)
    total_errors = sum(len(r.errors) for r in results)
    failed_files = len([r for r in results if not r.ok])
    
    return {
        "ok": failed_files == 0,
        "error_code": "violations" if failed_files > 0 else None,
        "checked_files": len(files_to_validate),
        "failed_files": failed_files,
        "warnings": total_warnings,
        "errors": total_errors,
        "results": [r.to_dict() for r in results if r.path.name == "segments.jsonl"],
    }

