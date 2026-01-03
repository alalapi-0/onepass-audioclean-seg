"""日志配置工具"""

import logging
import sys
from pathlib import Path
from typing import Optional


def setup_logging(level: str = "INFO", log_file: Optional[str] = None) -> None:
    """
    配置日志系统
    
    Args:
        level: 日志级别（DEBUG, INFO, WARNING, ERROR, CRITICAL）
        log_file: 可选日志文件路径，如果为 None 则只输出到 stderr
    """
    # 转换为 logging 级别
    log_level = getattr(logging, level.upper(), logging.INFO)
    
    # 配置日志格式
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"
    
    # 创建 handlers
    handlers = []
    
    # 标准错误输出 handler（默认）
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(logging.Formatter(log_format, date_format))
    handlers.append(console_handler)
    
    # 文件 handler（如果指定）
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(logging.Formatter(log_format, date_format))
        handlers.append(file_handler)
    
    # 配置根 logger
    logging.basicConfig(
        level=log_level,
        format=log_format,
        datefmt=date_format,
        handlers=handlers,
        force=True,  # 覆盖已有配置
    )

