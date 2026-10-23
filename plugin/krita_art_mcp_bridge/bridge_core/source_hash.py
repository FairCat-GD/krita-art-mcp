import hashlib
from pathlib import Path

# The server holds an equal copy, so probe and doctor can refuse a stale plugin.


def source_hash(package_dir: Path) -> str:
    digest = hashlib.sha256()
    sources = {
        path.relative_to(package_dir).as_posix(): path
        for path in package_dir.rglob("*.py")
        if "__pycache__" not in path.relative_to(package_dir).parts
    }
    for relative in sorted(sources):
        name = relative.encode("utf-8")
        content = sources[relative].read_bytes()
        digest.update(len(name).to_bytes(8, "big") + name)
        digest.update(len(content).to_bytes(8, "big") + content)
    return digest.hexdigest()
