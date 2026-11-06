import argparse
import importlib.metadata
import json
from pathlib import Path
import shutil
import sys

from PIL import Image, ImageDraw


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("build", type=Path)
    parser.add_argument("payload", type=Path)
    arguments = parser.parse_args()
    brand = Image.open(arguments.root / "backend/assets/IconNFE.png").convert("RGBA")
    icon = Image.new("RGBA", (256, 256), "#ffffff")
    brand.thumbnail((248, 248))
    icon.alpha_composite(brand, ((256 - brand.width) // 2, (256 - brand.height) // 2))
    icon.save(arguments.build / "planning.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (256, 256)])
    wizard = Image.new("RGB", (164, 314), "#003b80")
    wizard_brand = Image.open(arguments.root / "frontend/public/assets/brand/planning-nfe-logo.png").convert("RGBA")
    wizard_brand.thumbnail((144, 110))
    wizard.paste(wizard_brand, ((164 - wizard_brand.width) // 2, 65), wizard_brand)
    ImageDraw.Draw(wizard).rectangle((16, 225, 148, 232), fill="#ffdd00")
    wizard.save(arguments.build / "wizard.bmp")
    small = Image.new("RGB", (55, 55), "#003b80")
    small_brand = wizard_brand.copy()
    small_brand.thumbnail((51, 45))
    small.paste(small_brand, ((55 - small_brand.width) // 2, (55 - small_brand.height) // 2), small_brand)
    small.save(arguments.build / "wizard-small.bmp")
    licenses = arguments.payload / "licenses" / "python"
    licenses.mkdir(parents=True, exist_ok=True)
    versions = {}
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata["Name"]
        if name.lower().startswith(("pyinstaller", "pip", "setuptools", "altgraph", "pefile", "pywin32-ctypes", "packaging")):
            continue
        versions[name] = distribution.version
        for file in distribution.files or []:
            if ".dist-info/" in str(file).replace("\\", "/") and any(
                word in file.name.lower() for word in ("license", "copying", "notice", "authors")
            ):
                target = licenses / name / file.name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(distribution.locate_file(file), target)
    for candidate in (Path(sys.base_prefix) / "LICENSE.txt", Path(sys.base_prefix) / "LICENSE"):
        if candidate.is_file():
            shutil.copy2(candidate, licenses / "PYTHON-LICENSE.txt")
            break
    (arguments.payload / "python-dependencies.json").write_text(json.dumps(versions, indent=2), encoding="utf-8")
    frontend = arguments.build / "frontend-source"
    lock_path = frontend / "package-lock.json"
    if lock_path.is_file():
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        node_versions = {}
        for relative, metadata in lock.get("packages", {}).items():
            if not relative or metadata.get("dev"):
                continue
            node_versions[relative] = metadata.get("version")
            source = frontend / relative
            if not source.is_dir():
                continue
            for candidate in source.iterdir():
                if candidate.is_file() and any(word in candidate.name.lower() for word in ("license", "copying", "notice")):
                    target = arguments.payload / "licenses" / "npm" / relative / candidate.name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(candidate, target)
        (arguments.payload / "frontend-dependencies.json").write_text(json.dumps(node_versions, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()