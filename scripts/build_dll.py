#!/usr/bin/env python3
"""
Configure and build SRDBridge.dll with CMake if it is missing.

Usage (from repo root)::

    python scripts/build_dll.py
    python scripts/build_dll.py --force
    python scripts/build_dll.py --config Debug

Also used by ``spatial_reality.bridge.load()`` when the DLL is not found and
``SRD_AUTO_BUILD=1`` (default on Windows).
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def dll_candidates(config: str = "Release") -> list[Path]:
    names = ("SRDBridge.dll", "libSRDBridge.dll", "libSRDBridge.so")
    roots = [
        ROOT / "build" / config,
        ROOT / "build",
        ROOT / "build" / "Debug",
        ROOT / "build" / "Release",
    ]
    out: list[Path] = []
    for root in roots:
        for name in names:
            out.append(root / name)
    # de-dupe preserving order
    seen = set()
    uniq = []
    for p in out:
        s = str(p)
        if s not in seen:
            seen.add(s)
            uniq.append(p)
    return uniq


def find_dll(config: str = "Release") -> Path | None:
    for path in dll_candidates(config):
        if path.is_file():
            return path
    return None


def XR_API_present() -> bool:
    return (ROOT / "XR_API" / "include" / "xr_api_wrapper.h").is_file()


def default_generator() -> list[str]:
    """Prefer VS 2022 on Windows; otherwise let CMake pick."""
    if sys.platform == "win32":
        return ["-G", "Visual Studio 17 2022", "-A", "x64"]
    return []


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd), flush=True)
    try:
        subprocess.run(
            cmd,
            cwd=ROOT,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
    except subprocess.CalledProcessError as e:
        print(e.stdout)
        raise


def build(config: str = "Release", force: bool = False) -> Path:
    existing = find_dll(config)
    if existing is not None and not force:
        print(f"SRDBridge already built: {existing}")
        return existing

    if not XR_API_present():
        raise SystemExit(
            "Sony XR_API not found.\n"
            "Download Native API from:\n"
            "  https://xyn.sony.net/en/developer/setup/spatial-reality-display/download-info\n"
            "Copy the XR_API folder to:\n"
            f"  {ROOT / 'XR_API'}\n"
            "See XR_API/README.md"
        )

    if shutil.which("cmake") is None:
        raise SystemExit("cmake not found on PATH")

    build_dir = ROOT / "build"
    configure = ["cmake", "-B", str(build_dir), *default_generator()]

    try:
        run(configure)
    except subprocess.CalledProcessError:
        raise SystemExit("Failed to configure!")
        # print("CMake configure failed; cleaning build directory and retrying...")
        # shutil.rmtree(build_dir, ignore_errors=True)
        # run(configure)

    try:
        run(["cmake", "--build", str(build_dir), "--config", config])
    except subprocess.CalledProcessError:
        raise SystemExit("Failed to build!")

    built = find_dll(config)
    if built is None:
        raise SystemExit(
            "Build finished but SRDBridge.dll was not found. "
            f"Checked:\n  " + "\n  ".join(str(p) for p in dll_candidates(config))
        )
    print(f"Built: {built}")
    return built


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", default="Release", choices=("Release", "Debug"))
    p.add_argument("--force", action="store_true", help="Rebuild even if DLL exists")
    args = p.parse_args(argv)
    build(config=args.config, force=args.force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
