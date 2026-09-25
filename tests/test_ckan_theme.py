"""T-2744 (DS-01, UI-82): the catalogue's dataset pages are written for people.

`ckanext_jc_theme/plugin.py` turns a dataset's CKAN fields and the extras `jcctl` publishes
(crates/jcctl/src/publish/ckan.rs) into labelled rows, the live API box and resources grouped
by format. The helpers are plain functions, so they are tested here against a stand-in for
the two CKAN modules they import; the templates that call them were walked on a CKAN 2.11.6
(the image's base) with axe clean on every page.
"""

import importlib.util
import json
import re
import sys
import types
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
THEME = PROJECT_ROOT / "charts/ckan/files/jc_theme"


@pytest.fixture
def theme(tmp_path, monkeypatch):
    """The plugin module, loaded with a branding block for `dev.example` and the page in `lang`."""
    branding = tmp_path / "branding.json"
    branding.write_text(json.dumps({"domain": "dev.example", "instanceName": "joinedcontext"}))
    monkeypatch.setenv("JC_BRANDING_FILE", str(branding))

    page = types.SimpleNamespace(lang="en")
    toolkit = types.ModuleType("ckan.plugins.toolkit")
    toolkit.h = types.SimpleNamespace(lang=lambda: page.lang)
    plugins = types.ModuleType("ckan.plugins")
    plugins.toolkit = toolkit
    plugins.SingletonPlugin = object
    plugins.implements = lambda *args, **kwargs: None
    plugins.IConfigurer = plugins.ITemplateHelpers = plugins.IFacets = object
    ckan = types.ModuleType("ckan")
    ckan.__file__ = str(tmp_path / "ckan/__init__.py")
    ckan.plugins = plugins
    for name, module in (("ckan", ckan), ("ckan.plugins", plugins), ("ckan.plugins.toolkit", toolkit)):
        monkeypatch.setitem(sys.modules, name, module)

    # No __pycache__ beside the theme: the chart ships every file of that directory.
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    spec = importlib.util.spec_from_file_location("jc_theme_plugin", THEME / "plugin.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.page = page
    return module


ENDPOINT = "https://dev.example/api/endpoint/hkiair/"

PUBLISHED = {
    "metadata_modified": "2026-09-25T08:00:00.000000",
    "organization": {"name": "helsinki", "title": "City of Helsinki"},
    "license_id": "cc-by",
    "license_title": "Creative Commons Attribution",
    "license_url": "http://www.opendefinition.org/licenses/cc-by",
    "groups": [{"display_name": "Environment"}],
    "tags": [{"display_name": "air quality"}, {"display_name": "pollution"}],
    "extras": [
        {"key": "frequency", "value": "http://publications.europa.eu/resource/authority/frequency/DAILY"},
        {"key": "publisher_name", "value": "Environment Services"},
        {"key": "publisher_uri", "value": "https://www.hel.fi/"},
        {"key": "contact_email", "value": "data@hel.fi"},
        {"key": "temporal_start", "value": "2024-01-01"},
        {"key": "endpoint", "value": ENDPOINT},
        {"key": "generated_by", "value": "jcctl/ckan-publisher"},
        {"key": "source_note", "value": "Measured by HSY"},
    ],
    "resources": [
        {"format": "CSV"}, {"format": "NGSI-LD"}, {"format": "csv"}, {"format": ""},
    ],
}


def test_the_about_list_names_publisher_licence_and_freshness_in_plain_words(theme):
    rows = {label: (text, link) for label, text, link in theme.jc_about(PUBLISHED)}
    assert rows["Publisher"] == ("Environment Services", "https://www.hel.fi/")
    assert rows["Licence"] == ("Creative Commons Attribution", "http://www.opendefinition.org/licenses/cc-by")
    assert rows["Topic"] == ("Environment", None)
    assert rows["Keywords"] == ("air quality, pollution", None)
    assert rows["Updated"] == ("Every day", None)
    assert rows["Last update"] == ("2026-09-25", None)
    assert rows["Next update expected"] == ("2026-09-26", None)
    assert rows["Contact"] == ("data@hel.fi", "mailto:data@hel.fi")
    assert rows["Time covered"] == ("2024-01-01", None)


def test_an_hourly_dataset_promises_an_hour_and_an_irregular_one_no_date(theme):
    hourly = dict(PUBLISHED, extras=[{"key": "frequency", "value": "HOURLY"}])
    rows = {label: text for label, text, _ in theme.jc_about(hourly)}
    assert rows["Next update expected"] == "2026-09-25 09:00 UTC"
    irregular = dict(PUBLISHED, extras=[{"key": "frequency", "value": ".../frequency/IRREG"}])
    rows = {label: text for label, text, _ in theme.jc_about(irregular)}
    assert rows["Updated"] == "Irregularly" and "Next update expected" not in rows
    label, next_update = theme.jc_frequency(dict(PUBLISHED, metadata_modified="not a date"))
    assert (label, next_update) == ("Every day", None)


def test_a_bare_dataset_shows_only_what_it_has_and_the_publisher_falls_back_to_the_organization(theme):
    assert theme.jc_about({}) == []
    bare = {"organization": {"name": "helsinki", "title": "City of Helsinki"}}
    assert theme.jc_about(bare) == [("Publisher", "City of Helsinki", None)]
    assert theme.jc_live({}) is None and theme.jc_resource_groups({}) == [] and theme.jc_more({}) == []


def test_a_link_that_is_not_http_is_shown_as_text(theme):
    hostile = dict(PUBLISHED, license_url="javascript:alert(1)",
                   extras=[{"key": "publisher_name", "value": "X"}, {"key": "publisher_uri", "value": "javascript:alert(1)"}])
    for _, _, link in theme.jc_about(hostile):
        assert link is None or link.startswith(("https://", "http://", "mailto:")), link


def test_the_live_box_shows_only_an_https_address_of_the_platform_and_a_query_that_answers(theme):
    live = theme.jc_live(PUBLISHED)
    assert live["url"] == ENDPOINT
    assert live["example"].endswith(f"'{ENDPOINT}ngsi-ld/v1/types'")
    for endpoint in ("http://dev.example/api/endpoint/x/", "https://context-gateway.jc.svc:8080/x/",
                     "https://dev.example.evil/x/", "https://evildev.example/x/"):
        foreign = dict(PUBLISHED, extras=[{"key": "endpoint", "value": endpoint}])
        assert theme.jc_live(foreign) is None, endpoint
    sub = dict(PUBLISHED, extras=[{"key": "endpoint", "value": "https://api.dev.example/e/x"}])
    assert theme.jc_live(sub)["url"] == "https://api.dev.example/e/x/"


def test_internal_extras_never_reach_more_details(theme):
    assert theme.jc_more(PUBLISHED) == [("source_note", "Measured by HSY")]


def test_resources_are_grouped_by_format_with_what_each_is_for(theme):
    groups = theme.jc_resource_groups(PUBLISHED)
    assert [(g["format"], len(g["resources"])) for g in groups] == [("CSV", 1), ("csv", 1), ("NGSI-LD", 1), ("—", 1)]
    assert groups[0]["what"] == "A table for a spreadsheet"
    assert groups[-1]["what"] == ""


@pytest.mark.parametrize("lang, words", [
    ("sk", ("Vydavateľ", "Denne")), ("cs_CZ", ("Vydavatel", "Denně")), ("de", ("Herausgeber", "Täglich")), ("fi", ("Publisher", "Every day")),
])
def test_the_page_language_picks_the_words_and_an_unknown_one_reads_english(theme, lang, words):
    theme.page.lang = lang
    rows = dict((label, text) for label, text, _ in theme.jc_about(PUBLISHED))
    assert words[0] in rows and rows[words[0]] == "Environment Services"
    assert words[1] in rows.values()


def test_every_word_of_the_theme_is_in_all_four_languages(theme):
    for table in (theme.STRINGS, theme.FORMATS):
        for key, words in table.items():
            assert set(words) == {"en", "sk", "cs", "de"}, key
    for key, (words, _) in theme.FREQUENCIES.items():
        assert set(words) == {"en", "sk", "cs", "de"}, key


def test_the_search_filters_are_named_in_plain_words(theme):
    facets = {"organization": "Organizations", "groups": "Groups", "tags": "Tags", "res_format": "Formats", "license_id": "Licenses"}
    renamed = theme.JcThemePlugin().dataset_facets(dict(facets), "dataset")
    assert renamed == {"organization": "Publisher", "groups": "Topic", "tags": "Keywords", "res_format": "Format", "license_id": "Licence"}


def test_the_portal_link_is_on_the_installation_s_domain(theme):
    assert theme.jc_portal_url() == "https://portal.dev.example/"


def test_every_page_template_and_static_file_is_mounted_at_its_path(rendered):
    (ckan,) = [d for d in rendered("dev") if d.get("kind") == "Deployment" and d["metadata"]["name"].endswith("ckan")
               and any(c["name"] == "ckan" for c in d["spec"]["template"]["spec"]["containers"])]
    (container,) = [c for c in ckan["spec"]["template"]["spec"]["containers"] if c["name"] == "ckan"]
    mounts = {m["subPath"]: m["mountPath"] for m in container["volumeMounts"] if m["name"] == "theme"}
    files = [p.name for p in THEME.iterdir() if p.name.startswith(("templates__", "public__"))]
    assert files, "the theme has page templates"
    for name in files:
        assert mounts[name] == "/srv/theme/ckanext_jc_theme/" + name.replace("__", "/"), name
    assert "__init__.py" in mounts and mounts["__init__.py"].endswith("ckanext_jc_theme/__init__.py")


def test_the_theme_loads_nothing_from_another_origin():
    for path in THEME.iterdir():
        if path.suffix == ".py":
            continue
        text = path.read_text()
        assert not re.search(r"<script>|(src|href)=\"(https?:)?//|(?<!\w)url\(|@import", text), path.name
