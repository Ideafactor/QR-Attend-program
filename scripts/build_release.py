"""Build versioned artifacts and a portable offline-transfer bundle (deps need internet)."""

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = json.loads((ROOT / "js/attendance-client/package.json").read_text())["version"]
OUT = ROOT / "dist" / f"attendance-{VERSION}"
OUT.mkdir(parents=True, exist_ok=True)


def run(*args):
    subprocess.run(args, cwd=ROOT, check=True)


run("npm", "run", "build")
for package in ("attendance_core", "attendance_fastapi", "attendance_sqlalchemy"):
    run(sys.executable, "-m", "build", "--no-isolation", "--outdir", str(OUT), f"python/{package}")
for package in ("attendance-client", "attendance-react-mobile", "attendance-react-scanner"):
    run("npm", "pack", "--workspace", f"@attendance/{package}", "--pack-destination", str(OUT))
shutil.copy(ROOT / "docs/install.md", OUT / "INSTALL.md")
shutil.copy(ROOT / "examples/standalone.py", OUT / "app.py")
artifacts = sorted(
    p for p in OUT.iterdir()
    if p.suffix in (".whl", ".gz", ".tgz") or p.name in ("app.py", "INSTALL.md")
)
(OUT / "SHA256SUMS").write_text(
    "".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n" for p in artifacts)
)
with tarfile.open(ROOT / "dist" / f"attendance-{VERSION}-bundle.tar.gz", "w:gz") as archive:
    for artifact in [*artifacts, OUT / "SHA256SUMS"]:
        archive.add(artifact, arcname=f"{OUT.name}/{artifact.name}")
print(f"Release bundle: dist/attendance-{VERSION}-bundle.tar.gz")
