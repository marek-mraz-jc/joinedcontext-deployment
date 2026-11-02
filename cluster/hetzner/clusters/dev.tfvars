# dev.joinedcontext.com, the workbench: the primaleto cluster since T-3040 (node
# k3s-control-plane-nbg1-ivh, hcloud CSI), which this repository did not create. Its token and state
# are not on the board: T-6446 checks these values with a plan before anyone adopts it.
# k3s stays on the live minor until its upgrade task; secrets encryption is fixed at creation.
cluster_name              = "k3s"
node_pool_name            = "control-plane-nbg1"
enable_hetzner_csi        = true
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
