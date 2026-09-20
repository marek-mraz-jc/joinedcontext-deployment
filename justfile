# .DEFAULT_GOAL := help

set dotenv-load

# MINIKUBE_IP := $(shell minikube ip)
marker := 'LOCAL_JOINEDCONTEXT_HOSTS'
hosts := 'idm.joinedcontext.test joinedcontext.test'

default:
	@just --list

# Run pre-commit on all files
[group('test & lint')]
validate:
	pre-commit run --all-files;

sync-component environment='local' component='':
	echo "Syncing component: {{component}} in environment: {{environment}}"
	helmfile -f ./deployment/helmfile.yaml sync -e {{environment}} --selector component={{component}}

# Destroy a specific component in an environment
[group('deployment')]
destroy-component environment='local' component='':
	echo "Destroying component: {{component}} in environment: {{environment}}"
	helmfile -f ./deployment/helmfile.yaml destroy -e {{environment}} --selector component={{component}}

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
	@helmfile template -f deployment/helmfile.yaml -e local --selector component=keycloak --skip-deps -q | yq 'select(.kind == "StatefulSet") | .metadata.namespace'

# Get APISix namespace
[group('helpers')]
_get-apisix-namespace:
	@helmfile template -f deployment/helmfile.yaml -e local --selector component=apisix --skip-deps -q | yq 'select(.kind == "Deployment" ) | .metadata.namespace'

# Get Postgres namespace
[group('helpers')]
_get-postgres-namespace:
	@helmfile template -f deployment/helmfile.yaml -e local --selector component=postgres --skip-deps -q | yq 'select(.kind == "Deployment") | .metadata.namespace'

# Deploy the shared cluster operators (CloudNativePG, Strimzi) ONCE per cluster.
# Run this before deploying any instances; re-running is idempotent.
[group('deployment')]
deploy-operators environment='local':
	echo "Deploying shared cluster operators in environment: {{environment}}"
	helmfile -f ./deployment/helmfile-operators.yaml sync -e {{environment}}

# Deploy a single instance (everything except the shared operators). The shared operators
# must already be running (see deploy-operators). Optionally override the instance slug
# (namespace + Keycloak realm) ad-hoc; otherwise the environment's instanceSlug is used.
[group('deployment')]
deploy-instance environment='local' slug='':
	if [ -n "{{slug}}" ]; then \
		echo "Deploying instance '{{slug}}' in environment: {{environment}}"; \
		helmfile -f ./deployment/helmfile-instance.yaml.gotmpl sync -e {{environment}} --state-values-set-string instanceSlug={{slug}}; \
	else \
		echo "Deploying instance in environment: {{environment}}"; \
		helmfile -f ./deployment/helmfile-instance.yaml.gotmpl sync -e {{environment}}; \
	fi

# Destroy a single instance (everything except the shared operators)
[group('deployment')]
destroy-instance environment='local' slug='':
	if [ -n "{{slug}}" ]; then \
		helmfile -f ./deployment/helmfile-instance.yaml.gotmpl destroy -e {{environment}} --state-values-set-string instanceSlug={{slug}}; \
	else \
		helmfile -f ./deployment/helmfile-instance.yaml.gotmpl destroy -e {{environment}}; \
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
		helmfile -f ./deployment/helmfile.yaml sync -e {{environment}}; \
	else \
		echo "Syncing component: {{component}} in environment: {{environment}}"; \
		helmfile -f ./deployment/helmfile.yaml sync -e {{environment}} --selector component={{component}}; \
	fi

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
		if [ -d "$$d" ]; then \
			name=$$(basename "$$d"); \
			echo "Updating $$name..."; \
			( cd components && copier update --skip-answered --vcs-ref 8969ae22 -a "$$name/.copier-answers.yml" ) || echo "copier update failed for $$name"; \
		fi; \
	done

# Refresh .ci/golden/local.txt after an intentional change to the rendered output
[group('test & lint')]
golden-update:
	#!/usr/bin/env bash
	set -euo pipefail
	just _dev-assemble
	scripts/render.sh local /tmp/golden-local.yaml --deployed >/dev/null
	python3 .ci/golden/list-objects.py /tmp/golden-local.yaml > .ci/golden/local.txt
	wc -l .ci/golden/local.txt

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
		helmfile -f ./deployment/helmfile.yaml template -e {{environment}}; \
	else \
		echo "Rendering helmfile for component: {{component}} in environment: {{environment}}"; \
		helmfile -f ./deployment/helmfile.yaml template -e {{environment}} --selector component={{component}}; \
	fi

# Render helmfile for a specific component in an environment
[group('helpers')]
template-component environment='local' component='':
	helmfile -f ./deployment/helmfile.yaml template -e {{environment}} --selector component={{component}}

# Render the shared operator layer (deploy-operators)
[group('helpers')]
template-operators environment='local':
	helmfile -f ./deployment/helmfile-operators.yaml template -e {{environment}}

# Render a single instance layer (deploy-instance); optional ad-hoc slug override
[group('helpers')]
template-instance environment='local' slug='':
	if [ -n "{{slug}}" ]; then \
		helmfile -f ./deployment/helmfile-instance.yaml.gotmpl template -e {{environment}} --state-values-set-string instanceSlug={{slug}}; \
	else \
		helmfile -f ./deployment/helmfile-instance.yaml.gotmpl template -e {{environment}}; \
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
		helmfile template \
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
	@helmfile -f deployment/helmfile.yaml sync -e {{profile}}

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

# Install dependencies
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
		curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"; \
		sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl; \
	else \
		echo "kubectl is already installed."; \
	fi
	if ! which helm > /dev/null; then \
		curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash; \
		helm plugin install https://github.com/databus23/helm-diff; \
	else \
		echo "Helm is already installed."; \
	fi
	if ! which helmfile > /dev/null; then \
		curl -LO https://github.com/helmfile/helmfile/releases/download/v1.2.3/helmfile_1.2.3_linux_amd64.tar.gz; \
		tar -xzf helmfile_1.2.3_linux_amd64.tar.gz && sudo install -o root -g root -m 0755 helmfile /usr/local/bin/helmfile; \
		rm helmfile_1.2.3_linux_amd64.tar.gz; \
	else \
		echo "Helmfile is already installed."; \
	fi
	if ! which linkerd > /dev/null; then \
		export LINKERD2_VERSION=edge-25.12.2; \
		curl --proto '=https' --tlsv1.2 -sSfL https://run.linkerd.io/install-edge | sh; \
		export PATH=$HOME/.linkerd2/bin:$PATH; \
		echo 'export PATH="$HOME/.linkerd2/bin:$PATH"' >> ~/.bashrc; \
		linkerd version; \
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

dev_domain := env('JC_DEV_DOMAIN', '2.28.67.127.sslip.io')

# Refuse to touch anything but the dev cluster
[group('dev cluster')]
_dev-guard:
	#!/usr/bin/env bash
	set -euo pipefail
	ip="${JC_DEV_DOMAIN:-{{ dev_domain }}}"; ip="${ip%.sslip.io}"
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
	helmfile -f deployment/helmfile.yaml -e dev sync
	./scripts/wait-rollouts.sh dev

# Verify the dev cluster (see scripts/smoke.sh)
[group('dev cluster')]
dev-smoke:
	#!/usr/bin/env bash
	set -euo pipefail
	just _dev-guard
	rc=0
	./scripts/smoke.sh "https://{{ dev_domain }}" "https://idm.{{ dev_domain }}" || rc=1
	# A real forge login as the demo people (T-1422): the button can fail with the rest green.
	echo "forge login"
	./scripts/smoke-forge-login.sh "https://{{ dev_domain }}" || rc=1
	exit "$rc"

# Wipe the platform off the dev cluster (announce it in AI_shared_folder.md first!)
[group('dev cluster')]
dev-destroy:
	#!/usr/bin/env bash
	set -euo pipefail
	just _dev-guard
	just _dev-assemble
	helmfile -f deployment/helmfile.yaml -e dev destroy --skip-deps || true
	for ns in $(kubectl get ns -o name | sed 's|namespace/||' | grep -E '^(dev|dev-|jc-operators$)'); do
		kubectl delete pvc --all -n "$ns" --ignore-not-found --timeout=120s || true
		kubectl delete namespace "$ns" --ignore-not-found --timeout=300s || true
	done
	echo "remaining platform namespaces:"; kubectl get ns -o name | sed 's|namespace/||' | grep -E '^(dev|jc-operators)' || echo "  none"
