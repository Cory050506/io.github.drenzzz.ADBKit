#!/usr/bin/env python3
"""Generate flatpak-builder sources (go-sources.json) from a go.sum file.

The sources reproduce Go's module-proxy layout on disk:

    go-proxy/<escaped module>/@v/<escaped version>.{info,mod,zip}

and the manifest points GOPROXY at it with file://, so `go build` runs fully
offline and Go still verifies every module against go.sum. Nothing is vendored
and no modules.txt is needed, so re-running this script is the only step when
dependencies change.

Usage:  python tools/gen_go_sources.py <path/to/go.sum> -o go-sources.json
Needs network (proxy.golang.org) and the Python 3 standard library only.
Windows:  py tools\\gen_go_sources.py go.sum -o go-sources.json
(Use -o rather than ">": PowerShell 5 redirects as UTF-16, which breaks flatpak-builder.)
"""
import hashlib
import json
import re
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

PROXY = "https://proxy.golang.org"
DEST_ROOT = "go-proxy"


def escape(s):
    """Go module-proxy case escaping: uppercase 'A' -> '!a'."""
    return re.sub(r"[A-Z]", lambda m: "!" + m.group(0).lower(), s)


def parse_go_sum(path):
    zips, mods = set(), set()
    for line in open(path, encoding="utf-8"):
        parts = line.split()
        if len(parts) != 3:
            continue
        module, version, _hash = parts
        if version.endswith("/go.mod"):
            mods.add((module, version[: -len("/go.mod")]))
        else:
            zips.add((module, version))
    return zips, mods


def fetch_sha256(url):
    req = urllib.request.Request(url, headers={"User-Agent": "gen_go_sources"})
    h = hashlib.sha256()
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                h = hashlib.sha256()
                while chunk := r.read(1 << 16):
                    h.update(chunk)
            return h.hexdigest()
        except (urllib.error.URLError, TimeoutError):
            if attempt == 2:
                raise
    raise AssertionError("unreachable")


def main():
    import argparse
    ap = argparse.ArgumentParser(description="go.sum -> flatpak-builder sources")
    ap.add_argument("gosum")
    ap.add_argument("-o", "--output", required=True)
    args = ap.parse_args()
    zips, mods = parse_go_sum(args.gosum)
    wanted = []  # (module, version, ext)
    for module, version in sorted(mods | zips):
        wanted.append((module, version, "mod"))  # every go.sum module needs its go.mod
    for module, version in sorted(zips):
        wanted.append((module, version, "zip"))
        wanted.append((module, version, "info"))

    def make(item):
        module, version, ext = item
        em, ev = escape(module), escape(version)
        url = f"{PROXY}/{em}/@v/{ev}.{ext}"
        return {
            "type": "file",
            "url": url,
            "sha256": fetch_sha256(url),
            "dest": f"{DEST_ROOT}/{em}/@v",
        }

    with ThreadPoolExecutor(8) as ex:
        sources = list(ex.map(make, wanted))
    with open(args.output, "w", encoding="utf-8", newline="\n") as f:
        json.dump(sources, f, indent=2)
        f.write("\n")
    print(f"{len(sources)} sources for {len(mods | zips)} modules -> {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
