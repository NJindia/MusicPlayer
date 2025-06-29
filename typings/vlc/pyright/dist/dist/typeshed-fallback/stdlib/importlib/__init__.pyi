"""
This type stub file was generated by pyright.
"""

import sys
import types
from abc import ABCMeta
from importlib.machinery import ModuleSpec

if sys.version_info >= (3, 10):
    class Loader(metaclass=ABCMeta):
        def load_module(self, fullname: str) -> types.ModuleType:
            ...

        def create_module(self, spec: ModuleSpec) -> types.ModuleType | None:
            ...

        def exec_module(self, module: types.ModuleType) -> None:
            ...
