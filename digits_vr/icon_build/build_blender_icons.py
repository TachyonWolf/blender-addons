#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Builds `images/blender_icons.png`: the Blender UI icons named in `blender_icons.ICONS`, white on alpha, one CELL-pixel
square each, COLUMNS a row. Not run by Blender: run it by hand after changing that list.

    build_blender_icons.py <Blender source folder>

Needs Inkscape and ImageMagick (`magick`). Reads `release/datafiles/icons_svg/<name>.svg` and checks each icon's tint
against `source/blender/editors/include/UI_icons.hh` (DEF_ICON = text colour, DEF_ICON_OBJECT = object colour,
DEF_ICON_COLOR with a `blender_collection` part = collection colour). The icons are Blender's (GPL-3.0-or-later)."""
import importlib.util
import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ElementTree

HERE = os.path.dirname(os.path.abspath(__file__))
ADDON = os.path.dirname(HERE)
SVG_NAMESPACE = "http://www.w3.org/2000/svg"


def _icons_module():
    """blender_icons.py loaded by path (the package's __init__ needs bpy)."""
    spec = importlib.util.spec_from_file_location("blender_icons", os.path.join(ADDON, "blender_icons.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _blender_kinds(source):
    """{icon name: DEF_ICON macro suffix ("" for plain DEF_ICON)} from Blender's icon list."""
    header = os.path.join(source, "source", "blender", "editors", "include", "UI_icons.hh")
    with open(header, encoding="utf-8") as file:
        return {name: suffix for suffix, name in re.findall(r"^DEF_ICON(\w*)\((\w+)\)", file.read(), re.MULTILINE)}


def _expected_tint(icons, kind, svg_text):
    if kind == "":
        return icons.TEXT
    if kind == "_OBJECT":
        return icons.OBJECT
    if kind == "_COLOR" and 'id="blender_collection"' in svg_text:
        return icons.COLLECTION
    return None


def _square_svg(svg_path, out_path, cell):
    """A copy of the SVG on a square page (the wider side, centred) at `cell` pixels, its theme parts white."""
    ElementTree.register_namespace("", SVG_NAMESPACE)
    tree = ElementTree.parse(svg_path)
    root = tree.getroot()
    left, top, width, height = (float(value) for value in root.get("viewBox").replace(",", " ").split())
    side = max(width, height)
    root.set("viewBox", f"{left - (side - width) / 2} {top - (side - height) / 2} {side} {side}")
    root.set("width", str(cell))
    root.set("height", str(cell))
    for element in root.iter():
        if element.get("id", "").startswith("blender_"):      # parts Blender colours from the theme: white, tinted later
            element.set("fill", "#ffffff")
    tree.write(out_path)


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    source = sys.argv[1]
    icons = _icons_module()
    kinds = _blender_kinds(source)
    problems = []
    with tempfile.TemporaryDirectory() as work:
        cells = []
        for name in icons.NAMES:
            svg_path = os.path.join(source, "release", "datafiles", "icons_svg", name.lower() + ".svg")
            if name not in kinds or not os.path.exists(svg_path):
                problems.append(f"{name}: not in this Blender source")
                continue
            with open(svg_path, encoding="utf-8") as file:
                expected = _expected_tint(icons, kinds[name], file.read())
            if expected != icons.ICONS[name]:
                problems.append(f"{name}: Blender tints it {expected}, blender_icons.ICONS says {icons.ICONS[name]}")
            square, raw, cell = (os.path.join(work, f"{name}.{suffix}") for suffix in ("svg", "raw.png", "png"))
            _square_svg(svg_path, square, icons.CELL)
            subprocess.run(["inkscape", square, "--export-type=png", f"--export-filename={raw}",
                            f"--export-width={icons.CELL}", f"--export-height={icons.CELL}"],
                           check=True, capture_output=True)
            if icons.ICONS[name] == icons.COLLECTION:
                subprocess.run(["magick", raw, cell], check=True)       # colour icon: keep its dark parts
            else:                                                       # one-colour icon: only its shape counts
                subprocess.run(["magick", raw, "-channel", "RGB", "-evaluate", "set", "100%", "+channel", cell], check=True)
            cells.append(cell)
        if problems:
            sys.exit("Not built:\n  " + "\n  ".join(problems))
        width, height = icons.atlas_size()
        subprocess.run(["magick", "montage", *cells, "-background", "none", "-tile", f"{icons.COLUMNS}x",
                        "-geometry", f"{icons.CELL}x{icons.CELL}+0+0", os.path.join(work, "atlas.png")], check=True)
        subprocess.run(["magick", os.path.join(work, "atlas.png"), "-background", "none", "-extent", f"{width}x{height}",
                        "-strip", "-define", "png:color-type=6", icons.ATLAS], check=True)
    print(f"built {icons.ATLAS}: {len(icons.NAMES)} icons, {width} x {height}")


if __name__ == "__main__":
    main()
