# SPDX-License-Identifier: GPL-3.0-or-later
"""Imports the add-on's own layout and draw modules under plain python3 (no Blender): the Blender-only modules (bpy, blf,
gpu, gpu_extras, mathutils) are stand-ins, and the add-on folder is a package whose __init__ never runs (it registers
Blender classes). Only for the UI export: the add-on never loads this folder."""
import importlib
import importlib.abc
import importlib.machinery
import os
import sys
import types
from unittest import mock

ADDON = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKAGE = "digits_vr_export"
BLENDER_ONLY = ("bpy", "bpy_extras", "blf", "gpu", "gpu_extras", "mathutils", "bmesh", "aud", "idprop", "bl_math")


def stand_in(name):
    module = mock.MagicMock(name=name)
    module.__name__, module.__path__ = name, []
    return module


class _StandIns(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Any Blender-only module (and its submodules) imports as a stand-in, unless one is already in sys.modules."""

    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in BLENDER_ONLY:
            return importlib.machinery.ModuleSpec(fullname, self)
        return None

    def create_module(self, spec):
        return stand_in(spec.name)

    def exec_module(self, module):
        pass


def load(name):
    """`digits_vr.<name>` imported from the add-on folder (the Blender modules stand in)."""
    if not any(isinstance(finder, _StandIns) for finder in sys.meta_path):
        sys.meta_path.insert(0, _StandIns())
    if PACKAGE not in sys.modules:
        package = types.ModuleType(PACKAGE)
        package.__path__ = [ADDON]
        sys.modules[PACKAGE] = package
    return importlib.import_module(PACKAGE + "." + name)
