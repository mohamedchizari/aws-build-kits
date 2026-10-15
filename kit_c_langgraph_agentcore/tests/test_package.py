"""Review finding M3 and minor 18: what goes into the zip.

M3  `uv pip install --target` writes bin/ scripts whose first line names the Python of the
    build machine. That path does not exist in the runtime and it carries the builder's user
    name. 20_package.py rewrites those lines the way AWS's own packager does, then refuses
    to produce a zip that still names the build machine anywhere.
18  The hosted zip's full dependency set is pinned in a lock file.

These run on a small tree built here, shaped like the one uv produces (the real build was
run separately; see README section 8). No network.
"""
from __future__ import annotations

import os
import zipfile

import pytest
from conftest import ROOT, load_script

MAC_PATH = "/Users/someone/code/aws_kits/kit_c_langgraph_agentcore/.venv/bin/python3"
BODY = b"# -*- coding: utf-8 -*-\nimport sys\nfrom opentelemetry.instrumentation.auto_instrumentation import run\nsys.exit(run())\n"


@pytest.fixture()
def script(kit):
    module = load_script("20_package.py")
    module.STAGING = kit.BUILD_DIR / "deployment_package"
    module.MANIFEST = kit.BUILD_DIR / "package_manifest.json"
    return module


@pytest.fixture()
def tree(script):
    """bin/ as uv leaves it on four kinds of build machine, plus files that must not change."""
    staging = script.STAGING
    (staging / "bin").mkdir(parents=True)
    (staging / "pkg").mkdir()
    files = {
        "bin/opentelemetry-instrument": f"#!{MAC_PATH}\n".encode() + BODY,           # macOS venv
        "bin/uvicorn": b"#!/usr/bin/python\n" + BODY,                                 # Linux system Python
        "bin/httpx": b"#!/home/someone/.venv/bin/python3.13\n" + BODY,                # Linux venv
        "bin/jsonpatch": (b"#!/bin/sh\n'''exec' \"/Users/some one/long path/.venv/bin/python\" \"$0\" \"$@\"\n"
                          b"' '''\n" + BODY),                                         # a path with a space
        "bin/normalizer": b"#!/usr/bin/env python3\n" + BODY,                         # already portable
        "bin/a-shell-script": b"#!/bin/bash\necho not python\n",
        "bin/a-binary": b"\x7fELF\x02\x01\x01" + b"\x00" * 32,
        "pkg/__init__.py": b"VALUE = 1\n",
        "pkg/native.so": b"\x7fELF built in /root/project by upstream\n",             # not this machine
    }
    for name, data in files.items():
        (staging / name).write_bytes(data)
    return staging


def first_line(path) -> bytes:
    return path.read_bytes().split(b"\n", 1)[0]


def test_python_start_lines_in_bin_are_made_portable(script, tree):
    assert script.check_bin_scripts(tree)  # before: there is something to fix
    changed = script.rewrite_shebangs(tree)
    assert changed == ["httpx", "jsonpatch", "opentelemetry-instrument", "uvicorn"]
    for name in changed + ["normalizer"]:
        assert first_line(tree / "bin" / name) == b"#!/usr/bin/env python3"
        assert (tree / "bin" / name).read_bytes().endswith(BODY)  # the script itself is untouched
    assert (tree / "bin" / "jsonpatch").read_bytes() == b"#!/usr/bin/env python3\n" + BODY
    assert first_line(tree / "bin" / "a-shell-script") == b"#!/bin/bash"
    assert (tree / "bin" / "a-binary").read_bytes().startswith(b"\x7fELF")
    assert script.check_bin_scripts(tree) == []
    assert script.rewrite_shebangs(tree) == []  # doing it twice changes nothing


def test_the_build_machines_paths_are_found_wherever_they_are(script, tree):
    markers = ["/Users/someone", "/home/someone", "/Users/some one"]
    before = script.find_build_paths(tree, markers)
    assert len(before) == 3 and all(hit.startswith("bin/") for hit in before)
    script.rewrite_shebangs(tree)
    assert script.find_build_paths(tree, markers) == []
    (tree / "pkg" / "direct_url.json").write_text('{"url": "file:///Users/someone/code/wheel"}')
    assert script.find_build_paths(tree, markers) == ["pkg/direct_url.json contains '/Users/someone'"]


def test_markers_name_this_machine_and_nothing_generic(script, kit, monkeypatch):
    monkeypatch.setattr(script.pathlib.Path, "home", classmethod(lambda cls: script.pathlib.Path("/Users/someone")))
    monkeypatch.setattr(script.getpass, "getuser", lambda: "someone")
    markers = script.build_machine_markers()
    assert "/Users/someone" in markers and "/home/someone" in markers
    assert str(kit.KIT_DIR) in markers and str(script.STAGING) in markers
    for generic in ("/", "/usr", "/root", "/home", "/Users", "/opt", ""):
        assert generic not in markers


def test_the_finished_zip_is_checked_too(script, tree, tmp_path):
    def build(path):
        with zipfile.ZipFile(path, "w") as zf:
            script._zip_tree(zf, tree)

    bad = tmp_path / "bad.zip"
    build(bad)  # zipped before the rewrite
    problems = script.check_zip(bad, ["/Users/someone", "/home/someone"])
    assert any(p.startswith("bin/opentelemetry-instrument starts with") for p in problems)
    assert any("bin/uvicorn starts with '#!/usr/bin/python'" in p for p in problems)
    assert any("contains '/home/someone'" in p for p in problems)

    script.rewrite_shebangs(tree)
    good = tmp_path / "good.zip"
    build(good)
    assert script.check_zip(good, ["/Users/someone", "/home/someone", "/Users/some one"]) == []
    with zipfile.ZipFile(good) as zf:
        for info in zf.infolist():
            if info.filename.startswith("bin/"):
                assert (info.external_attr >> 16) & 0o777 == 0o755  # still executable in the zip
        assert zf.read("bin/opentelemetry-instrument").startswith(b"#!/usr/bin/env python3\n")


def _fake_uv(script, kit, monkeypatch, tree, extra_file=None):
    """Replace uv with a function that leaves the tree above in the staging folder.
    main() empties .build before it runs uv, so the tree is put back at that moment."""
    saved = {str(p.relative_to(script.STAGING)): p.read_bytes() for p in script.STAGING.rglob("*") if p.is_file()}
    if extra_file:
        saved[extra_file[0]] = extra_file[1]
    commands = []

    def run(command, capture_output=True, text=True):
        commands.append(command)
        for name, data in saved.items():
            target = script.STAGING / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)

        class Done:
            returncode, stdout, stderr = 0, "", ""
        return Done()

    monkeypatch.setattr(script.shutil, "which", lambda name: "/usr/bin/uv")
    monkeypatch.setattr(script.subprocess, "run", run)
    monkeypatch.setattr(script, "installed_distributions",
                        lambda staging: script.read_pins(script.lock_path(kit.Config.from_env())))
    monkeypatch.setattr(script, "build_machine_markers",
                        lambda: ["/Users/someone", "/home/someone", "/Users/some one"])
    return commands


def test_a_build_that_still_names_the_machine_writes_no_zip(script, kit, tree, monkeypatch):
    """The whole main(). Something outside bin/ carries the builder's path: the build must stop."""
    commands = _fake_uv(script, kit, monkeypatch, tree,
                        extra_file=("pkg/leak.txt", b"built in /Users/someone/code\n"))
    lines: list[str] = []
    assert script.main([], out=lines.append) == 1
    assert commands[0][:3] == ["uv", "pip", "install"] and "--no-deps" in commands[0]
    text = "\n".join(lines)
    assert "PROBLEM: the package still names this machine. Nothing was packaged." in text
    assert "pkg/leak.txt contains '/Users/someone'" in text
    assert not kit.PACKAGE_ZIP.exists() and not script.MANIFEST.exists()


def test_a_clean_build_writes_the_zip_and_records_what_was_checked(script, kit, tree, monkeypatch):
    _fake_uv(script, kit, monkeypatch, tree)
    lines: list[str] = []
    assert script.main([], out=lines.append) == 0, "\n".join(lines)
    import json

    manifest = json.loads(script.MANIFEST.read_text())
    assert manifest["shebangs_rewritten"] == ["httpx", "jsonpatch", "opentelemetry-instrument", "uvicorn"]
    assert manifest["pinned"] is True and manifest["lock_file"] == "requirements-runtime.lock.txt"
    assert manifest["entry_point"] == ["opentelemetry-instrument", "agentcore_app.py"]
    with zipfile.ZipFile(kit.PACKAGE_ZIP) as zf:
        names = set(zf.namelist())
        assert {"agentcore_app.py", "agent/graph.py", "bin/opentelemetry-instrument"} <= names
        for name in names:
            data = zf.read(name)
            assert b"/Users/" not in data and b"/home/someone" not in data
    assert any("Checked: no path of this machine is inside the zip." in line for line in lines)


# ---------------------------------------------------------------- the lock files (minor 18)
@pytest.mark.parametrize("enable_otel, lock_name, packages", [
    (True, "requirements-runtime.lock.txt", 119), (False, "requirements-runtime-no-otel.lock.txt", 50)])
def test_lock_files_pin_everything_and_agree_with_the_short_list(script, enable_otel, lock_name, packages):
    pins = script.read_pins(ROOT / lock_name)
    assert len(pins) == packages
    for line in script.runtime_requirements(enable_otel):
        name, _, version = line.partition("==")
        assert pins[script._normal(name)] == version, f"{lock_name} disagrees with requirements-runtime.txt on {name}"
    text = (ROOT / lock_name).read_text()
    assert "uv pip compile" in text and "aarch64-manylinux2014" in text
    for forbidden in ("/Users/", "/home/", "/tmp/", "/root"):
        assert forbidden not in text
    if not enable_otel:
        assert not any("opentelemetry" in name for name in pins)


def test_the_default_build_installs_from_the_lock_and_other_pythons_say_not_pinned(script, kit, monkeypatch):
    cfg = kit.Config.from_env()
    assert script.lock_path(cfg).name == "requirements-runtime.lock.txt"
    command = script.uv_command(cfg, str(script.lock_path(cfg)), locked=True)
    assert "--no-deps" in command and command[-1].endswith("requirements-runtime.lock.txt")
    assert ["--python-platform", "aarch64-manylinux2014"] == command[3:5] and "--only-binary=:all:" in command

    monkeypatch.setenv("ENABLE_OTEL", "false")
    assert script.lock_path(kit.Config.from_env()).name == "requirements-runtime-no-otel.lock.txt"

    monkeypatch.setenv("PYTHON_RUNTIME", "PYTHON_3_12")
    assert script.lock_path(kit.Config.from_env()) is None
    lines: list[str] = []
    assert script.main(["--dry-run"], out=lines.append) == 0
    text = "\n".join(lines)
    assert "Versions: NOT PINNED" in text and "--no-deps" not in text


def test_installed_set_is_read_from_dist_info(script, tree):
    info = tree / "Some_Package-1.2.3.dist-info"
    info.mkdir()
    (info / "METADATA").write_text("Metadata-Version: 2.1\nName: Some_Package\nVersion: 1.2.3\n")
    assert script.installed_distributions(tree) == {"some-package": "1.2.3"}
    assert os.path.exists(tree / "bin")
