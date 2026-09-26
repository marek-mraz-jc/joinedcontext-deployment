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
import yaml

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
    # CKAN's actions, answered from `page.actions` by name: a callable or an exception to raise.
    page.actions = {}

    def get_action(name):
        def action(context, data_dict):
            answer = page.actions[name]
            if isinstance(answer, Exception):
                raise answer
            return answer(data_dict)
        return action

    for error in ("ObjectNotFound", "NotAuthorized", "ValidationError"):
        setattr(toolkit, error, type(error, (Exception,), {}))
    toolkit.get_action = get_action
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
    assert theme.jc_live({}) is None and theme.jc_resource_sections({}) == [] and theme.jc_more({}) == []
    assert theme.jc_preview({}) is None and theme.jc_formats({}) == []


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


SCHEMA = "https://dev.example/api/endpoint/praha/schema/v1/"

# The resources `jcctl` publishes for an Endpoint, in its order: the DataStore table last.
PUBLISHED_RESOURCES = [
    {"id": "r-ngsi", "name": "NGSI-LD API", "format": "NGSI-LD", "url": ENDPOINT + "ngsi-ld/v1/"},
    {"id": "r-geo", "name": "GeoJSON", "format": "GeoJSON", "url": ENDPOINT + "file.geojson"},
    {"id": "r-csv", "name": "CSV", "format": "CSV", "url": ENDPOINT + "file.csv"},
    {"id": "r-mcp", "name": "Model Context Protocol", "format": "MCP", "url": ENDPOINT + "mcp"},
    {"id": "r-index", "name": "Schema artifacts", "format": "JSON", "url": ENDPOINT + "schema/index.json"},
    {"id": "r-shacl", "name": "model.shacl.ttl", "format": "SHACL", "url": SCHEMA + "model.shacl.ttl"},
    {"id": "r-ctx", "name": "context.jsonld", "format": "JSON-LD", "url": SCHEMA + "context.jsonld?v=1"},
    {"id": "r-odd", "name": "Unlabelled", "format": "", "url": ENDPOINT + "other"},
    {"id": "r-table", "name": "DataStore", "format": "CSV", "url": "https://data.dev.example/datastore/dump/r-table",
     "datastore_active": True},
]


def test_the_datastore_table_leads_the_files_and_the_model_is_a_section_of_its_own(theme):
    """T-3009: the DataStore resource was the last of fourteen links; it leads the data now."""
    sections = theme.jc_resource_sections({"resources": PUBLISHED_RESOURCES})
    ids = {s["key"]: [i["resource"]["id"] for i in s["items"]] for s in sections}
    assert [s["key"] for s in sections] == ["data", "api", "schema"]
    assert ids["data"] == ["r-table", "r-csv", "r-geo", "r-odd"]
    assert ids["api"] == ["r-ngsi", "r-mcp"]
    # Everything under the Endpoint's /schema/ path is the model, whatever format it names.
    assert sorted(ids["schema"]) == ["r-ctx", "r-index", "r-shacl"]
    data = sections[0]["items"]
    assert data[0]["what"] == "The table above, as one file"
    assert data[1]["what"] == "A table for a spreadsheet"
    assert data[-1]["format"] == "—" and data[-1]["what"] == ""
    assert sections[2]["title"] == "Data model" and sections[1]["lead"]


def test_a_dataset_with_only_files_has_one_section_and_a_search_result_names_no_model_format(theme):
    files = [r for r in PUBLISHED_RESOURCES if r["id"] in ("r-csv", "r-geo")]
    assert [s["key"] for s in theme.jc_resource_sections({"resources": files})] == ["data"]
    assert theme.jc_formats({"resources": PUBLISHED_RESOURCES}) == ["CSV", "GeoJSON", "NGSI-LD", "MCP"]


def test_the_page_frames_the_datastore_table_with_its_row_count(theme):
    theme.page.actions = {
        "resource_view_list": lambda d: [{"id": "v-image", "view_type": "image_view"},
                                         {"id": "v-table", "view_type": "datatables_view"}],
        "datastore_search": lambda d: {"total": 25108} if d == {"resource_id": "r-table", "limit": 0} else {},
    }
    preview = theme.jc_preview({"resources": PUBLISHED_RESOURCES})
    assert preview["resource"]["id"] == "r-table"
    assert preview["view"]["id"] == "v-table" and preview["total"] == 25108
    assert theme.jc_number(preview["total"]) == "25\u202f108"


def test_a_table_without_a_view_or_a_count_still_shows_and_says_so(theme, tmp_path):
    theme.page.actions = {
        "resource_view_list": theme.toolkit.NotAuthorized(),
        "datastore_search": theme.toolkit.ObjectNotFound(),
    }
    preview = theme.jc_preview({"resources": PUBLISHED_RESOURCES})
    assert preview == {"resource": PUBLISHED_RESOURCES[-1], "view": None, "total": None}
    assert theme.jc_number(None) == "" and theme.jc_number("x") == ""
    read = (THEME / "templates__package__read.html").read_text()
    assert "h.jc_t('no_view')" in read and "preview.total is not none" in read


def test_the_table_comes_before_the_about_list_on_the_dataset_page():
    read = (THEME / "templates__package__read.html").read_text()
    assert read.index("h.jc_preview(pkg)") < read.index("h.jc_about(pkg)") < read.index("h.jc_live(pkg)")
    # The framed table carries a title a screen reader announces.
    assert re.search(r"<iframe[^>]*title=\"\{\{ h.jc_t\('table_title'\) \}\}", read)


def test_each_resource_has_its_one_action_named_for_a_screen_reader():
    item = (THEME / "templates__package__snippets__resource_item.html").read_text()
    assert "dropdown" not in item and "{{ _('Explore') }}" not in item
    assert "h.jc_t('open') if jc_section == 'api' else h.jc_t('download')" in item
    assert item.count('<span class="visually-hidden"> {{ name }}</span>') == 2
    assert "{% if not url_is_edit %}" in item


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


# --- T-2888: the catalogue wears the installation's look, and a failed sign-in says why ---------


def test_the_brand_colour_reaches_bootstrap_and_its_text_stays_legible(theme, tmp_path):
    assert theme.BRANDING["primaryRgb"] == "29, 78, 216"
    assert theme.BRANDING["primaryForeground"] == "#ffffff"
    light = tmp_path / "light.json"
    light.write_text(json.dumps({"colours": {"primary": "#ffe977"}}))
    theme.BRANDING_FILE = str(light)
    block = theme._load()
    assert block["primaryRgb"] == "255, 233, 119"
    # White on a pale yellow is unreadable; the login theme's YIQ rule gives black.
    assert block["primaryForeground"] == "#000000"
    short = tmp_path / "short.json"
    short.write_text(json.dumps({"colours": {"primary": "#00f"}}))
    theme.BRANDING_FILE = str(short)
    assert theme._load()["primaryRgb"] == "0, 0, 255"


STOCK_TEALS = r"#206b82|#187794|#1a5668|#005d7a|#003647|#00232e|#bfd7de|#d9e7eb|#000f14"


def test_no_stock_ckan_colour_survives_the_theme():
    """CKAN compiles its teal into its own rules; each group of them is restated on the brand."""
    css = (THEME / "public__jc-theme.css").read_text()
    for variable in ("--bs-primary: var(--jc-primary)", "--bs-primary-rgb: var(--jc-primary-rgb)",
                     "--bs-link-color: var(--jc-primary)"):
        assert variable in css, variable
    for rule in (".btn-link, .link-primary", ".btn-primary:hover", ".form-check-input:checked",
                 ".form-control:focus", ".masthead .main-navbar ul li:hover a", ".view-list li a.active .icon",
                 ".account-masthead {", ".dropdown-item.active", ".page-item.active .page-link",
                 "body.dt-view .page-item.active .page-link"):
        assert rule in css, rule
    for path in THEME.iterdir():
        if path.suffix in (".html", ".css"):
            assert not re.search(STOCK_TEALS, path.read_text(), re.I), path.name


def test_the_stylesheet_carries_no_colour_of_its_own():
    """T-3009: every colour is the branding block's or mixed from it, so values restyle it all."""
    css = (THEME / "public__jc-theme.css").read_text()
    assert not re.search(r"#[0-9a-f]{3,8}\b|\brgba?\(|\bhsla?\(", css, re.I)
    named = re.findall(r":\s*(white|black|red|blue|green|gray|grey|navy|teal)\b", css, re.I)
    assert not named, named
    styles = (THEME / "templates__snippets__jc_styles.html").read_text()
    for token in ("--jc-primary:", "--jc-primary-fg:", "--jc-primary-rgb:", "--jc-secondary:", "--jc-accent:",
                  "--jc-background:", "--jc-text:", "--jc-font-heading:", "--jc-font-body:"):
        assert token in styles, token
    assert "h.url_for_static('/jc-theme.css')" in styles


def test_the_table_view_wears_the_theme_and_the_theme_s_templates_win():
    """The table view's own template empties the styles block; the theme restores it there, and
    only the first plugin's templates outrank the table view's."""
    view = (THEME / "templates__datatables__datatables_view.html").read_text()
    assert "{% ckan_extends %}" in view and "snippets/jc_styles.html" in view
    assert "snippets/jc_styles.html" in (THEME / "templates__base.html").read_text()
    values = yaml.safe_load((PROJECT_ROOT / "charts/ckan/values.yaml").read_text())
    assert values["ckan"]["plugins"].split()[0] == "jc_theme"


def test_the_home_page_replaces_ckan_s_sample_page():
    home = (THEME / "templates__home__index.html").read_text()
    assert "{% block primary_content %}" in home
    for part in ("brand.tagline or h.jc_t('tagline')", "h.get_site_statistics()", "h.jc_recent(6)",
                 "get_facet_items_dict('organization'", 'role="search"', '<label for="jc-hero-q">'):
        assert part in home, part
    assert "home/snippets/" not in home


def test_tagline_and_footer_lines_are_read_as_words_and_nothing_else(theme, tmp_path):
    assert theme.BRANDING["tagline"] == "" and theme.BRANDING["footerLines"] == []
    block = tmp_path / "words.json"
    block.write_text(json.dumps({"tagline": "Open data of the city",
                                 "footerLines": ["Demo instance, not affiliated.", "", "  ", 7, None]}))
    theme.BRANDING_FILE = str(block)
    loaded = theme._load()
    assert loaded["tagline"] == "Open data of the city"
    assert loaded["footerLines"] == ["Demo instance, not affiliated."]
    block.write_text(json.dumps({"tagline": {"x": 1}, "footerLines": "not a list"}))
    loaded = theme._load()
    assert loaded["tagline"] == "" and loaded["footerLines"] == []


def test_the_footer_carries_the_installations_links_and_none_of_ckans():
    footer = (THEME / "footer.html").read_text()
    assert "{% block footer_links_ckan %}{% endblock %}" in footer
    for stock in ("docs.ckan.org", "ckan.org", "opendefinition", "od_80x15"):
        assert stock not in footer, stock
    assert "h.jc_t('about_site')" in footer and "h.jc_portal_url()" in footer
    # The demo disclaimer stays: the organisation line, and the footer lines of the block.
    assert "brand.organisation" in footer and "brand.footerLines" in footer


def test_a_second_deployment_restyles_the_catalogue_from_values_alone(rendered, rendered_variant):
    """T-3009: a new palette, logo, tagline and footer reach the theme with no file of it edited."""
    logo = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><rect width="1" height="1" fill="#8a1538"/></svg>'

    def rebrand(tree):
        env = tree / "deployment/environments/dev/global.yaml.gotmpl"
        text = env.read_text()
        assert "primary: '#0000bf'" in text
        text = text.replace("primary: '#0000bf'", "primary: '#8a1538'")
        text = text.replace("    logo: logo.svg\n", "    logo: logo.svg\n    tagline: Otvorené dáta mesta\n"
                            "    footerLines:\n      - Demo, not affiliated.\n", 1)
        env.write_text(text)
        (tree / "deployment/environments/dev/branding/logo.svg").write_text(logo + "\n")

    def theme_of(docs):
        (cm,) = [d for d in docs if d.get("kind") == "ConfigMap" and d["metadata"]["name"] == "ckan-theme"]
        (ckan,) = [d for d in docs if d.get("kind") == "Deployment" and d["metadata"]["name"] == "ckan"]
        return cm["data"], ckan["spec"]["template"]["metadata"]["annotations"]["checksum/theme"]

    before, before_sum = theme_of(rendered("dev"))
    after, after_sum = theme_of(rendered_variant("dev", rebrand))
    branding = json.loads(after["branding.json"])
    assert branding["colours"]["primary"] == "#8a1538"
    assert branding["tagline"] == "Otvorené dáta mesta" and branding["footerLines"] == ["Demo, not affiliated."]
    assert after["logo.svg"].strip() == logo
    # The theme's own files are byte for byte the same: only the values changed.
    assert {k: v for k, v in after.items() if k not in ("branding.json", "logo.svg")} == \
        {k: v for k, v in before.items() if k not in ("branding.json", "logo.svg")}
    # And the pod restarts to show it.
    assert after_sum != before_sum


@pytest.mark.parametrize("reason, key", [
    ("Login process was not started properly", "sso_cookie"),
    ("The app state does not match", "sso_state"),
    ("Unsupported token type. Should be 'Bearer'.", "sso_refused"),
    ("No access token returned from the token endpoint.", "sso_refused"),
    ("Unique user not found", "sso_account"),
    ("access_denied", "sso_other"),
])
def test_a_failed_sign_in_says_why_once_in_words_a_person_acts_on(theme, reason, key):
    session = {theme.SSO_ERROR: reason}
    assert theme.jc_sso_error(session) == theme.STRINGS[key]["en"]
    # Said once: a reload of the login page does not repeat an old failure.
    assert theme.jc_sso_error(session) is None
    theme.page.lang = "sk"
    session[theme.SSO_ERROR] = reason
    assert theme.jc_sso_error(session) == theme.STRINGS[key]["sk"]


def test_a_sign_in_that_did_not_fail_says_nothing(theme):
    assert theme.jc_sso_error({}) is None


def test_the_login_page_shows_the_reason_as_an_alert():
    login = (THEME / "templates__user__login.html").read_text()
    assert "h.jc_sso_error()" in login and 'role="alert"' in login
