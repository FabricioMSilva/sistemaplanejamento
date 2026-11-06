import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, copy_metadata

root = Path(SPECPATH).parents[1]
metadata = []
for package in ("fastapi", "uvicorn", "pandas", "openpyxl", "xlrd", "python-multipart", "selenium", "reportlab"):
    metadata += copy_metadata(package, recursive=True)

analysis = Analysis(
    [str(root / "distribution/windows/launcher.py")],
    pathex=[str(root / "backend"), str(root / "distribution/windows")],
    binaries=[],
    datas=[
        (str(root / "database/catalogos/especialidades.json"), "database/catalogos"),
        (str(root / "database/catalogos/turnos-2026.json"), "database/catalogos"),
        (str(root / "database/catalogos/regras_rondas.json"), "database/catalogos"),
        (str(root / "database/data/funcionario.json"), "database/data"),
        (str(root / "backend/assets"), "backend/assets"),
        *metadata,
    ],
    hiddenimports=["main", *collect_submodules("uvicorn"), *collect_submodules("selenium.webdriver.firefox")],
    hookspath=[],
    runtime_hooks=[],
    excludes=["pytest", "IPython", "matplotlib", "tkinter"],
    noarchive=False,
)
archive = PYZ(analysis.pure)
executable = EXE(
    archive, analysis.scripts, [], exclude_binaries=True, name="PlanningScheduling",
    console=False, debug=False, strip=False, upx=False,
    uac_admin=False, uac_uiaccess=False,
    icon=os.environ["BMA_BUILD_ICON"],
)
collection = COLLECT(executable, analysis.binaries, analysis.datas, strip=False, upx=False, name="PlanningScheduling")