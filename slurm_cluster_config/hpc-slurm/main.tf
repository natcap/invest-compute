/**
  * Copyright 2026 Google LLC
  *
  * Licensed under the Apache License, Version 2.0 (the "License");
  * you may not use this file except in compliance with the License.
  * You may obtain a copy of the License at
  *
  *      http://www.apache.org/licenses/LICENSE-2.0
  *
  * Unless required by applicable law or agreed to in writing, software
  * distributed under the License is distributed on an "AS IS" BASIS,
  * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
  * See the License for the specific language governing permissions and
  * limitations under the License.
  */

module "network" {
  source          = "github.com/GoogleCloudPlatform/cluster-toolkit//modules/network/vpc?ref=v1.90.0"
  deployment_name = var.deployment_name
  firewall_rules = [{
    allow = [{
      ports    = [22]
      protocol = "tcp"
    }]
    direction = "INGRESS"
    name      = "fw-allow-ssh"
    ranges    = ["0.0.0.0/0"]
    }, {
    allow = [{
      ports    = [5000]
      protocol = "tcp"
    }]
    direction = "INGRESS"
    name      = "fw-allow-health-checks"
    ranges    = ["35.191.0.0/16", "130.211.0.0/22"]
  }]
  labels     = var.labels
  project_id = var.project_id
  region     = var.region
}

module "private_service_access" {
  source          = "github.com/GoogleCloudPlatform/cluster-toolkit//modules/network/private-service-access?ref=v1.90.0"
  deletion_policy = "ABANDON"
  labels          = var.labels
  network_id      = module.network.network_id
  project_id      = var.project_id
}

module "homefs" {
  source            = "github.com/GoogleCloudPlatform/cluster-toolkit//modules/file-system/filestore?ref=v1.90.0"
  connect_mode      = module.private_service_access.connect_mode
  deployment_name   = var.deployment_name
  labels            = var.labels
  local_mount       = "/home"
  network_id        = module.network.network_id
  project_id        = var.project_id
  region            = var.region
  reserved_ip_range = module.private_service_access.reserved_ip_range
  zone              = var.zone
  size_gb           = 2560
}

module "debug_nodeset" {
  source                  = "github.com/GoogleCloudPlatform/cluster-toolkit//community/modules/compute/schedmd-slurm-gcp-v6-nodeset?ref=v1.90.0"
  allow_automatic_updates = false
  labels                  = var.labels
  machine_type            = "c2-standard-4"
  disk_type               = "pd-ssd"
  name                    = "debug_nodeset"
  node_count_dynamic_max  = 4
  project_id              = var.project_id
  region                  = var.region
  startup_script          = "/home/bin/startup_script.sh"
  subnetwork_self_link    = module.network.subnetwork_self_link
  zone                    = var.zone
}

module "debug_partition" {
  source         = "github.com/GoogleCloudPlatform/cluster-toolkit//community/modules/compute/schedmd-slurm-gcp-v6-partition?ref=v1.90.0"
  exclusive      = false
  is_default     = true
  nodeset        = flatten([module.debug_nodeset.nodeset])
  partition_name = "debug"
}

module "compute_nodeset" {
  source                  = "github.com/GoogleCloudPlatform/cluster-toolkit//community/modules/compute/schedmd-slurm-gcp-v6-nodeset?ref=v1.90.0"
  allow_automatic_updates = false
  bandwidth_tier          = "gvnic_enabled"
  labels                  = var.labels
  machine_type            = "c2-standard-4"
  name                    = "compute_nodeset"
  node_count_dynamic_max  = 20
  project_id              = var.project_id
  region                  = var.region
  startup_script          = "/home/bin/startup_script.sh"
  subnetwork_self_link    = module.network.subnetwork_self_link
  zone                    = var.zone
}

module "compute_partition" {
  source         = "github.com/GoogleCloudPlatform/cluster-toolkit//community/modules/compute/schedmd-slurm-gcp-v6-partition?ref=v1.90.0"
  nodeset        = flatten([module.compute_nodeset.nodeset])
  partition_name = "compute"
}

module "h3_nodeset" {
  source                  = "github.com/GoogleCloudPlatform/cluster-toolkit//community/modules/compute/schedmd-slurm-gcp-v6-nodeset?ref=v1.90.0"
  allow_automatic_updates = false
  bandwidth_tier          = "gvnic_enabled"
  disk_type               = "pd-balanced"
  labels                  = var.labels
  machine_type            = "h3-standard-88"
  name                    = "h3_nodeset"
  node_count_dynamic_max  = 20
  project_id              = var.project_id
  region                  = var.region
  subnetwork_self_link    = module.network.subnetwork_self_link
  zone                    = var.zone
}

module "h3_partition" {
  source         = "github.com/GoogleCloudPlatform/cluster-toolkit//community/modules/compute/schedmd-slurm-gcp-v6-partition?ref=v1.90.0"
  nodeset        = flatten([module.h3_nodeset.nodeset])
  partition_name = "h3"
}

module "slurm_login" {
  source                  = "github.com/GoogleCloudPlatform/cluster-toolkit//community/modules/scheduler/schedmd-slurm-gcp-v6-login?ref=v1.90.0"
  enable_login_public_ips = true
  labels                  = var.labels
  machine_type            = "n2-standard-2"
  name_prefix             = "slurm_login"
  project_id              = var.project_id
  region                  = var.region
  static_ips              = ["10.0.0.3"]
  subnetwork_self_link    = module.network.subnetwork_self_link
  zone                    = var.zone
}

module "slurm_controller" {
  source                       = "github.com/GoogleCloudPlatform/cluster-toolkit//community/modules/scheduler/schedmd-slurm-gcp-v6-controller?ref=v1.90.0"
  deployment_name              = var.deployment_name
  enable_controller_public_ips = true
  labels                       = var.labels
  login_nodes                  = flatten([module.slurm_login.login_nodes])
  machine_type                 = "n2-standard-2"
  network_storage              = flatten([module.homefs.network_storage])
  nodeset                      = flatten([module.h3_partition.nodeset, flatten([module.compute_partition.nodeset, flatten([module.debug_partition.nodeset])])])
  nodeset_dyn                  = flatten([module.h3_partition.nodeset_dyn, flatten([module.compute_partition.nodeset_dyn, flatten([module.debug_partition.nodeset_dyn])])])
  nodeset_tpu                  = flatten([module.h3_partition.nodeset_tpu, flatten([module.compute_partition.nodeset_tpu, flatten([module.debug_partition.nodeset_tpu])])])
  partitions                   = flatten([module.h3_partition.partitions, flatten([module.compute_partition.partitions, flatten([module.debug_partition.partitions])])])
  project_id                   = var.project_id
  region                       = var.region
  subnetwork_self_link         = module.network.subnetwork_self_link
  subnetwork_stack_type        = module.network.subnetwork_stack_type
  zone                         = var.zone
}
