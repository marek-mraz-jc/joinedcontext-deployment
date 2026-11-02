# smartcity.joinedcontext.com, production (T-4677, T-4684). Only prod-deployer plans and applies it.
# k3s_server_config stays empty: the leader-elect flags restart k3s on prod, its own decision.
cluster_name              = "k3s"
ssh_key_name              = "ssh-prod"
server_type               = "cpx52"
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
