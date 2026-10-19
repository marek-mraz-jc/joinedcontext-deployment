"""Every attribute a visitor sees has a heading in their language, never its camelCase name (T-4682).

The hand models carry sk, cs, en and de labels on every slot and enum value; a generated catalogue
model carries the source column's own Slovak heading where the column is one, at no model cost.
"""

import importlib.util
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
SEED = ROOT / "components/context-gateway/seed"
CAMEL = re.compile(r"[a-z][A-Z]")

spec = importlib.util.spec_from_file_location("generate_od", ROOT / "scripts/open-data/generate.py")
generate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generate)


def label(node: dict | None) -> dict | None:
    found = ((node or {}).get("annotations") or {}).get("label")
    return found.get("value", found) if isinstance(found, dict) else None


@pytest.mark.parametrize("model", ["bbsk/bbsk-registre", "zilina/zilina-verejne"])
def test_every_slot_and_enum_value_of_a_hand_model_reads_in_sk_and_en(model):
    schema = yaml.safe_load((SEED / f"{model}.linkml.yaml").read_text())
    for name, slot in schema["slots"].items():
        words = label(slot)
        assert words, f"{model}: {name} has no label"
        for lang in ("sk", "en"):
            assert words.get(lang) and words[lang] != name and not CAMEL.search(words[lang]), (model, name, lang)
    for enum, about in (schema.get("enums") or {}).items():
        for value, said in about["permissible_values"].items():
            words = label(said)
            assert words and words.get("sk") and words.get("en") and words["sk"] != value, (enum, value)


def test_the_bike_stations_the_widget_lists_read_in_sk_and_en():
    schema = yaml.safe_load((SEED / "helsinki/helsinki.linkml.yaml").read_text())
    station = schema["classes"]["BikeHireDockingStation"]
    for name in station["slots"]:
        words = label((station.get("slot_usage") or {}).get(name)) or label(schema["slots"].get(name))
        assert words and words.get("sk") and words.get("en"), name


@pytest.mark.parametrize(("column", "heading"), [
    ("Dĺžka_premostenia__m_", "Dĺžka premostenia (m)"),
    ("Rok_výstavby", "Rok výstavby"),
    ("Cena_celkom", "Cena celkom"),
    ("Č._zasadnutia", "Č. zasadnutia"),
    ("IČO", "IČO"),
    ("KRAJ_ID", None), ("datumzmeny", None), ("TypSaSZKod", None), ("content", None), ("dlzka_VU_1", None),
])
def test_a_source_column_that_is_a_slovak_heading_becomes_the_sk_label_and_a_code_does_not(column, heading):
    assert generate.heading(column) == heading


def test_the_generated_catalogue_models_carry_those_headings():
    schema = yaml.safe_load((SEED / "bbsk/bbsk-otvorene-data.linkml.yaml").read_text())
    assert label(schema["slots"]["dlzkaPremosteniaM"]) == {"sk": "Dĺžka premostenia (m)"}
    assert label(schema["slots"]["source"])["en"] == "Source"
    labelled = [s for s in schema["slots"].values() if label(s)]
    assert all(not CAMEL.search(label(s)["sk"]) for s in labelled)
    assert len(labelled) > len(schema["slots"]) / 2
