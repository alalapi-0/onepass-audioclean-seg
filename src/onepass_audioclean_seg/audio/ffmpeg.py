"""FFmpeg/FFprobe 封装：which、run、version 解析、silencedetect 检查"""

import re
import shutil
import subprocess
from subprocess import CompletedProcess
from typing import Optional


def which(exe_name: str) -> Optional[str]:
    """查找可执行文件路径（使用 shutil.which）
    
    Args:
        exe_name: 可执行文件名（如 'ffmpeg', 'ffprobe'）
    
    Returns:
        可执行文件完整路径，若未找到则返回 None
    """
    return shutil.which(exe_name)


def run_cmd(cmd: list[str], timeout_sec: int = 30) -> CompletedProcess[str]:
    """执行命令并返回结果
    
    Args:
        cmd: 命令列表（如 ['ffmpeg', '-version']）
        timeout_sec: 超时时间（秒）
    
    Returns:
        CompletedProcess 对象，包含 stdout、stderr、returncode
    
    Raises:
        subprocess.TimeoutExpired: 命令执行超时
        OSError: 无法执行命令（如权限问题）
    """
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            check=False,  # 不自动抛出异常，让调用方处理
        )
        return result
    except subprocess.TimeoutExpired as e:
        # 将超时异常包装为可读的错误信息
        raise TimeoutError(f"命令执行超时（>{timeout_sec}秒）: {' '.join(cmd)}") from e
    except OSError as e:
        raise OSError(f"无法执行命令: {' '.join(cmd)}, 错误: {e}") from e


def parse_version_from_dash_version(output: str) -> Optional[str]:
    """从 'ffmpeg version X' 或 'ffprobe version X' 输出中提取版本号
    
    Args:
        output: 命令输出文本（通常是 stdout）
    
    Returns:
        版本号字符串（如 '6.0' 或 '6.0.1'），若无法解析则返回 None
    """
    # 匹配 "ffmpeg version X.Y.Z" 或 "ffprobe version X.Y.Z" 格式
    # 也支持 "version X.Y.Z" 开头的情况
    patterns = [
        r"ffmpeg\s+version\s+([\d.]+)",
        r"ffprobe\s+version\s+([\d.]+)",
        r"version\s+([\d.]+)",
    ]
    
    for pattern in patterns:
        match = re.search(pattern, output, re.IGNORECASE)
        if match:
            return match.group(1)
    
    return None


def get_ffmpeg_version(ffmpeg_path: str) -> Optional[str]:
    """获取 ffmpeg 版本号
    
    Args:
        ffmpeg_path: ffmpeg 可执行文件路径
    
    Returns:
        版本号字符串，若无法获取则返回 None
    """
    try:
        result = run_cmd([ffmpeg_path, "-version"], timeout_sec=10)
        if result.returncode == 0:
            return parse_version_from_dash_version(result.stdout)
        return None
    except (TimeoutError, OSError):
        return None


def get_ffprobe_version(ffprobe_path: str) -> Optional[str]:
    """获取 ffprobe 版本号
    
    Args:
        ffprobe_path: ffprobe 可执行文件路径
    
    Returns:
        版本号字符串，若无法获取则返回 None
    """
    try:
        result = run_cmd([ffprobe_path, "-version"], timeout_sec=10)
        if result.returncode == 0:
            return parse_version_from_dash_version(result.stdout)
        return None
    except (TimeoutError, OSError):
        return None


def check_silencedetect(ffmpeg_path: str) -> tuple[bool, str]:
    """检查 ffmpeg 是否支持 silencedetect 滤镜
    
    Args:
        ffmpeg_path: ffmpeg 可执行文件路径
    
    Returns:
        (是否可用, 详细信息消息) 元组
        - 若可用：返回 (True, "可用")
        - 若不可用：返回 (False, 错误消息)
    """
    try:
        result = run_cmd(
            [ffmpeg_path, "-hide_banner", "-h", "filter=silencedetect"],
            timeout_sec=10
        )
        
        if result.returncode == 0 and "silencedetect" in result.stdout.lower():
            # 提取第一行或关键信息作为 detail
            lines = result.stdout.strip().split("\n")
            detail = lines[0] if lines else "silencedetect 滤镜可用"
            return (True, detail)
        else:
            error_msg = result.stderr or "未找到 silencedetect 滤镜"
            return (False, error_msg)
    except (TimeoutError, OSError) as e:
        return (False, str(e))

