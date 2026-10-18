"""scripts/ckan-restore-issued.py (T-4644): the source's own date first, the platform's first commit
next, nothing invented; a dry run writes nothing and a second run finds nothing to do."""
import importlib.util
import pathlib
import subprocess

SCRIPT = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "ckan-restore-issued.py"
NKOD_SET = "https://data.gov.sk/set/aaaa"
SOURCE = "https://data.statistics.sk/api/v2/dataset/sk1001rs/all?lang=sk&type=json"


def load():
    spec = importlib.util.spec_from_file_location("restore_issued", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def repo(tmp_path, text):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "values.yaml").write_text(text)
    env = {"GIT_AUTHOR_DATE": "2026-09-20T10:00:00Z", "GIT_COMMITTER_DATE": "2026-09-20T10:00:00Z",
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x"}
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "add"], check=True, env=env)
    return str(tmp_path)


def pkg(name, created="2026-10-17T17:31:52.1", **extra):
    return {"id": "id-" + name, "name": name, "metadata_created": created,
            "extras": [{"key": k, "value": v} for k, v in extra.items()]}


class Catalogue:
    def __init__(self, packages):
        self.packages, self.writes = packages, []

    def __call__(self, base, action, payload=None, token=None):
        if action == "package_search":
            return {"count": len(self.packages), "results": self.packages[payload["start"]:payload["start"] + payload["rows"]]}
        assert action == "package_patch" and token == "secret"
        self.writes.append(payload)
        target = next(p for p in self.packages if p["id"] == payload["id"])
        target["extras"] = payload["extras"]
        return target


def test_the_source_date_wins_then_the_first_commit_and_no_evidence_changes_nothing(tmp_path):
    restore = load()
    restore.sparql = lambda query: [{"ds": NKOD_SET, "issued": "2015-12-30T15:10:37Z"}] if SOURCE in query else []
    catalogue = Catalogue([
        pkg("susr-sk", source=f'[{{"url": "{SOURCE}", "title": "ŠÚ SR"}}]', identifier="slugsk"),
        pkg("bb-mosty", identifier="mostyslug0123456789"),
        pkg("hub-harvested", issued="2019-04-02T10:00:00Z"),
        pkg("brand-new", identifier="neverinthehistory"),
        pkg("later-commit", created="2026-09-01T00:00:00", identifier="mostyslug0123456789"),
    ])
    restore.ckan = catalogue
    history = repo(tmp_path, "endpoints:\n  - slug: mostyslug0123456789\n")

    rows = {r[0]: r[2:] for r in restore.restore("https://ckan", history, write=False)}
    assert rows["susr-sk"] == ("2015-12-30T15:10:37Z", f"NKOD {NKOD_SET} dct:issued", "would write")
    assert rows["bb-mosty"][0] == "2026-09-20T10:00:00Z" and rows["bb-mosty"][2] == "would write"
    assert rows["hub-harvested"] == ("2019-04-02T10:00:00Z", "issued already set", "kept")
    assert rows["brand-new"] == (None, "no evidence", "unchanged")
    # Evidence later than CKAN's own date is no earlier origin: the dataset keeps its date.
    assert rows["later-commit"][0] is None and rows["later-commit"][2] == "unchanged"
    assert catalogue.writes == [], "a dry run wrote"

    restore.restore("https://ckan", history, write=True, token="secret")
    assert [w["id"] for w in catalogue.writes] == ["id-bb-mosty", "id-susr-sk"]
    susr = next(p for p in catalogue.packages if p["name"] == "susr-sk")
    assert susr["extras"][-1] == {"key": "issued", "value": "2015-12-30T15:10:37Z"}
    assert susr["extras"][0]["key"] == "source", "the other extras survive the patch"

    again = restore.restore("https://ckan", history, write=True, token="secret")
    assert len(catalogue.writes) == 2 and {r[4] for r in again} <= {"kept", "unchanged"}


def test_a_name_inside_a_longer_one_is_no_evidence(tmp_path):
    restore = load()
    history = repo(tmp_path, "datasets: [susr-sk-extra]\n")
    assert restore.first_commit(history, pkg("susr-sk")) is None
    assert restore.first_commit(history, pkg("susr-sk-extra"))[0] == "2026-09-20T10:00:00Z"


def test_a_date_that_does_not_read_is_none():
    restore = load()
    assert restore.iso("unknown") is None
    assert restore.iso("2022-05-12T00:00:00") == "2022-05-12T00:00:00Z"
    assert restore.iso("2021-07-13T18:43:22+02:00") == "2021-07-13T16:43:22Z"
