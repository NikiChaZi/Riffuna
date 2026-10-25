"""Generate Windows file/product version metadata from pyproject.toml."""
from pathlib import Path
import tomllib


def main():
    root = Path(__file__).resolve().parents[1]
    version = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    parts = tuple(int(value) for value in version.split("."))
    if len(parts) != 3:
        raise ValueError("Expected a three-part release version")
    windows = parts + (0,)
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
