"""Load and validate the versioned standards (reference data class, kept in git)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from . import resources

ROOT = resources.root()
PAGE_TEMPLATES = Path(__file__).resolve().parent / "page_templates"


# libyaml's loader when the install has it (about ten times faster), else the pure-Python one. Same resolvers, so
# the same documents: dates still load as dates (roster.py keeps its own loader that turns them into strings).
_YamlLoader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)

MEMO_MAX = 256  # entries; the oldest goes first
_MEMO: dict[Any, Any] = {}


def memo(key: Any, make: Callable[[], Any]) -> Any:
    """`make()` once per `key`, in a bounded module-level cache. Callers build keys from the bytes of the files a value
    comes from, so an edit is a different key; a `make` that raises caches nothing. The values are shared, so callers
    must not change them."""
    try:
        return _MEMO[key]
    except KeyError:
        pass
    value = make()
    if len(_MEMO) >= MEMO_MAX:
        _MEMO.pop(next(iter(_MEMO)))
    _MEMO[key] = value
    return value


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_yaml(data: bytes | str) -> Any:
    return yaml.load(data, Loader=_YamlLoader)


def load_yaml(path: Path) -> dict[str, Any]:
    return parse_yaml(Path(path).read_bytes())


def load_schema(name: str, root: Path = ROOT) -> dict[str, Any]:
    with (root / "contracts" / name).open(encoding="utf-8") as fh:
        return json.load(fh)


def _validator(schema_name: str, root: Path) -> Draft202012Validator:
    data = (Path(root) / "contracts" / schema_name).read_bytes()
    return memo(("validator", sha256_hex(data)), lambda: Draft202012Validator(json.loads(data.decode("utf-8"))))


def validate(doc: dict[str, Any], schema_name: str, root: Path = ROOT) -> list[str]:
    """Return a list of human-readable schema errors (empty when valid)."""
    validator = _validator(schema_name, root)
    return [f"{'/'.join(map(str, e.path)) or '<root>'}: {e.message}" for e in validator.iter_errors(doc)]


# step.signer (decision 0012): the subject kinds whose attrs hold the signer(s) it names
SIGNER_SUBJECTS = {"attrs.observer": ("assignment",), "attrs.instructor": ("candidate", "assignment"),
                   "attrs.observers": ("exercise",)}
WORKFLOWS_DIR = "workflows"  # under standards/: one tm:contract/workflows@1 document per file
MERGED_WORKFLOWS_ID = "tm:standards/workflows"


def workflow_files(root: Path = ROOT) -> list[Path]:
    """The per-workflow files, sorted by file name (the merge order)."""
    return sorted((root / "standards" / WORKFLOWS_DIR).glob("*.yaml"), key=lambda p: p.name)


def merge_workflows(docs: list[dict[str, Any]]) -> dict[str, Any]:
    """One workflows document from the per-file documents, in the order given. The merged status is the
    shared status, or `draft` when the files differ (the least committed state wins)."""
    statuses = {d["status"] for d in docs}
    return {
        "schema_version": 1,
        "id": MERGED_WORKFLOWS_ID,
        "status": statuses.pop() if len(statuses) == 1 else "draft",
        "workflows": [wf for d in docs for wf in d["workflows"]],
    }


def load_standards(root: Path = ROOT) -> dict[str, dict[str, Any]]:
    std = root / "standards"
    return {
        "framework": load_yaml(std / "framework.yaml"),
        "rubric": load_yaml(std / "rubric.yaml"),
        "rules": load_yaml(std / "rules.yaml"),
        "workflows": merge_workflows([load_yaml(f) for f in workflow_files(root)]),
    }


def check_standards(root: Path = ROOT) -> list[str]:
    """Schema-validate the standards and check they agree with each other."""
    s = load_standards(root)
    errors = [f"framework: {e}" for e in validate(s["framework"], "framework.schema.json", root)]
    errors += [f"rules: {e}" for e in validate(s["rules"], "rules.schema.json", root)]
    domains = [d["id"] for d in s["framework"]["domains"]]
    anchored = list(s["rubric"]["anchors"])
    if sorted(domains) != sorted(anchored):
        errors.append(f"rubric anchors {anchored} do not match framework domains {domains}")
    for dom, points in s["rubric"]["anchors"].items():
        if sorted(points) != [1, 2, 3, 4]:
            errors.append(f"rubric: domain {dom} needs anchors for points 1-4")
    version = s["framework"]["version"]
    for name in ("rubric", "rules"):
        if s[name]["framework_version"] != version:
            errors.append(f"{name}: framework_version {s[name]['framework_version']} != {version}")
    file_errors: list[str] = []
    for f in workflow_files(root):
        file_errors += [f"workflows/{f.name}: {e}" for e in validate(load_yaml(f), "workflows.schema.json", root)]
    # Cross-checks run on the merged document, so step ids are unique across files and needs may cross files.
    errors += file_errors or check_workflows(s["workflows"], root)
    from . import units  # lazy: units imports this module

    errors += units.check_units(root)
    retention = load_yaml(root / "standards" / "retention.yaml")
    retention_schema_errors = validate(retention, "retention.schema.json", root)
    errors += [f"retention: {e}" for e in retention_schema_errors]
    if not retention_schema_errors:
        from . import privacy, setup  # lazy: both import this module

        errors += [f"retention: {e}" for e in setup.retention_errors(retention, root)]
        errors += privacy.check_privacy(
            root,
            workflow_ids={wf["id"] for wf in s["workflows"]["workflows"]},
            category_ids=[c["id"] for c in setup.data_categories(root)],
            retention=retention,
        )
    if (root / "standards" / "chains.yaml").is_file():  # decision 0029
        from . import interventions

        errors += [f"chains: {e}" for e in interventions.problems(interventions.chains_doc(root), root)]
    return errors


def check_workflows(doc: dict[str, Any], root: Path = ROOT) -> list[str]:
    """Schema-validate the merged workflows document and check its cross-references and event kinds."""
    errors = [f"workflows: {e}" for e in validate(doc, "workflows.schema.json", root)]
    if errors:
        return errors  # cross-checks assume a well-formed document
    from . import due, flows  # noqa: F401 - importing the flows registers their due rules

    rule_names = due.names()
    event_kinds = set(load_schema("event.schema.json", root)["properties"]["kind"]["enum"])
    steps = {st["id"]: st for wf in doc["workflows"] for st in wf["steps"]}
    seen: set[str] = set()
    for wf in doc["workflows"]:
        declared = set(wf["event_kinds"])
        for kind in sorted(declared - event_kinds):
            errors.append(f"workflows: {wf['id']} event_kinds entry {kind!r} is not in the event schema kind enum")
        for st in wf["steps"]:
            sid = st["id"]
            done = st["done_when"]
            kind = done["kind"]
            if kind not in declared:
                errors.append(f"workflows: {sid} done_when.kind {kind!r} is not in event_kinds of {wf['id']}")
            if done.get("bind") and kind != "signoff":
                errors.append(f"workflows: {sid} done_when.bind needs kind 'signoff' (only a sign-off carries input_sha256)")
            if done.get("skippable") and done.get("bind") != "input":
                errors.append(f"workflows: {sid} done_when.skippable needs bind 'input' (a skip must cover the inputs it was made on)")
            if done.get("revocable") and (done.get("bind") != "input" or st.get("signer") is not None):
                errors.append(f"workflows: {sid} done_when.revocable needs bind 'input' and no signer (decision 0019: a "
                              f"revocation withdraws the one approval in force)")
            signer = st.get("signer")
            if signer is not None and (st["type"] != "human" or st["subject"] not in SIGNER_SUBJECTS[signer]):
                errors.append(f"workflows: {sid} signer {signer!r} needs a human step on a "
                              f"{'/'.join(SIGNER_SUBJECTS[signer])} subject")
            if sid in seen:
                errors.append(f"workflows: duplicate step id {sid}")
            seen.add(sid)
            for need in st["needs"]:
                if need not in steps:
                    errors.append(f"workflows: {sid} needs unknown step {need}")
            for need, openers in (st.get("needs_except_opened_by") or {}).items():
                if need not in st["needs"]:
                    errors.append(f"workflows: {sid} needs_except_opened_by names {need}, which is not one of its needs")
                errors += [f"workflows: {sid} needs_except_opened_by names unknown step {o}" for o in openers if o not in steps]
            step_due = st.get("due")
            if isinstance(step_due, str) and step_due not in rule_names:
                errors.append(f"workflows: {sid} due rule {step_due!r} is not registered (teachermodel.due, @due_rule in a flow module)")
            page = st.get("page")
            if page is not None and not (PAGE_TEMPLATES / f"{page}.html").is_file():
                errors.append(f"workflows: {sid} page template {page!r} not found in {PAGE_TEMPLATES}")
    errors += _cycle_errors({sid: [n for n in st["needs"] if n in steps] for sid, st in steps.items()})
    return errors


def _cycle_errors(graph: dict[str, list[str]]) -> list[str]:
    """Depth-first search; report each distinct cycle found once."""
    errors: list[str] = []
    state: dict[str, int] = {}  # 1 = on the current path, 2 = finished

    def visit(node: str, path: list[str]) -> None:
        state[node] = 1
        for nxt in graph[node]:
            if state.get(nxt) == 1:
                loop = path[path.index(nxt):] + [nxt] if nxt in path else [nxt, node, nxt]
                errors.append("workflows: needs cycle " + " -> ".join(loop))
            elif nxt not in state:
                visit(nxt, path + [nxt])
        state[node] = 2

    for node in graph:
        if node not in state:
            visit(node, [node])
    return errors


def domain_ids(root: Path = ROOT) -> list[str]:
    return [d["id"] for d in load_standards(root)["framework"]["domains"]]
