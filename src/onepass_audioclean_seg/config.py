"""配置文件支持模块（R11）"""

import json
import logging
import sys
from pathlib import Path
from typing import Any, Optional

from onepass_audioclean_seg.constants import (
    DEFAULT_AUTO_STRATEGY_MIN_SEGMENTS,
    DEFAULT_AUTO_STRATEGY_MIN_SPEECH_TOTAL_SEC,
    DEFAULT_AUTO_STRATEGY_ORDER,
    DEFAULT_JOBS,
    DEFAULT_MAX_SEG_SEC,
    DEFAULT_MIN_SEG_SEC,
    DEFAULT_MIN_SILENCE_SEC,
    DEFAULT_PAD_SEC,
    DEFAULT_SILENCE_THRESHOLD_DB,
    DEFAULT_STRATEGY,
    DEFAULT_VAD_AGGRESSIVENESS,
    DEFAULT_VAD_FRAME_MS,
    DEFAULT_VAD_MIN_SPEECH_SEC,
    DEFAULT_VAD_SAMPLE_RATE,
)
from onepass_audioclean_seg.errors import ConfigError, DependencyMissingError

logger = logging.getLogger(__name__)

# 音频指纹读取的前N秒（常量）
FINGERPRINT_READ_SECONDS = 10.0


def get_default_config() -> dict[str, Any]:
    """获取默认配置
    
    Returns:
        默认配置字典
    """
    return {
        "strategy": {
            "name": DEFAULT_STRATEGY,
            "auto": {
                "enabled": False,
                "order": DEFAULT_AUTO_STRATEGY_ORDER.split(","),
                "min_segments": DEFAULT_AUTO_STRATEGY_MIN_SEGMENTS,
                "min_speech_total_sec": DEFAULT_AUTO_STRATEGY_MIN_SPEECH_TOTAL_SEC,
            },
        },
        "silence": {
            "threshold_db": DEFAULT_SILENCE_THRESHOLD_DB,
            "min_silence_sec": DEFAULT_MIN_SILENCE_SEC,
        },
        "energy": {
            "threshold_rms": 0.02,
            "frame_ms": 30.0,
            "hop_ms": 10.0,
            "smooth_ms": 100.0,
            "min_speech_sec": 0.20,
        },
        "vad": {
            "aggressiveness": DEFAULT_VAD_AGGRESSIVENESS,
            "frame_ms": DEFAULT_VAD_FRAME_MS,
            "sample_rate": DEFAULT_VAD_SAMPLE_RATE,
            "min_speech_sec": DEFAULT_VAD_MIN_SPEECH_SEC,
        },
        "postprocess": {
            "min_seg_sec": DEFAULT_MIN_SEG_SEC,
            "max_seg_sec": DEFAULT_MAX_SEG_SEC,
            "pad_sec": DEFAULT_PAD_SEC,
        },
        "exports": {
            "timeline": False,
            "csv": False,
            "mask": "none",
            "mask_bin_ms": 50.0,
        },
        "runtime": {
            "jobs": DEFAULT_JOBS,
            "overwrite": False,
            "out_mode": "in_place",
        },
        "validate": {
            "enabled": False,
            "strict": False,
        },
    }


def load_config_file(config_path: Path) -> dict[str, Any]:
    """加载配置文件（JSON 或 YAML）
    
    Args:
        config_path: 配置文件路径
    
    Returns:
        配置字典
    
    Raises:
        ConfigError: 配置文件格式错误或无法解析
        DependencyMissingError: YAML 文件但 pyyaml 未安装
    """
    if not config_path.exists():
        raise ConfigError(f"配置文件不存在: {config_path}")
    
    suffix = config_path.suffix.lower()
    
    if suffix == ".json":
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            raise ConfigError(f"JSON 配置文件格式错误: {e}")
        except OSError as e:
            raise ConfigError(f"读取配置文件失败: {e}")
    
    elif suffix in [".yaml", ".yml"]:
        try:
            import yaml
        except ImportError:
            raise DependencyMissingError(
                f"YAML 配置文件需要 pyyaml，但未安装。请运行: pip install -e \".[yaml]\""
            )
        
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except yaml.YAMLError as e:
            raise ConfigError(f"YAML 配置文件格式错误: {e}")
        except OSError as e:
            raise ConfigError(f"读取配置文件失败: {e}")
    
    else:
        raise ConfigError(f"不支持的配置文件格式: {suffix}（支持 .json, .yaml, .yml）")


def set_nested_value(config: dict[str, Any], key_path: str, value: Any) -> None:
    """使用点号路径设置嵌套字典的值
    
    Args:
        config: 配置字典
        key_path: 点号路径（如 "strategy.auto.enabled"）
        value: 要设置的值
    """
    keys = key_path.split(".")
    current = config
    
    # 遍历到倒数第二层
    for key in keys[:-1]:
        if key not in current:
            current[key] = {}
        elif not isinstance(current[key], dict):
            # 如果中间键不是字典，将其替换为字典
            current[key] = {}
        current = current[key]
    
    # 设置最后一层的值
    last_key = keys[-1]
    
    # 尝试转换值的类型（如果可能）
    if isinstance(value, str):
        # 尝试转换为 bool
        if value.lower() in ("true", "false"):
            value = value.lower() == "true"
        # 尝试转换为 int
        elif value.isdigit() or (value.startswith("-") and value[1:].isdigit()):
            value = int(value)
        # 尝试转换为 float
        else:
            try:
                value = float(value)
            except ValueError:
                pass  # 保持为字符串
    
    current[last_key] = value


def merge_configs(
    defaults: dict[str, Any],
    file_config: Optional[dict[str, Any]] = None,
    set_overrides: Optional[dict[str, str]] = None,
) -> dict[str, Any]:
    """合并配置（优先级：defaults < file_config < set_overrides）
    
    Args:
        defaults: 默认配置
        file_config: 文件配置（可选）
        set_overrides: --set 覆盖（key=value 字典，可选）
    
    Returns:
        合并后的配置字典
    """
    # 深拷贝默认配置
    import copy
    merged = copy.deepcopy(defaults)
    
    # 合并文件配置
    if file_config:
        _deep_merge(merged, file_config)
    
    # 应用 --set 覆盖
    if set_overrides:
        for key_path, value in set_overrides.items():
            set_nested_value(merged, key_path, value)
    
    return merged


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> None:
    """深度合并两个字典（递归）
    
    Args:
        base: 基础字典（会被修改）
        override: 覆盖字典
    """
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            # 递归合并嵌套字典
            _deep_merge(base[key], value)
        else:
            # 直接覆盖
            base[key] = value


def config_to_cli_params(config: dict[str, Any]) -> dict[str, Any]:
    """将配置字典转换为 CLI 参数字典（扁平化）
    
    Args:
        config: 配置字典
    
    Returns:
        CLI 参数字典
    """
    params = {}
    
    # strategy
    strategy_name = config.get("strategy", {}).get("name", DEFAULT_STRATEGY)
    params["strategy"] = strategy_name
    
    # auto_strategy
    auto = config.get("strategy", {}).get("auto", {})
    params["auto_strategy"] = auto.get("enabled", False)
    if isinstance(auto.get("order"), list):
        params["auto_strategy_order"] = ",".join(auto["order"])
    else:
        params["auto_strategy_order"] = auto.get("order", DEFAULT_AUTO_STRATEGY_ORDER)
    params["auto_strategy_min_segments"] = auto.get("min_segments", DEFAULT_AUTO_STRATEGY_MIN_SEGMENTS)
    params["auto_strategy_min_speech_total_sec"] = auto.get("min_speech_total_sec", DEFAULT_AUTO_STRATEGY_MIN_SPEECH_TOTAL_SEC)
    
    # silence
    silence = config.get("silence", {})
    params["silence_threshold_db"] = silence.get("threshold_db", DEFAULT_SILENCE_THRESHOLD_DB)
    params["min_silence_sec"] = silence.get("min_silence_sec", DEFAULT_MIN_SILENCE_SEC)
    
    # energy
    energy = config.get("energy", {})
    params["energy_threshold_rms"] = energy.get("threshold_rms", 0.02)
    params["energy_frame_ms"] = energy.get("frame_ms", 30.0)
    params["energy_hop_ms"] = energy.get("hop_ms", 10.0)
    params["energy_smooth_ms"] = energy.get("smooth_ms", 100.0)
    params["energy_min_speech_sec"] = energy.get("min_speech_sec", 0.20)
    
    # vad
    vad = config.get("vad", {})
    params["vad_aggressiveness"] = vad.get("aggressiveness", DEFAULT_VAD_AGGRESSIVENESS)
    params["vad_frame_ms"] = vad.get("frame_ms", DEFAULT_VAD_FRAME_MS)
    params["vad_sample_rate"] = vad.get("sample_rate", DEFAULT_VAD_SAMPLE_RATE)
    params["vad_min_speech_sec"] = vad.get("min_speech_sec", DEFAULT_VAD_MIN_SPEECH_SEC)
    
    # postprocess
    postprocess = config.get("postprocess", {})
    params["min_seg_sec"] = postprocess.get("min_seg_sec", DEFAULT_MIN_SEG_SEC)
    params["max_seg_sec"] = postprocess.get("max_seg_sec", DEFAULT_MAX_SEG_SEC)
    params["pad_sec"] = postprocess.get("pad_sec", DEFAULT_PAD_SEC)
    
    # exports
    exports = config.get("exports", {})
    params["export_timeline"] = exports.get("timeline", False)
    params["export_csv"] = exports.get("csv", False)
    params["export_mask"] = exports.get("mask", "none")
    params["mask_bin_ms"] = exports.get("mask_bin_ms", 50.0)
    
    # runtime
    runtime = config.get("runtime", {})
    params["jobs"] = runtime.get("jobs", DEFAULT_JOBS)
    params["overwrite"] = runtime.get("overwrite", False)
    params["out_mode"] = runtime.get("out_mode", "in_place")
    
    # validate
    validate = config.get("validate", {})
    params["validate_output"] = validate.get("enabled", False)
    params["validate_strict"] = validate.get("strict", False)
    
    return params


def compute_config_hash(config: dict[str, Any]) -> str:
    """计算配置的稳定哈希值（用于可复现性）
    
    Args:
        config: 配置字典
    
    Returns:
        SHA256 哈希值（十六进制字符串）
    """
    import hashlib
    
    # 使用 sort_keys=True 和紧凑格式确保稳定性
    config_json = json.dumps(config, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    hash_obj = hashlib.sha256(config_json.encode("utf-8"))
    return hash_obj.hexdigest()

