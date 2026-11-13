import argparse
import fcntl
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from service import API_PORT, APP, ETC, KEY, PROFILE, RUN, runtime_env
from strata_cli.launch.catalog import Catalog
from strata_cli.launch.cmd import apply_defaults
from strata_cli.launch.runner import LaunchError, Runner
from strata_cli.launch.settings import LaunchSettings, parse_context
from strata_control import engine_component


class LocalModelRunner(Runner):
    def ensure_engine(self):
        if self.multi_file() or self.model_shape():
            raise LaunchError("This model needs a separate engine. Choose a model for the bundled Strata CUDA engine.")
        report = engine_component.status(full=True)
        if not report["usable"]:
            raise LaunchError(report.get("notice") or "The bundled CUDA engine is unavailable.")


def configure(args):
    model = Path(args.path).expanduser().resolve(strict=True)
    if not (model.is_dir() or model.is_file() and model.suffix.lower() == ".gguf"):
        raise ValueError("Choose a readable GGUF file or a folder containing all its shards.")
    destination = PROFILE
    if args.profile_id:
        directory = ETC / "profiles"
        directory.mkdir(mode=0o700, exist_ok=True)
        destination = directory / f"{args.profile_id}.json"
        if destination.exists():
            raise ValueError("A profile with this ID already exists.")
    catalog = Catalog(src=APP / "control", root=RUN / "install")
    settings = LaunchSettings(
        name=f"fnos-{args.profile_id}" if args.profile_id else "fnos",
        model_path=str(model), family=args.family, model=args.model,
        data_dir=str(RUN / "data"), context=args.context, parallel=1, vision="off",
        drafting="off", split_engine="off", tune="skip", access="lan", port=API_PORT,
        api_key=KEY.read_text().strip(),
    )
    runner = LocalModelRunner(settings, catalog=catalog, assume_yes=True, emit=lambda event: print(event.text, flush=True))
    runner.check_own_files()
    runner.s, _ = apply_defaults(runner.s, catalog)
    result = runner.run(start=False)
    config = json.loads(Path(result.config).read_text())
    config["api_key"] = settings.api_key
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=ETC, delete=False) as output:
        pending = Path(output.name)
        json.dump(config, output, ensure_ascii=False, indent=2)
        output.write("\n")
    try:
        subprocess.run(
            [str(APP / "control/bin/strata"), "serve", "--profile", str(pending),
             "--host", "0.0.0.0", "--port", str(API_PORT), "--offline", "--plan", "--quiet"],
            env=runtime_env(), cwd=RUN, stdout=subprocess.DEVNULL, check=True,
        )
        pending.replace(destination)
    finally:
        pending.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description="Prepare a local model for Strata on fnOS.")
    parser.add_argument("path", help="absolute path of a GGUF file or shard directory on the NAS")
    parser.add_argument("--family", help="optional Strata catalog family, e.g. qwen")
    parser.add_argument("--model", help="optional Strata catalog variant, e.g. iq3_xxs")
    parser.add_argument("--context", type=parse_context, default=8192, help="context size (default: 8192)")
    parser.add_argument("--profile-id", help="register a model without changing the active profile")
    args = parser.parse_args()
    if bool(args.family) != bool(args.model):
        parser.error("--family and --model must be provided together")
    if args.profile_id and not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", args.profile_id):
        parser.error("--profile-id must contain 1–64 letters, digits, underscores or hyphens")
    try:
        with (RUN / "configure.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            configure(args)
    except (LaunchError, OSError, ValueError, subprocess.CalledProcessError) as error:
        sys.exit(getattr(error, "text", None) or str(error))
    if args.profile_id:
        print("Model registered. Select it on the workstation homepage.")
    else:
        print("Model configured. Restart Strata from fnOS App Center.")


if __name__ == "__main__":
    main()
