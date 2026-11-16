"""Vendor the pinned official VK Bridge npm package, verifying npm integrity."""
import base64
import hashlib
import io
import json
from pathlib import Path
import tarfile
from urllib.request import urlopen

VERSION = "2.15.0"
ROOT = Path(__file__).resolve().parents[1] / "website" / "static"

def main():
    with urlopen(f"https://registry.npmjs.org/@vkontakte%2Fvk-bridge/{VERSION}", timeout=30) as response:
        metadata = json.load(response)
    dist = metadata["dist"]
    with urlopen(dist["tarball"], timeout=30) as response:
        archive = response.read()
    integrity = "sha512-" + base64.b64encode(hashlib.sha512(archive).digest()).decode()
    if integrity != dist["integrity"]:
        raise ValueError("VK Bridge package integrity mismatch")
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        # Read named members only. No archive paths are extracted onto disk.
        script = tar.extractfile("package/dist/browser.min.js").read()
        license_text = tar.extractfile("package/LICENSE").read()
    (ROOT / f"vk-bridge-{VERSION}.min.js").write_bytes(script)
    (ROOT / "vk-bridge-LICENSE.txt").write_bytes(license_text)
    print(f"VK Bridge {VERSION} vendored and SHA-512 verified ({len(script)} bytes)")

if __name__ == "__main__":
    main()
