"""Create the Windows and source distributions from a completed build."""
from hashlib import file_digest
from importlib.metadata import files
from pathlib import Path
from shutil import copy2, copytree
import sys
from zipfile import ZIP_DEFLATED, ZipFile


PROJECT = Path(__file__).resolve().parents[1]
DIST = PROJECT / "dist"
NAME = "PokemonRedSaveEditor"
WINDOWS = DIST / NAME


def package_license(distribution, old_name, new_name):
    path = next(p for p in files(distribution) if p.name == old_name and "licenses" in p.parts)
    copy2(path.locate(), WINDOWS / "docs" / "licenses" / new_name)


def archive(name, folder, paths):
    zip_path = DIST / (name + ".zip")
    with ZipFile(zip_path, "w", compression=ZIP_DEFLATED, compresslevel=6) as release:
        for path in sorted(paths):
            release.write(path, Path(NAME) / path.relative_to(folder))
    with ZipFile(zip_path) as release:
        bad = release.testzip()
        if bad:
            raise RuntimeError(f"CRC verification failed for {bad}")
    return zip_path


def all_files(root):
    return (path for path in root.rglob("*") if path.is_file() and "__pycache__" not in path.parts)


def main():
    if not (WINDOWS / (NAME + ".exe")).is_file():
        raise FileNotFoundError("Build the Windows executable before packaging.")
    for name in ("README.md", "LICENSE"):
        copy2(PROJECT / name, WINDOWS)
    copytree(PROJECT / "docs", WINDOWS / "docs", dirs_exist_ok=True)
    package_license("Pillow", "LICENSE", "Pillow.txt")
    package_license("PyInstaller", "COPYING.txt", "PyInstaller.txt")
    copy2(Path(sys.base_prefix) / "LICENSE.txt", WINDOWS / "docs" / "licenses" / "Python.txt")
    windows = archive(NAME + "_Windows_x64", WINDOWS, all_files(WINDOWS))
    top_level = (".gitignore", "LICENSE", "README.md", "main.py", "build.ps1", NAME + ".spec",
                 "requirements.txt", "requirements-dev.txt")
    source_files = [PROJECT / name for name in top_level]
    for part in ("docs", "editor", "tests", "tools"):
        source_files.extend(all_files(PROJECT / part))
    source = archive(NAME + "_Source", PROJECT, source_files)
    hashes = []
    for path in (windows, source):
        with path.open("rb") as file:
            hashes.append(f"{file_digest(file, 'sha256').hexdigest()}  {path.name}\n")
    (DIST / "SHA256SUMS.txt").write_text("".join(hashes), encoding="ascii")
    print(f"Windows archive: {windows}\nSource archive: {source}")


if __name__ == "__main__":
    main()
