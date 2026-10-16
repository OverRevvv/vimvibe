#!/usr/bin/env python3
"""Regenerate the PNG icon sizes (and docs/icon.png) from packaging/icons/vimvibe.svg — run it after editing the SVG:
    python3 packaging/icons/make-icons.py
Needs PySide6 (already a vimvibe dependency)."""
import os, shutil
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

here = os.path.dirname(os.path.abspath(__file__))
app = QGuiApplication([])
svg = QSvgRenderer(os.path.join(here, "vimvibe.svg"))
for size in (16, 24, 32, 48, 64, 128, 256, 512):
    d = os.path.join(here, "hicolor", f"{size}x{size}", "apps")
    os.makedirs(d, exist_ok=True)
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    svg.render(p)
    p.end()
    img.save(os.path.join(d, "vimvibe.png"))
os.makedirs(os.path.join(here, "hicolor", "scalable", "apps"), exist_ok=True)
shutil.copy(os.path.join(here, "vimvibe.svg"), os.path.join(here, "hicolor", "scalable", "apps", "vimvibe.svg"))
shutil.copy(os.path.join(here, "hicolor", "128x128", "apps", "vimvibe.png"), os.path.join(here, "..", "..", "docs", "icon.png"))
print("icons written to", os.path.join(here, "hicolor"))
