# The catalogue image: stock CKAN plus the one extension a Keycloak login needs (T-0403, OPS-26).
#
# `ckan/ckan-base` carries no OIDC authenticator, and CKAN exits on a plugin it cannot import,
# so `global.ckan.sso` only works against this image. The extension is `ckanext-oidc-pkce` and
# not the `ckanext-oauth2` the task named: that one still calls `before_map()` and reads
# `repoze.who.identity`, both of which CKAN dropped in 2.10, and its last commit is from 2019.
# `ckanext-oidc-pkce` is tested against 2.9, 2.10 and 2.11 upstream and speaks plain OIDC, which
# is what the realm serves.
#
# Nothing else is added: the theme is still mounted from a ConfigMap (OPS-46), so a rebrand stays
# a values edit and never a rebuild.
FROM ckan/ckan-base:2.11.6@sha256:fc040c5b1e6e04de76187b478b3037c8c6c4e97ef4b7f1c03cbc6b0008e04ce7

USER root

# The base image is rebuilt a few times a year and its Debian packages are whatever was current
# then: the stock 2.11.3 carried 25 CRITICAL and 3355 HIGH fixable findings, openssl, gnutls and
# git among them. An image this platform publishes is scanned at build time and has to pass it,
# so it takes the security updates that exist on the day it is built (OPS-27).
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Pinned like every other dependency here (OPS-27): a floating version is a different login
# flow on the next build. `--no-cache-dir` keeps the layer to what is installed.
RUN pip install --no-cache-dir 'ckanext-oidc-pkce==0.4.1'

# DCAT-AP for harvesters (T-3010): /catalog.{rdf,ttl,jsonld} and /dataset/{id}.{rdf,ttl,jsonld}
# with the `euro_dcat_ap_3` profile. 2.4 is the line that supports CKAN 2.11 and DCAT-AP 3; the
# theme's `jc_dcat_ap` profile (charts/ckan/files/jc_theme/dcat_profile.py) runs on top of it.
RUN pip install --no-cache-dir 'ckanext-dcat==2.4.4'

# The Python packages CKAN pins that have a fix published. CKAN's own pins are floors, not
# ceilings, and each of these is a patch release of a library CKAN uses through a stable API.
RUN pip install --no-cache-dir --upgrade \
        'urllib3>=2.7.0' \
        'PyJWT>=2.13.0' \
        'Mako>=1.3.12' \
        'sqlparse>=0.6.0' \
        'wheel>=0.46.2' \
        'jaraco.context>=6.1.0' \
        'setuptools>=78.1.1' \
        'msgpack>=1.2.1'

# The kernel headers the base image needs to build wheels, which a running CKAN does not: they
# are 1306 of the 1321 findings a scan of the stock image reports, and they are reported because
# the code is genuinely there. Removing it is the honest fix; `ignore-unfixed` would not have
# hidden them anyway. Last, so nothing above needs a compiler that goes with them.
RUN apt-get purge -y --auto-remove 'linux-headers-*' \
    && rm -rf /var/lib/apt/lists/*

# pip itself, and the libraries it vendors. `pip/_vendor/vendor.txt` pins msgpack and setuptools
# at versions with published advisories, and a scanner reads that file whatever the site-packages
# beside it hold — correctly, because the vendored code is in the image. Nothing installs at run
# time here: the plugins are in the layers above and the theme is a mounted ConfigMap, so pip has
# no work left to do once the image is built.
RUN python3 -m pip uninstall --yes pip \
    && rm -rf /usr/local/lib/python3.10/site-packages/pip \
             /usr/local/lib/python3.10/site-packages/pip-*.dist-info \
             /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.10

USER ckan
