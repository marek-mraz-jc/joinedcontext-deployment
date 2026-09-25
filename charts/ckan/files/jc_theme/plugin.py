"""Renders any branding block (OPS-47).

The block is read once at start-up from the file the chart mounts. A missing or broken
file is not an error: CKAN then looks like a plain CKAN, which is what an installation
without branding should look like.
"""

import datetime
import json
import os

import ckan
import ckan.plugins as plugins
import ckan.plugins.toolkit as toolkit

BRANDING_FILE = os.environ.get("JC_BRANDING_FILE", "/etc/jc/branding/branding.json")

NEUTRAL = {
    "instanceName": "joinedcontext",
    "shortName": "joinedcontext",
    "organisation": "",
    "contactEmail": "",
    "logo": "",
    "colours": {
        "primary": "#1d4ed8",
        "secondary": "#0f766e",
        "accent": "#f59e0b",
        "background": "#ffffff",
        "text": "#0f172a",
    },
    "fonts": {"heading": "system-ui, sans-serif", "body": "system-ui, sans-serif"},
    "languages": {"default": "en", "offered": ["en"]},
    "primaryForeground": "#ffffff",
}

HEX = set("0123456789abcdefABCDEF")


def _is_colour(value):
    """`#rgb` or `#rrggbb`. A custom property is a value the browser evaluates, so
    nothing else may reach a stylesheet."""
    return (
        isinstance(value, str)
        and value.startswith("#")
        and len(value) in (4, 7)
        and all(character in HEX for character in value[1:])
    )


def _load():
    try:
        with open(BRANDING_FILE, encoding="utf-8") as handle:
            block = json.load(handle)
    except (OSError, ValueError):
        return dict(NEUTRAL)
    if not isinstance(block, dict):
        return dict(NEUTRAL)
    branding = dict(NEUTRAL)
    branding.update(block)
    colours = dict(NEUTRAL["colours"])
    for name, value in (branding.get("colours") or {}).items():
        if _is_colour(value):
            colours[name] = value
    branding["colours"] = colours
    red, green, blue = _rgb(colours["primary"])
    branding["primaryRgb"] = "%d, %d, %d" % (red, green, blue)
    # The text on the primary colour, by the YIQ rule the login theme uses too
    # (components/keycloak/charts/theme), so a light brand colour gets dark text.
    branding["primaryForeground"] = "#000000" if (red * 299 + green * 587 + blue * 114) // 1000 >= 128 else "#ffffff"
    return branding


def _rgb(colour):
    """`#rgb` or `#rrggbb` as three integers, for Bootstrap's `--bs-primary-rgb`."""
    digits = colour[1:]
    if len(digits) == 3:
        digits = "".join(character * 2 for character in digits)
    return tuple(int(digits[index:index + 2], 16) for index in (0, 2, 4))


def _available(codes):
    """The subset of `codes` CKAN can actually serve, in the order given.

    A locale CKAN does not ship makes it exit at start-up with "Locale(s) not available".
    The branding block is written by whoever deploys, not by whoever wrote CKAN, so an
    unsupported code narrows the language switcher instead of taking the catalogue down.
    """
    directory = os.path.join(os.path.dirname(ckan.__file__), "i18n")
    try:
        installed = set(os.listdir(directory))
    except OSError:
        installed = set()
    # English is the source language and has no catalogue of its own.
    installed.add("en")
    seen, out = set(), []
    for code in codes:
        if isinstance(code, str) and code in installed and code not in seen:
            seen.add(code)
            out.append(code)
    return out


BRANDING = _load()

# The words the theme adds to CKAN's own, in the four languages of the Portal (UI-82). CKAN's
# catalogues translate everything else; a language CKAN names `cs_CZ` reads the `cs` column.
STRINGS = {
    "about": {"en": "About this dataset", "sk": "O tomto datasete", "cs": "O této datové sadě", "de": "Über diesen Datensatz"},
    "publisher": {"en": "Publisher", "sk": "Vydavateľ", "cs": "Vydavatel", "de": "Herausgeber"},
    "licence": {"en": "Licence", "sk": "Licencia", "cs": "Licence", "de": "Lizenz"},
    "topic": {"en": "Topic", "sk": "Téma", "cs": "Téma", "de": "Thema"},
    "keywords": {"en": "Keywords", "sk": "Kľúčové slová", "cs": "Klíčová slova", "de": "Schlagwörter"},
    "format": {"en": "Format", "sk": "Formát", "cs": "Formát", "de": "Format"},
    "frequency": {"en": "Updated", "sk": "Aktualizácia", "cs": "Aktualizace", "de": "Aktualisierung"},
    "last_update": {"en": "Last update", "sk": "Posledná aktualizácia", "cs": "Poslední aktualizace", "de": "Letzte Aktualisierung"},
    "next_update": {"en": "Next update expected", "sk": "Ďalšia aktualizácia", "cs": "Další aktualizace", "de": "Nächste Aktualisierung"},
    "coverage": {"en": "Area covered", "sk": "Pokryté územie", "cs": "Pokryté území", "de": "Abgedecktes Gebiet"},
    "period": {"en": "Time covered", "sk": "Obdobie", "cs": "Období", "de": "Zeitraum"},
    "contact": {"en": "Contact", "sk": "Kontakt", "cs": "Kontakt", "de": "Kontakt"},
    "identifier": {"en": "Identifier", "sk": "Identifikátor", "cs": "Identifikátor", "de": "Kennung"},
    "language": {"en": "Language", "sk": "Jazyk", "cs": "Jazyk", "de": "Sprache"},
    "conforms_to": {"en": "Follows the standard", "sk": "Zodpovedá štandardu", "cs": "Odpovídá standardu", "de": "Folgt dem Standard"},
    "status": {"en": "Status", "sk": "Stav", "cs": "Stav", "de": "Status"},
    "live": {"en": "Live data (API)", "sk": "Živé dáta (API)", "cs": "Živá data (API)", "de": "Live-Daten (API)"},
    "live_lead": {
        "en": "The current state of this data, answered by the platform on every request (NGSI-LD).",
        "sk": "Aktuálny stav týchto dát, ktorý platforma vracia pri každej požiadavke (NGSI-LD).",
        "cs": "Aktuální stav těchto dat, který platforma vrací při každém požadavku (NGSI-LD).",
        "de": "Der aktuelle Stand dieser Daten, von der Plattform bei jeder Anfrage beantwortet (NGSI-LD).",
    },
    "example": {"en": "Start here: the kinds of entities it holds", "sk": "Začnite tu: aké druhy entít obsahuje", "cs": "Začněte zde: jaké druhy entit obsahuje", "de": "Hier beginnen: welche Arten von Entitäten es enthält"},
    "copy": {"en": "Copy", "sk": "Kopírovať", "cs": "Kopírovat", "de": "Kopieren"},
    "copied": {"en": "Copied", "sk": "Skopírované", "cs": "Zkopírováno", "de": "Kopiert"},
    "resources": {"en": "Data and downloads", "sk": "Dáta na stiahnutie", "cs": "Data ke stažení", "de": "Daten und Downloads"},
    "no_resources": {"en": "This dataset has no downloads yet.", "sk": "Tento dataset zatiaľ nemá nič na stiahnutie.", "cs": "Tato datová sada zatím nemá nic ke stažení.", "de": "Dieser Datensatz hat noch keine Downloads."},
    "empty": {
        "en": "Nothing matches. Try fewer or other words, or remove a filter on the left.",
        "sk": "Nič nezodpovedá. Skúste menej alebo iné slová, alebo zrušte filter vľavo.",
        "cs": "Nic neodpovídá. Zkuste méně nebo jiná slova, nebo zrušte filtr vlevo.",
        "de": "Nichts gefunden. Versuchen Sie weniger oder andere Wörter, oder entfernen Sie links einen Filter.",
    },
    "portal": {"en": "Portal", "sk": "Portál", "cs": "Portál", "de": "Portal"},
    "about_site": {"en": "About this catalogue", "sk": "O tomto katalógu", "cs": "O tomto katalogu", "de": "Über diesen Katalog"},
    "catalogue_api": {"en": "Catalogue API", "sk": "API katalógu", "cs": "API katalogu", "de": "Katalog-API"},
    # What a failed single sign-on says (T-2888). The extension keeps its reason in the session
    # and shows it nowhere, so the person was sent back to the login page without a word.
    "sso_cookie": {
        "en": "The sign-in could not finish: this browser did not keep the catalogue's cookie from the start of the sign-in. Allow cookies for this site and sign in again.",
        "sk": "Prihlásenie sa nedokončilo: prehliadač si neponechal súbor cookie katalógu zo začiatku prihlásenia. Povoľte súbory cookie pre túto stránku a prihláste sa znova.",
        "cs": "Přihlášení se nedokončilo: prohlížeč si neponechal soubor cookie katalogu ze začátku přihlášení. Povolte soubory cookie pro tento web a přihlaste se znovu.",
        "de": "Die Anmeldung wurde nicht abgeschlossen: Der Browser hat das Cookie des Katalogs vom Beginn der Anmeldung nicht behalten. Erlauben Sie Cookies für diese Seite und melden Sie sich erneut an.",
    },
    "sso_state": {
        "en": "The sign-in expired or was started in another tab. Sign in again.",
        "sk": "Prihlásenie vypršalo alebo sa začalo na inej karte. Prihláste sa znova.",
        "cs": "Přihlášení vypršelo nebo bylo zahájeno na jiné kartě. Přihlaste se znovu.",
        "de": "Die Anmeldung ist abgelaufen oder wurde in einem anderen Tab begonnen. Melden Sie sich erneut an.",
    },
    "sso_refused": {
        "en": "The identity service refused the catalogue's sign-in request. Tell the administrator: the catalogue's log names the reason.",
        "sk": "Služba identity odmietla žiadosť katalógu o prihlásenie. Povedzte to správcovi: dôvod je v logu katalógu.",
        "cs": "Služba identity odmítla žádost katalogu o přihlášení. Řekněte to správci: důvod je v logu katalogu.",
        "de": "Der Identitätsdienst hat die Anmeldeanfrage des Katalogs abgelehnt. Melden Sie es der Administration: Das Protokoll des Katalogs nennt den Grund.",
    },
    "sso_account": {
        "en": "More than one catalogue account uses your e-mail address, so the catalogue cannot tell which one is yours. Ask the administrator to merge them.",
        "sk": "Vašu e-mailovú adresu používa viac účtov katalógu, takže katalóg nevie, ktorý je váš. Požiadajte správcu, aby ich zlúčil.",
        "cs": "Vaši e-mailovou adresu používá více účtů katalogu, takže katalog neví, který je váš. Požádejte správce, aby je sloučil.",
        "de": "Mehrere Katalogkonten verwenden Ihre E-Mail-Adresse, daher weiß der Katalog nicht, welches Ihres ist. Bitten Sie die Administration, sie zusammenzuführen.",
    },
    "sso_other": {
        "en": "The sign-in did not finish. Sign in again; if it fails again, tell the administrator when it happened.",
        "sk": "Prihlásenie sa nedokončilo. Prihláste sa znova; ak zlyhá opäť, povedzte správcovi, kedy sa to stalo.",
        "cs": "Přihlášení se nedokončilo. Přihlaste se znovu; pokud selže znovu, řekněte správci, kdy se to stalo.",
        "de": "Die Anmeldung wurde nicht abgeschlossen. Melden Sie sich erneut an; schlägt es wieder fehl, nennen Sie der Administration den Zeitpunkt.",
    },
    "more": {"en": "More details", "sk": "Ďalšie údaje", "cs": "Další údaje", "de": "Weitere Angaben"},
}

# What a reader gets from each format, in one line (T-2744). A format not listed gets none.
FORMATS = {
    "NGSI-LD": {"en": "Live entities through the API", "sk": "Živé entity cez API", "cs": "Živé entity přes API", "de": "Live-Entitäten über die API"},
    "JSON-LD": {"en": "Linked data with its context", "sk": "Prepojené dáta s kontextom", "cs": "Propojená data s kontextem", "de": "Verknüpfte Daten mit Kontext"},
    "GEOJSON": {"en": "Points and shapes for a map", "sk": "Body a tvary pre mapu", "cs": "Body a tvary pro mapu", "de": "Punkte und Formen für eine Karte"},
    "CSV": {"en": "A table for a spreadsheet", "sk": "Tabuľka pre tabuľkový procesor", "cs": "Tabulka pro tabulkový procesor", "de": "Eine Tabelle für die Tabellenkalkulation"},
    "JSON": {"en": "Machine-readable JSON", "sk": "Strojovo čitateľný JSON", "cs": "Strojově čitelný JSON", "de": "Maschinenlesbares JSON"},
    "XLSX": {"en": "A spreadsheet", "sk": "Tabuľkový súbor", "cs": "Tabulkový soubor", "de": "Eine Tabellendatei"},
    "ZIP": {"en": "Everything in one download", "sk": "Všetko v jednom súbore", "cs": "Vše v jednom souboru", "de": "Alles in einem Download"},
    "MCP": {"en": "For AI assistants (Model Context Protocol)", "sk": "Pre AI asistentov (Model Context Protocol)", "cs": "Pro AI asistenty (Model Context Protocol)", "de": "Für KI-Assistenten (Model Context Protocol)"},
    "LINKML": {"en": "The data model", "sk": "Dátový model", "cs": "Datový model", "de": "Das Datenmodell"},
    "SHACL": {"en": "Validation rules of the data model", "sk": "Pravidlá kontroly dátového modelu", "cs": "Pravidla kontroly datového modelu", "de": "Prüfregeln des Datenmodells"},
}

# The EU frequency vocabulary, publications.europa.eu/resource/authority/frequency, as a label
# and the days to the next update. Irregular and unknown frequencies promise no date.
FREQUENCIES = {
    "CONT": ({"en": "Continuously", "sk": "Priebežne", "cs": "Průběžně", "de": "Laufend"}, None),
    "UPDATE_CONT": ({"en": "Continuously", "sk": "Priebežne", "cs": "Průběžně", "de": "Laufend"}, None),
    "HOURLY": ({"en": "Every hour", "sk": "Každú hodinu", "cs": "Každou hodinu", "de": "Stündlich"}, 1 / 24),
    "DAILY": ({"en": "Every day", "sk": "Denne", "cs": "Denně", "de": "Täglich"}, 1),
    "WEEKLY": ({"en": "Every week", "sk": "Týždenne", "cs": "Týdně", "de": "Wöchentlich"}, 7),
    "MONTHLY": ({"en": "Every month", "sk": "Mesačne", "cs": "Měsíčně", "de": "Monatlich"}, 30),
    "QUARTERLY": ({"en": "Every quarter", "sk": "Štvrťročne", "cs": "Čtvrtletně", "de": "Vierteljährlich"}, 91),
    "ANNUAL": ({"en": "Every year", "sk": "Ročne", "cs": "Ročně", "de": "Jährlich"}, 365),
    "IRREG": ({"en": "Irregularly", "sk": "Nepravidelne", "cs": "Nepravidelně", "de": "Unregelmäßig"}, None),
}

# The extras the About list reads by name, in the order a reader sees them. Everything else
# the publisher wrote stays under "More details"; the internal ones are never shown.
ABOUT_EXTRAS = ("identifier", "language", "contact", "conforms_to", "status")
INTERNAL_EXTRAS = {"generated_by", "endpoint", "publisher_name", "publisher_uri", "contact_name",
                   "contact_email", "frequency", "spatial", "spatial_uri", "temporal_start",
                   "temporal_end", "theme"}


def _language():
    try:
        code = toolkit.h.lang() or "en"
    except (AttributeError, RuntimeError):
        code = "en"
    return code.split("_")[0].split("-")[0]


def jc_t(key):
    """One of the theme's words in the page's language, English when there is none."""
    words = STRINGS.get(key) or {}
    return words.get(_language()) or words.get("en") or key


def _extras(pkg):
    return {e.get("key"): e.get("value") for e in (pkg or {}).get("extras") or [] if e.get("key")}


def _is_url(value):
    return isinstance(value, str) and value.startswith(("https://", "http://"))


_DAY = datetime.timedelta(days=1)


def _parse(stamp):
    """CKAN's `metadata_modified`, naive UTC without a zone, as an aware datetime."""
    parsed = datetime.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=datetime.timezone.utc)


def jc_frequency(pkg):
    """(label, next update as a datetime or None) of the dataset's frequency; None when unset."""
    value = _extras(pkg).get("frequency")
    if not value:
        return None
    code = str(value).rstrip("/").rsplit("/", 1)[-1].upper()
    known = FREQUENCIES.get(code)
    if not known:
        return (str(value), None)
    words, days = known
    label = words.get(_language()) or words["en"]
    modified = (pkg or {}).get("metadata_modified")
    if days is None or not modified:
        return (label, None)
    try:
        last = _parse(modified)
    except ValueError:
        return (label, None)
    return (label, last + datetime.timedelta(days=days))


def jc_about(pkg):
    """The rows of "About this dataset" as (label, text, link or None), empty ones left out."""
    pkg = pkg or {}
    extras = _extras(pkg)
    rows = []
    organization = pkg.get("organization") or {}
    publisher = extras.get("publisher_name") or organization.get("title") or organization.get("name")
    if publisher:
        link = extras.get("publisher_uri")
        rows.append((jc_t("publisher"), publisher, link if _is_url(link) else None))
    if pkg.get("license_title") or pkg.get("license_id"):
        link = pkg.get("license_url")
        rows.append((jc_t("licence"), pkg.get("license_title") or pkg.get("license_id"),
                     link if _is_url(link) else None))
    groups = [g.get("display_name") or g.get("title") or g.get("name") for g in pkg.get("groups") or []]
    if groups:
        rows.append((jc_t("topic"), ", ".join(g for g in groups if g), None))
    tags = [t.get("display_name") or t.get("name") for t in pkg.get("tags") or []]
    if tags:
        rows.append((jc_t("keywords"), ", ".join(t for t in tags if t), None))
    frequency = jc_frequency(pkg)
    if frequency:
        rows.append((jc_t("frequency"), frequency[0], None))
    if pkg.get("metadata_modified"):
        rows.append((jc_t("last_update"), str(pkg["metadata_modified"])[:10], None))
    if frequency and frequency[1]:
        # A dataset updated more than once a day promises an hour, not only a date.
        pattern = "%Y-%m-%d %H:%M UTC" if frequency[1] - _parse(pkg["metadata_modified"]) < _DAY else "%Y-%m-%d"
        rows.append((jc_t("next_update"), frequency[1].strftime(pattern), None))
    coverage = extras.get("spatial_uri")
    if coverage:
        rows.append((jc_t("coverage"), coverage, coverage if _is_url(coverage) else None))
    start, end = extras.get("temporal_start"), extras.get("temporal_end")
    if start or end:
        rows.append((jc_t("period"), " – ".join(v for v in (start, end) if v), None))
    contact = extras.get("contact_name") or extras.get("contact_email")
    if contact:
        email = extras.get("contact_email")
        rows.append((jc_t("contact"), contact, "mailto:" + email if email and "@" in email else None))
    for key in ("identifier", "language", "conforms_to", "status"):
        value = extras.get(key)
        if value:
            rows.append((jc_t(key), value, value if _is_url(value) else None))
    return rows


def jc_more(pkg):
    """The extras the About list does not show, as (key, value), for "More details"."""
    shown = set(ABOUT_EXTRAS) | INTERNAL_EXTRAS | {"identifier", "language", "conforms_to", "status"}
    return sorted((k, v) for k, v in _extras(pkg).items() if k not in shown and v)


def jc_live(pkg):
    """The dataset's live NGSI-LD address and an example query, or None.

    Only an https address under the platform's own domain is shown: the extra is written by
    the publisher, and a page must never point a reader at an internal service address.
    """
    endpoint = _extras(pkg).get("endpoint")
    domain = BRANDING.get("domain") or ""
    if not (isinstance(endpoint, str) and endpoint.startswith("https://") and domain):
        return None
    host = endpoint[len("https://"):].split("/", 1)[0]
    if host != domain and not host.endswith("." + domain):
        return None
    base = endpoint if endpoint.endswith("/") else endpoint + "/"
    # `types` answers without a filter; a query for entities needs a type the reader learns here.
    example = "curl -H 'Accept: application/ld+json' '%sngsi-ld/v1/types'" % base
    return {"url": base, "example": example}


def jc_resource_groups(pkg):
    """The resources grouped by format, each group with its one-line "what is this"."""
    groups = {}
    for resource in (pkg or {}).get("resources") or []:
        name = (resource.get("format") or "").strip() or "—"
        groups.setdefault(name, []).append(resource)
    out = []
    for name in sorted(groups, key=lambda n: (n == "—", n.upper())):
        words = FORMATS.get(name.upper()) or {}
        out.append({"format": name, "what": words.get(_language()) or words.get("en") or "",
                    "resources": groups[name]})
    return out


def jc_portal_url():
    """The Portal of this installation, for staff who signed in; None without a domain."""
    domain = BRANDING.get("domain")
    return "https://portal.%s/" % domain if domain else None


def jc_branding():
    """The block, for the templates."""
    return BRANDING


# The session key `ckanext-oidc-pkce` writes its reason under, and each reason it writes
# (views.py of 0.4.1, pinned in images/ckan/Dockerfile) mapped to words a person can act on.
SSO_ERROR = "ckanext:oidc-pkce:error"
SSO_REASONS = {
    "Login process was not started properly": "sso_cookie",
    "The app state does not match": "sso_state",
    "Unsupported token type. Should be 'Bearer'.": "sso_refused",
    "No access token returned from the token endpoint.": "sso_refused",
    "Unique user not found": "sso_account",
}


def jc_sso_error(session=None):
    """Why the last single sign-on failed, once, in the page's language; None when it did not.

    The raw reason stays in the extension's log line: it can name the identity service's own
    error, which is for the administrator and not for the page.
    """
    if session is None:
        from ckan.common import session
    reason = session.pop(SSO_ERROR, None)
    if not reason:
        return None
    return jc_t(SSO_REASONS.get(reason, "sso_other"))


class JcThemePlugin(plugins.SingletonPlugin):
    plugins.implements(plugins.IConfigurer)
    plugins.implements(plugins.ITemplateHelpers)
    plugins.implements(plugins.IFacets, inherit=True)

    def update_config(self, config):
        toolkit.add_template_directory(config, "templates")
        # The logo is a file beside this package, so CKAN serves it from its own origin and
        # no page reaches a third party for an asset.
        toolkit.add_public_directory(config, "public")
        title = BRANDING.get("instanceName")
        if title:
            config["ckan.site_title"] = title
            config["ckan.site_description"] = BRANDING.get("organisation", "")
        logo = BRANDING.get("logo")
        if logo and os.path.exists(os.path.join(os.path.dirname(__file__), "public", logo)):
            config["ckan.site_logo"] = "/" + logo
        languages = BRANDING.get("languages") or {}
        offered = _available(languages.get("offered") or [])
        default = languages.get("default")
        if default in offered:
            config["ckan.locale_default"] = default
        if offered:
            config["ckan.locales_offered"] = " ".join(offered)

    def get_helpers(self):
        return {
            "jc_branding": jc_branding,
            "jc_t": jc_t,
            "jc_about": jc_about,
            "jc_more": jc_more,
            "jc_live": jc_live,
            "jc_resource_groups": jc_resource_groups,
            "jc_portal_url": jc_portal_url,
            "jc_sso_error": jc_sso_error,
        }

    def dataset_facets(self, facets_dict, package_type):
        """The search filters in plain words: Publisher, Topic, Keywords, Format, Licence."""
        names = {"organization": "publisher", "groups": "topic", "tags": "keywords",
                 "res_format": "format", "license_id": "licence"}
        for field, key in names.items():
            if field in facets_dict:
                facets_dict[field] = jc_t(key)
        return facets_dict
