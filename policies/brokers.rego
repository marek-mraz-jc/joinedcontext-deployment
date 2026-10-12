# Each ContextBroker is its own island (ADR-N-046 §2.5, T-3989): a broker's database admits its
# own broker and no other, and a broker reaches no other broker's database. `main` runs as
# context-broker-broker on the platform's postgres-cluster; every further broker as
# context-broker-{name} on its own context-broker-{name}-db. Checked from both sides, since
# either policy alone opens the path.
package main

broker_of(cluster) := "context-broker-broker" if cluster == "postgres-cluster"

broker_of(cluster) := trim_suffix(cluster, "-db") if {
	startswith(cluster, "context-broker-")
	endswith(cluster, "-db")
}

is_broker(name) if startswith(name, "context-broker-")

deny contains msg if {
	input.kind == "NetworkPolicy"
	own := broker_of(input.spec.podSelector.matchLabels["cnpg.io/cluster"])
	some rule in input.spec.ingress
	some peer in rule.from
	name := peer.podSelector.matchLabels["app.kubernetes.io/name"]
	is_broker(name)
	name != own
	msg := sprintf("NetworkPolicy/%s: the database of %s admits the broker %s", [input.metadata.name, own, name])
}

# A peer naming no pod admits every pod of its namespaces, other brokers among them.
deny contains msg if {
	input.kind == "NetworkPolicy"
	own := broker_of(input.spec.podSelector.matchLabels["cnpg.io/cluster"])
	startswith(input.spec.podSelector.matchLabels["cnpg.io/cluster"], "context-broker-")
	some rule in input.spec.ingress
	some peer in object.get(rule, "from", [{}])
	count(object.get(object.get(peer, "podSelector", {}), "matchLabels", {})) == 0
	msg := sprintf("NetworkPolicy/%s: the database of %s admits a peer that names no pod", [input.metadata.name, own])
}

deny contains msg if {
	input.kind == "NetworkPolicy"
	name := input.spec.podSelector.matchLabels["app.kubernetes.io/name"]
	is_broker(name)
	some rule in input.spec.egress
	some peer in rule.to
	cluster := peer.podSelector.matchLabels["cnpg.io/cluster"]
	owner := broker_of(cluster)
	owner != name
	msg := sprintf("NetworkPolicy/%s: the broker %s reaches the database of %s", [input.metadata.name, name, owner])
}
