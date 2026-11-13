"""Run the bundled Strata engine under the workstation's existing app identity."""
import os
from pathlib import Path
import sys


if __name__ == "__main__":
    env = os.environ.copy()
    for name in ("TRIM_PKGVAR", "TRIM_PKGETC"):
        path = Path(env[name]) / "engines" / "strata"
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        env[name] = str(path)
    engine = Path(__file__).resolve().parent / "engines/strata/service.py"
    os.execve(sys.executable, [sys.executable, "-B", str(engine), *sys.argv[1:]], env)
