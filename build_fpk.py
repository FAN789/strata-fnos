"""Build the Strata-only workstation FPK from the pinned Strata distribution."""
import argparse
import ast
import hashlib
import io
from pathlib import Path, PurePosixPath
import tarfile
import tempfile

from strata_search_default import patch_server
from strata_web_zh import patch_web


ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parents[1]
PACKAGE = ROOT / "package"
STRATA = ROOT / "upstream-integration"
if not STRATA.is_dir():
    STRATA = WORKSPACE / "302-strata/fnos-fpk"

CONTROL_SHA256 = "73fb612848cf00fa1072623029b35405bbbb63e3f4c688fe6f38c78e3fc022ac"
ENGINE_SHA256 = "42ab04fa3201e41bef5fac28c05f5c35c909419ec937d879b505bf1516742610"
LLAMA_COMMIT = "3cf03257f219afbe7334045ff7c6a06ac68c627d"
LLAMA_SHA256 = "c076d7534afa0e5d0ec2a0d425b11e791c16f3de0d727221aea071cef156a280"
ENGINE_DIR = "components/engine/0.1.59-linux-x86_64-cuda13"


def add_bytes(archive, name, data, mode=0o644):
    item = tarfile.TarInfo(name)
    item.size = len(data)
    item.mode = mode
    archive.addfile(item, io.BytesIO(data))


def workstation_launcher(path):
    source = path.read_text(encoding="utf-8")
    first = source.index("def supervise():")
    last = source.index("def start():", first)
    if source.count("API_PORT = 18082") != 1:
        raise ValueError(f"Unexpected engine launcher format: {path}")
    source = source[:first] + '''def supervise():
    sys.path.insert(0, str(APP.parents[1]))
    from strata_setup import supervise_workstation
    supervise_workstation(sys.modules[__name__])


''' + source[last:]
    return source.replace("API_PORT = 18082", "API_PORT = 18180").encode()


def require_sha256(path, expected):
    with path.open("rb") as stream:
        actual = hashlib.file_digest(stream, "sha256").hexdigest()
    if actual != expected:
        raise ValueError(f"SHA-256 mismatch for {path}: {actual}")


def patch_import(source, old, new):
    if source.count(old) != 1:
        raise ValueError("Unexpected Strata GGUF preparation source")
    updated = source.replace(old, new)
    ast.parse(updated)
    return updated


def add_gguf_python(bundle, source):
    prefix = f"llama.cpp-{LLAMA_COMMIT}/gguf-py/"
    with tarfile.open(source, "r|gz") as archive:
        for member in archive:
            if not member.isfile() or not member.name.startswith(prefix):
                continue
            name = member.name.removeprefix(prefix)
            if name == "LICENSE" or (name.startswith("gguf/") and ".." not in PurePosixPath(name).parts):
                add_bytes(bundle, f"engines/strata/control/gguf-py/{name}", archive.extractfile(member).read())


def add_upstream(bundle, source, folder):
    with tarfile.open(source, "r|gz") as archive:
        for member in archive:
            name = member.name.removeprefix("./")
            if not name or name == ".":
                continue
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError(f"Unexpected archive path in {source}: {name}")
            if folder == "control" and name.split("/")[:2] == ["data", "experimental-speed-projection"]:
                continue
            target = f"engines/strata/{folder}/{name}"
            if folder == "control" and name in {
                "serve/web/index.html", "serve/web/monitor.html", "serve/web/app.js",
                "serve/web/monitor.js", "serve/web/locales/zh.json",
            }:
                add_bytes(bundle, target, patch_web(name.removeprefix("serve/web/"), archive.extractfile(member).read()))
                continue
            if folder == "control" and name == "serve/server.py":
                code = archive.extractfile(member).read().decode()
                add_bytes(bundle, target, patch_server(code).encode())
                continue
            if folder == "control" and name == "setup.py":
                code = archive.extractfile(member).read().decode()
                old = '    gguf_py = (env or {}).get("STRATA_GGUF_PY")\n'
                new = old + '''    bundled_gguf = ROOT / "gguf-py"
    if gguf_py and (bundled_gguf / "gguf" / "__init__.py").is_file():
        env = dict(env, STRATA_GGUF_PY=str(bundled_gguf))
        gguf_py = str(bundled_gguf)
'''
                add_bytes(bundle, target, patch_import(code, old, new).encode())
                continue
            if folder == "control" and name == "tools/iq_pack.py":
                code = archive.extractfile(member).read().decode()
                old = '    ap.add_argument("--compat-bf16", action="store_true",\n'
                new = old + '                    default=os.environ.get("STRATA_FNOS_COMPAT_BF16") == "1",\n'
                add_bytes(bundle, target, patch_import(code, old, new).encode())
                continue
            member.name = target
            if member.islnk():
                member.linkname = f"engines/strata/{folder}/{member.linkname.removeprefix('./')}"
            bundle.addfile(member, archive.extractfile(member) if member.isfile() else None)


def build(control, engine, search_runtime, llama_source):
    require_sha256(control, CONTROL_SHA256)
    require_sha256(engine, ENGINE_SHA256)
    require_sha256(llama_source, LLAMA_SHA256)
    manifest = (PACKAGE / "manifest").read_text(encoding="utf-8")
    version = next(line.partition("=")[2].strip() for line in manifest.splitlines() if line.startswith("version "))
    output = ROOT / f"strata-fnos-{version}.fpk"
    with tempfile.TemporaryDirectory(dir=ROOT) as work:
        app = Path(work) / "app.tgz"
        with tarfile.open(app, "w:gz", compresslevel=2) as bundle:
            app_source = PACKAGE / "app"
            add_bytes(bundle, "strata_workstation.py", (app_source / "strata_workstation.py").read_bytes())
            add_bytes(bundle, "strata_setup.py", (app_source / "strata_setup.py").read_bytes())
            add_bytes(bundle, "strata-setup.html", (app_source / "strata-setup.html").read_bytes())
            add_bytes(bundle, "strata_settings.py", (app_source / "strata_settings.py").read_bytes())
            add_bytes(bundle, "strata-wizard.json", (PACKAGE / "wizard/config").read_bytes())
            add_bytes(bundle, "configure", (app_source / "configure").read_bytes(), mode=0o755)
            add_bytes(bundle, "public-search/search.py", (STRATA / "public_search.py").read_bytes())
            with tarfile.open(search_runtime) as runtime:
                for member in runtime:
                    if not member.name.startswith("python/") or not member.isfile():
                        continue
                    data = runtime.extractfile(member).read()
                    add_bytes(bundle, "public-search/vendor/" + member.name.removeprefix("python/"), data)
            for folder in ("ui", "licenses"):
                for path in sorted((app_source / folder).rglob("*")):
                    if path.is_file():
                        add_bytes(bundle, path.relative_to(app_source).as_posix(), path.read_bytes())
            integration = STRATA / "package/app"
            launcher = integration / "service.py"
            add_bytes(bundle, "engines/strata/service.py", workstation_launcher(launcher))
            add_bytes(bundle, "engines/strata/configure_env.py", (integration / "configure_env.py").read_bytes())
            code = (integration / "configure_model.py").read_text(encoding="utf-8")
            code = patch_import(code, "import json\n", "import json\nimport os\n")
            old = '''    model = Path(args.path).expanduser().resolve(strict=True)
    if not (model.is_dir() or model.is_file() and model.suffix.lower() == ".gguf"):
        raise ValueError("Choose a readable GGUF file or a folder containing all its shards.")
'''
            new = '''    model = Path(args.path).expanduser().resolve(strict=True) if args.path else None
    if model and not (model.is_dir() or model.is_file() and model.suffix.lower() == ".gguf"):
        raise ValueError("Choose a readable GGUF file or a folder containing all its shards.")
'''
            code = patch_import(code, old, new)
            code = patch_import(code, "model_path=str(model),", "model_path=str(model) if model else None,")
            code = patch_import(code, '    settings = LaunchSettings(\n', '''    model_data = RUN / "data"
    if args.profile_id and os.environ.get("STRATA_FNOS_PROGRESS") == "1":
        model_data = RUN / "library" / args.profile_id
    settings = LaunchSettings(
''')
            code = patch_import(code, 'data_dir=str(RUN / "data"),', 'data_dir=str(model_data),')
            code = patch_import(code, 'emit=lambda event: print(event.text, flush=True)', '''emit=show_progress''')
            code = patch_import(code, "def configure(args):", '''def show_progress(event):
    if os.environ.get("STRATA_FNOS_PROGRESS") == "1":
        print(json.dumps({"stage": event.stage, "text": event.text, "percent": event.pct,
                          "step": event.data.get("step")}), flush=True)
    else:
        print(event.text, flush=True)


def configure(args):''')
            code = patch_import(code, '    config["api_key"] = settings.api_key\n', '''    config["api_key"] = settings.api_key
    if args.profile_id:
        config["_fnos_model"] = args.profile_id
        config["_fnos_source"] = ("local" if model else os.environ.get("STRATA_SOURCE", "huggingface"))
''')
            code = patch_import(code, 'parser.add_argument("path", help=', 'parser.add_argument("path", nargs="?", help=')
            old = "    args = parser.parse_args()\n"
            new = '''    parser.add_argument("--compat-bf16", action="store_true",
                        help="convert non-native projection tensors when the GGUF requires it")
    parser.add_argument("--download", action="store_true", help="download a named model from the Strata catalog")
    args = parser.parse_args()
    if args.download and (args.path or not args.family or not args.model):
        parser.error("--download requires --family and --model and cannot be combined with a local path")
    if not args.download and not args.path:
        parser.error("choose a local path or --download")
    os.environ["STRATA_FNOS_COMPAT_BF16"] = "1" if args.compat_bf16 else "0"
'''
            add_bytes(bundle, "engines/strata/configure_model.py", patch_import(code, old, new).encode())
            add_upstream(bundle, control, "control")
            add_gguf_python(bundle, llama_source)
            add_upstream(bundle, engine, ENGINE_DIR)
        staged = Path(work) / output.name
        # app.tgz is already compressed. Recompressing it offers little gain.
        with tarfile.open(staged, "w:gz", compresslevel=1) as fpk:
            fpk.add(app, arcname="app.tgz")
            for path in sorted(PACKAGE.iterdir()):
                if path.name in ("app", "wizard"):
                    continue
                fpk.add(path, arcname=path.name, filter=set_mode)
            wizard = tarfile.TarInfo("wizard")
            wizard.type, wizard.mode = tarfile.DIRTYPE, 0o755
            fpk.addfile(wizard)
            config = tarfile.TarInfo("wizard/config")
            config.type, config.mode = tarfile.SYMTYPE, 0o777
            config.linkname = "../etc/strata-wizard.json"
            fpk.addfile(config)
        staged.replace(output)
    print(output)


def set_mode(item):
    item.mode = 0o755 if item.isdir() or item.name.startswith("cmd/") else 0o644
    return item


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--control", required=True, type=Path, help="Official Strata Control archive")
    parser.add_argument("--engine", required=True, type=Path, help="Official Strata CUDA 13 engine archive")
    parser.add_argument("--search-runtime", required=True, type=Path, help="Archive containing the Python MCP tool dependencies")
    parser.add_argument("--llama-source", required=True, type=Path, help="Pinned llama.cpp source archive containing gguf-py")
    args = parser.parse_args()
    build(args.control, args.engine, args.search_runtime, args.llama_source)
