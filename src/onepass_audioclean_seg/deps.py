"""依赖检查模块：检查 ffmpeg/ffprobe/silencedetect 可用性"""

import platform
import sys
from typing import Any

from onepass_audioclean_seg import __version__
from onepass_audioclean_seg.audio.ffmpeg import (
    check_silencedetect,
    get_ffmpeg_version,
    get_ffprobe_version,
    which,
)


class DepsChecker:
    """依赖检查器：检查系统依赖并生成报告"""
    
    def check(self, verbose: bool = False) -> dict[str, Any]:
        """执行依赖检查并返回报告字典
        
        Args:
            verbose: 是否输出详细信息
        
        Returns:
            包含检查结果的字典，结构如下：
            {
                "ok": bool,
                "error_code": str | None,
                "missing": list[str],
                "deps": {
                    "ffmpeg": {...},
                    "ffprobe": {...},
                    "silencedetect": {...}
                },
                "platform": {...},
                "python": {...},
                "package": {...}
            }
        """
        report: dict[str, Any] = {
            "ok": True,
            "error_code": None,
            "missing": [],
            "deps": {},
            "platform": {
                "system": platform.system(),
                "release": platform.release(),
                "machine": platform.machine(),
            },
            "python": {
                "version": sys.version.split()[0],
                "executable": sys.executable,
            },
            "package": {
                "name": "onepass-audioclean-seg",
                "version": __version__,
            },
        }
        
        # 检查 ffmpeg
        ffmpeg_path = which("ffmpeg")
        ffmpeg_ok = ffmpeg_path is not None
        ffmpeg_version = None
        ffmpeg_detail = ""
        
        if ffmpeg_ok:
            try:
                ffmpeg_version = get_ffmpeg_version(ffmpeg_path)
                if verbose and ffmpeg_version:
                    # 获取完整版本信息作为 detail
                    from onepass_audioclean_seg.audio.ffmpeg import run_cmd
                    result = run_cmd([ffmpeg_path, "-version"], timeout_sec=10)
                    if result.returncode == 0:
                        ffmpeg_detail = result.stdout.split("\n")[0]  # 第一行
            except Exception:
                ffmpeg_ok = False
        
        if not ffmpeg_ok:
            report["missing"].append("ffmpeg")
            report["ok"] = False
            report["error_code"] = "deps_missing"
        
        report["deps"]["ffmpeg"] = {
            "ok": ffmpeg_ok,
            "path": ffmpeg_path or "",
            "version": ffmpeg_version or "",
            "detail": ffmpeg_detail,
        }
        
        # 检查 ffprobe
        ffprobe_path = which("ffprobe")
        ffprobe_ok = ffprobe_path is not None
        ffprobe_version = None
        ffprobe_detail = ""
        
        if ffprobe_ok:
            try:
                ffprobe_version = get_ffprobe_version(ffprobe_path)
                if verbose and ffprobe_version:
                    from onepass_audioclean_seg.audio.ffmpeg import run_cmd
                    result = run_cmd([ffprobe_path, "-version"], timeout_sec=10)
                    if result.returncode == 0:
                        ffprobe_detail = result.stdout.split("\n")[0]  # 第一行
            except Exception:
                ffprobe_ok = False
        
        if not ffprobe_ok:
            report["missing"].append("ffprobe")
            report["ok"] = False
            report["error_code"] = "deps_missing"
        
        report["deps"]["ffprobe"] = {
            "ok": ffprobe_ok,
            "path": ffprobe_path or "",
            "version": ffprobe_version or "",
            "detail": ffprobe_detail,
        }
        
        # 检查 silencedetect（需要 ffmpeg 存在）
        silencedetect_ok = False
        silencedetect_detail = ""
        
        if ffmpeg_ok and ffmpeg_path:
            try:
                silencedetect_ok, silencedetect_detail = check_silencedetect(ffmpeg_path)
            except Exception as e:
                silencedetect_ok = False
                silencedetect_detail = str(e)
        else:
            silencedetect_detail = "ffmpeg 不存在，无法检查"
        
        if not silencedetect_ok:
            report["missing"].append("silencedetect")
            report["ok"] = False
            report["error_code"] = "deps_missing"
        
        report["deps"]["silencedetect"] = {
            "ok": silencedetect_ok,
            "detail": silencedetect_detail,
        }
        
        # 如果没有缺失，确保 error_code 为 None
        if report["ok"]:
            report["error_code"] = None
        
        return report


def format_text_output(report: dict[str, Any], verbose: bool = False) -> str:
    """格式化文本输出
    
    Args:
        report: 依赖报告字典
        verbose: 是否输出详细信息
    
    Returns:
        格式化的文本字符串
    """
    lines = []
    
    # 检查各个依赖
    for dep_name in ["ffmpeg", "ffprobe", "silencedetect"]:
        dep_info = report["deps"][dep_name]
        if dep_info["ok"]:
            if dep_name in ["ffmpeg", "ffprobe"]:
                path = dep_info["path"]
                version = dep_info["version"]
                if verbose:
                    lines.append(f"{dep_name}: OK (path={path}, version={version})")
                    if dep_info.get("detail"):
                        lines.append(f"  Detail: {dep_info['detail']}")
                else:
                    lines.append(f"{dep_name}: OK (path={path}, version={version})")
            else:  # silencedetect
                lines.append(f"{dep_name}: OK")
                if verbose and dep_info.get("detail"):
                    lines.append(f"  Detail: {dep_info['detail']}")
        else:
            lines.append(f"{dep_name}: MISSING")
            if verbose and dep_info.get("detail"):
                lines.append(f"  Detail: {dep_info['detail']}")
    
    # 如果有关键依赖缺失，给出安装提示
    if not report["ok"]:
        lines.append("")
        lines.append("安装提示:")
        system = report["platform"]["system"]
        if system == "Darwin":  # macOS
            lines.append("  macOS: brew install ffmpeg")
        elif system == "Linux":
            lines.append("  Ubuntu/Debian: sudo apt-get install ffmpeg")
            lines.append("  CentOS/RHEL: sudo yum install ffmpeg")
        else:
            lines.append("  Windows: 请从 https://ffmpeg.org 下载并加入 PATH")
    
    return "\n".join(lines)

