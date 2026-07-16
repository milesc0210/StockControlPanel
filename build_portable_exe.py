from __future__ import annotations

import shutil
from pathlib import Path

from PyInstaller.__main__ import run as pyinstaller_run

PROJECT_ROOT = Path(__file__).resolve().parent
RELEASE_ROOT = PROJECT_ROOT / "Release" / "PortableEXE"
DIST_ROOT = RELEASE_ROOT / "dist"
WORK_ROOT = RELEASE_ROOT / "build"
SPEC_ROOT = RELEASE_ROOT / "spec"
APP_NAME = "StockControlPanel"

DATA_ENTRIES = [
    (PROJECT_ROOT / "app.py", "."),
    (PROJECT_ROOT / "README.md", "."),
    (PROJECT_ROOT / "requirements.txt", "."),
    (PROJECT_ROOT / ".env.example", "."),
    (PROJECT_ROOT / "scripts", "scripts"),
    (PROJECT_ROOT / "static", "static"),
    (PROJECT_ROOT / "templates", "templates"),
    (PROJECT_ROOT / "data", "data"),
]


def clean() -> None:
    if RELEASE_ROOT.exists():
        shutil.rmtree(RELEASE_ROOT)
    DIST_ROOT.mkdir(parents=True, exist_ok=True)
    WORK_ROOT.mkdir(parents=True, exist_ok=True)
    SPEC_ROOT.mkdir(parents=True, exist_ok=True)


def build_args() -> list[str]:
    args = [
        str(PROJECT_ROOT / "stock_control_panel_boot.py"),
        "--noconfirm",
        "--clean",
        "--onedir",
        "--windowed",
        f"--name={APP_NAME}",
        f"--distpath={DIST_ROOT}",
        f"--workpath={WORK_ROOT}",
        f"--specpath={SPEC_ROOT}",
    ]
    for source, destination in DATA_ENTRIES:
        args.append(f"--add-data={source}{';'}{destination}")
    return args


def post_build() -> Path:
    bundle_root = DIST_ROOT / APP_NAME
    (bundle_root / "logs").mkdir(exist_ok=True)
    return bundle_root


def main() -> int:
    clean()
    pyinstaller_run(build_args())
    bundle_root = post_build()
    print(bundle_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
