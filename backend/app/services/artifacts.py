"""Integrity metadata and safe path checks for scientific artifacts.

Manifests live alongside result JSON so deployments using the existing
SQLite schema need no destructive migration.
"""
from __future__ import annotations

import hashlib
import mimetypes
from pathlib import Path


def artifact_manifest(*, data: bytes, path: Path, root: Path, artifact_id: str,
                      artifact_type: str, source_run_id: str | int,
                      parent_data_ids: list[str], tool_id: str, tool_version: str,
                      parameters: dict, source_type: str, validation_status: str,
                      review_status: str, content_type: str | None = None) -> dict:
    """Return a JSON-safe manifest with a root-relative path, never an absolute path."""
    resolved_root = root.resolve()
    resolved_path = path.resolve()
    if resolved_root not in resolved_path.parents:
        raise ValueError("Artifact path must be contained by its configured root")
    rel = resolved_path.relative_to(resolved_root).as_posix()
    digest = hashlib.sha256(data).hexdigest()
    return {
        "artifact_id": str(artifact_id), "artifact_type": artifact_type,
        "sha256": digest, "content_type": content_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream",
        "size_bytes": len(data), "path": rel, "source_run_id": str(source_run_id),
        "parent_data_ids": list(dict.fromkeys(str(value) for value in parent_data_ids)),
        "tool_id": tool_id, "tool_version": tool_version, "parameters": parameters,
        "source_type": source_type, "validation_status": validation_status,
        "review_status": review_status,
    }


def read_contained_file(*, path: Path, root: Path) -> bytes:
    """Read a regular file under root without following symlink components."""
    resolved_root = root.resolve()
    candidate = path if path.is_absolute() else root / path
    # Check every existing component before resolving: resolving first would
    # hide a symlink that points back into the trusted directory.
    lexical = candidate.absolute()
    try:
        relative = lexical.relative_to(root.absolute())
    except ValueError as exc:
        raise ValueError("Artifact path escapes configured root") from exc
    if ".." in relative.parts:
        raise ValueError("Artifact path escapes configured root")
    cursor = root.absolute()
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ValueError("Artifact paths may not contain symlinks")
    try:
        resolved = lexical.resolve(strict=True)
    except OSError as exc:
        raise ValueError("Artifact path does not resolve to an existing file") from exc
    if resolved_root not in resolved.parents or not resolved.is_file():
        raise ValueError("Artifact is not a regular file under configured root")
    return resolved.read_bytes()


def read_verified_artifact(*, path: Path, root: Path, manifest: dict) -> bytes:
    """Read only regular files under root; reject symlinks, traversal, and hash/size drift."""
    resolved_root = root.resolve()
    candidate = path if path.is_absolute() else root / path
    data = read_contained_file(path=candidate,root=root)
    resolved = candidate.resolve(strict=True)
    if resolved_root not in resolved.parents or not resolved.is_file():
        raise ValueError("Artifact is not a regular file under configured root")
    manifest_path = Path(str(manifest.get("path", "")))
    if manifest_path.is_absolute() or ".." in manifest_path.parts or manifest_path.as_posix() != resolved.relative_to(resolved_root).as_posix():
        raise ValueError("Artifact manifest path does not match the stored file")
    digest = manifest.get("sha256")
    if (not isinstance(manifest.get("size_bytes"), int) or not isinstance(digest, str) or len(digest) != 64
            or len(data) != manifest.get("size_bytes") or hashlib.sha256(data).hexdigest() != digest):
        raise ValueError("Artifact integrity check failed")
    return data
