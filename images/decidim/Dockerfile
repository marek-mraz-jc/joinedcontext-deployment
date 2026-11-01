# The participation platform image (T-6316, ADR-N-065): stock Decidim plus the one gem a Keycloak
# sign-in needs, run as a user of its own.
#
# `decidim/decidim` is the generated application the Decidim project publishes. It carries
# OmniAuth strategies for Facebook, X and Google only, runs as root and ships the generator's
# `config/master.key`. This layer adds `omniauth_openid_connect`, the initializer that registers
# the realm as the one sign-in provider (joinedcontext.rb), the bootstrap that creates the one
# organization (bootstrap.rb), deletes the shipped key (SECRET_KEY_BASE comes from a Secret, so
# Rails never reads the credentials file) and drops root. No Ruby of ours beyond configuration.
FROM ghcr.io/decidim/decidim:0.31.6@sha256:df6cfb6caa80a908681259bd953bb4535e6529b7afa5c99fcf49f35009c96f85 AS build

WORKDIR /code

# Pinned like every other dependency here (OPS-27); 0.8.0 is from 2024-07-04. The lock update
# moves, inside the ranges Decidim 0.31.6 declares, every gem trivy finds a fixed release of
# (Rails 7.2.4 for the Active Storage file-access CVEs, nokogiri, rack, net-imap, erb, uri ...),
# plus resolv and zlib, which Ruby 3.3.4 ships as default gems with known holes: the Gemfile
# names the fixed releases, so Bundler loads those, and the superseded default copies are deleted
# (their code is never loaded once the lockfile names a newer one). What Decidim pins to a
# vulnerable line (puma ~> 6.5, ransack ~> 4.2.0, rubyzip ~> 2.3.0, shakapacker ~> 8.3.0,
# oauth through omniauth-twitter) stays until Decidim moves it: ADR-N-065 section 4.
RUN bundle config set --local frozen false \
    && bundle add omniauth_openid_connect --version '0.8.0' --skip-install \
    && bundle add resolv --version '>= 0.3.2' --skip-install \
    && bundle add zlib --version '>= 3.1.2' --skip-install \
    && bundle lock --update rails actioncable actionmailbox actionmailer actionpack actiontext \
         actionview activejob activemodel activerecord activestorage activesupport railties \
         addressable bcrypt concurrent-ruby crass css_parser erb faraday jwt net-imap nokogiri \
         oauth2 puma rack rexml uri websocket-driver resolv zlib \
    && bundle install \
    && bundle clean --force \
    && bundle config set --local frozen true \
    && rm -f /usr/local/lib/ruby/gems/3.3.0/specifications/default/resolv-0.3.0.gemspec \
             /usr/local/lib/ruby/gems/3.3.0/specifications/default/zlib-3.1.1.gemspec \
             /usr/local/lib/ruby/gems/3.3.0/specifications/default/erb-4.0.3.gemspec \
             /usr/local/lib/ruby/gems/3.3.0/specifications/default/uri-0.13.0.gemspec \
    && rm -rf /usr/local/lib/ruby/gems/3.3.0/specifications/net-imap-0.4.9.1.gemspec \
              /usr/local/lib/ruby/gems/3.3.0/gems/net-imap-0.4.9.1 \
              /usr/local/lib/ruby/gems/3.3.0/specifications/rexml-3.2.8.gemspec \
              /usr/local/lib/ruby/gems/3.3.0/gems/rexml-3.2.8 \
    && rm -f config/master.key config/credentials.yml.enc \
    && rm -rf /usr/local/bundle/cache /root/.bundle

# Node built the packs in public/decidim-packs; nothing runs it at runtime, and its modules
# carried 140 of the base's findings.
RUN rm -rf /code/node_modules /usr/lib/node_modules \
    && apt-get purge -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Debian's fixes for the base's packages, so the scan below sees today's archive (T-5372: never
# from a cached layer, the workflow builds with no cache for this step's sake).
RUN apt-get update \
    && apt-get -y --no-install-recommends upgrade \
    && rm -rf /var/lib/apt/lists/*

COPY joinedcontext.rb config/initializers/joinedcontext.rb
COPY bootstrap.rb db/joinedcontext_bootstrap.rb

# The writable places a Rails process needs, owned by the runtime user; everything else stays
# root's and read-only to it. /code/storage is the attachments claim in the cluster.
RUN groupadd --system --gid 10001 decidim \
    && useradd --system --uid 10001 --gid decidim --home-dir /code --shell /usr/sbin/nologin decidim \
    && mkdir -p tmp log storage public/uploads \
    && chown -R 10001:10001 tmp log storage public/uploads

# One layer of what the steps above left: the files they deleted are gone from the image too,
# instead of sitting in the base's layers (5.0 GB unflattened). The base's environment, then ours.
FROM scratch
COPY --from=build / /
WORKDIR /code
ENV PATH=/usr/local/bundle/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    GEM_HOME=/usr/local/bundle \
    BUNDLE_APP_CONFIG=/usr/local/bundle \
    RAILS_ENV=production \
    RAILS_SERVE_STATIC_FILES=true \
    RAILS_LOG_TO_STDOUT=1 \
    QUEUE_ADAPTER=sidekiq \
    PORT=3000
USER 10001:10001
EXPOSE 3000
CMD ["bundle", "exec", "puma", "-C", "config/puma.rb"]
