"""
This type stub file was generated by pyright.
"""

import sys
from ctypes import Structure, Union

class BigEndianStructure(Structure):
    ...


class LittleEndianStructure(Structure):
    ...


if sys.version_info >= (3, 11):
    class BigEndianUnion(Union):
        ...


    class LittleEndianUnion(Union):
        ...
