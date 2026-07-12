"""Адаптеры инструментов — единственная сменная деталь панели.

Весь остальной код от выбора инструмента не зависит: воркер вызывает submit()
на шаге 3 и parse_callback() при вебхуке. Меняется только модуль здесь.
"""
from __future__ import annotations

from importlib import import_module

from .base import Adapter

_REGISTRY = {
    "stub": ".stub",
    # v1: реальные адаптеры подключаются по мере готовности —
    # "trendy": ".trendy", "heygen": ".heygen", ...
}


def get_adapter(tool: str) -> Adapter:
    mod_path = _REGISTRY.get(tool)
    if not mod_path:
        raise ValueError(f"Нет адаптера для инструмента {tool!r}. Есть: {list(_REGISTRY)}")
    mod = import_module(mod_path, package=__name__)
    return mod.ADAPTER
