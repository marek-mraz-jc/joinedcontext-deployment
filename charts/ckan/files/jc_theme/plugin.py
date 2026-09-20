"""Renders any branding block (OPS-47).

The block is read once at start-up from the file the chart mounts. A missing or broken
file is not an error: CKAN then looks like a plain CKAN, which is what an installation
without branding should look like.
"""

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
    return branding


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


def jc_branding():
    """The block, for the templates."""
    return BRANDING


class JcThemePlugin(plugins.SingletonPlugin):
    plugins.implements(plugins.IConfigurer)
    plugins.implements(plugins.ITemplateHelpers)

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
        return {"jc_branding": jc_branding}
