#!/usr/bin/env python3
"""Generate flatpak-builder sources (node-sources.json) from a bun.lock file.

Why this exists: flatpak-node-generator understands npm/yarn/pnpm lockfiles but
not bun's text lockfile. bun.lock already pins the exact version, tarball
location and sha512 of every package, so we can turn it straight into
`type: archive` sources that unpack into frontend/node_modules (no package
manager and no network needed at build time).

Usage:  python tools/gen_node_sources.py <path/to/bun.lock> -o node-sources.json
        [--dest frontend/node_modules]   (relative to the module source root)
Use -o instead of ">" on Windows: PowerShell 5 redirects as UTF-16, which breaks flatpak-builder.
Needs only the Python 3 standard library. Runs fine on Windows.
"""
import base64
import json
import re
import sys

# Only these (os, cpu) combos matter for Flathub: linux + x86_64/aarch64 + glibc.
ARCH_MAP = {"x64": "x86_64", "arm64": "aarch64"}


def load_bun_lock(path):
    text = open(path, encoding="utf-8").read()
    # bun.lock is JSONC: strip trailing commas.
    text = re.sub(r",(\s*[}\]])", r"\1", text)
    return json.loads(text)


def as_list(v):
    if v is None:
        return None
    return v if isinstance(v, list) else [v]


def arches_for(meta):
    """Return (include, only_arches or None)."""
    os_ = as_list(meta.get("os"))
    cpu = as_list(meta.get("cpu"))
    libc = as_list(meta.get("libc"))
    if os_ and "linux" not in os_:
        return False, None
    if libc and "glibc" not in libc:
        return False, None
    if cpu:
        arches = [ARCH_MAP[c] for c in cpu if c in ARCH_MAP]
        if not arches:
            return False, None
        return True, arches
    return True, None


def main():
    import argparse
    ap = argparse.ArgumentParser(description="bun.lock -> flatpak-builder sources")
    ap.add_argument("lockfile")
    ap.add_argument("-o", "--output", required=True)
    ap.add_argument("--dest", default="frontend/node_modules")
    args = ap.parse_args()
    lock = load_bun_lock(args.lockfile)
    dest_root = args.dest
    sources, skipped = [], []
    for key, entry in sorted(lock["packages"].items()):
        ident, registry, meta, integrity = (entry + [None] * 4)[:4]
        if not isinstance(meta, dict):
            sys.exit(f"error: unexpected lock entry shape for {key}: {entry!r}")
        name, _, version = ident.rpartition("@")
        if not name or not re.fullmatch(r"[0-9][^\s]*", version) or registry:
            skipped.append((key, ident, "non-registry package"))
            continue
        include, only = arches_for(meta)
        if not include:
            continue
        if not integrity or not integrity.startswith("sha512-"):
            sys.exit(f"error: {key} has no sha512 integrity ({integrity!r})")
        sha512 = base64.b64decode(integrity[len("sha512-"):]).hex()
        base = name.split("/")[-1]
        src = {
            "type": "archive",
            "url": f"https://registry.npmjs.org/{name}/-/{base}-{version}.tgz",
            "sha512": sha512,
            "strip-components": 1,
            "dest": f"{dest_root}/{nested(key)}",
        }
        if only:
            src["only-arches"] = only
        sources.append(src)
    if skipped:
        for s in skipped:
            print("warning: skipped", s, file=sys.stderr)
    with open(args.output, "w", encoding="utf-8", newline="\n") as f:
        json.dump(sources, f, indent=2)
        f.write("\n")
    print(f"{len(sources)} sources -> {args.output}", file=sys.stderr)


def nested(key):
    """bun key -> relative node_modules path (nested installs get node_modules/ inserted)."""
    parts, pkgs, i = key.split("/"), [], 0
    while i < len(parts):
        if parts[i].startswith("@") and i + 1 < len(parts):
            pkgs.append(parts[i] + "/" + parts[i + 1])
            i += 2
        else:
            pkgs.append(parts[i])
            i += 1
    return "/node_modules/".join(pkgs)


if __name__ == "__main__":
    main()
