"""Generate Windows file/product version metadata from pyproject.toml."""
from pathlib import Path
import tomllib
import re


def main():
    root = Path(__file__).resolve().parents[1]
    version = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:\.dev(\d+))?", version)
    if not match:
        raise ValueError("Expected x.y.z or x.y.z.devN")
    windows = tuple(int(value or 0) for value in match.groups())
    fields = {"FileDescription": "Riffuna music player", "FileVersion": version,
              "InternalName": "Riffuna", "OriginalFilename": "Riffuna.exe",
              "ProductName": "Riffuna", "ProductVersion": version}
    strings = ",\n".join(f"StringStruct({key!r}, {value!r})" for key, value in fields.items())
    source = f"""VSVersionInfo(ffi=FixedFileInfo(filevers={windows!r}, prodvers={windows!r},
mask=0x3f, flags=0, OS=0x40004, fileType=1, subtype=0, date=(0, 0)),
kids=[StringFileInfo([StringTable('040904B0', [{strings}])]),
VarFileInfo([VarStruct('Translation', [1033, 1200])])])
"""
    target = root / "build" / "version-info.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source, encoding="utf-8")
    print(target)


if __name__ == "__main__":
    main()
