"""CC-06, S6 (T-1712): every encrypted file of this repository is readable by exactly the
recipients `.sops.yaml` records, and by no key, KMS or PGP identity it does not name.

The attack: a secret encrypted to a key nobody reviews (a developer's laptop key, a stray KMS ARN)
is a secret that key's holder reads. The defence: one reviewed list in `.sops.yaml`; this test
reads every file carrying a `sops:` block and refuses one whose recipients differ from that list.
"""

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
AGE_KEY = re.compile(r"^age1[0-9a-z]{58}$")
SKIP = {".git", "node_modules", ".venv"}


def _rules():
    config = yaml.safe_load((ROOT / ".sops.yaml").read_text())
    rules = config.get("creation_rules") or []
    assert rules, ".sops.yaml records no creation rule"
    return [
        (re.compile(rule["path_regex"]), sorted(k.strip() for k in str(rule.get("age", "")).split(",") if k.strip()))
        for rule in rules
    ]


def _encrypted_files():
    for path in ROOT.rglob("*.y*ml"):
        if SKIP.intersection(path.parts) or path.name == ".sops.yaml":
            continue
        text = path.read_text(errors="ignore")
        if re.search(r"^sops:\s*$", text, re.M):
            yield path, yaml.safe_load(text)["sops"]


def test_the_recorded_recipients_are_age_keys_and_nothing_else():
    """CC-06: only age keys are recorded; no KMS, PGP or vault identity reaches a rule."""
    config = yaml.safe_load((ROOT / ".sops.yaml").read_text())
    for rule in config["creation_rules"]:
        assert set(rule) <= {"path_regex", "age"}, f"a rule names more than age keys: {sorted(rule)}"
    for _, keys in _rules():
        assert keys, "a rule records no recipient"
        assert all(AGE_KEY.match(key) for key in keys), keys


@pytest.mark.parametrize("path,block", list(_encrypted_files()), ids=lambda v: str(v)[-60:] if isinstance(v, Path) else "")
def test_every_encrypted_file_names_exactly_the_recorded_recipients(path, block):
    """S6: a file encrypted to anyone the review did not record is refused."""
    relative = str(path.relative_to(ROOT))
    matching = [keys for pattern, keys in _rules() if pattern.search(relative)]
    assert matching, f"{relative} is encrypted but no rule of .sops.yaml covers it"
    for other in ("kms", "gcp_kms", "azure_kv", "hc_vault", "pgp"):
        assert not block.get(other), f"{relative} is encrypted to {other}, which .sops.yaml does not record"
    named = sorted(entry["recipient"] for entry in block.get("age") or [])
    assert named == matching[0], f"{relative} names {named}, .sops.yaml records {matching[0]}"


def test_there_is_an_encrypted_file_to_check():
    """The check above runs on something: a repository with no encrypted file would pass it silently."""
    assert list(_encrypted_files())


def test_a_file_encrypted_to_an_unrecorded_key_is_refused():
    """The test fails when the defence is off: a file naming a second key does not pass."""
    stray = "age1" + "q" * 58
    block = {"age": [{"recipient": _rules()[0][1][0]}, {"recipient": stray}]}
    with pytest.raises(AssertionError, match="names"):
        test_every_encrypted_file_names_exactly_the_recorded_recipients(ROOT / "x.enc.yaml", block)
