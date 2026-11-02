# dev.joinedcontext.com, the workbench. Values from hetzner-kit (kube-hetzner 3.1.0 there): k3s stays
# on the live minor until its upgrade task; secrets encryption is fixed at creation.
cluster_name              = "k3s"
ssh_key_name              = "ssh-dev"
server_type               = "cpx42"
location                  = "nbg1"
network_region            = "eu-central"
acme_email                = "marek.mraz@joinedcontext.com"
enable_monitoring         = "false"
firewall_allowed_ips      = ["89.167.20.156/32"] # the agents' server
mqtt_ports_open           = true
k3s_channel               = "v1.33"
enable_secrets_encryption = false
automatically_upgrade_os  = false
# T-5892: on one node a lost lease only restarts k3s (leaderelection lost under load). A key given
# here replaces the module's, so the controller manager keeps its flex-volume-plugin-dir.
k3s_server_config = {
  kube-controller-manager-arg       = ["flex-volume-plugin-dir=/var/lib/kubelet/volumeplugins", "leader-elect=false"]
  kube-scheduler-arg                = ["leader-elect=false"]
  kube-cloud-controller-manager-arg = ["leader-elect=false"]
}
