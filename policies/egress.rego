# Workloads that fetch an address somebody else chose (a DataSource URL a person types and a
# check probes, a subscriber a subscription names) reach public addresses only (T-0752, MF-39).
# An egress range that leaves a private range reachable lets that address steer the workload at
# the Kubernetes API, a node, a webhook or a metadata service.
package main

private_ranges := {"10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16", "127.0.0.0/8"}

fetches_chosen_addresses(policy) if {
	policy.spec.podSelector.matchLabels["app.kubernetes.io/name"] in {"pipeline-runner-runner", "context-gateway-gateway"}
}

deny contains msg if {
	input.kind == "NetworkPolicy"
	fetches_chosen_addresses(input)
	some rule in input.spec.egress
	some peer in rule.to
	excepted := {cidr | some cidr in object.get(peer.ipBlock, "except", [])}
	missing := private_ranges - excepted
	count(missing) > 0
	msg := sprintf("NetworkPolicy/%s: egress to %s leaves %v reachable", [input.metadata.name, peer.ipBlock.cidr, sort(missing)])
}
