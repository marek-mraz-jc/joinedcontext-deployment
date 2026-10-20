"""T-4769 (owner 2026-10-19T20:45Z): every starting question a public assistant offers has an eval
row in tests/assistant_starters.json, with the numbers its answer must hold and the human page it
must link. joinedcontext-conformance tests/assistant/eval_starters.py asks each one on prod, three
times, from that file."""

import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
STARTERS = json.loads((ROOT / "tests/assistant_starters.json").read_text())["starters"]
DEMO = ROOT / "components/context-gateway/seed/bbsk/bbsk-assistant-demo.yaml"
CATALOGUE = [ROOT / f".ci/example-deployments/environments/{env}/ckan.yaml.gotmpl" for env in ("smartcity", "dev")]
# A page a person reads: a dataset page or an assistant guide of the catalogue, or a page of the
# body's own site.
HUMAN = re.compile(r"https://(opendata\.\{domain\}/(dataset/[a-z0-9-]+|assistants/[a-z]+)|www\.bbsk\.sk/[a-z0-9-]+|www\.idsbbsk\.sk)")
KEYS = {"id", "assistant", "lang", "q", "must", "links", "reference", "source"}


def cards():
    """(publicId, language, question) of every card the seeds offer."""
    found = set()
    demo = yaml.safe_load(DEMO.read_text())["spec"]
    for lang, questions in demo["suggestions"].items():
        found |= {(demo["publicId"], lang, q) for q in questions}
    for values in CATALOGUE:
        catalogue = yaml.safe_load(values.read_text())["ckan"]["catalogue"]
        for lang, questions in catalogue["assistantSeed"]["suggestions"].items():
            found |= {(catalogue["assistant"], lang, q) for q in questions}
    return found


def test_every_starter_has_one_eval_row_and_no_row_is_stale():
    rows = [(r["assistant"], r["lang"], r["q"]) for r in STARTERS]
    assert len(rows) == len(set(rows)), "one row per card and language"
    assert len({r["id"] for r in STARTERS}) == len(STARTERS), "ids are unique"
    offered = cards()
    assert offered - set(rows) == set(), "a card without an eval row"
    assert set(rows) - offered == set(), "an eval row for a card no seed offers"


def test_both_catalogue_environments_offer_the_same_cards():
    seeds = [yaml.safe_load(v.read_text())["ckan"]["catalogue"]["assistantSeed"]["suggestions"] for v in CATALOGUE]
    assert seeds[0] == seeds[1]


def test_each_row_names_what_the_answer_must_hold_and_a_page_a_person_can_open():
    for row in STARTERS:
        assert KEYS <= set(row) <= KEYS | {"live"}, row["id"]
        assert row["must"] and all(group and all(isinstance(a, str) and a for a in group) for group in row["must"]), row["id"]
        assert row["links"] and all(HUMAN.fullmatch(link) for link in row["links"]), row["id"]
        assert row["reference"].strip() and row["source"].strip(), row["id"]
        if "live" in row:
            # A measured value is read from the Endpoint when the eval asks; it has no fixed truth.
            assert set(row["live"]) == {"url", "attr"}, row["id"]
            assert row["live"]["url"].startswith("https://api.{domain}/api/endpoint/"), row["id"]


def test_the_pothole_card_is_gone_and_no_card_needs_a_machine_link():
    # Owner 2026-10-19T20:45Z: the pothole card goes. Prod 2026-10-20: the office hours card cited
    # only schema/index.json, so it is off until its answer links a dataset page.
    demo = yaml.safe_load(DEMO.read_text())["spec"]["suggestions"]
    assert not any(re.search(r"výtlk|pothole", q, re.I) for q in demo["sk"] + demo["en"])
    assert all("/api/endpoint/" not in link for row in STARTERS for link in row["links"])


def test_an_age_question_names_its_year():
    # Prod 2026-10-20: "starších ako 100 rokov" read as built in 1926 or before (51, not 48); a
    # bridge card names the year it counts from.
    for row in STARTERS:
        if re.search(r"most|bridge", row["q"], re.I) and len(row["must"]) > 1:
            assert re.search(r"\b1900\b", row["q"]), row["id"]
