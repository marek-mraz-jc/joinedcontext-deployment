# stage.joinedcontext.com (T-6443): prod's shape, a bigger node for Decidim.
cluster_name              = "k3s"
ssh_key_name              = "ssh-stage"
server_type               = "cpx62"
location                  = "nbg1"
network_region            = "eu-central"
acme_email                = "marek.mraz@joinedcontext.com"
enable_monitoring         = "false"
firewall_allowed_ips      = ["89.167.20.156/32"] # the agents' server
mqtt_ports_open           = false
k3s_channel               = "v1.35"
k3s_version               = "v1.35.9+k3s1"
enable_secrets_encryption = true
automatically_upgrade_os  = true
# T-5892: on one node a lost lease only restarts k3s (leaderelection lost under load). A key given
# here replaces the module's, so the controller manager keeps its flex-volume-plugin-dir.
k3s_server_config = {
  kube-controller-manager-arg       = ["flex-volume-plugin-dir=/var/lib/kubelet/volumeplugins", "leader-elect=false"]
  kube-scheduler-arg                = ["leader-elect=false"]
  kube-cloud-controller-manager-arg = ["leader-elect=false"]
}
