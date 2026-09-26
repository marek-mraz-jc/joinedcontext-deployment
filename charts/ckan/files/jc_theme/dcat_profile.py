"""DCAT-AP 3 the way an EU harvester reads it (T-3010).

`euro_dcat_ap_3` (ckanext-dcat, pinned in images/ckan/Dockerfile) writes what a dataset holds
as CKAN strings: a media type, a format label, a checksum algorithm and a theme stay literals,
a location named only by its IRI is dropped, and the catalogue has no publisher. The DCAT-AP
3.0.1 shapes refuse all of that, and data.europa.eu scores it down. This profile runs after
it (`ckanext.dcat.rdf.profiles = euro_dcat_ap_3 jc_dcat_ap`) and turns each into the
controlled-vocabulary IRI the shapes ask for. Everything it adds comes from the dataset or
from the deployment's branding block; nothing here is a value of its own.
"""

from rdflib import BNode, Literal, URIRef
from rdflib.namespace import RDF, RDFS, SKOS

from ckanext.dcat.profiles import DCAT, DCT, FOAF, SPDX, VCARD, CleanedURIRef, RDFProfile
from ckanext.dcat.utils import resource_uri

from ckanext_jc_theme.plugin import BRANDING

EU = "http://publications.europa.eu/resource/authority/"
IANA = "http://www.iana.org/assignments/media-types/"

# CKAN format label (as crates/jcctl/src/publish/ckan.rs writes it) -> EU file-type code. A
# label not listed loses its dct:format; its dcat:mediaType still says what it is.
FILE_TYPES = {
    "CSV": "CSV",
    "JSON": "JSON",
    "GEOJSON": "GEOJSON",
    "JSON-LD": "JSON_LD",
    "NGSI-LD": "JSON_LD",
    "XLSX": "XLSX",
    "ZIP": "ZIP",
    "MARKDOWN": "MARKDOWN",
    "OWL": "OWL",
    "RDF": "RDF_TURTLE",
    "SHACL": "RDF_TURTLE",
    "LINKML": "YAML",
    "JSON SCHEMA": "JSON",
    "MCP": "JSON",
    "OGCFEAT": "GEOJSON",
    "STA": "JSON",
}

# The formats that are a live API rather than a file: each gets a dcat:DataService (DCAT-AP
# 3 §accessService) naming the standard it speaks.
SERVICES = {
    "NGSI-LD": "https://www.etsi.org/deliver/etsi_gs/CIM/001_099/009/",
    "MCP": "https://modelcontextprotocol.io/specification",
    "OGCFEAT": "http://www.opengis.net/doc/IS/ogcapi-features-1/1.0",
    "STA": "http://www.opengis.net/doc/is/sensorthings/1.1",
}

# The EU data-theme table (13 themes plus provisional data): a skos:Concept needs a label.
THEMES = {
    "AGRI": "Agriculture, fisheries, forestry and food",
    "ECON": "Economy and finance",
    "EDUC": "Education, culture and sport",
    "ENER": "Energy",
    "ENVI": "Environment",
    "GOVE": "Government and public sector",
    "HEAL": "Health",
    "INTR": "International issues",
    "JUST": "Justice, legal system and public safety",
    "OP_DATPRO": "Provisional data",
    "REGI": "Regions and cities",
    "SOCI": "Population and society",
    "TECH": "Science and technology",
    "TRAN": "Transport",
}

# The Portal's languages (UI-82) and their EU language codes. A language not listed is left
# out rather than written as a literal the shapes refuse.
LANGUAGES = {"en": "ENG", "cs": "CES", "sk": "SLK", "fi": "FIN", "sv": "SWE", "de": "DEU"}


def _extra(dataset_dict, key):
    for extra in dataset_dict.get("extras") or []:
        if extra.get("key") == key:
            return extra.get("value")
    return None


def _iri(value):
    return isinstance(value, str) and value.startswith(("http://", "https://"))


class JcDcatApProfile(RDFProfile):
    """Controlled vocabularies, services and the catalogue's publisher on top of euro_dcat_ap_3."""

    def graph_from_dataset(self, dataset_dict, dataset_ref):
        g = self.g
        for theme in list(g.objects(dataset_ref, DCAT.theme)):
            code = str(theme).rsplit("/", 1)[-1]
            g.add((theme, RDF.type, SKOS.Concept))
            g.add((theme, SKOS.prefLabel, Literal(THEMES.get(code, code), lang="en")))

        # dct:description is mandatory for a dataset; an Endpoint whose record has none is
        # described by its title rather than refused by every harvester.
        if (dataset_ref, DCT.description, None) not in g:
            for title in list(g.objects(dataset_ref, DCT.title)):
                g.add((dataset_ref, DCT.description, title))

        spatial = _extra(dataset_dict, "spatial_uri")
        if _iri(spatial) and (dataset_ref, DCT.spatial, None) not in g:
            g.add((dataset_ref, DCT.spatial, URIRef(spatial)))
            g.add((URIRef(spatial), RDF.type, DCT.Location))

        contact = BRANDING.get("contactEmail")
        if contact and (dataset_ref, DCAT.contactPoint, None) not in g:
            # The installation that publishes the record answers for it when the Endpoint
            # names no contact of its own.
            point = BNode()
            g.add((dataset_ref, DCAT.contactPoint, point))
            g.add((point, RDF.type, VCARD.Organization))
            g.add((point, VCARD.fn, Literal(BRANDING.get("instanceName") or contact)))
            g.add((point, VCARD.hasEmail, URIRef("mailto:" + contact)))
        # vcard:Organization is a vcard:Kind, stated: a validator without RDFS inference
        # checks the range itself.
        for point in list(g.objects(dataset_ref, DCAT.contactPoint)):
            g.add((point, RDF.type, VCARD.Kind))

        # The EU licence IRI jcctl carries as an extra, else CKAN's own licence page.
        licence = _extra(dataset_dict, "license_url") or dataset_dict.get("license_url")
        resources = {CleanedURIRef(resource_uri(r)): r for r in dataset_dict.get("resources") or []}
        for distribution in list(g.objects(dataset_ref, DCAT.distribution)):
            self._distribution(distribution, resources.get(distribution) or {}, licence, dataset_ref)

    def _distribution(self, distribution, resource_dict, licence, dataset_ref):
        g = self.g
        for media_type in list(g.objects(distribution, DCAT.mediaType)):
            if isinstance(media_type, Literal):
                g.remove((distribution, DCAT.mediaType, media_type))
                iri = URIRef(IANA + str(media_type).strip())
                g.add((distribution, DCAT.mediaType, iri))
                g.add((iri, RDF.type, DCT.MediaType))

        label = (resource_dict.get("format") or "").strip().upper()
        for fmt in list(g.objects(distribution, DCT["format"])):
            if isinstance(fmt, Literal):
                g.remove((distribution, DCT["format"], fmt))
        if label in FILE_TYPES:
            iri = URIRef(EU + "file-type/" + FILE_TYPES[label])
            g.add((distribution, DCT["format"], iri))
            g.add((iri, RDF.type, DCT.MediaTypeOrExtent))

        for checksum in list(g.objects(distribution, SPDX.checksum)):
            for algorithm in list(g.objects(checksum, SPDX.algorithm)):
                if isinstance(algorithm, Literal):
                    g.remove((checksum, SPDX.algorithm, algorithm))
                    iri = URIRef("http://spdx.org/rdf/terms#checksumAlgorithm_" + str(algorithm).lower())
                    g.add((checksum, SPDX.algorithm, iri))
                    g.add((iri, RDF.type, SPDX.ChecksumAlgorithm))

        if _iri(licence) and (distribution, DCT.license, None) not in g:
            g.add((distribution, DCT.license, URIRef(licence)))
            g.add((URIRef(licence), RDF.type, DCT.LicenseDocument))

        url = resource_dict.get("url")
        if label in SERVICES and _iri(url):
            service = BNode()
            g.add((distribution, DCAT.accessService, service))
            g.add((service, RDF.type, DCAT.DataService))
            g.add((service, DCT.title, Literal(resource_dict.get("name") or label)))
            g.add((service, DCAT.endpointURL, URIRef(url)))
            g.add((URIRef(url), RDF.type, RDFS.Resource))
            g.add((service, DCAT.servesDataset, dataset_ref))
            standard = URIRef(SERVICES[label])
            g.add((service, DCT.conformsTo, standard))
            g.add((standard, RDF.type, DCT.Standard))

    def graph_from_catalog(self, catalog_dict, catalog_ref):
        g = self.g
        name = BRANDING.get("organisation") or BRANDING.get("instanceName")
        if name and (catalog_ref, DCT.publisher, None) not in g:
            publisher = BNode()
            g.add((catalog_ref, DCT.publisher, publisher))
            g.add((publisher, RDF.type, FOAF.Agent))
            g.add((publisher, FOAF.name, Literal(name)))
            if BRANDING.get("contactEmail"):
                g.add((publisher, FOAF.mbox, URIRef("mailto:" + BRANDING["contactEmail"])))
        if (catalog_ref, DCT.description, None) not in g:
            title = g.value(catalog_ref, DCT.title) or BRANDING.get("instanceName")
            g.add((catalog_ref, DCT.description, Literal("%s open-data catalogue" % title, lang="en")))

        for homepage in list(g.objects(catalog_ref, FOAF.homepage)):
            g.add((homepage, RDF.type, FOAF.Document))

        for language in list(g.objects(catalog_ref, DCT.language)):
            if isinstance(language, Literal):
                g.remove((catalog_ref, DCT.language, language))
        offered = (BRANDING.get("languages") or {}).get("offered") or []
        for code in offered:
            if code in LANGUAGES:
                iri = URIRef(EU + "language/" + LANGUAGES[code])
                g.add((catalog_ref, DCT.language, iri))
                g.add((iri, RDF.type, DCT.LinguisticSystem))
