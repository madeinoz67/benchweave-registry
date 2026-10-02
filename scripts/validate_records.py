"""Records-validity gate for the BenchWeave registry lane (CR-9/CR-10/CR-56/CR-60/CR-38/CR-35).

Every record under ``records/`` must be canonical JSON (sorted keys, compact
separators, one trailing newline), schema-valid against
``records/records.schema.json``, and semantically consistent:

- a changes-requested review citing no failure is refused (CR-10);
- a review naming no platform findings at the pinned revision is refused (CR-60);
- a record without a kind tag is refused (CR-56);
- a publish record without a closure diff, or whose sign-off names a different
  closure digest than the one published, is refused (CR-38);
- no dev-prefixed registry id appears anywhere in the records or the published
  releases (CR-35's index half);
- a yank record whose release carries no ``status.json`` with lifecycle
  yanked-or-revoked is refused (``yank_status_absent:``; fold R2 renamed by
  issue #225 slice 3 to the design's prefix family): ``status.json`` is
  the single catalogue authority (Q8) and the generator honours status
  documents only — the coherence rule keeps a canonical yank record from
  being silently inert;
- the yank pairing is bidirectional and sequence-pinned (§2.3): a served
  status saying yanked-or-revoked with no governing yank/takedown record
  refuses (``status_yank_unrecorded:``), and the record's
  ``status_sequence`` must equal the sequence actually served
  (``yank_status_sequence_mismatch:``);
- an advisory record whose advisory id is absent from the served status's
  ``advisories[]`` refuses (``advisory_status_absent:``);
- a withdraw record for an already-published submission refuses
  (``withdraw_after_publication:``; CR-32 — post-signing withdrawal is
  advisory or unlist);
- namespace hygiene reaches the records side (issue #225 slice 3,
  CR-15/16/39): every record's publisher must be a vetted
  ``publishers.json`` entry (``publisher_unvetted:``), reserved plugin
  names never reach a record (``namespace_reserved:``), and
  ``publishers.json`` itself is vetted at admission — reserved or
  near-reserved namespaces refuse (``namespace_reserved:``), a namespace
  claimed by two publishers refuses (``namespace_collision:``), a
  lookalike of a vetted namespace refuses (``namespace_lookalike:``),
  and every cited vetting row must resolve in ``vetting-checklist.md``
  (``vetting_row_unknown:``; a missing checklist file refuses with
  ``vetting_checklist_absent:``);
- a transfer record requires a vetted receiver
  (``transfer_receiver_unvetted:``), a vetting reference that resolves to
  the receiver's citation (``transfer_vetting_unresolved:``) and consents
  naming both publishers (``transfer_consents_incomplete:``) — CR-17/Q9;
- the review block inside a published release's manifest pins the review
  record's own canonical digest, and the record's closure digest matches the
  manifest's dependency closure (the review-to-sign swap defense, CR-11/CR-14).

Structural validity does not establish trust; these checks are the machine
half, and identified human review remains the accountable one.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

import jsonschema

REPO = Path(__file__).resolve().parents[1]
RECORDS = REPO / "records"

_SCHEMA_CACHE: dict[str, jsonschema.Draft202012Validator] = {}


def canonical_bytes(obj: object) -> bytes:
    """The lane's canonical serialization: sorted keys, compact, LF, newline."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode() + b"\n"


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _validator(name: str) -> jsonschema.Draft202012Validator:
    if name not in _SCHEMA_CACHE:
        schema = json.loads((RECORDS / name).read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(schema)
        _SCHEMA_CACHE[name] = jsonschema.Draft202012Validator(schema)
    return _SCHEMA_CACHE[name]


def _lane_rules(root: Path) -> dict[str, Any] | None:
    """The tree's lane-rules.json, or None when the tree carries none.

    The namespace checks run only when their authorities are present in the
    tree — publishers.json for the vetted set, lane-rules.json for the
    reserved lists and the similarity rule — so a minimal fixture tree
    without them is not a refusal, while the repository of record always
    carries both.
    """
    path = root / "lane-rules.json"
    if not path.is_file():
        return None
    rules = json.loads(path.read_bytes())
    return rules if isinstance(rules, dict) else None


def _skeleton(name: str, params: dict[str, Any]) -> str:
    """Fold a name to its confusable skeleton (the lane's committed rule)."""
    folded = str(name).casefold()
    for separator in params.get("separator_characters", ("-", "_", ".", "/")):
        folded = folded.replace(str(separator), "")
    confusables = params.get("confusable_map", {})
    for source, target in sorted(confusables.items(), key=lambda kv: -len(str(kv[0]))):
        folded = folded.replace(str(source), str(target))
    return folded


def _edit_distance(left: str, right: str) -> int:
    if left == right:
        return 0
    previous = list(range(len(right) + 1))
    for i, left_char in enumerate(left, start=1):
        current = [i]
        for j, right_char in enumerate(right, start=1):
            current.append(
                min(
                    previous[j] + 1,  # deletion
                    current[j - 1] + 1,  # insertion
                    previous[j - 1] + (left_char != right_char),  # substitution
                )
            )
        previous = current
    return previous[-1]


def _segment_prefix_names(name: str, params: dict[str, Any]) -> list[str]:
    """The skeletons of name's separator-delimited PREFIX SPANS (fold B6).

    Containment is delimiter-bounded (coordinator ruling): a claim on an
    existing name is the existing name followed by a SEPARATOR (or exact
    equality) — ``otdp-tools`` claims ``otdp``, ``dev-tools-inc`` claims
    ``dev``, but ``devlin-instruments`` merely begins with the letters and
    claims nothing. Prefix spans keep multi-token names whole: ``sim-psu``
    is claimed by ``sim-psu-labs`` (span "sim-psu" + separator).
    """
    separators = params.get("separator_characters", ("-", "_", ".", "/"))
    spans: list[str] = []
    tokens: list[str] = []
    token = ""
    for char in str(name):
        if char in separators:
            tokens.append(token)
            token = ""
            spans.append("-".join(tokens))
        else:
            token += char
    tokens.append(token)
    spans.append("-".join(tokens))
    return [_skeleton(span, params) for span in spans if span]


def namespace_verdict(
    candidate: str, existing: str, *, reserved: bool, rules: dict[str, Any]
) -> str:
    """Classify a candidate namespace against an existing name (CR-39).

    Two comparison sets, disclosed in the slice-3 fixture README: near a
    RESERVED name the verdict is ``reserved`` (a claim on the standard's
    name — ``otdp-tools`` extends ``otdp``); near a VETTED namespace it is
    ``lookalike`` (impersonation for review). Near = skeleton edit distance
    within the committed maximum, or one skeleton containing the other
    (the extension shapes the committed vectors pin). The twin-test
    discipline: this rule and the SDK's package-time rule are both pinned
    against the same committed ``lane-rules.json`` vectors.

    ``rules`` is explicit (fold row 6): no caller silently falls back to
    this repository's own lane rules — a tree is validated against its own
    authorities or not at all.
    """
    params = rules.get("similarity_rule", {}).get("params", {})
    left, right = _skeleton(candidate, params), _skeleton(existing, params)
    if left == right:
        return "same"
    # Fold B6: delimiter-bounded containment — the other name's skeleton is
    # one of this name's separator-delimited prefix spans (the full-equality
    # case returned "same" above).
    candidate_spans = _segment_prefix_names(candidate, params)
    existing_spans = _segment_prefix_names(existing, params)
    near = (
        _edit_distance(left, right) <= int(params.get("max_edit_distance", 2))
        or right in candidate_spans
        or left in existing_spans
    )
    if not near:
        return "distinct"
    return "reserved" if reserved else "lookalike"


def _reserved_plugins(root: Path) -> frozenset[str]:
    rules = _lane_rules(root)
    if rules is None:
        return frozenset()
    return frozenset(rules.get("namespace_rules", {}).get("reserved_plugins", ()))


def _vetting_checks(
    root: Path, publishers_doc: dict[str, Any]
) -> tuple[set[str], list[str]]:
    """Admission checks over publishers.json (issue #225 slice 3, §2.4).

    Returns the vetted publisher id set and the findings. Vetting REFUSES
    where package-time only flags: a lookalike of a vetted namespace never
    admits, and a reserved-or-extending namespace never admits.
    """
    findings: list[str] = []
    entries = [
        entry for entry in publishers_doc.get("publishers", []) if isinstance(entry, dict)
    ]
    vetted = {str(entry.get("publisher_id")) for entry in entries}
    rules = _lane_rules(root)
    namespaces = [str(entry.get("namespace")) for entry in entries]

    # Fold row 8 (conditional arm - the check held: every committed and
    # fixture entry carries the equality): a publisher's namespace IS its
    # publisher id. Cross-field equality is not expressible in JSON Schema
    # 2020-12, so the arm lives here rather than in publishers.schema.json.
    for entry in entries:
        if entry.get("namespace") != entry.get("publisher_id"):
            findings.append(
                f"publisher_namespace_mismatch:publishers.json: "
                f"{entry.get('publisher_id')} claims namespace "
                f"{entry.get('namespace')} (equality pinned: a publisher's "
                "namespace is its publisher id)"
            )

    seen: set[str] = set()
    for namespace in namespaces:
        if namespace in seen:
            findings.append(
                f"namespace_collision:publishers.json: namespace {namespace} is "
                "claimed by more than one publisher (CR-15: another author's "
                "claim to an existing package namespace collides)"
            )
        seen.add(namespace)

    if rules is not None:
        reserved_namespaces = sorted(
            rules.get("namespace_rules", {}).get("reserved_namespaces", ())
        )
        others = set(namespaces)
        for namespace in sorted(set(namespaces)):
            for reserved_name in reserved_namespaces:
                verdict = namespace_verdict(
                    namespace, reserved_name, reserved=True, rules=rules
                )
                if verdict in ("same", "reserved"):
                    findings.append(
                        f"namespace_reserved:publishers.json: {namespace} is "
                        f"{verdict} against reserved {reserved_name} "
                        "(lane-rules.json)"
                    )
                    break
            for other in sorted(others - {namespace}):
                verdict = namespace_verdict(namespace, other, reserved=False, rules=rules)
                if verdict in ("same", "lookalike"):
                    findings.append(
                        f"namespace_lookalike:publishers.json: {namespace} ~ {other} "
                        "(refused at vetting, CR-39 — the similarity rule with "
                        "the committed vectors)"
                    )

    checklist_rel = "vetting-checklist.md"
    if rules is not None:
        registered = rules.get("vetting_checklist", {}).get("path")
        if isinstance(registered, str) and registered:
            checklist_rel = registered
    checklist = root / checklist_rel
    if not checklist.is_file():
        findings.append(
            f"vetting_checklist_absent:{checklist_rel}: publishers.json cites a "
            "checklist the tree does not carry"
        )
    else:
        known_rows = set(re.findall(r"\|\s*(V-\d{2})\s*\|", checklist.read_text(encoding="utf-8")))
        for entry in entries:
            vetting = entry.get("vetting", {})
            if not isinstance(vetting, dict):
                continue
            for row in vetting.get("cited_rows", ()):
                if row not in known_rows:
                    findings.append(
                        f"vetting_row_unknown:publishers.json: "
                        f"{entry.get('publisher_id')} cites {row}, not a row of "
                        f"{checklist_rel} v{vetting.get('checklist_version')}"
                    )
    return vetted, findings


def _release_status_docs(
    manifests: dict[tuple[str, str, str], Path],
) -> dict[tuple[str, str, str], dict[str, Any] | None]:
    """Each release's served status document, or None when absent/unparseable."""
    docs: dict[tuple[str, str, str], dict[str, Any] | None] = {}
    for key, manifest_path in manifests.items():
        status_path = manifest_path.parent / "status.json"
        if not status_path.is_file():
            docs[key] = None
            continue
        try:
            docs[key] = json.loads(status_path.read_bytes())
        except ValueError:
            docs[key] = None
    return docs


def _record_publisher(parsed: dict[str, Any]) -> str | None:
    if parsed.get("record_type") == "review":
        review = parsed.get("review", {})
        return review.get("publisher") if isinstance(review, dict) else None
    lifecycle = parsed.get("lifecycle", {})
    return lifecycle.get("publisher") if isinstance(lifecycle, dict) else None


def _transfer_findings(
    name: str, lifecycle: dict[str, Any], publishers_doc: dict[str, Any] | None
) -> list[str]:
    """The transfer arm (CR-17/Q9): receiver vetted, reference resolving,
    both consents naming both publishers."""
    findings: list[str] = []
    transfer = lifecycle.get("transfer", {})
    if not isinstance(transfer, dict):
        return findings
    to_publisher = transfer.get("to_publisher")
    entries = {
        str(entry.get("publisher_id")): entry
        for entry in (publishers_doc or {}).get("publishers", [])
        if isinstance(entry, dict)
    }
    receiver = entries.get(str(to_publisher))
    if receiver is None:
        findings.append(
            f"transfer_receiver_unvetted:{name}: to_publisher {to_publisher} is "
            "not a vetted publishers.json entry"
        )
        return findings
    reference = transfer.get("vetting_reference", "")
    expected_reference = f"publishers.json#{to_publisher}"
    if reference != expected_reference or "vetting" not in receiver:
        findings.append(
            f"transfer_vetting_unresolved:{name}: vetting_reference {reference!r} "
            f"does not resolve to {to_publisher}'s vetting citation "
            f"({expected_reference})"
        )
    consents = set(transfer.get("consents", ()))
    needed = {transfer.get("from_publisher"), to_publisher}
    if not needed <= consents:
        missing = sorted(str(part) for part in needed if part not in consents)
        findings.append(
            f"transfer_consents_incomplete:{name}: consents must name both "
            f"publishers; missing {missing}"
        )
    return findings


def _seq_uniqueness_findings(parsed_by_path: dict[Path, dict[str, Any]]) -> list[str]:
    """Fold row 4: per-release record filename sequences must be unique.

    Two records at one numeric sequence on one release must not merge
    silently. Gap-free stays OPTIONAL — a documented choice: sequences name
    order, not a contiguous clock, and git history is the floor.
    """
    findings: list[str] = []
    seen: dict[Path, set[int]] = {}
    for path in parsed_by_path:
        match = re.fullmatch(r"(\d+)-[a-z]+\.json", path.name)
        if match is None:
            continue
        sequences = seen.setdefault(path.parent, set())
        number = int(match.group(1))
        if number in sequences:
            findings.append(
                f"record_seq_duplicate:{path.parent.name}/{path.name}: sequence "
                f"{number} is already taken on this release"
            )
        sequences.add(number)
    return findings


def record_paths(records_dir: Path) -> list[Path]:
    """Every committed record file, sorted (submissions and lifecycle).

    Fold C2 (named exclusion, coordinator ruling): ``artefacts/`` subtrees
    under ``records/submissions/`` are submission PAYLOAD staged by the
    submit flow and read by the index generator — a document class the
    records-validity gate does not judge. Without the exclusion every
    genuine submission PR was red by construction (the artefact JSON is not
    a record); with it, real records still require their authorities
    (the fail-closed census is pinned by test, not weakened).
    """
    collected: list[Path] = []
    for sub in ("submissions", "lifecycle"):
        for path in (records_dir / sub).rglob("*.json"):
            if not path.is_file():
                continue
            relative = path.relative_to(records_dir).parts
            if sub == "submissions" and "artefacts" in relative[1:]:
                continue
            collected.append(path)
    return sorted(collected)


def closure_digest_of_dependencies(dependencies: list[dict[str, Any]]) -> str:
    """CR-38's closure digest: sha256 over the canonical sorted dependency pins.

    One definition, used by the submission tooling, the review record, the
    publish record and this checker, so the sign-off can never cover a
    different closure than the one published.
    """
    pins = sorted(
        (dep["registry_id"], dep["package_id"], dep["version"], dep["manifest_sha256"])
        for dep in dependencies
    )
    return sha256_hex(canonical_bytes(pins))


def validate_record(raw: bytes, path: Path) -> tuple[list[str], dict[str, Any] | None]:
    """Validate one record's bytes; returns (findings, parsed-or-None)."""
    findings: list[str] = []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        return [f"record_schema_invalid:{path.name}: not JSON: {exc}"], None
    if not isinstance(parsed, dict):
        return [f"record_schema_invalid:{path.name}: record is not an object"], None
    if canonical_bytes(parsed) != raw:
        findings.append(f"record_not_canonical:{path.name}")
    errors = sorted(_validator("records.schema.json").iter_errors(parsed), key=str)
    for err in errors:
        findings.append(
            f"record_schema_invalid:{path.name}: {err.json_path}: {err.message}"
        )
    return findings, parsed


def _record_order(path: Path) -> tuple[str, int, str]:
    """Numeric-aware record ordering (fold A2): filenames carry a sequence
    (``review-10`` / ``2-publish``) and lexicographic order is WRONG for
    two-digit sequences (``review-10`` sorts before ``review-9``)."""
    match = re.search(r"(\d+)", path.stem)
    return (str(path.parent), int(match.group(1)) if match else 0, path.name)


def _review_records(parsed_by_path: dict[Path, dict[str, Any]]) -> dict[tuple[str, str, str], Path]:
    """Map (publisher, plugin, version) -> the LATEST review record's path.

    Fold A2: latest = highest numeric filename sequence, not last
    lexicographic write — the pre-existing wound silently governed by the
    older review whenever a submission passed nine reviews.
    """
    reviews: dict[tuple[str, str, str], Path] = {}
    for path, parsed in sorted(
        parsed_by_path.items(), key=lambda item: _record_order(item[0])
    ):
        if parsed.get("record_type") != "review":
            continue
        review = parsed.get("review", {})
        key = (review.get("publisher"), review.get("plugin"), review.get("version"))
        reviews[key] = path
    return reviews


def _release_manifests(releases_dir: Path) -> dict[tuple[str, str, str], Path]:
    """Map (publisher, plugin, version) -> manifest path under releases/."""
    manifests: dict[tuple[str, str, str], Path] = {}
    if not releases_dir.is_dir():
        return manifests
    for path in sorted(releases_dir.rglob("manifest.json")):
        parts = path.relative_to(releases_dir).parts
        # <registry-id>/<publisher>/<plugin>/<version>/manifest.json
        if len(parts) != 5 or parts[-1] != "manifest.json":
            continue
        manifests[(parts[1], parts[2], parts[3])] = path
    return manifests


def validate_tree(root: Path) -> list[str]:
    """All findings for the committed records tree; empty means valid."""
    findings: list[str] = []
    records_dir = root / "records"
    releases_dir = root / "releases"

    publishers_raw = records_dir / "publishers.json"
    publishers_doc: dict[str, Any] | None = None
    if publishers_raw.is_file():
        raw = publishers_raw.read_bytes()
        parsed = json.loads(raw)
        if canonical_bytes(parsed) != raw:
            findings.append("record_not_canonical:publishers.json")
        for err in sorted(
            _validator("publishers.schema.json").iter_errors(parsed), key=str
        ):
            findings.append(
                f"record_schema_invalid:publishers.json: {err.json_path}: {err.message}"
            )
        publishers_doc = parsed if isinstance(parsed, dict) else None

    parsed_by_path: dict[Path, dict[str, Any]] = {}
    for path in record_paths(records_dir):
        record_findings, parsed = validate_record(path.read_bytes(), path)
        findings.extend(record_findings)
        if parsed is not None:
            parsed_by_path[path] = parsed

    reviews = _review_records(parsed_by_path)
    manifests = _release_manifests(releases_dir)

    vetted_publishers: set[str] = set()
    if publishers_doc is not None:
        vetted_publishers, vetting_findings = _vetting_checks(root, publishers_doc)
        findings.extend(vetting_findings)
    status_docs = _release_status_docs(manifests)

    # CR-35's releases half: no dev-prefixed origin or dependency lineage in
    # the published tree (the docstring's records-AND-releases claim, made
    # true here): a dev-unsigned origin under releases/ refuses.
    _segment = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
    for manifest_path in sorted(manifests.values()):
        manifest = json.loads(manifest_path.read_bytes())
        rel = manifest_path.relative_to(releases_dir).as_posix()
        # Fold L2 (read side): a traversal-shaped identity never resolves.
        parts = manifest_path.relative_to(releases_dir).parts
        for part in parts[:-1]:
            if _segment.fullmatch(part) is None:
                findings.append(f"release_path_unsafe:{rel}")
        # Fold M3 (identity agreement): the manifest must claim the path it
        # lives at - a ghost at 0.9.0 claiming 0.1.0 refuses here too.
        path_package = f"{parts[1]}/{parts[2]}"
        if manifest.get("package_id") != path_package or manifest.get("version") != parts[3]:
            findings.append(
                f"release_identity_mismatch:{rel}: claims "
                f"{manifest.get('package_id')}@{manifest.get('version')}"
            )
        if str(manifest.get("registry_id", "")).startswith("dev-"):
            findings.append(f"dev_lineage_in_release:{rel}")
        for dep in manifest.get("dependencies", []):
            if str(dep.get("registry_id", "")).startswith("dev-"):
                findings.append(f"dev_lineage_in_release:{rel}")
        # Fold H2: the consumed manifest is reconciled against the signed
        # bytes and the recorded digest - a post-recording tamper refuses.
        submission_path = manifest_path.parent / "submission-manifest.json"
        if submission_path.is_file():
            signed = json.loads(submission_path.read_bytes())
            reconciled = {k: v for k, v in manifest.items() if k != "review"}
            reconciled["manifest_version"] = signed.get("manifest_version", "0.1.1")
            if reconciled != signed:
                findings.append(f"manifest_reconciliation_failed:{rel}")

    # Fold row 3 (fail-closed authority presence): records without their
    # authorities are §1.2's vacuity class reborn — the gate was green with
    # unvetted and reserved records planted because nothing forced the
    # authority files to exist. Any record at all requires both authorities.
    if parsed_by_path:
        for authority in ("records/publishers.json", "lane-rules.json"):
            if not (root / authority).is_file():
                findings.append(
                    f"authority_absent:{authority}: the tree carries records "
                    "without their authority files"
                )

    # Fold row 4: per-release filename sequences must be unique; gap-free
    # stays optional (see _seq_uniqueness_findings for the documented choice).
    findings.extend(_seq_uniqueness_findings(parsed_by_path))

    publish_keys: set[tuple[str, str, str]] = set()
    yank_keys: set[tuple[str, str, str]] = set()
    advisory_ids: dict[tuple[str, str, str], set[str]] = {}
    # Fold row 2 (two-pass): the per-record arms compare against keys drawn
    # from ALL records, but paths sort lexicographically — "10-withdraw.json"
    # sorts BEFORE "2-publish.json" — so a single mid-pass evaluation saw a
    # withdraw before the publish it conflicts with existed. Collect first,
    # evaluate second.
    for parsed in parsed_by_path.values():
        if parsed.get("record_type") != "lifecycle":
            continue
        lifecycle = parsed.get("lifecycle", {})
        collect_key = (
            lifecycle.get("publisher"),
            lifecycle.get("plugin"),
            lifecycle.get("version"),
        )
        if lifecycle.get("op") == "publish":
            publish_keys.add(collect_key)
        elif lifecycle.get("op") in ("yank", "takedown"):
            yank_keys.add(collect_key)
        if lifecycle.get("op") == "advisory":
            advisory = lifecycle.get("advisory", {})
            if isinstance(advisory, dict) and advisory.get("id"):
                advisory_ids.setdefault(collect_key, set()).add(str(advisory["id"]))

    for path, parsed in parsed_by_path.items():
        # CR-35's index half: no dev-prefixed registry id in any record.
        if "dev-" in json.dumps(parsed):
            findings.append(f"dev_lineage_in_records:{path.name}")
        # CR-15's records half (issue #225): every record's publisher is a
        # vetted publishers.json entry.
        if vetted_publishers:
            claimed = _record_publisher(parsed)
            if claimed is not None and claimed not in vetted_publishers:
                findings.append(
                    f"publisher_unvetted:{path.name}: {claimed} is not a vetted "
                    "publishers.json entry"
                )
        if parsed.get("record_type") != "lifecycle":
            continue
        lifecycle = parsed.get("lifecycle", {})
        # Fold B5 (path<->block agreement): the record's DIRECTORY names the
        # submission it belongs to; a block claiming another identity is a
        # record filed where no reader will look for it.
        relative = path.relative_to(records_dir).parts
        if len(relative) == 5 and relative[0] in ("submissions", "lifecycle"):
            block = parsed.get("review", {}) if relative[0] == "submissions" else lifecycle
            if isinstance(block, dict) and (
                block.get("publisher"),
                block.get("plugin"),
                block.get("version"),
            ) != (relative[1], relative[2], relative[3]):
                findings.append(
                    f"record_path_mismatch:{path.name}: filed at "
                    f"{'/'.join(relative[:-1])}, claims "
                    f"{block.get('publisher')}/{block.get('plugin')}@{block.get('version')}"
                )
        # CR-16's records half + fold C1: reserved plugin names never reach a
        # record, under the SAME near-aware predicate as the namespace arm —
        # '5im-psu' skeleton-folds exactly onto reserved 'sim-psu' and
        # 'sim-psu-labs' is the delimiter-bounded extension; exact matches
        # refuse as before.
        plugin = lifecycle.get("plugin")
        plugin_rules = _lane_rules(root)
        reserved_plugin = False
        if isinstance(plugin, str) and plugin_rules is not None:
            for name in sorted(
                plugin_rules.get("namespace_rules", {}).get("reserved_plugins", ())
            ):
                if namespace_verdict(
                    plugin, name, reserved=True, rules=plugin_rules
                ) in ("same", "reserved"):
                    findings.append(
                        f"namespace_reserved:{path.name}: plugin {plugin} is "
                        f"reserved (near {name}, lane-rules.json)"
                    )
                    reserved_plugin = True
                    break
        if reserved_plugin:
            continue
        key = (
            lifecycle.get("publisher"),
            lifecycle.get("plugin"),
            lifecycle.get("version"),
        )
        op = lifecycle.get("op")
        # Fold G5 (inert-record existence): a lifecycle record whose SUBJECT
        # does not exist is inert — refused loudly instead of merging green.
        # withdraw's subject is the submission (the staged artefacts or a
        # committed record under records/submissions/<p>/<x>/<v>/); unlist and
        # transfer govern a release. yank/advise are status-paired already.
        if op in ("withdraw", "unlist", "transfer"):
            if op == "withdraw":
                subject = (
                    records_dir / "submissions" / str(key[0]) / str(key[1]) / str(key[2])
                )
                subject_present = subject.is_dir() and any(
                    entry.is_file() for entry in subject.rglob("*")
                )
                subject_kind = "submission"
            else:
                subject_present = key in manifests
                subject_kind = "release"
            if not subject_present:
                findings.append(
                    f"record_subject_absent:{path.name}: {op} for "
                    f"{'/'.join(str(part) for part in key)} but its {subject_kind} "
                    "does not exist"
                )
                continue
        if op == "yank":
            # Fold R2 (lane A F2, round-2 refute) + slice 3's §2.3 pairing:
            # a canonical yank record whose release lacks a status.json with
            # lifecycle yanked or revoked is INERT — the row stays served,
            # every gate green, because the generator honours status
            # documents only. The coherence rule makes the trap loud while
            # keeping status.json the single catalogue authority (Q8); the
            # generator does NOT honour yank records directly.
            status = status_docs.get(key)
            if not (
                isinstance(status, dict)
                and status.get("lifecycle") in ("yanked", "revoked")
            ):
                findings.append(
                    f"yank_status_absent:{path.name}: no status.json with "
                    f"lifecycle yanked|revoked governs {'/'.join(str(k) for k in key)} "
                    "— the catalogue serves the row unchanged (status.json is the "
                    "single authority, Q8)"
                )
            else:
                # Fold row 1: ORDERING, not equality. §2.3's own words are
                # "mirroring exactly what the resolver enforces" — and the
                # resolver's check_status is a high-water ORDERING refusal,
                # never equality. This keeps yank-then-advise (§2.3's
                # CVE-documentation pattern, advisories preserved through
                # yank) representable. Residual, stated: a stale yank record
                # (cited < served) rides a newer status revision — ordering
                # + lifecycle still pin coherence.
                cited = lifecycle.get("status_sequence")
                served = status.get("sequence")
                if cited is None or served is None or cited > served:
                    findings.append(
                        f"yank_status_sequence_mismatch:{path.name}: record cites "
                        f"sequence {cited}, the served status is at sequence "
                        f"{served} — the record must not claim a status revision "
                        "newer than the served document"
                    )
            continue
        if op == "advisory":
            # §2.3: the advisory the record appends must be IN the served
            # status's advisories[] — record and served state cannot diverge.
            advisory = lifecycle.get("advisory", {})
            advisory_id = (
                advisory.get("id") if isinstance(advisory, dict) else None
            )
            status = status_docs.get(key)
            served_ids = [
                entry.get("id")
                for entry in status.get("advisories", ())
                if isinstance(entry, dict)
            ] if isinstance(status, dict) else []
            if advisory_id not in served_ids:
                findings.append(
                    f"advisory_status_absent:{path.name}: advisory "
                    f"{advisory_id!r} is not in the served status's advisories[] "
                    f"for {'/'.join(str(k) for k in key)}"
                )
            continue
        if op == "withdraw":
            # CR-32: withdraw is pre-acceptance only; post-signing withdrawal
            # is advisory or unlist.
            if key in publish_keys:
                findings.append(
                    f"withdraw_after_publication:{path.name}: a publish record "
                    f"exists for {'/'.join(str(k) for k in key)} — post-signing "
                    "withdrawal is advisory or unlist (CR-32)"
                )
            continue
        if op == "transfer":
            findings.extend(_transfer_findings(path.name, lifecycle, publishers_doc))
            continue
        if op != "publish":
            continue
        if "closure" not in lifecycle:
            # Belt and braces: the schema's if/then already refuses this
            # (A4's closure_diff_absent mutant names exactly this component).
            findings.append(f"closure_diff_absent:{path.name}")
            continue
        release_path: Path | None = manifests.get(key)
        if release_path is None:
            findings.append(
                f"publish_record_without_release:{path.name}: no manifest under releases/"
            )
            continue
        manifest = json.loads(release_path.read_bytes())
        # Fold H2: the publish record's release_manifest_sha256 must pin the
        # manifest bytes actually on disk.
        recorded_digest = lifecycle.get("release_manifest_sha256")
        if recorded_digest and recorded_digest != sha256_hex(release_path.read_bytes()):
            findings.append(
                f"release_digest_mismatch:{path.name}: record pins "
                f"{recorded_digest[:12]}…, on disk is "
                f"{sha256_hex(release_path.read_bytes())[:12]}…"
            )
        # CR-38: the sign-off names the closure digest actually published.
        expected = closure_digest_of_dependencies(manifest.get("dependencies", []))
        if lifecycle.get("closure_digest") != expected:
            findings.append(
                f"closure_digest_mismatch:{path.name}: sign-off names "
                f"{lifecycle.get('closure_digest')}, published closure is {expected}"
            )
        review_path = reviews.get(key)
        if review_path is None:
            findings.append(
                f"publish_record_without_review:{path.name}: no review record for {key}"
            )
            continue
        review = parsed_by_path[review_path]["review"]
        if review.get("closure_digest") != expected:
            findings.append(
                f"closure_digest_mismatch:{review_path.name}: review sign-off names "
                f"{review.get('closure_digest')}, published closure is {expected}"
            )
        # CR-11/CR-14: the signed manifest's review block pins the review
        # record's own canonical digest, and the record pins the release.
        review_raw = review_path.read_bytes()
        block = manifest.get("review", {})
        if block.get("record_sha256") != sha256_hex(review_raw):
            findings.append(
                f"review_record_digest_mismatch:{release_path.name}: review block pins "
                f"{block.get('record_sha256')}, record digest is {sha256_hex(review_raw)}"
            )
        if block.get("outcome") != review.get("outcome"):
            findings.append(
                f"review_outcome_mismatch:{release_path.name}: manifest review block says "
                f"{block.get('outcome')}, record says {review.get('outcome')}"
            )

    # §2.3's reverse pairing: a served status saying yanked or revoked with
    # no governing yank/takedown record — record and served state cannot
    # diverge silently in EITHER direction.
    for key, status in status_docs.items():
        if not (
            isinstance(status, dict) and status.get("lifecycle") in ("yanked", "revoked")
        ):
            continue
        if key not in yank_keys:
            findings.append(
                f"status_yank_unrecorded:{'/'.join(str(k) for k in key)}: the "
                f"served status says {status.get('lifecycle')} but no yank|takedown "
                "record governs it"
            )

    # Fold B2: the advisory pairing's reverse direction — every advisory the
    # served status carries must have the advisory record that appended it.
    for key, status in status_docs.items():
        if not isinstance(status, dict):
            continue
        for served in status.get("advisories", ()):
            if not isinstance(served, dict):
                continue
            served_id = served.get("id")
            if served_id and served_id not in advisory_ids.get(key, set()):
                findings.append(
                    f"status_advisory_unrecorded:{'/'.join(str(k) for k in key)}: "
                    f"the served status carries advisory {served_id!r} with no "
                    "advisory record"
                )
    return findings


def main(argv: list[str] | str | None = None) -> int:
    """The records-validity CLI (fold R5): ``--root`` routes like its sibling
    gates — the pre-fold entry point ignored unknown arguments entirely and
    validated its own tree, exit 0, whatever it was handed."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO)
    args = parser.parse_args([argv] if isinstance(argv, str) else argv)
    root = args.root.resolve()
    findings = validate_tree(root)
    for finding in findings:
        print(f"validate_records: {finding}", file=sys.stderr)
    if findings:
        return 1
    print(f"validate_records: {len(record_paths(root / 'records'))} records valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
