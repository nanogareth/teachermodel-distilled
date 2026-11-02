"""claudekit.py: the Claude buttons' deployment files, generated from standards/chains.yaml (decision 0029)."""

import json

import pytest
import yaml

from teachermodel import claudekit, cli, interventions
from teachermodel.standards import ROOT

KIT = ROOT / "deploy" / "claude" / "kit"


@pytest.fixture(scope="module")
def files():
    return claudekit.build()


def front(text):
    return yaml.safe_load(text.split("---\n")[1])


def test_the_committed_kit_is_what_the_chains_generate(files):
    """A change to standards/chains.yaml must ship with `teachermodel claude-kit --out deploy/claude/kit`."""
    on_disk = {p.relative_to(KIT).as_posix(): p.read_text(encoding="utf-8") for p in KIT.rglob("*") if p.is_file()}
    assert on_disk == files


def test_an_acting_agent_reads_freely_and_asks_before_every_write(files):
    doc = interventions.chains_doc()
    for b in (b for b in doc["buttons"] if b["kind"] == "act"):
        agent = front(files[f"agents/{b['id']}.md"])
        assert agent["model"] == "claude-opus-5-5"
        for toolset in agent["tools"]:
            assert toolset["default_config"] == {"enabled": False, "permission_policy": {"type": "always_ask"}}
            policy = {c["name"]: c["permission_policy"]["type"] for c in toolset["configs"]}
            server = toolset["mcp_server_name"]
            assert {t for t, p in policy.items() if p == "always_ask"} == set(b["writes"].get(server, []))
            assert {t for t, p in policy.items() if p == "always_allow"} == set(b["reads"].get(server, []))
        assert "auto" not in files[f"agents/{b['id']}.md"].split("---")[1]  # never the server's own evaluation


def test_a_drafting_request_reads_only_and_sends_a_schema_the_api_accepts(files):
    doc = interventions.chains_doc()
    for b in (b for b in doc["buttons"] if b["kind"] == "draft"):
        req = json.loads(files[f"drafting/{b['id']}.json"])
        body = req["body"]
        text = json.dumps(body["output_config"]["format"]["schema"])
        assert not [k for k in claudekit.UNSUPPORTED if f'"{k}"' in text]
        assert '"type": [' not in text  # type lists become anyOf
        assert body["model"] == "claude-opus-5-5" and body["output_config"]["effort"] == b["effort"]
        assert body["fallbacks"] == "default" and "server-side-fallback-2026-07-01" in req["anthropic-beta"]
        for toolset in body.get("tools", []):
            enabled = set(toolset["configs"])
            assert toolset["default_config"] == {"enabled": False}
            assert enabled == set(b["reads"][toolset["mcp_server_name"]])
        if b["reads"]:
            assert "mcp-client-2026-09-15" in req["anthropic-beta"]
            assert all(s["authorization_token"] == f"{{{{token:{s['name']}}}}}" for s in body["mcp_servers"])
        assert body["system"][0]["cache_control"] == {"type": "ephemeral"}


def test_every_prompt_carries_the_rules_and_ids_only(files):
    never = interventions.chains_doc()["never"]
    prompts = [t for p, t in files.items() if p.startswith("prompts/")]
    assert prompts and all(all(rule in t for rule in never) for t in prompts)


def test_connectors_without_a_listed_url_are_left_to_fill(files):
    manifest = json.loads(files["manifest.json"])
    assert {f["connector"] for f in manifest["to_fill"]} == {"salesforce", "workday"}
    filled = claudekit.build({"salesforce": "https://mcp.salesforce.example/mcp"})
    assert "salesforce" not in {f["connector"] for f in json.loads(filled["manifest.json"])["to_fill"]}
    assert "https://mcp.salesforce.example/mcp" in filled["agents/crm-task.md"]
    with pytest.raises(claudekit.KitError, match="no connector"):
        claudekit.build({"servicenow": "https://x.example"})


def test_the_command_writes_the_kit(tmp_path, capsys):
    assert cli.main(["claude-kit", "--out", str(tmp_path)]) == 0
    assert (tmp_path / "agents" / "grader-ticket.md").is_file() and "file(s) written" in capsys.readouterr().out
    assert cli.main(["claude-kit", "--out", str(tmp_path)]) == 0
    assert "0 file(s) written" in capsys.readouterr().out  # deterministic: nothing changes on a second run
