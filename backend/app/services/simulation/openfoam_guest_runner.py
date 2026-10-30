"""Guest-side template parameterization. Invoked only with server-validated SI values."""
import json
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path


def replace_once(path: Path, pattern: str, replacement: str) -> None:
    text = path.read_text()
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.M)
    if count != 1:
        raise RuntimeError(f"Expected exactly one template parameter in {path.name}: {pattern}")
    path.write_text(updated)


cfg = json.loads(Path(sys.argv[1]).read_text())
case = Path(cfg["case_dir"])
template = Path("/opt/openfoam14/tutorials/incompressibleFluid/simpleRushtonMRF")
if case.exists():
    shutil.rmtree(case)
shutil.copytree(template, case, ignore=shutil.ignore_patterns("polyMesh", "postProcessing", "processor*", "log.*", "*.foam"))
D, H, d, rpm, nu = (float(cfg[k]) for k in ("tank_diameter_m", "tank_height_m", "impeller_diameter_m", "rpm", "nu_m2_s"))
if not all(math.isfinite(x) and x > 0 for x in (D, H, d, rpm, nu)):
    raise RuntimeError("Non-positive or non-finite input")
replace_once(case / "system/blockMeshDict.orig", r"^D\s+[^;]+;", f"D       {D:.12g};")
replace_once(case / "system/blockMeshDict.orig", r"^H\s+[^;]+;", f"H       {H:.12g};")
replace_once(case / "system/blockMeshDict.orig", r"^r\s+#calc[^;]+;", f"r       {d / 2:.12g};")
zc = H / 2
replace_once(case / "system/createZonesDict.orig", r"origin\s+\(0 0 [^)]+\);", f"origin      (0 0 {zc:.12g});")
replace_once(case / "system/createZonesDict.orig", r"radius\s+0\.1125;", f"radius      {d * .375:.12g};")
zones_path = case / "system/createZonesDict.orig"
zones_text = zones_path.read_text()
zones_text, count1 = re.subn(r"point1\s+\(0 0 [^)]+\);", f"point1      (0 0 {zc - d * .2:.12g});", zones_text)
zones_text, count2 = re.subn(r"point2\s+\(0 0 [^)]+\);", f"point2      (0 0 {zc + d * .2:.12g});", zones_text)
if count1 != 2 or count2 != 2:
    raise RuntimeError("Rushton rotating zone template shape changed; refusing to run")
zones_path.write_text(zones_text)
zones_text = zones_path.read_text()
zones_text, radius_count = re.subn(r"radius\s+0\.2;", f"radius      {D * .2:.12g};", zones_text)
if radius_count != 2:
    raise RuntimeError("Rushton zone radius template changed; refusing to run")
zones_path.write_text(zones_text)
replace_once(case / "constant/rotatingZoneProperties", r"^omega\s+[^;]+;", f"omega     {rpm:.12g} [rpm];")
replace_once(case / "constant/physicalProperties", r"^nu\s+[^;]+;", f"nu {nu:.12g};")
impeller_scale = d / .3
for filename, sx, sy, sz, z_origin in (("stirrer4.obj", impeller_scale, impeller_scale, impeller_scale, zc - .6 * impeller_scale), ("stirrer6.obj", impeller_scale, impeller_scale, impeller_scale, zc - .6 * impeller_scale), ("baffles.obj", D, D, H / 1.2, 0.0)):
    geometry = case / "constant/geometry" / filename
    transformed = []
    for line in geometry.read_text().splitlines():
        match = re.match(r"^(v\s+)([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)$", line)
        if match:
            x, y, z = map(float, match.groups()[1:])
            z = (z + z_origin) * sz if filename == "baffles.obj" else z_origin + z * sz
            line = f"v {x * sx:.12g} {y * sy:.12g} {z:.12g}"
        transformed.append(line)
    geometry.write_text("\n".join(transformed) + "\n")
if "--stage-only" in sys.argv[2:]:
    print(f"LAB_RAG_CASE_STAGED={case}")
    raise SystemExit(0)
cmd = ["./Allrun", "-i", str(int(cfg["blade_count"])), "-s", "1"]
result = subprocess.run(cmd, cwd=case, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=1700)
print(result.stdout[-30000:])
if result.returncode:
    raise SystemExit(result.returncode)
print(f"LAB_RAG_CASE={case}")
