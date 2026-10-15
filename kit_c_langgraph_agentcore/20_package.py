#!/usr/bin/env python3
"""20_package.py: build the zip that AgentCore Runtime will run. No AWS call.

AgentCore Runtime runs on arm64. With "direct code deployment" you upload a zip
that already contains your code and every dependency built for arm64 Linux; the
runtime does not run pip. This script follows the documented steps:
  https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-code-deploy-python.html  (read 2026-10-07)

  1. uv pip install --python-platform aarch64-manylinux2014 --python-version 3.13
        --target .build/deployment_package --only-binary=:all: -r <requirements>
  2. zip the dependencies at the root of the archive
  3. add agentcore_app.py and the agent/ package at the root

Three things it does that the page does not spell out:

  a. Which versions. For PYTHON_3_13 (the default) the install comes from a lock
     file that pins every package, direct and indirect: requirements-runtime.lock.txt,
     or requirements-runtime-no-otel.lock.txt when ENABLE_OTEL=false. The zip you
     build is then the same set of packages that was built and inspected when the
     kit was written. For PYTHON_3_11 or PYTHON_3_12 there is no lock: uv resolves
     the indirect dependencies on the day you build, the script says NOT PINNED,
     and your zip may differ from the one described in the README.
     `python 20_package.py --relock` rewrites both lock files (needs the network).

  b. Portable start lines. `uv pip install --target` writes console scripts into
     bin/ whose first line names the Python of the machine that ran the install,
     for example #!/Users/<you>/kit/.venv/bin/python3. That path does not exist in
     the runtime, and it carries your user name into the uploaded zip. AWS's own
     packager rewrites such lines to "#!/usr/bin/env python3" (aws/agentcore-cli,
     src/lib/packaging/helpers.ts, rewriteUnixShebangs, commit dd6304e, read
     2026-10-07). This script does the same for every bin/ script that starts
     Python, whatever the path was. The default start command,
     ["opentelemetry-instrument", "agentcore_app.py"], depends on it.
     UNVERIFIED: that this is enough for the runtime to start the command; it
     was not run on AgentCore. Fallback: ENABLE_OTEL=false, which starts
     agentcore_app.py directly and uses nothing in bin/.

  c. No build-machine paths. After the rewrite the whole tree is searched for
     this machine's paths (the kit folder, the build folder, your home folder,
     the virtual environment). If one is found the build stops and names the
     file, and no zip is written. Paths that a package's own publisher left in
     a compiled library (three of them contain /root/.cargo/...) are not this
     machine's and are left alone.

It then checks the documented limits (250 MB zipped, 750 MB unzipped), sets the
file modes the page asks for (644 for files, 755 for directories and
executables) and writes .build/package_manifest.json for 30_deploy.py.

Usage:
    python 20_package.py
    python 20_package.py --dry-run
    python 20_package.py --relock
"""
from __future__ import annotations

import getpass
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import zipfile

import kitlib

MAX_ZIPPED_BYTES = 250 * 1024 * 1024
MAX_UNZIPPED_BYTES = 750 * 1024 * 1024
STAGING = kitlib.BUILD_DIR / "deployment_package"
MANIFEST = kitlib.BUILD_DIR / "package_manifest.json"
SOURCE_FILES = ["agentcore_app.py", "agent/__init__.py", "agent/fr_tools.py", "agent/graph.py",
                "agent/model.py", "agent/fake_model.py"]
ENTRY_FILE = "agentcore_app.py"
PORTABLE_SHEBANG = b"#!/usr/bin/env python3"
LOCKED_PYTHON_RUNTIME = "PYTHON_3_13"
LOCK_FILES = {True: "requirements-runtime.lock.txt", False: "requirements-runtime-no-otel.lock.txt"}


def _shown(path: pathlib.Path) -> str:
    """The path as printed and recorded: relative to the kit folder, never this machine's full path."""
    try:
        return str(path.relative_to(kitlib.KIT_DIR))
    except ValueError:
        return f".build/{path.name}"


def entry_point(enable_otel: bool) -> list[str]:
    # The documented direct-code example passes ['opentelemetry-instrument', 'main.py'] and says
    # to drop the first item when the OpenTelemetry dependency is not included.
    return ["opentelemetry-instrument", ENTRY_FILE] if enable_otel else [ENTRY_FILE]


def runtime_requirements(enable_otel: bool) -> list[str]:
    lines = []
    for raw in (kitlib.KIT_DIR / "requirements-runtime.txt").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        is_otel = line.endswith("# otel")
        line = line.split("#")[0].strip()
        if is_otel and not enable_otel:
            continue
        lines.append(line)
    return lines


def lock_path(cfg: kitlib.Config) -> pathlib.Path | None:
    """The lock file for this configuration, or None when there is none (not Python 3.13)."""
    if cfg.python_runtime != LOCKED_PYTHON_RUNTIME:
        return None
    path = kitlib.KIT_DIR / LOCK_FILES[cfg.enable_otel]
    return path if path.exists() else None


def read_pins(path: pathlib.Path) -> dict[str, str]:
    """{normalised name: version} from a requirements file of name==version lines."""
    pins: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#")[0].strip()
        if not line:
            continue
        name, _, version = line.partition("==")
        if not version:
            raise ValueError(f"{path.name}: not a name==version line: {raw!r}")
        pins[_normal(name)] = version.strip()
    return pins


def _normal(name: str) -> str:
    return name.strip().lower().replace("_", "-").replace(".", "-")


def uv_command(cfg: kitlib.Config, requirements_file: str, locked: bool = False) -> list[str]:
    command = [
        "uv", "pip", "install",
        "--python-platform", "aarch64-manylinux2014",
        "--python-version", cfg.python_version,
        "--target", str(STAGING),
        "--only-binary=:all:",
    ]
    if locked:
        command.append("--no-deps")  # the lock lists everything; nothing else may be resolved
    return command + ["-r", requirements_file]


def relock_command(input_file: str, output_file: str) -> list[str]:
    return ["uv", "pip", "compile", input_file,
            "--python-platform", "aarch64-manylinux2014", "--python-version", "3.13",
            "--only-binary=:all:", "--no-header", "-o", output_file]


def installed_distributions(staging: pathlib.Path) -> dict[str, str]:
    """{normalised name: version} of what is in the staging folder, read from *.dist-info."""
    found: dict[str, str] = {}
    for info in staging.glob("*.dist-info"):
        metadata = info / "METADATA"
        if not metadata.exists():
            continue
        name = version = None
        for line in metadata.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("Name:") and name is None:
                name = line[5:].strip()
            elif line.startswith("Version:") and version is None:
                version = line[8:].strip()
            if name and version:
                break
        if name and version:
            found[_normal(name)] = version
    return found


# --------------------------------------------------------------------------
# start lines and build-machine paths
# --------------------------------------------------------------------------
def rewrite_shebangs(staging: pathlib.Path) -> list[str]:
    """Make every bin/ script that starts Python start it as '#!/usr/bin/env python3'.

    Two forms are written by pip and uv:
      #!/path/to/python                        a plain start line
      #!/bin/sh                                used when the path is long or has a space:
      '''exec' "/path/to/python" "$0" "$@"     the shell re-runs the file with that Python
      ' '''
    Both are replaced by the one portable line. Scripts that do not start Python, and files
    that are not scripts, are left alone. Returns the names of the files that were changed.
    """
    changed: list[str] = []
    bin_dir = staging / "bin"
    if not bin_dir.is_dir():
        return changed
    for path in sorted(bin_dir.iterdir()):
        if not path.is_file() or path.is_symlink():
            continue
        data = path.read_bytes()
        if not data.startswith(b"#!"):
            continue
        first, _, rest = data.partition(b"\n")
        new = None
        if first.strip() == PORTABLE_SHEBANG:
            continue
        if b"python" in first.lower():
            new = PORTABLE_SHEBANG + b"\n" + rest
        elif first.strip() in (b"#!/bin/sh", b"#!/usr/bin/sh") and rest.lstrip().startswith(b"'''exec'"):
            second, _, after_second = rest.partition(b"\n")
            third, _, after_third = after_second.partition(b"\n")
            if b"python" in second.lower() and third.strip() == b"' '''":
                new = PORTABLE_SHEBANG + b"\n" + after_third
        if new is not None:
            path.write_bytes(new)
            changed.append(path.name)
    return changed


def build_machine_markers() -> list[str]:
    """Strings that identify this machine: paths that must not be inside the zip."""
    markers = {str(STAGING), str(kitlib.BUILD_DIR), str(kitlib.KIT_DIR), str(pathlib.Path.home())}
    if sys.prefix != sys.base_prefix:  # a virtual environment
        markers.add(sys.prefix)
    try:
        user = getpass.getuser()
    except Exception:
        user = ""
    if user:
        markers.update({f"/Users/{user}", f"/home/{user}", f"\\Users\\{user}"})
    # A marker such as "/", "/usr" or "/root" would match library files and says nothing
    # about a person, so only paths at least two folders deep are kept.
    return sorted(m for m in markers if m.count("/") + m.count("\\") >= 2)


def find_build_paths(staging: pathlib.Path, markers: list[str], limit: int = 20) -> list[str]:
    """Files under staging that contain one of the markers. Bytecode is skipped: it is not zipped."""
    needles = [m.encode("utf-8") for m in markers if m]
    hits: list[str] = []
    for dirpath, dirnames, filenames in os.walk(staging):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for name in filenames:
            if name.endswith((".pyc", ".pyo")):
                continue
            full = pathlib.Path(dirpath) / name
            try:
                data = full.read_bytes()
            except OSError:
                continue
            for needle in needles:
                if needle in data:
                    hits.append(f"{full.relative_to(staging).as_posix()} contains {needle.decode()!r}")
                    break
            if len(hits) >= limit:
                return hits
    return hits


def check_bin_scripts(staging: pathlib.Path) -> list[str]:
    """Every bin/ script that starts Python must do so with the portable line."""
    problems: list[str] = []
    bin_dir = staging / "bin"
    if not bin_dir.is_dir():
        return problems
    for path in sorted(bin_dir.iterdir()):
        if not path.is_file():
            continue
        head = path.read_bytes()[:400]
        if not head.startswith(b"#!"):
            continue
        first = head.split(b"\n", 1)[0].strip()
        starts_python = b"python" in first.lower() or b"'''exec'" in head
        if starts_python and first != PORTABLE_SHEBANG:
            problems.append(f"bin/{path.name} starts with {first[:80].decode(errors='replace')!r}")
    return problems


def check_zip(zip_path: pathlib.Path, markers: list[str]) -> list[str]:
    """The same two checks, made on the finished zip, so what is uploaded is what was checked."""
    problems: list[str] = []
    needles = [m.encode("utf-8") for m in markers if m]
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            data = zf.read(info)
            if info.filename.startswith("bin/") and data.startswith(b"#!"):
                first = data.split(b"\n", 1)[0].strip()
                if (b"python" in first.lower() or b"'''exec'" in data[:400]) and first != PORTABLE_SHEBANG:
                    problems.append(f"{info.filename} starts with {first[:80].decode(errors='replace')!r}")
            for needle in needles:
                if needle in data:
                    problems.append(f"{info.filename} contains {needle.decode()!r}")
                    break
            if len(problems) >= 20:
                break
    return problems


def _zip_tree(zf: zipfile.ZipFile, root, arc_prefix: str = "") -> tuple[int, int]:
    files = 0
    raw_bytes = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d != "__pycache__")
        for name in sorted(filenames):
            if name.endswith((".pyc", ".pyo")):
                continue
            full = os.path.join(dirpath, name)
            arc = os.path.join(arc_prefix, os.path.relpath(full, root)).replace(os.sep, "/")
            executable = os.access(full, os.X_OK) or arc.startswith("bin/")
            info = zipfile.ZipInfo.from_file(full, arc)
            info.external_attr = ((0o100755 if executable else 0o100644) & 0xFFFF) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            with open(full, "rb") as fh:
                data = fh.read()
            zf.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=6)
            files += 1
            raw_bytes += len(data)
    return files, raw_bytes


def relock(out=print) -> int:
    """Rewrite both lock files from requirements-runtime.txt. Needs uv and the network."""
    if not shutil.which("uv"):
        out("uv is not installed. See https://docs.astral.sh/uv/getting-started/installation/")
        return 1
    work = kitlib.BUILD_DIR / "relock"
    work.mkdir(parents=True, exist_ok=True)
    try:
        for enable_otel, name in LOCK_FILES.items():
            source = work / "requirements-in.txt"
            target = work / name
            source.write_text("\n".join(runtime_requirements(enable_otel)) + "\n", encoding="utf-8")
            # Run inside the work folder with bare file names, so no path of this machine can
            # end up in the "via" comments uv writes.
            proc = subprocess.run(relock_command(source.name, target.name), cwd=work,
                                  capture_output=True, text=True)
            if proc.returncode != 0:
                out(proc.stderr[-3000:])
                out(f"uv could not resolve the set for {name}. The lock files were not changed.")
                return 1
            body = "\n".join(line.replace(f"-r {source.name}", "-r requirements-runtime.txt")
                             for line in target.read_text(encoding="utf-8").splitlines())
            header = (
                f"# Every package in the hosted zip, direct and indirect, pinned. ENABLE_OTEL="
                f"{'true' if enable_otel else 'false'}, {LOCKED_PYTHON_RUNTIME}, arm64 Linux.\n"
                f"# Written {kitlib.utc_now_iso()[:10]} by `python 20_package.py --relock`, which runs:\n"
                f"#   {' '.join(relock_command('<requirements-runtime.txt' + ('' if enable_otel else ', otel lines removed') + '>', name))}\n"
                "# 20_package.py installs exactly this list with --no-deps and then checks that\n"
                "# what was installed is this list. Do not edit by hand.\n")
            (kitlib.KIT_DIR / name).write_text(header + body + "\n", encoding="utf-8")
            out(f"wrote {name}: {len(read_pins(kitlib.KIT_DIR / name))} packages")
    finally:
        shutil.rmtree(work, ignore_errors=True)
        if kitlib.BUILD_DIR.exists() and not any(kitlib.BUILD_DIR.iterdir()):
            kitlib.BUILD_DIR.rmdir()
    return 0


def main(argv: list[str] | None = None, out=print) -> int:
    parser = kitlib.make_parser(__doc__, bills=False)
    parser.add_argument("--relock", action="store_true",
                        help="rewrite the two lock files from requirements-runtime.txt and stop "
                             "(needs the network; builds nothing)")
    args = parser.parse_args(argv)
    cfg = kitlib.Config.from_env()
    if args.relock and not args.dry_run:
        return relock(out)
    reqs = runtime_requirements(cfg.enable_otel)
    lock = lock_path(cfg)
    req_file = kitlib.BUILD_DIR / "requirements-resolved.txt"
    command = uv_command(cfg, str(lock or req_file), locked=lock is not None)

    out(f"Packaging for AgentCore Runtime: {cfg.python_runtime}, arm64, OpenTelemetry "
        f"{'on' if cfg.enable_otel else 'off'}. No AWS call is made by this script.")
    if lock is not None:
        out(f"Versions: PINNED, every package comes from {lock.name}.")
    else:
        out(f"Versions: NOT PINNED. There is no lock file for {cfg.python_runtime}; the indirect "
            "dependencies are resolved today, so this zip may differ from the one in the README.")
    if args.dry_run:
        if args.relock:
            for enable_otel, name in LOCK_FILES.items():
                out("DRY-RUN  would run: " + " ".join(relock_command("<requirements>", name)))
            return 0
        if lock is None:
            out(f"DRY-RUN  would write {_shown(req_file)} with: {', '.join(reqs)}")
        out("DRY-RUN  would run: " + " ".join(command))
        out("DRY-RUN  would rewrite the first line of every bin/ script that starts Python to "
            f"{PORTABLE_SHEBANG.decode()!r}")
        out("DRY-RUN  would search the tree for this machine's paths and stop if one is found")
        out(f"DRY-RUN  would zip the result plus {', '.join(SOURCE_FILES)} into "
            f"{_shown(kitlib.PACKAGE_ZIP)}")
        out(f"DRY-RUN  entry point would be {entry_point(cfg.enable_otel)}")
        return 0

    if not shutil.which("uv"):
        out("uv is not installed. See https://docs.astral.sh/uv/getting-started/installation/")
        return 1
    if kitlib.BUILD_DIR.exists():
        shutil.rmtree(kitlib.BUILD_DIR)
    kitlib.BUILD_DIR.mkdir(parents=True)
    if lock is None:
        req_file.write_text("\n".join(reqs) + "\n", encoding="utf-8")

    out("Running: " + " ".join(command))
    proc = subprocess.run(command, capture_output=True, text=True)
    if proc.returncode != 0:
        out(proc.stdout[-2000:])
        out(proc.stderr[-4000:])
        out("uv could not install the arm64 wheels. Nothing was packaged.")
        return 1

    installed = installed_distributions(STAGING)
    if lock is not None:
        pins = read_pins(lock)
        if installed != pins:
            missing = sorted(set(pins) - set(installed))
            extra = sorted(set(installed) - set(pins))
            other = sorted(n for n in set(pins) & set(installed) if pins[n] != installed[n])
            out(f"PROBLEM: what was installed is not what {lock.name} lists. Missing: {missing}. "
                f"Not in the lock: {extra}. Other version: {other}. Nothing was packaged.")
            return 1

    rewritten = rewrite_shebangs(STAGING)
    out(f"Start lines: {len(rewritten)} script(s) in bin/ now begin {PORTABLE_SHEBANG.decode()!r}")
    markers = build_machine_markers()
    problems = check_bin_scripts(STAGING) + find_build_paths(STAGING, markers)
    if problems:
        out("PROBLEM: the package still names this machine. Nothing was packaged.")
        for problem in problems:
            out(f"  - {problem}")
        return 1

    with zipfile.ZipFile(kitlib.PACKAGE_ZIP, "w") as zf:
        dep_files, dep_bytes = _zip_tree(zf, STAGING)
        src_bytes = 0
        for rel in SOURCE_FILES:
            path = kitlib.KIT_DIR / rel
            info = zipfile.ZipInfo.from_file(path, rel)
            info.external_attr = (0o100644 & 0xFFFF) << 16
            data = path.read_bytes()
            zf.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=6)
            src_bytes += len(data)
    shutil.rmtree(STAGING)

    problems = check_zip(kitlib.PACKAGE_ZIP, markers)
    if problems:
        kitlib.PACKAGE_ZIP.unlink()
        out("PROBLEM: the finished zip names this machine. It was deleted.")
        for problem in problems:
            out(f"  - {problem}")
        return 1

    zipped = kitlib.PACKAGE_ZIP.stat().st_size
    unzipped = dep_bytes + src_bytes
    sha = hashlib.sha256(kitlib.PACKAGE_ZIP.read_bytes()).hexdigest()
    manifest = {
        "zip": _shown(kitlib.PACKAGE_ZIP),
        "sha256": sha,
        "zipped_bytes": zipped,
        "unzipped_bytes": unzipped,
        "files": dep_files + len(SOURCE_FILES),
        "python_runtime": cfg.python_runtime,
        "entry_point": entry_point(cfg.enable_otel),
        "otel": cfg.enable_otel,
        "requirements": reqs,
        "pinned": lock is not None,
        "lock_file": lock.name if lock else None,
        "packages": len(installed),
        "shebangs_rewritten": rewritten,
        "build_path_check": "no path of the build machine found in the zip",
        "built_at": kitlib.utc_now_iso(),
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    out(f"Built {manifest['zip']}: {zipped / 1e6:.1f} MB zipped (limit 250 MB), "
        f"{unzipped / 1e6:.1f} MB unzipped (limit 750 MB), {manifest['files']} files, "
        f"{len(installed)} packages")
    out("Checked: no path of this machine is inside the zip.")
    out(f"Entry point: {manifest['entry_point']}")
    if zipped > MAX_ZIPPED_BYTES or unzipped > MAX_UNZIPPED_BYTES:
        out("PROBLEM: the package is over the documented size limit. Do not deploy it.")
        return 1
    out("Next: python 30_deploy.py --dry-run")
    return 0


if __name__ == "__main__":
    kitlib.script_main(main)
