"""Render charts/can-i with helm: image dropdown, generated OpenShell policy."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from cani.policy import policy_to_checks

CHART = Path(__file__).parent.parent / "charts" / "can-i"

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")


def render(tmp_path, **values) -> list[dict]:
    vals = tmp_path / "values.yaml"
    vals.write_text(json.dumps(values))
    out = subprocess.run(
        ["helm", "template", "demo", str(CHART), "-f", str(vals)],
        check=True, capture_output=True, text=True,
    ).stdout
    return [d for d in yaml.safe_load_all(out) if d]


def kind(docs, k):
    return next(d for d in docs if d["kind"] == k)


def env(docs) -> dict[str, str]:
    container = kind(docs, "Deployment")["spec"]["template"]["spec"]["containers"][0]
    return {e["name"]: e["value"] for e in container["env"]}


@pytest.mark.parametrize("choice,image", [
    ("suse", "ghcr.io/suse-technical-marketing/can-i:latest"),
    ("opensuse", "ghcr.io/suse-technical-marketing/can-i-opensuse:latest"),
    ("nvidia", "ghcr.io/suse-technical-marketing/can-i-nvidia:latest"),
])
def test_image_dropdown_picks_sandbox_image(tmp_path, choice, image):
    assert env(render(tmp_path, sandbox={"image": choice}))["SANDBOX_IMAGE"] == image


def test_custom_image_requires_a_reference(tmp_path):
    docs = render(tmp_path, sandbox={"image": "custom", "customImage": "reg.example/can-i:dev"})
    assert env(docs)["SANDBOX_IMAGE"] == "reg.example/can-i:dev"
    with pytest.raises(subprocess.CalledProcessError) as exc:
        render(tmp_path, sandbox={"image": "custom"})
    assert "customImage is required" in exc.value.stderr


def test_policy_is_a_valid_openshell_policy(tmp_path):
    docs = render(tmp_path, policy={"egress": "suse.com:443, opensuse.org", "extraReadWrite": "/data"})
    text = kind(docs, "ConfigMap")["data"]["policy.yaml"]
    policy = yaml.safe_load(text)
    assert "/data" in policy["filesystem_policy"]["read_write"]
    assert "/opt" in policy["filesystem_policy"]["read_only"]  # venv in the opensuse/nvidia images
    assert policy["process"]["run_as_user"] == "10001"
    endpoints = policy["network_policies"]["can-i-egress"]["endpoints"]
    assert endpoints == [{"host": "suse.com", "port": 443}, {"host": "opensuse.org", "port": 443}]
    policy_to_checks(text)  # can-i's own policy reader accepts it


def test_blank_egress_denies_all_network(tmp_path):
    policy = yaml.safe_load(kind(render(tmp_path, policy={"egress": ""}), "ConfigMap")["data"]["policy.yaml"])
    assert "network_policies" not in policy


def test_policy_or_image_change_restarts_the_client(tmp_path):
    def annotations(**values):
        return kind(render(tmp_path, **values), "Deployment")["spec"]["template"]["metadata"]["annotations"]

    base = annotations()
    assert annotations(sandbox={"image": "nvidia"})["checksum/image"] != base["checksum/image"]
    assert annotations(policy={"egress": "opensuse.org:443"})["checksum/policy"] != base["checksum/policy"]


def policy_of(tmp_path, **policy):
    docs = render(tmp_path, policy=policy)
    return yaml.safe_load(kind(docs, "ConfigMap")["data"]["policy.yaml"])


def hosts(policy, rule):
    return [e["host"] for e in policy["network_policies"][rule]["endpoints"]]


def test_locked_down_profile_denies_all_network(tmp_path):
    assert "network_policies" not in policy_of(tmp_path, profile="locked-down")


def test_profile_overrides_the_egress_field_but_custom_keeps_it(tmp_path):
    assert hosts(policy_of(tmp_path, profile="suse-only", egress="example.com"), "can-i-egress") == ["suse.com"]
    assert hosts(policy_of(tmp_path, profile="custom", egress="example.com"), "can-i-egress") == ["example.com"]


def test_agent_installer_gives_python_its_own_rule(tmp_path):
    policy = policy_of(tmp_path, profile="agent-installer")
    assert hosts(policy, "can-i-egress") == ["suse.com", "opensuse.org", "one.one.one.one"]
    assert hosts(policy, "can-i-python3") == ["pypi.org", "files.pythonhosted.org"]
    assert all(b["path"].startswith(("/usr/bin/python3", "/opt/")) for b in policy["network_policies"]["can-i-python3"]["binaries"])


def test_grants_widen_any_profile(tmp_path):
    policy = policy_of(tmp_path, profile="locked-down", grants={"nmap": True, "varTmp": True, "agentTools": True})
    assert hosts(policy, "can-i-nmap") == ["suse.com"]
    assert "can-i-egress" not in policy["network_policies"]
    assert "/var/tmp" in policy["filesystem_policy"]["read_write"]
    assert "/srv/can-i-tools" in policy["filesystem_policy"]["read_only"]


def test_suse_pypi_grant_uses_the_index_host(tmp_path):
    docs = render(tmp_path, policy={"profile": "locked-down", "grants": {"susePypi": True}},
                  checks={"susePypiUrl": "https://pypi.example.suse.com/simple/pip/"})
    policy = yaml.safe_load(kind(docs, "ConfigMap")["data"]["policy.yaml"])
    assert hosts(policy, "can-i-python3") == ["pypi.example.suse.com"]


def test_extra_yaml_rules_are_added_last(tmp_path):
    extra = "my-rule:\n  name: my-rule\n  endpoints:\n    - {host: foo.bar, port: 443}\n  binaries:\n    - {path: /usr/bin/curl}\n"
    policy = policy_of(tmp_path, profile="suse-only", extraYaml=extra)
    assert hosts(policy, "my-rule") == ["foo.bar"] and hosts(policy, "can-i-egress") == ["suse.com"]
    policy_to_checks(yaml.safe_dump(policy))  # can-i's own policy reader accepts it


def test_suse_pypi_grant_without_a_url_is_skipped_not_fatal(tmp_path):
    policy = policy_of(tmp_path, profile="locked-down", grants={"susePypi": True, "pypi": True})
    assert hosts(policy, "can-i-python3") == ["pypi.org", "files.pythonhosted.org"]
    policy = policy_of(tmp_path, profile="locked-down", grants={"susePypi": True})
    assert "network_policies" not in policy


def test_every_grant_ticked_renders(tmp_path):
    grants = yaml.safe_load((CHART / "policy-grants.yaml").read_text())
    docs = render(tmp_path, policy={"profile": "custom", "grants": {k: True for k in grants}})
    policy_to_checks(kind(docs, "ConfigMap")["data"]["policy.yaml"])


@pytest.mark.parametrize("bad", [{"profile": "nope"}, {"grants": {"bogus": True}}, {"extraYaml": "a: ["}])
def test_bad_policy_input_fails_the_render(tmp_path, bad):
    with pytest.raises(subprocess.CalledProcessError):
        render(tmp_path, policy=bad)


def test_every_policy_profile_renders_a_policy_can_i_reads(tmp_path):
    profiles = yaml.safe_load((CHART / "policy-profiles.yaml").read_text())
    for name in profiles:
        text = kind(render(tmp_path, policy={"profile": name}), "ConfigMap")["data"]["policy.yaml"]
        policy_to_checks(text)
