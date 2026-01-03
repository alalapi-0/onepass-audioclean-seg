"""统一错误类型与退出码规范（R11）"""


class ConfigError(Exception):
    """配置错误：配置文件格式错误、无法解析等 -> exit 2"""
    pass


class ArgError(Exception):
    """参数错误：CLI 参数无效、冲突等 -> exit 2"""
    pass


class DependencyMissingError(Exception):
    """依赖缺失错误：必需依赖未安装（如 pyyaml 缺失但使用了 .yaml 配置）-> exit 2"""
    pass


class InputNotFoundError(Exception):
    """输入文件不存在 -> exit 2"""
    pass


class RuntimeProcessingError(Exception):
    """运行时处理错误：分析失败、生成片段失败等 -> exit 1"""
    pass


class ValidationError(Exception):
    """验证错误：validate 命令发现的问题 -> exit 2"""
    pass

