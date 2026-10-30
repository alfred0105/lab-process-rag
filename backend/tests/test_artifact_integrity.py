import pytest

from app.services.artifacts import artifact_manifest, read_verified_artifact


def _manifest(tmp_path, data=b"measured bytes"):
    root = tmp_path / "artifacts"
    root.mkdir()
    path = root / "input.xy"
    path.write_bytes(data)
    return root, path, artifact_manifest(
        data=data, path=path, root=root, artifact_id="run:original",
        artifact_type="measurement_original", source_run_id="run",
        parent_data_ids=["experiment:1"], tool_id="xrd.local_peaks.v1",
        tool_version="1", parameters={"xrd_x_unit": "2theta_deg"},
        source_type="LAB_RESULT", validation_status="INPUT_ACCEPTED",
        review_status="PENDING",
    )


def test_manifest_tracks_hash_size_mime_lineage_and_review(tmp_path):
    root, path, manifest = _manifest(tmp_path)
    assert manifest["sha256"]
    assert manifest["size_bytes"] == len(path.read_bytes())
    assert manifest["content_type"]
    assert manifest["path"] == "input.xy"
    assert manifest["parent_data_ids"] == ["experiment:1"]
    assert read_verified_artifact(path=path, root=root, manifest=manifest) == path.read_bytes()


def test_integrity_rejects_changed_bytes_and_symlink(tmp_path):
    root, path, manifest = _manifest(tmp_path)
    path.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="integrity"):
        read_verified_artifact(path=path, root=root, manifest=manifest)
    outside = tmp_path / "outside.xy"
    outside.write_bytes(b"measured bytes")
    path.unlink()
    path.symlink_to(outside)
    with pytest.raises(ValueError, match="symlinks"):
        read_verified_artifact(path=path, root=root, manifest=manifest)


def test_integrity_rejects_path_traversal(tmp_path):
    root, _path, manifest = _manifest(tmp_path)
    with pytest.raises(ValueError, match="escapes"):
        read_verified_artifact(path=root / ".." / "outside", root=root, manifest=manifest)
