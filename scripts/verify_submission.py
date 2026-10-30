"""Build, run offline, and verify the exact stage-one package contents."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.validate_outputs import validate_directory


EVIDENCE = ROOT / "output/submission_validation"
IMAGE = "chameleon-submission:stage1"
TEST_IMAGE = "chameleon-submission:tests"


def runtime_hashes():
    paths = [ROOT / name for name in ("Dockerfile", "requirements.txt", "constraints.txt",
                                      "chameleon_design_schema_v0.9.json")]
    for directory in ("engine", "renderer", "brand_kit", "input", "tests", "scripts"):
        paths.extend(p for p in (ROOT / directory).rglob("*") if p.is_file()
                     and "__pycache__" not in p.parts and p.name != ".DS_Store")
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(paths)}


def run(command, log_name):
    print(f"Running {log_name} ...", flush=True)
    start = time.monotonic()
    with (EVIDENCE / log_name).open("w") as log:
        result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    elapsed = round(time.monotonic() - start, 2)
    if result.returncode:
        raise RuntimeError(f"{log_name} failed (exit {result.returncode}); inspect {EVIDENCE / log_name}")
    print(f"Passed {log_name} ({elapsed}s)", flush=True)
    return elapsed


def main():
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    record = dict(passed=False, checked_at=datetime.now(timezone.utc).isoformat(),
                  platform="linux/amd64", runtime_network="none", source_sha256=runtime_hashes())
    try:
        run(["docker", "build", "--platform", "linux/amd64", "-t", IMAGE, "."], "build.log")
        info = json.loads(subprocess.check_output(["docker", "image", "inspect", IMAGE], cwd=ROOT))[0]
        record["image_id"] = info["Id"]
        if info["Architecture"] != "amd64" or info["Os"] != "linux":
            raise RuntimeError("The built image is not Linux/AMD64")
        run(["docker", "run", "--rm", "--platform", "linux/amd64", "--network", "none",
             "-v", f"{ROOT / 'input'}:/app/input:ro", "-v", f"{EVIDENCE}:/app/output", IMAGE], "run.log")
        validation = validate_directory(ROOT / "input", EVIDENCE)
        (EVIDENCE / "validation.json").write_text(json.dumps(validation, indent=2) + "\n")
        if not validation["passed"]:
            raise RuntimeError("Output validation failed; inspect validation.json")
        record["validated_inputs"] = len(validation["cases"])
        run(["docker", "build", "--platform", "linux/amd64", "-f", "scripts/Dockerfile.test",
             "-t", TEST_IMAGE, "."], "test-build.log")
        run(["docker", "run", "--rm", "--platform", "linux/amd64", "--network", "none", TEST_IMAGE], "tests.log")
        count = re.search(r"Ran (\d+) tests?", (EVIDENCE / "tests.log").read_text())
        if not count or int(count[1]) == 0:
            raise RuntimeError("No regression tests ran")
        record["tests_passed"] = int(count[1])
        if record["source_sha256"] != runtime_hashes():
            raise RuntimeError("Source files changed during validation; run verification again")
        record["passed"] = True
        print(f"Submission validation passed: {record['tests_passed']} tests, {record['validated_inputs']} inputs.", flush=True)
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        record["error"] = str(error)
        print(f"FAILED: {error}", file=sys.stderr)
    (EVIDENCE / "environment.json").write_text(json.dumps(record, indent=2) + "\n")
    return 0 if record["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
