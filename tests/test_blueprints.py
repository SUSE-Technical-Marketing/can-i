"""Blueprints must reference charts that exist in this repo at the pinned version."""
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parent.parent
BLUEPRINTS = sorted((ROOT / "catalog" / "blueprints").glob("can-i-openshell-*.yaml"))
CLUSTER_REPO = yaml.safe_load((ROOT / "catalog" / "clusterrepo.yaml").read_text())["metadata"]["name"]
CATALOG = yaml.safe_load((ROOT / "catalog" / "blueprints" / "blueprint-catalog.yaml").read_text())


def chart_version(name: str) -> str:
    return yaml.safe_load((ROOT / "charts" / name / "Chart.yaml").read_text())["version"]


@pytest.mark.parametrize("path", BLUEPRINTS, ids=lambda p: p.name)
def test_components_pin_current_chart_versions(path):
    bp = yaml.safe_load(path.read_text())
    for c in bp["spec"]["components"]:
        assert c["chartRepo"] == CLUSTER_REPO, c["chartName"]
        # publish-charts.sh ships the current Chart.yaml version; older pins 404
        assert c["chartVersion"] == chart_version(c["chartName"]), c["chartName"]


@pytest.mark.parametrize("path", BLUEPRINTS, ids=lambda p: p.name)
def test_blueprint_name_and_version_agree(path):
    bp = yaml.safe_load(path.read_text())
    version = bp["spec"]["version"]
    labels = bp["metadata"]["labels"]
    assert labels["ai-factory.suse.com/blueprint-version"] == version
    assert bp["metadata"]["name"] == f"can-i-openshell-{version.replace('.', '-')}"
    assert path.stem == bp["metadata"]["name"]
    listed = {b["name"] for b in CATALOG["spec"]["blueprints"]}
    assert labels["ai-factory.suse.com/blueprint-name"] in listed
