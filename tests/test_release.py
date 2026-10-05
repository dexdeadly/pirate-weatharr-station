"""plugin.json stays in sync with plugin.py; release zip folder matches the registry key."""
import json
import re

from conftest import REPO


def test_manifest_matches_code(plugin_env):
    manifest = json.loads((REPO / "plugin.json").read_text())
    module = plugin_env.module
    assert manifest["fields"] == module._build_fields()
    assert manifest["actions"] == module.Plugin.actions
    assert manifest["version"] == module.Plugin.version


def test_release_zip_folder_matches_registry_slug():
    # Dispatcharr only lets a plugin-browser update overwrite the install whose
    # key equals the sanitized registry slug; the zip's top folder sets the key.
    workflow = (REPO / ".github/workflows/create_release_zip.yaml").read_text()
    folder = re.search(r"PLUGIN_DIR=(\S+)", workflow).group(1)
    slug = "pirate-weatharr-station"
    assert folder == re.sub(r"[^a-z0-9_]", "_", slug.replace("-", "_").lower())
