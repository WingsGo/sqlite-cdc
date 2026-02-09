"""
字段转换器 - 支持各种字段值转换
"""

from typing import Any, Callable, Dict, Optional

from sqlite_cdc.models.sync_config import ConverterType

# 转换器函数类型
ConverterFunc = Callable[[Any, Dict[str, Any]], Any]


def _lowercase(value: Any, params: Dict[str, Any]) -> Any:
    """转为小写"""
    if value is None:
        return None
    return str(value).lower()


def _uppercase(value: Any, params: Dict[str, Any]) -> Any:
    """转为大写"""
    if value is None:
        return None
    return str(value).upper()


def _trim(value: Any, params: Dict[str, Any]) -> Any:
    """去除空白"""
    if value is None:
        return None
    return str(value).strip()


def _default(value: Any, params: Dict[str, Any]) -> Any:
    """设置默认值"""
    if value is None or value == "":
        return params.get("value")
    return value


def _typecast(value: Any, params: Dict[str, Any]) -> Any:
    """类型转换"""
    target_type = params.get("target_type", "str")

    if value is None:
        return None

    type_map = {
        "str": str,
        "int": int,
        "float": float,
        "bool": bool,
    }

    if target_type in type_map:
        try:
            return type_map[target_type](value)
        except (ValueError, TypeError):
            return value

    return value


# 转换器注册表
CONVERTER_REGISTRY: Dict[ConverterType, ConverterFunc] = {
    ConverterType.LOWERCASE: _lowercase,
    ConverterType.UPPERCASE: _uppercase,
    ConverterType.TRIM: _trim,
    ConverterType.DEFAULT: _default,
    ConverterType.TYPECAST: _typecast,
}


def convert(value: Any, converter_type: ConverterType, params: Optional[Dict[str, Any]] = None) -> Any:
    """
    执行字段值转换

    参数:
        value: 原始值
        converter_type: 转换器类型
        params: 转换器参数

    返回:
        转换后的值

    示例:
        >>> convert("  HELLO  ", ConverterType.TRIM)
        'HELLO'
        >>> convert("hello", ConverterType.UPPERCASE)
        'HELLO'
        >>> convert(None, ConverterType.DEFAULT, {"value": "default"})
        'default'
    """
    if params is None:
        params = {}

    if converter_type not in CONVERTER_REGISTRY:
        raise ValueError(f"未知的转换器类型: {converter_type}")

    converter_func = CONVERTER_REGISTRY[converter_type]
    return converter_func(value, params)


def get_converter(name: str) -> Optional[ConverterFunc]:
    """
    通过名称获取转换器函数

    参数:
        name: 转换器名称（小写）

    返回:
        转换器函数或 None
    """
    try:
        converter_type = ConverterType(name.lower())
        return CONVERTER_REGISTRY.get(converter_type)
    except ValueError:
        return None
