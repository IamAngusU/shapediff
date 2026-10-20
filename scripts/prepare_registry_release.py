"""Verify a canonical release tag and download its exact checked distributions."""
from pathlib import Path
import hashlib
import os
import re
import subprocess
import tarfile
import tomllib
import urllib.request
import zipfile

tag = os.environ["RELEASE_TAG"]
if not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+(?:(?:a|b|rc)[0-9]+)?", tag):
    raise SystemExit("Select an existing canonical version tag.")
with open("pyproject.toml", "rb") as stream:
    project = tomllib.load(stream)["project"]
if project["name"] != "shapediff" or tag != "v" + project["version"]:
    raise SystemExit("Tag must match the canonical project metadata.")
version = project["version"]
commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
refs = subprocess.check_output([
    "git", "ls-remote", "https://github.com/IamAngusU/shapediff.git",
    "refs/tags/" + tag, "refs/tags/" + tag + "^{}"
], text=True, timeout=30).splitlines()
if not refs or commit != refs[-1].split()[0]:
    raise SystemExit("Checkout does not match the canonical release tag.")

def download(name):
    url = f"https://github.com/IamAngusU/shapediff/releases/download/{tag}/{name}"
    with urllib.request.urlopen(url, timeout=60) as response:
        data = response.read(10 * 1024 * 1024 + 1)
    if len(data) > 10 * 1024 * 1024:
        raise ValueError("Unexpected release asset size.")
    return data

checksums = {}
for line in download("SHA256SUMS.txt").decode("utf-8").splitlines():
    sha, name = line.split("  ", 1)
    if name in checksums or not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise ValueError("Invalid release checksum index.")
    checksums[name] = sha
destination = Path("dist")
destination.mkdir(exist_ok=False)
names = [f"shapediff-{version}-py3-none-any.whl", f"shapediff-{version}.tar.gz"]
for name in names:
    data = download(name)
    if hashlib.sha256(data).hexdigest() != checksums.get(name):
        raise ValueError("Release checksum mismatch: " + name)
    (destination / name).write_bytes(data)
source = Path("shapediff.py").read_bytes()
with zipfile.ZipFile(destination / names[0]) as archive:
    if archive.read("shapediff.py") != source:
        raise ValueError("Wheel code differs from the selected source tag.")
with tarfile.open(destination / names[1], "r:gz") as archive:
    member = archive.extractfile(f"shapediff-{version}/shapediff.py")
    if member is None or member.read() != source:
        raise ValueError("Source distribution code differs from the selected tag.")
print("Verified canonical source:", commit)
print("Verified exact GitHub release wheel and sdist:", *names)
