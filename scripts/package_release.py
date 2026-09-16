"""Build the source release ZIP and the incremental RPi5 deployment bundle."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parent.parent
UPDATE = ROOT / "deploy" / "rpi5-update"
CHANGED = (
    "autocar/config.py", "autocar/motor.py", "autocar/autopilot.py",
    "autocar/server.py", "web/app.js", "web/index.html", "web/style.css",
)
GENERATED = {"update.tar.gz", "update.sha256", "manifest.json"}


def source_files(folder: str):
    for path in sorted((ROOT / folder).rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
            yield path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    UPDATE.mkdir(parents=True, exist_ok=True)
    bundle = UPDATE / "update.tar.gz"
    with tarfile.open(bundle, "w:gz") as archive:
        for folder in ("autocar", "web", "tests"):
            for path in source_files(folder):
                archive.add(path, arcname=path.relative_to(ROOT).as_posix())
    (UPDATE / "update.sha256").write_text(
        f"{sha256(bundle)}  {bundle.name}\n", encoding="ascii")
    (UPDATE / "manifest.json").write_text(
        json.dumps({name: sha256(ROOT / name) for name in CHANGED}, indent=2) + "\n",
        encoding="utf-8")

    release = ROOT / "RPI5_AutoCAR-YOLO-integrated.zip"
    included = [ROOT / name for name in (
        "README.md", "requirements.txt", "requirements-autonomy.txt")]
    for folder in ("autocar", "web", "tests", "scripts", "deploy", "docs", "training"):
        included.extend(path for path in source_files(folder)
                        if not (path.parent == UPDATE and path.name in GENERATED))
    with zipfile.ZipFile(release, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in included:
            archive.write(path, path.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(release) as archive:
        assert archive.testzip() is None, "ZIP integrity failure"
        for path in included:
            name = path.relative_to(ROOT).as_posix()
            assert archive.read(name) == path.read_bytes(), f"ZIP mismatch: {name}"
    release.with_suffix(".zip.sha256").write_text(
        f"{sha256(release)}  {release.name}\n", encoding="ascii")
    print(f"Verified {len(included)} files: {release}")
    print(f"Incremental bundle: {bundle}")


if __name__ == "__main__":
    main()
