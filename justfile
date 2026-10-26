# .DEFAULT_GOAL := help

set dotenv-load

# MINIKUBE_IP := $(shell minikube ip)
marker := 'LOCAL_JOINEDCONTEXT_HOSTS'
hosts := 'idm.joinedcontext.test joinedcontext.test'
# How many helm processes one helmfile run starts at once (T-3095). Unbounded (helmfile's 0) the
# hourly dev-apply ran dozens beside the agents' builds and put the server at load 335 on 8 CPUs.
helmfile_concurrency := env('JC_HELMFILE_CONCURRENCY', '4')

default:
	@just --list

# Run pre-commit on all files
[group('test & lint')]
validate:
	pre-commit run --all-files;

sync-component environment='local' component='':
	echo "Syncing component: {{component}} in environment: {{environment}}"
	helmfile -f ./deployment/helmfile.yaml sync --concurrency {{helmfile_concurrency}} -e {{environment}} --selector component={{component}}

# Destroy a specific component in an environment
[group('deployment')]
destroy-component environment='local' component='':
	echo "Destroying component: {{component}} in environment: {{environment}}"
	helmfile -f ./deployment/helmfile.yaml destroy --concurrency {{helmfile_concurrency}} -e {{environment}} --selector component={{component}}

# Get Keycloak Realm
[group('helpers')]
_get-keycloak-realm profile='local':
	@yq '(.global.instanceSlug // error("missing"))' deployment/environments/{{ profile }}/global.yaml.gotmpl 2>/dev/null || yq '.global.instanceSlug' defaults/environment/global.yaml

# Get domain
[group('helpers')]
_get-domain profile='local':
	@yq '(.global.domain // error("missing"))' deployment/environments/local/global.yaml.gotmpl 2>/dev/null || yq '.global.domain' defaults/environment/global.yaml

# Get Keycloak namespace
[group('helpers')]
_get-keycloak-namespace:
	@helmfile template --concurrency {{helmfile_concurrency}} -f deployment/helmfile.yaml -e local --selector component=keycloak --skip-deps -q | yq 'select(.kind == "StatefulSet") | .metadata.namespace'

# Get APISix namespace
[group('helpers')]
_get-apisix-namespace:
	@helmfile template --concurrency {{helmfile_concurrency}} -f deployment/helmfile.yaml -e local --selector component=apisix --skip-deps -q | yq 'select(.kind == "Deployment" ) | .metadata.namespace'

# Get Postgres namespace
[group('helpers')]
_get-postgres-namespace:
	@helmfile template --concurrency {{helmfile_concurrency}} -f deployment/helmfile.yaml -e local --selector component=postgres --skip-deps -q | yq 'select(.kind == "Deployment") | .metadata.namespace'

# Deploy the shared cluster operators (CloudNativePG, Strimzi) ONCE per cluster.
# Run this before deploying any instances; re-running is idempotent.
[group('deployment')]
deploy-operators environment='local':
	echo "Deploying shared cluster operators in environment: {{environment}}"
	helmfile -f ./deployment/helmfile-operators.yaml sync --concurrency {{helmfile_concurrency}} -e {{environment}}

# Deploy a single instance (everything except the shared operators). The shared operators
# must already be running (see deploy-operators). Optionally override the instance slug
# (namespace + Keycloak realm) ad-hoc; otherwise the environment's instanceSlug is used.
[group('deployment')]
deploy-instance environment='local' slug='':
	if [ -n "{{slug}}" ]; then \
		echo "Deploying instance '{{slug}}' in environment: {{environment}}"; \
		helmfile -f ./deployment/helmfile-instance.yaml.gotmpl sync --concurrency {{helmfile_concurrency}} -e {{environment}} --state-values-set-string instanceSlug={{slug}}; \
	else \
		echo "Deploying instance in environment: {{environment}}"; \
		helmfile -f ./deployment/helmfile-instance.yaml.gotmpl sync --concurrency {{helmfile_concurrency}} -e {{environment}}; \
	fi

# Destroy a single instance (everything except the shared operators)
[group('deployment')]
destroy-instance environment='local' slug='':
	if [ -n "{{slug}}" ]; then \
		helmfile -f ./deployment/helmfile-instance.yaml.gotmpl destroy --concurrency {{helmfile_concurrency}} -e {{environment}} --state-values-set-string instanceSlug={{slug}}; \
	else \
		helmfile -f ./deployment/helmfile-instance.yaml.gotmpl destroy --concurrency {{helmfile_concurrency}} -e {{environment}}; \
	fi

# Deploy minikube
[group('deployment')]
_minikube namespace='dev':
	which minikube > /dev/null || (echo "Minikube CLI not found. Please install Minikube CLI first." && exit 1)
	echo "Starting minikube and deploying to namespace: {{namespace}}"
	minikube start --cpus=4 --memory=8192
	minikube addons enable metrics-server
	minikube addons enable ingress

	helm install \
		cert-manager oci://quay.io/jetstack/charts/cert-manager \
		--version v1.19.2 \
		--namespace cert-manager \
		--create-namespace \
		--set crds.enabled=true

	kubectl create namespace {{namespace}}

	kubectl create secret generic keycloak-smtp \
		--from-literal=host='smtp.example.com' \
		--from-literal=port='587' \
		--from-literal=from='noreply@example.com' \
		--from-literal=user='noreply@example.com' \
		--from-literal=password='YOUR_SMTP_PASSWORD' \
		-n {{namespace}}

# Deploy k3d
[group('deployment')]
deploy-k3d:
	which k3d > /dev/null || (echo "k3d CLI not found. Please install k3d CLI first." && exit 1)
	./dev-deployment/startup.sh -k
sync environment='local' component='all':
	if [ "{{component}}" = "all" ]; then \
		echo "Syncing environment: {{environment}}"; \
		helmfile -f ./deployment/helmfile.yaml sync --concurrency {{helmfile_concurrency}} -e {{environment}}; \
	else \
		echo "Syncing component: {{component}} in environment: {{environment}}"; \
		helmfile -f ./deployment/helmfile.yaml sync --concurrency {{helmfile_concurrency}} -e {{environment}} --selector component={{component}}; \
	fi

# Update an installation to a release: backup, diff, apply, steps, smoke, roll back on red
# (T-3794, docs Deployment/06-updating); `--check` shows the plan and changes nothing
[group('deployment')]
upgrade environment version *flags:
	./scripts/upgrade.py {{environment}} {{version}} --concurrency {{helmfile_concurrency}} {{flags}}

# Write releases/<version>.md from the pinned images, the commits and releases/next.yaml; commit
# it, then tag that commit <version>
[group('deployment')]
release-notes version:
	./scripts/release-notes.py {{version}}

# Cut the next release from main as pushed (T-4955): releases/<v>.md, its CHANGELOG.md section,
# one commit and an annotated tag; prints the push (`--push` pushes both, never forced)
[group('deployment')]
release part *flags:
	./scripts/release.py cut {{part}} {{flags}}

# Deploy linkerd (idempotent — skips if the control plane is already installed)
[group('deployment')]
linkerd:
	#!/usr/bin/env bash
	set -euo pipefail
	just _check-dependencies linkerd
	if kubectl get deploy linkerd-destination -n linkerd >/dev/null 2>&1; then
		echo "Linkerd control plane already installed — skipping."
		exit 0
	fi
	linkerd check --pre
	kubectl apply --server-side -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.4.0/standard-install.yaml
	linkerd install --crds | kubectl apply -f -
	linkerd install --set proxy.nativeSidecar=true \
		--proxy-cpu-request=20m --proxy-cpu-limit=40m \
		--proxy-memory-request=32Mi --proxy-memory-limit=64Mi | kubectl apply -f -
	linkerd check

# Deploy Kyverno (idempotent, required by runtime-policies; same script as CI)
[group('deployment')]
kyverno:
	just _check-dependencies helmfile
	./scripts/ci/install-kyverno-if-missing.sh

# Mesh the local nginx ingress controller so it can reach APISIX under mandatory mTLS
[group('deployment')]
mesh-ingress-nginx:
	#!/usr/bin/env bash
	set -euo pipefail
	if ! kubectl get deployment ingress-nginx-controller -n ingress-nginx >/dev/null 2>&1; then
		echo "ingress-nginx not found; skipping mesh step."
		exit 0
	fi
	# opaque-ports is about the OTHER direction: skip-inbound-ports lets external plaintext
	# reach the controller, opaque-ports stops a meshed CLIENT from running HTTP protocol
	# detection on the TLS it sends here. The Portal resolves the public issuer host onto this
	# controller, so it speaks its own HTTPS to a meshed destination on 443; without this the
	# stream is parsed as HTTP and reset (`Connection reset by peer (os error 104)`), and OIDC
	# discovery fails at boot. mTLS between the proxies is unaffected.
	kubectl annotate namespace ingress-nginx \
		linkerd.io/inject=enabled \
		config.linkerd.io/skip-inbound-ports=80,443,8443 \
		config.linkerd.io/opaque-ports=443 --overwrite
	# Marking the Service opaque as well did not keep a meshed client's hop alive (ci-full
	# 34784223904 reset Gitea's OIDC discovery with both annotations in place), so every meshed
	# pod that dials the public host carries config.linkerd.io/skip-outbound-ports: "443" (T-0418).
	kubectl rollout restart deployment ingress-nginx-controller -n ingress-nginx
	kubectl rollout status deployment ingress-nginx-controller -n ingress-nginx --timeout=300s

# Add host entries to /etc/hosts for Linux systems
[group('helpers')]
[linux]
add-hosts:
	@if ! minikube status > /dev/null 2>&1; then \
		echo "Minikube is not running. Please start minikube first."; \
		exit 1; \
	fi
	@echo "Updating /etc/hosts with Minikube IP $(minikube ip)"
	@sudo sed -i.bak '/# {{marker}}/,/^$$/d' /etc/hosts
	@echo "# {{marker}}" | sudo tee -a /etc/hosts > /dev/null
	@for h in {{hosts}}; do \
		echo "$(minikube ip) $h" | sudo tee -a /etc/hosts > /dev/null ; \
	done
	@echo "" | sudo tee -a /etc/hosts > /dev/null
	@echo "Done."

# Add host entries to /etc/hosts for MacOS systems
[group('helpers')]
[macos]
add-hosts:
	@if ! minikube status > /dev/null 2>&1; then \
		echo "Minikube is not running. Please start minikube first."; \
		exit 1; \
	fi
	@echo "Updating /etc/hosts with 127.0.0.1"
	@sudo sed -i.bak '/# {{marker}}/,/^$$/d' /etc/hosts
	@echo "# {{marker}}" | sudo tee -a /etc/hosts > /dev/null
	@for h in {{hosts}}; do \
		echo "127.0.0.1 $h" | sudo tee -a /etc/hosts > /dev/null ; \
	done
	@echo "" | sudo tee -a /etc/hosts > /dev/null
	@echo "Done."

# Create a new platform component
[group('components')]
new-component:
	cd components && copier copy .. .

# Update platform components
[group('components')]
update:
	copier update --skip-answered -a test/.copier-answers.yaml components

# Update all components in the components/ directory
[group('components')]
update-components:
	@for d in components/*; do \
		if [ -d "$d" ]; then \
			name=$(basename "$d"); \
			echo "Updating $name..."; \
			( cd components && copier update --skip-answered --vcs-ref 8969ae22 -a "$name/.copier-answers.yml" ) || echo "copier update failed for $name"; \
		fi; \
	done

# Refresh .ci/golden/<env>.txt for every environment ci.yml renders, after an intentional change
[group('test & lint')]
golden-update:
	#!/usr/bin/env bash
	set -euo pipefail
	just _dev-assemble
	out=$(mktemp -d -t golden.XXXXXX)
	trap 'rm -rf "$out"' EXIT
	mapfile -t environments < .ci/golden/ENVIRONMENTS
	# GOLDEN_JOBS renders at once (T-5552); the goldens are written only after every render passed.
	RENDER_JOBS="${GOLDEN_JOBS:-3}" scripts/render-all.sh "$out" "${environments[@]}"
	printf '%s\n' "${environments[@]}" | xargs -P "${GOLDEN_JOBS:-3}" -I{} \
		sh -c 'python3 .ci/golden/list-objects.py "$1/$2.yaml" > ".ci/golden/$2.txt"' sh "$out" {}
	for env in dev smartcity; do
		helmfile -f demos/bbsk/helmfile.yaml.gotmpl -e "$env" template --skip-deps -q --concurrency {{helmfile_concurrency}} >"$out/demo-bbsk-$env.yaml"
		python3 .ci/golden/list-objects.py "$out/demo-bbsk-$env.yaml" > ".ci/golden/demo-bbsk-$env.txt"
	done
	wc -l .ci/golden/*.txt

# Verify Kyverno policies
[group('test & lint')]
verify-policies:
	.ci/policies/verify-kyverno-policies.sh

# Run Kyverno policy regression tests (good/bad fixtures)
[group('test & lint')]
test-policies:
	kyverno test .ci/policies

# Smoke-test deployment variants in fresh k3d clusters (no args = all 8; pass triplets/flags or --help)
[group('test & lint')]
test-deployment-variants *args:
	./scripts/test-deployment-variants.sh {{args}}

# Re-vendor upstream Kyverno policies (pinned ref in the script)
[group('helpers')]
vendor-policies:
	.ci/policies/vendor-upstream-policies.sh

# Render helmfile for specific environment
[group('helpers')]
template environment='local' component='all':
	if [ "{{component}}" = "all" ]; then \
		echo "Rendering helmfile for environment: {{environment}}"; \
		helmfile -f ./deployment/helmfile.yaml template --concurrency {{helmfile_concurrency}} -e {{environment}}; \
	else \
		echo "Rendering helmfile for component: {{component}} in environment: {{environment}}"; \
		helmfile -f ./deployment/helmfile.yaml template --concurrency {{helmfile_concurrency}} -e {{environment}} --selector component={{component}}; \
	fi

# Render helmfile for a specific component in an environment
[group('helpers')]
template-component environment='local' component='':
	helmfile -f ./deployment/helmfile.yaml template --concurrency {{helmfile_concurrency}} -e {{environment}} --selector component={{component}}

# Render the shared operator layer (deploy-operators)
[group('helpers')]
template-operators environment='local':
	helmfile -f ./deployment/helmfile-operators.yaml template --concurrency {{helmfile_concurrency}} -e {{environment}}

# Render a single instance layer (deploy-instance); optional ad-hoc slug override
[group('helpers')]
template-instance environment='local' slug='':
	if [ -n "{{slug}}" ]; then \
		helmfile -f ./deployment/helmfile-instance.yaml.gotmpl template --concurrency {{helmfile_concurrency}} -e {{environment}} --state-values-set-string instanceSlug={{slug}}; \
	else \
		helmfile -f ./deployment/helmfile-instance.yaml.gotmpl template --concurrency {{helmfile_concurrency}} -e {{environment}}; \
	fi

deploy cri='k3d' namespace='dev' profile='local':
	@if [ "{{cri}}" = "k3d" ]; then \
		just _check-dependencies k3d || exit 1; \
		./dev-deployment/startup.sh -k; \
	else if [ "{{cri}}" = "minikube" ]; then \
		just _check-dependencies minikube || exit 1; \
		./dev-deployment/startup.sh -m; \
	else \
		echo "Invalid container runtime interface (CRI) specified. Use 'k3d' or 'minikube'."; \
		exit 1; \
	fi; fi
	@just linkerd
	@just kyverno
	@just mesh-ingress-nginx
	@if [ ! -d "./deployment" ]; then \
		cp -r defaults/deployment deployment; \
	fi
	@( timeout 30 bash -c 'until kubectl get ns {{namespace}} >/dev/null 2>&1; do sleep 1; done'; \
	KEYCLOAK_NS=$( \
		helmfile template --concurrency {{helmfile_concurrency}} \
		-f deployment/helmfile.yaml \
		-e {{profile}} \
		--selector component=keycloak -q | \
		yq eval -r 'select(.kind == "StatefulSet" and .metadata.name == "keycloak-app-keycloakx") | .metadata.namespace'); \
	kubectl create secret generic keycloak-smtp \
		--from-literal=host='smtp.example.com' \
		--from-literal=port='587' \
		--from-literal=from='noreply@example.com' \
		--from-literal=user='noreply@example.com' \
		--from-literal=password='YOUR_SMTP_PASSWORD' \
		-n ${KEYCLOAK_NS} ) &
	@helmfile -f deployment/helmfile.yaml sync --concurrency {{helmfile_concurrency}} -e {{profile}}

# Remove local cluster
[group('deployment')]
destroy:
	@./dev-deployment/startup.sh -u

# Check for dependencies
[group('helpers')]
_check-dependencies dependencies='k3d':
	#!/usr/bin/env bash
	set -euo pipefail
	RED='\033[0;31m'
	NC='\033[0m' # No Color
	dependencies="docker kubectl helm helmfile linkerd openssl gettext"
	for dep in $dependencies; do
		if ! which $dep > /dev/null 2>&1; then
			echo -e "${RED}ERROR: $dep not found. Please install $dep first.${NC}"
			exit 1
		fi
	done
	if ! which {{dependencies}} > /dev/null 2>&1; then
		echo -e "${RED}ERROR: {{dependencies}} not found. Please install {{dependencies}} first.${NC}"
		exit 1
	fi
	if ! helm diff version > /dev/null 2>&1; then
		echo -e "${RED}ERROR: Helm Diff plugin not found. Please install Helm Diff plugin first.${NC}"
		exit 1
	fi

# Install dependencies: release downloads checked against the sha256 images/gitops-helmfile/Dockerfile
# pins (linkerd's from tools.env), never an install script from a branch (F-DEP2-012).
[group('helpers')]
[linux]
install-dependencies:
	if ! which docker > /dev/null; then \
		curl -fsSL https://get.docker.com -o get-docker.sh; \
		sh get-docker.sh; \
		sudo usermod -aG docker $USER; \
		newgrp docker; \
		rm get-docker.sh; \
	else \
		echo "Docker is already installed."; \
	fi
	if ! which kubectl > /dev/null; then \
		curl -fsSLO "https://dl.k8s.io/release/v1.35.9/bin/linux/amd64/kubectl"; \
		echo "3cfeaf80be482b435b0aa214aff6e0b2c312ee23c0ff20810c75517b6004c6eb  kubectl" | sha256sum -c - || exit 1; \
		sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl && rm kubectl; \
	else \
		echo "kubectl is already installed."; \
	fi
	if ! which helm > /dev/null; then \
		curl -fsSL -o helm.tgz https://get.helm.sh/helm-v4.3.0-linux-amd64.tar.gz; \
		echo "86584a54def73570558f66f5111cc53dfed56689637ae32c1201205d494f54fb  helm.tgz" | sha256sum -c - || exit 1; \
		tar -xzf helm.tgz linux-amd64/helm && sudo install -o root -g root -m 0755 linux-amd64/helm /usr/local/bin/helm; \
		rm -rf helm.tgz linux-amd64; \
		helm plugin install https://github.com/databus23/helm-diff; \
	else \
		echo "Helm is already installed."; \
	fi
	if ! which helmfile > /dev/null; then \
		curl -fsSLO https://github.com/helmfile/helmfile/releases/download/v1.8.1/helmfile_1.8.1_linux_amd64.tar.gz; \
		echo "ccabbe75dddbc25008d055fe92a44f95a184342211e7244d32b870409239c7a3  helmfile_1.8.1_linux_amd64.tar.gz" | sha256sum -c - || exit 1; \
		tar -xzf helmfile_1.8.1_linux_amd64.tar.gz helmfile && sudo install -o root -g root -m 0755 helmfile /usr/local/bin/helmfile; \
		rm helmfile_1.8.1_linux_amd64.tar.gz helmfile; \
	else \
		echo "Helmfile is already installed."; \
	fi
	if ! which linkerd > /dev/null; then \
		curl -fsSL -o linkerd https://github.com/linkerd/linkerd2/releases/download/edge-26.9.1/linkerd2-cli-edge-26.9.1-linux-amd64; \
		echo "094e1de06215fbe76fc011cf62c96214f8dae0cd5a58135fb40307be88b6b176  linkerd" | sha256sum -c - || exit 1; \
		sudo install -o root -g root -m 0755 linkerd /usr/local/bin/linkerd && rm linkerd; \
		linkerd version --client; \
	else \
		echo "Linkerd is already installed."; \
	fi
	if ! which sops > /dev/null; then \
		curl -sSL -o sops https://github.com/getsops/sops/releases/download/v3.13.3/sops-v3.13.3.linux.amd64; \
		sudo install -o root -g root -m 0755 sops /usr/local/bin/sops && rm sops; \
	else \
		echo "sops is already installed."; \
	fi
	if ! which age > /dev/null; then \
		curl -sSL https://github.com/FiloSottile/age/releases/download/v1.2.1/age-v1.2.1-linux-amd64.tar.gz | tar xz; \
		sudo install -o root -g root -m 0755 age/age age/age-keygen /usr/local/bin/ && rm -r age; \
	else \
		echo "age is already installed."; \
	fi
	if ! which openssl > /dev/null; then \
		sudo apt-get update && sudo apt-get install -y openssl; \
	else \
		echo "OpenSSL is already installed."; \
	fi
	if ! which gettext > /dev/null; then \
		sudo apt-get update && sudo apt-get install -y gettext-base; \
	else \
		echo "gettext is already installed."; \
	fi
[macos]
install-dependencies:
	echo "Please check ../docs/Deployment/01-prerequisites.md for required dependencies and adjust your system accordingly."


# ---------------------------------------------------------------------------
# dev cluster (single-node Hetzner k3s, see CLAUDE.md). The recipes below are the
# only supported way to change it: they assemble deployment/ from the committed
# defaults + .ci/example-deployments/environments/dev, so the cluster equals main.
# ---------------------------------------------------------------------------

dev_domain := env('JC_DEV_DOMAIN', 'dev.joinedcontext.com')
# The node the dev domain points at (primaleto since 2026-09-26, T-3042); the guard compares it
# with the kube context's server.
dev_node_ip := env('JC_DEV_NODE_IP', '116.203.134.249')

# Refuse to touch anything but the dev cluster
[group('dev cluster')]
_dev-guard:
	#!/usr/bin/env bash
	set -euo pipefail
	ip="{{ dev_node_ip }}"
	server=$(kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}' 2>/dev/null || true)
	case "$server" in
		*"$ip"*) ;;
		*) echo "refusing: current kube context points at '${server:-<none>}', not the dev cluster ($ip). Set KUBECONFIG=.secrets/kubeconfig-dev.yaml" >&2; exit 1 ;;
	esac

# Assemble deployment/ from the committed defaults and the dev environment
[group('dev cluster')]
_dev-assemble:
	#!/usr/bin/env bash
	set -euo pipefail
	rm -rf deployment
	cp -r defaults/deployment deployment
	cp .ci/example-deployments/helmfile.yaml deployment/helmfile.yaml
	cp -r .ci/example-deployments/environments/. deployment/environments/

# Apply the dev environment to the dev cluster and wait for every rollout
[group('dev cluster')]
dev-apply:
	#!/usr/bin/env bash
	set -euo pipefail
	just _dev-guard
	just _dev-assemble
	# Every platform digest of the render carries our workflows' signature, or nothing is applied (T-5564).
	./scripts/verify-pinned-images.py dev
	helmfile -f deployment/helmfile.yaml -e dev sync --concurrency {{helmfile_concurrency}}
	./scripts/wait-rollouts.sh dev
	# What dev runs now, who applied it and when (T-4955); dev-smoke prints it.
	./scripts/release.py record dev dev

# The checks dev-smoke and prod-smoke share, against one instance (its domain and namespace)
[group('dev cluster')]
_smoke domain namespace:
	#!/usr/bin/env bash
	set -euo pipefail
	rc=0
	./scripts/release.py show "{{ namespace }}"
	# One lookup, then every curl goes to that address (T-3420): the sandbox resolver stalls up
	# to 15 s per lookup, which ate the 20 s request budget and failed checks the cluster passed.
	# TLS is still verified per hostname; the wildcard record is checked here instead.
	edge=$(getent ahostsv4 "{{ domain }}" | awk 'NR==1{print $1}')
	wild=$(getent ahostsv4 "smoke-$RANDOM.apps.{{ domain }}" | awk 'NR==1{print $1}')
	if [ -z "$edge" ] || [ "$wild" != "$edge" ]; then
		echo "  FAIL  *.{{ domain }} resolves to '${wild}', the apex to '${edge}'"; exit 1
	fi
	export CURL_HOME; CURL_HOME=$(mktemp -d); trap 'rm -rf "$CURL_HOME"' EXIT
	printf 'resolve = *:443:%s\nresolve = *:80:%s\n' "$edge" "$edge" >"$CURL_HOME/.curlrc"
	JC_REALM="{{ namespace }}" ./scripts/smoke.sh "https://{{ domain }}" "https://idm.{{ domain }}" || rc=1
	# Every catalogue dataset and public Endpoint on every interface (T-4716): read-only; the
	# entity count of every dataset first, 6 at once (T-5768), then 50 requests a minute for
	# 10 minutes at most; its table lands in .smoke/.
	echo "catalogue"
	python3 scripts/smoke-catalogue.py "{{ domain }}" "{{ namespace }}" || rc=1
	# Rows of every public Endpoint x type link the dataset of their space and type (T-4802).
	echo "source links"
	python3 scripts/smoke-source-links.py "{{ domain }}" "{{ namespace }}" || rc=1
	# A CronJob whose newest run failed (T-4385): a harvest dead since the night is no green smoke.
	echo "cron jobs"
	kubectl -n "{{ namespace }}" get jobs -o json | python3 scripts/failed-jobs.py || rc=1
	# The Portal's edge wave (T-5318): the served edge stays the same when the Portal's write of
	# apisix-standalone-config is refused, so the smoke makes it write once and checks it landed.
	echo "edge wave"
	python3 scripts/smoke-edge-wave.py || rc=1
	# The background map (T-4638): a range request answers 206, and the monthly refresh kept the
	# file younger than 40 days (Last-Modified is the file's own time).
	echo "basemap"
	hdr=$(curl -sS -o /dev/null -D - -m 20 -H 'Range: bytes=0-16383' "https://tiles.{{ domain }}/basemap.pmtiles" 2>&1 | tr -d '\r' || true)
	status=$(printf '%s\n' "$hdr" | awk 'NR == 1 { print $2 }')
	lm=$(printf '%s\n' "$hdr" | sed -n 's/^[Ll]ast-[Mm]odified: //p')
	modified=$( { [ -n "$lm" ] && date -u -d "$lm" +%s; } 2>/dev/null || echo 0)
	age=$(( ($(date -u +%s) - modified) / 86400 ))
	if [ "$status" != 206 ]; then echo "  FAIL  basemap: a range request answered '${status}', not 206"; rc=1
	elif [ "$age" -gt 40 ]; then echo "  FAIL  basemap: the file is ${age} days old, the refresh is overdue"; rc=1
	else echo "  ok    basemap: 206, the file is ${age} days old"; fi
	# The chart renderer (T-4641): the frame that runs a spec may connect nowhere, and CKAN answers
	# CORS to the host page that reads the views.
	echo "viz"
	csp=$(curl -sS -o /dev/null -D - -m 20 "https://viz.{{ domain }}/render.html" 2>&1 | tr -d '\r' | sed -n 's/^[Cc]ontent-[Ss]ecurity-[Pp]olicy: //p')
	cors=$(curl -sS -o /dev/null -D - -m 20 -H "Origin: https://viz.{{ domain }}" "https://opendata.{{ domain }}/api/3/action/status_show" 2>&1 | tr -d '\r' | sed -n 's/^[Aa]ccess-[Cc]ontrol-[Aa]llow-[Oo]rigin: //p')
	case "$csp" in *"connect-src 'none'"*) ;; *) echo "  FAIL  viz: render.html answered no connect-src 'none' ('${csp}')"; rc=1;; esac
	if [ "$cors" != "https://viz.{{ domain }}" ]; then echo "  FAIL  viz: CKAN answered CORS '${cors}' to the renderer"; rc=1
	else echo "  ok    viz: the renderer connects nowhere, CKAN answers its host page"; fi
	# The postgres data volume (T-4414): the broker's history once filled it ~30 GB a week, every
	# smoke green. Every instance of the cluster, wherever its namespace is; no reading fails too.
	echo "postgres data volume"
	# Instances only: the cluster's completed initdb Job pod carries the same cluster label (smoke 13:45Z).
	pods=$(kubectl get pods -A -l cnpg.io/cluster=postgres-cluster,cnpg.io/podRole=instance -o jsonpath='{range .items[*]}{.metadata.namespace}/{.metadata.name}{"\n"}{end}')
	[ -n "$pods" ] || { echo "  FAIL  postgres data: no pod of postgres-cluster"; rc=1; }
	for pod in $pods; do
		kubectl -n "${pod%%/*}" exec "${pod##*/}" -c postgres -- df -P /var/lib/postgresql/data 2>&1 \
			| python3 scripts/disk-full.py --max 85 --label "postgres data of ${pod##*/}" || rc=1
	done
	exit "$rc"

# Verify the dev cluster (see scripts/smoke.sh)
[group('dev cluster')]
dev-smoke:
	#!/usr/bin/env bash
	set -euo pipefail
	just _dev-guard
	rc=0
	just _smoke "{{ dev_domain }}" dev || rc=1
	# A real forge login as the demo people (T-1422): the button can fail with the rest green.
	echo "forge login"
	./scripts/smoke-forge-login.sh "https://{{ dev_domain }}" || rc=1
	exit "$rc"

# Validate dev against main (T-2799): drift, image pins and signatures, NetworkPolicy probes,
# certificate and backup expiry, Kyverno; the summary is what tasks/file-failures reads
[group('dev cluster')]
dev-validate out='deployment/validate-dev.json':
	#!/usr/bin/env bash
	set -euo pipefail
	just _dev-guard
	just _dev-assemble
	./scripts/validate-dev.py --out "{{ out }}"

# Nightly drift (T-4956): helmfile diff --three-way-merge of dev or smartcity (production) under
# a read-only token (jc-drift-reader, get/list, 30 min). One result per release in <out>; hand it
# to tasks/file-failures, which files one task per drifting release. Never applies anything.
[group('dev cluster')]
drift env out='':
	#!/usr/bin/env bash
	set -euo pipefail
	case "{{ env }}" in
		dev) just _dev-guard ;;
		smartcity) just _prod-guard ;;
		*) echo "drift: environment must be dev or smartcity, not '{{ env }}'" >&2; exit 2 ;;
	esac
	just _dev-assemble
	out="{{ out }}"; out="${out:-deployment/drift-{{ env }}.json}"
	ns=$(kubectl get serviceaccounts -A --field-selector metadata.name=jc-drift-reader -o jsonpath='{.items[0].metadata.namespace}')
	[ -n "$ns" ] || { echo "drift: no jc-drift-reader ServiceAccount on the cluster; apply runtime-policies first" >&2; exit 1; }
	server=$(kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}')
	ca=$(kubectl config view --minify --raw -o jsonpath='{.clusters[0].cluster.certificate-authority-data}')
	token=$(kubectl -n "$ns" create token jc-drift-reader --duration 30m)
	umask 077
	ro=$(mktemp -t drift-kubeconfig.XXXXXX)
	trap 'rm -f "$ro"' EXIT
	cat > "$ro" <<KUBECONFIG
	apiVersion: v1
	kind: Config
	clusters: [{name: c, cluster: {server: "$server", certificate-authority-data: "$ca"}}]
	users: [{name: drift-reader, user: {token: "$token"}}]
	contexts: [{name: drift, context: {cluster: c, user: drift-reader}}]
	current-context: drift
	KUBECONFIG
	unset token
	# Refuse to run with anything that can write: the check reads, it never applies.
	for verb in create patch delete; do
		if [ "$(KUBECONFIG="$ro" kubectl auth can-i "$verb" deployments -A 2>/dev/null)" != no ]; then
			echo "drift: the drift identity can $verb deployments; refusing" >&2; exit 1
		fi
	done
	# Nor anything beyond object reads: nodes/proxy is the kubelet API (exec over a GET).
	for sub in nodes/proxy services/proxy pods/log; do
		if [ "$(KUBECONFIG="$ro" kubectl auth can-i get "$sub" -A 2>/dev/null)" != no ]; then
			echo "drift: the drift identity can get $sub; refusing" >&2; exit 1
		fi
	done
	KUBECONFIG="$ro" ./scripts/validate-dev.py --env "{{ env }}" --skip images,expiry,kyverno,probes --out "$out"

# The monthly restore drill (T-2802): dev's databases copied into a throwaway namespace, counted,
# timed and deleted; with a pinned portal image, its migrations run against the copy
[group('dev cluster')]
dev-restore-drill portal_image='' out='deployment/restore-drill.json':
	#!/usr/bin/env bash
	set -euo pipefail
	just _dev-guard
	mkdir -p "$(dirname "{{ out }}")"
	./scripts/restore-drill.py --out "{{ out }}" {{ if portal_image != '' { '--portal-image ' + portal_image } else { '' } }}

# The recovery test (T-5117): under 50 reads and 5 writes a second, kill the broker, gateway, Portal
# leader, Postgres primary and pipeline-runner one at a time; times, lost writes and stuck pipelines
# in the summary. dev only; announce it with tasks/note first, dev answers errors meanwhile
[group('dev cluster')]
dev-chaos targets='broker,gateway,portal,postgres,pipeline-runner' out='deployment/chaos-recovery.json':
	#!/usr/bin/env bash
	set -euo pipefail
	just _dev-guard
	./scripts/chaos-recovery.py --targets "{{ targets }}" --out "{{ out }}"

# Rotate one credential on dev without downtime (T-5106, OPS-45, Operations/01 Runbook 5):
# scripts/rotate-secret.sh deletes it, applies what makes it again, restarts its readers and
# measures the old value refused; dry=true prints that plan and changes nothing
[group('dev cluster')]
_dev-rotate secret dry *args:
	#!/usr/bin/env bash
	set -euo pipefail
	just _dev-guard
	just _dev-assemble
	./scripts/rotate-secret.sh --instance dev --secret "{{ secret }}" {{ args }} {{ if dry == 'true' { '--dry-run' } else { '' } }}

# A Keycloak client's secret, pushed to the realm by keycloak-config-cli
[group('dev cluster')]
dev-rotate-client client='activity-ingest' dry='false':
	just _dev-rotate "keycloak-client-{{ client }}" "{{ dry }}" --idm "https://idm.{{ dev_domain }}" --realm dev

# A database role's password, applied by CloudNativePG
[group('dev cluster')]
dev-rotate-db role='portal' dry='false':
	just _dev-rotate "db-{{ role }}" "{{ dry }}"

# A forge token, minted again by the forge bootstrap
[group('dev cluster')]
dev-rotate-forge-token holder='gateway' dry='false':
	just _dev-rotate "gitea-token-{{ holder }}" "{{ dry }}" --forge "https://{{ dev_domain }}/git"

# The catalogue's API token, revoked and minted again by the catalogue's token Job
[group('dev cluster')]
dev-rotate-ckan-token dry='false':
	just _dev-rotate ckan-api-token "{{ dry }}" --catalogue "https://opendata.{{ dev_domain }}"

# The model key: the owner creates a new key at the provider and passes its file; delete the old
# key in the provider's account afterwards
[group('dev cluster')]
dev-rotate-model-key file dry='false':
	just _dev-rotate agent-runner-model-key "{{ dry }}" --from-file "{{ file }}" --model-base https://openrouter.ai/api/v1

# The quarterly rotation drill (T-5106): one credential of each kind, with probes read every 2 s;
# the summary goes to the Health tab, which marks the drill stale when none ran for two months
[group('dev cluster')]
dev-rotation-drill model_key_file='' dry='false' out='deployment/rotation-drill.json':
	#!/usr/bin/env bash
	set -euo pipefail
	just _dev-guard
	just _dev-assemble
	mkdir -p "$(dirname "{{ out }}")"
	rc=0
	./scripts/rotation-drill.py --instance dev --domain "{{ dev_domain }}" --realm dev --out "{{ out }}" \
		{{ if model_key_file != '' { '--model-key-file ' + model_key_file } else { '' } }} \
		{{ if dry == 'true' { '--dry-run' } else { '' } }} || rc=$?
	[ "{{ dry }}" = true ] || ./scripts/publish-health.py "{{ out }}" --every-hours 744
	exit "$rc"

# Publish one check's summary to the Portal's Organization > Health tab (T-2803, OPS-53); run it
# after tasks/file-failures, so the tasks it links exist; passed=true for the App probe's chips
[group('dev cluster')]
dev-publish-health summary every_hours passed='false':
	#!/usr/bin/env bash
	set -euo pipefail
	just _dev-guard
	./scripts/publish-health.py "{{ summary }}" --every-hours "{{ every_hours }}" {{ if passed == 'true' { '--passed' } else { '' } }}

# Count each city's validated Smart Data Models datasets against its target of 100 (T-5275); run it
# after dev-apply. Read-only and anonymous; exits 1 when a dataset that passed before fails now
[group('dev cluster')]
dev-open-data-scoreboard out='../evidence/open-data-scoreboard' *cities:
	python3 scripts/open-data-scoreboard.py "{{ dev_domain }}" "{{ out }}" {{ cities }}

# Pin the portal and both app-builder images to one portal commit, checked against the seeded
# workflows (T-2633); run it the moment the portal's image.yml publishes, then dev-apply
[group('dev cluster')]
pin-portal commit:
	./scripts/pin-portal.sh {{ commit }}

# Images by digest (repository@sha256:...), our signature required; empty = dev's pinned Portal.
# Refuses unless dev runs global.branchPreviews and the reaper, the node is under 90 % memory,
# fewer than 2 previews run and fewer than 10 preview certificates were issued this week.
# Start or update the code-branch preview https://preview-<slug>.<dev domain> (ADR-N-062, T-5548)
[group('dev cluster')]
dev-preview $slug $portal_image='' $ui_image='':
	#!/usr/bin/env bash
	set -euo pipefail
	just _dev-guard
	./scripts/preview.sh up "$slug" "$portal_image" "$ui_image"

# Lists what is left afterwards: nothing, or it exits 1 naming it.
# Delete the preview pv-<slug>: namespace, Certificate, database, role and Keycloak client
[group('dev cluster')]
dev-preview-down $slug:
	#!/usr/bin/env bash
	set -euo pipefail
	just _dev-guard
	./scripts/preview.sh down "$slug"

# The kubectl half runs from here, the network half as a Job inside the preview; `runner` is the
# conformance image by digest.
# Run the isolation suite (conformance tests/security/test_preview_isolation.py) against pv-<slug>
[group('dev cluster')]
dev-preview-isolation $slug $runner:
	#!/usr/bin/env bash
	set -euo pipefail
	just _dev-guard
	./scripts/preview.sh isolation "$slug" "$runner"

# Wipe the platform off the dev cluster (announce it in AI_shared_folder.md first!)
[group('dev cluster')]
dev-destroy:
	#!/usr/bin/env bash
	set -euo pipefail
	just _dev-guard
	just _dev-assemble
	helmfile -f deployment/helmfile.yaml -e dev destroy --concurrency {{helmfile_concurrency}} --skip-deps || true
	for ns in $(kubectl get ns -o name | sed 's|namespace/||' | grep -E '^(dev|dev-.*|jc-operators)$'); do
		kubectl delete pvc --all -n "$ns" --ignore-not-found --timeout=120s || true
		kubectl delete namespace "$ns" --ignore-not-found --timeout=300s || true
	done
	echo "remaining platform namespaces:"; kubectl get ns -o name | sed 's|namespace/||' | grep -E '^(dev|dev-.*|jc-operators)$' || echo "  none"

# ---------------------------------------------------------------------------
# The production instance smartcity (T-4678, docs Deployment/14): its own cluster, never dev.
# Run with KUBECONFIG=.secrets/kubeconfig-prod.yaml per command; the guard refuses anything else.
# ---------------------------------------------------------------------------

prod_domain := 'smartcity.joinedcontext.com'
prod_node_ip := '2.28.56.179'

# Refuse to touch anything but the production cluster
[group('prod cluster')]
_prod-guard:
	#!/usr/bin/env bash
	set -euo pipefail
	ip="{{ prod_node_ip }}"
	server=$(kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}' 2>/dev/null || true)
	case "$server" in
		"https://${ip}:"*|"https://${ip}") ;;
		*) echo "refusing: current kube context points at '${server:-<none>}', not the production cluster ($ip). Set KUBECONFIG=.secrets/kubeconfig-prod.yaml" >&2; exit 1 ;;
	esac

# Apply the smartcity environment to the production cluster and wait for every rollout
[group('prod cluster')]
prod-apply:
	#!/usr/bin/env bash
	set -euo pipefail
	just _prod-guard
	# Only an annotated release tag on origin is applied (T-4955); a rollback checks out the
	# previous tag and runs this recipe again.
	tag=$(./scripts/release.py verify HEAD)
	echo "applying release $tag to smartcity"
	just _dev-assemble
	# Every platform digest of the render carries our workflows' signature, or nothing is applied (T-5564).
	./scripts/verify-pinned-images.py smartcity
	# The public assistant is asked every 15 s while the rollouts run (T-4809, at most 40 questions);
	# its summary line closes the apply's output on success and on failure, for the apply report.
	probe_log=$(mktemp -t assistant-probe.XXXXXX)
	./scripts/assistant-probe.py "https://assistant.{{ prod_domain }}" 2>"$probe_log" >"$probe_log.summary" &
	probe=$!
	trap 'kill "$probe" 2>/dev/null; wait "$probe" 2>/dev/null; cat "$probe_log.summary"; echo "assistant probe log: $probe_log"' EXIT
	helmfile -f deployment/helmfile.yaml -e smartcity sync --concurrency {{helmfile_concurrency}}
	./scripts/wait-rollouts.sh smartcity
	./scripts/release.py record smartcity smartcity

# Verify the production instance (scripts/smoke.sh and the shared checks; no demo login exists there)
[group('prod cluster')]
prod-smoke:
	#!/usr/bin/env bash
	set -euo pipefail
	just _prod-guard
	JC_SMOKE_NO_TEST_WRITER=1 just _smoke "{{ prod_domain }}" smartcity

# Moves the `dev-green` branch forward to that commit (never back, never forced).
# Record a commit as green on dev: run after a green `just dev-apply` + `just dev-smoke` of it
[group('prod cluster')]
dev-green sha='HEAD':
	#!/usr/bin/env bash
	set -euo pipefail
	sha=$(git rev-parse --verify "{{ sha }}^{commit}")
	git fetch -q origin main dev-green 2>/dev/null || git fetch -q origin main
	git merge-base --is-ancestor "$sha" origin/main || { echo "refusing: $sha is not on main" >&2; exit 1; }
	git push origin "$sha:refs/heads/dev-green"

# The push is fast-forward only: after a rollback the promotion is a merge commit carrying the
# promoted tree. A rollback is `just rollback prod-<UTC>`.
# Promote a dev-green commit to production, whose Argo CD syncs the `release` branch (T-4678)
[group('prod cluster')]
promote sha='origin/dev-green':
	#!/usr/bin/env bash
	set -euo pipefail
	git fetch -q --tags origin main dev-green release 2>/dev/null || git fetch -q --tags origin main dev-green
	sha=$(git rev-parse --verify "{{ sha }}^{commit}")
	git merge-base --is-ancestor "$sha" origin/dev-green || { echo "refusing: $sha is not green on dev (not in origin/dev-green)" >&2; exit 1; }
	tag="prod-$(date -u +%Y%m%dT%H%MZ)"
	if git rev-parse -q --verify origin/release >/dev/null && ! git merge-base --is-ancestor origin/release "$sha"; then
		sha=$(git commit-tree "$sha^{tree}" -p origin/release -p "$sha" -m "promote $sha to production")
	fi
	git push origin "$sha:refs/heads/release"
	git tag --annotate "$tag" "$sha" -m "promote $sha to production" && git push -q origin "refs/tags/$tag"
	echo "promoted $sha as $tag"

# A new commit on `release` with that tag's tree, so the branch only ever moves forward.
# Put production back on what an earlier promotion shipped
[group('prod cluster')]
rollback tag:
	#!/usr/bin/env bash
	set -euo pipefail
	git fetch -q --tags origin release
	[[ "{{ tag }}" == prod-* ]] || { echo "refusing: '{{ tag }}' is no promotion tag (prod-*)" >&2; exit 1; }
	tree=$(git rev-parse --verify "refs/tags/{{ tag }}^{tree}")
	commit=$(git commit-tree "$tree" -p origin/release -m "rollback production to {{ tag }}")
	git push origin "$commit:refs/heads/release"
	echo "release is now $commit, the tree of {{ tag }}"

# ---------------------------------------------------------------------------
# The BBSK demo (T-4687, demos/bbsk/): its own helmfile and namespace `demo-bbsk`, outside the
# platform's deployment, on dev (the preview) or smartcity. Each recipe refuses a cluster that is
# not the environment's own, as dev-apply and prod-apply do.
# ---------------------------------------------------------------------------

# The catalogue smoke alone (T-4716, Testing/05 §4.1): dev or smartcity, read-only
[group('dev cluster')]
catalogue-smoke env:
	#!/usr/bin/env bash
	set -euo pipefail
	case "{{ env }}" in
		dev) just _dev-guard; domain="{{ dev_domain }}" ;;
		smartcity) just _prod-guard; domain="{{ prod_domain }}" ;;
		*) echo "refusing: the catalogue smoke runs on dev or smartcity, not '{{ env }}'" >&2; exit 1 ;;
	esac
	python3 scripts/smoke-catalogue.py "$domain" "{{ env }}"

# Refuse an environment other than dev or smartcity, or a cluster that is not that one
[group('demo bbsk')]
_demo-bbsk-guard env:
	#!/usr/bin/env bash
	set -euo pipefail
	case "{{ env }}" in
		dev) just _dev-guard ;;
		smartcity) just _prod-guard ;;
		*) echo "refusing: the BBSK demo runs on dev or smartcity, not '{{ env }}'" >&2; exit 1 ;;
	esac

# Render the BBSK demo for one environment to stdout (no cluster needed)
[group('demo bbsk')]
demo-bbsk-render env:
	helmfile -f demos/bbsk/helmfile.yaml.gotmpl -e {{ env }} template --skip-deps --concurrency {{helmfile_concurrency}}

# Install or update the BBSK demo on dev or smartcity
[group('demo bbsk')]
demo-bbsk-apply env:
	#!/usr/bin/env bash
	set -euo pipefail
	just _demo-bbsk-guard {{ env }}
	helmfile -f demos/bbsk/helmfile.yaml.gotmpl -e {{ env }} sync --concurrency {{helmfile_concurrency}}
	kubectl -n demo-bbsk rollout status statefulset/demo-bbsk-db --timeout=300s
	kubectl -n demo-bbsk rollout status deployment/ckan-demo-bbsk --timeout=600s
	kubectl -n demo-bbsk rollout status deployment/demo-bbsk-landing --timeout=120s

# Remove the BBSK demo whole: its releases, volumes and namespace, and nothing of the platform
[group('demo bbsk')]
demo-bbsk-destroy env:
	#!/usr/bin/env bash
	set -euo pipefail
	just _demo-bbsk-guard {{ env }}
	helmfile -f demos/bbsk/helmfile.yaml.gotmpl -e {{ env }} destroy --concurrency {{helmfile_concurrency}} --skip-deps || true
	kubectl delete namespace demo-bbsk --ignore-not-found --timeout=300s
