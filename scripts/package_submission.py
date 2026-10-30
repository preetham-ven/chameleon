"""Package current, verified files without Git history, environments, or caches."""

import hashlib
import json
from pathlib import Path
import sys
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.verify_submission import EVIDENCE, runtime_hashes


def main():
    evidence = json.loads((EVIDENCE / "environment.json").read_text())
    if not evidence.get("passed") or evidence.get("source_sha256") != runtime_hashes():
        raise SystemExit("Run python scripts/verify_submission.py successfully on the current source before packaging.")
    required = ["Dockerfile", ".dockerignore", ".gitignore", "README.md", "SUBMISSION.md",
                "RULES.md", "FAQ.md", "requirements.txt", "requirements-dev.txt", "constraints.txt",
                "chameleon_design_schema_v0.9.json"]
    files = {name: ROOT / name for name in required}
    for directory in ("engine", "renderer", "brand_kit", "input", "tests", "scripts"):
        for path in sorted((ROOT / directory).rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts and path.name != ".DS_Store":
                if path.is_symlink():
                    raise SystemExit(f"Refusing to package a symbolic link: {path}")
                files[path.relative_to(ROOT).as_posix()] = path
    for path in EVIDENCE.iterdir():
        if path.is_file() and (path.suffix in (".json", ".log") or path.name.endswith("_output.png")):
            files[f"examples/{path.name}"] = path
    for path in files.values():
        if not path.is_file():
            raise SystemExit(f"Required submission file missing: {path}")

    destination = ROOT / "dist/chameleon-stage1.zip"
    destination.parent.mkdir(exist_ok=True)
    manifest = {}
    with ZipFile(destination, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for name, path in sorted(files.items()):
            data = path.read_bytes()
            manifest[name] = hashlib.sha256(data).hexdigest()
            info = ZipInfo(f"chameleon/{name}", date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
        archive.writestr("chameleon/output/.gitkeep", "")
        archive.writestr("chameleon/MANIFEST.sha256.json", json.dumps(manifest, indent=2) + "\n")
    checksum = hashlib.sha256(destination.read_bytes()).hexdigest()
    destination.with_suffix(".zip.sha256").write_text(f"{checksum}  {destination.name}\n")
    print(f"Archive: {destination}")
    print(f"Files: {len(files)}, size: {destination.stat().st_size:,} bytes")
    print(f"SHA-256: {checksum}")


if __name__ == "__main__":
    main()
