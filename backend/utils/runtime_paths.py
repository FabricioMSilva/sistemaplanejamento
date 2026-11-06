import os
import sys
from pathlib import Path


def resource_root() -> Path:
    bundle_root = getattr(sys, "_MEIPASS", None)
    return Path(bundle_root) if bundle_root else Path(__file__).resolve().parents[2]


def data_root() -> Path:
    configured = os.environ.get("BMA_DATA_DIR", "").strip()
    return Path(configured).resolve() if configured else resource_root()


def uploads_dir() -> Path:
    return data_root() / "backend" / "uploads"