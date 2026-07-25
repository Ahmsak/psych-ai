"""Artifact-correctness tests: experiment manifests are valid JSON.

The capture experiments write manifest.json per run. A truncated or
malformed manifest silently corrupts results, so we validate that every
manifest present parses as JSON and has the expected structure. If no
experiments exist yet, the test skips (never fabricates a pass).
"""

from __future__ import annotations

import glob
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _manifests():
    return glob.glob(os.path.join(ROOT, "experiments", "*", "manifest.json"))


def test_all_manifests_are_valid_json():
    import pytest
    manifests = _manifests()
    if not manifests:
        pytest.skip("no experiment manifests present")
    for path in manifests:
        assert os.path.getsize(path) > 0, f"empty manifest: {path}"
        with open(path, encoding="utf-8") as f:
            data = json.load(f)  # raises on malformed JSON
        assert "mode" in data, f"manifest missing 'mode': {path}"


def test_dual_manifests_have_both_stream_keys():
    import pytest
    dual = [p for p in _manifests() if "_dual" in p]
    if not dual:
        pytest.skip("no dual experiment manifests present")
    for path in dual:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        assert "mic" in data and "loopback" in data, path
        for stream in ("mic", "loopback"):
            assert "audio_captured" in data[stream], f"{path}:{stream}"
