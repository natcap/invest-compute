# Configure remote state
terraform {
  backend "gcs" {
    bucket  = "invest_compute_terraform_state"
  }
}

# Enable the necessary APIs ---------------------------------------------------
resource "google_project_service" "enable_services" {
  project = var.project_id
  for_each = toset([
    "apigateway.googleapis.com",
    "apikeys.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "servicemanagement.googleapis.com",
    "servicecontrol.googleapis.com"
  ])
  service            = each.key
  disable_on_destroy = false
}


# Cloud Run Service -----------------------------------------------------------
#
# This service runs a minimal nginx proxy that redirects traffic to the
# internal server. This is necessary because the server is running privately
# in the VPC network, but the API Gateway is outside the VPC network and needs
# a public URL to point to. Cloud Run provides that public URL while also
# having access to the VPC network and the private server running there.

# Create a Service Account for the Cloud Run Service
resource "google_service_account" "cloud_run_sa" {
  account_id   = "cloud-run-sa"
  display_name = "Service Account for Cloud Run"
}

# Grant it access to the nginx Secret
resource "google_secret_manager_secret_iam_member" "cloud_run_secret_access" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.nginx_config.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.cloud_run_sa.email}"
}

# Create the Cloud Run Service
resource "google_cloud_run_v2_service" "proxy" {
  name     = "cloud-run-proxy"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL" # Accessible from Gateway (Public)
  deletion_protection = false

  template {
    service_account = google_service_account.cloud_run_sa.email

    containers {
      image = "nginx:alpine"

      # Mount the config volume
      volume_mounts {
        name       = "nginx-conf"
        mount_path = "/etc/nginx/conf.d"
      }
    }

    annotations = {
      # this causes terraform to redeploy the service whenever the secret changes
      force-update-key = google_secret_manager_secret_version.nginx_config_data.name
    }

    # Create a volume containing the config defined below
    volumes {
      name = "nginx-conf"
      secret {
        secret = google_secret_manager_secret.nginx_config.secret_id
        items {
          version  = "latest"
          path = "default.conf"
        }
      }
    }

    # Enable VPC egress so that this service can reach the internal server
    vpc_access {
      network_interfaces {
        network    = "hpc-slurm-net"
        subnetwork = "hpc-slurm-primary-subnet"
      }
      egress = "ALL_TRAFFIC"
    }
  }
}

# Define the nginx config
# Though the contents are not really secret, storing the config data
# as a Secret is a convenient way to make it accessible as a volume
# in the Cloud Run service.
resource "google_secret_manager_secret" "nginx_config" {
  secret_id = "proxy-nginx-config"
  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "nginx_config_data" {
  secret = google_secret_manager_secret.nginx_config.id

  # This config listens on 8080 and proxies to the internal server
  # Cloud Run listens on port 8080 by default
  # No trailing slash on the URL tells it to pass the full path along
  # TODO: get the interal server IP dynamically in terraform
  secret_data = <<EOF
server {
    listen 8080;
    location / {
        proxy_pass http://10.0.0.3:5000;
    }
}
EOF
}


# Allow the Gateway SA to invoke the Cloud Run service
resource "google_cloud_run_v2_service_iam_binding" "invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.proxy.name
  role     = "roles/run.invoker"

  members = [
    "serviceAccount:${google_service_account.gateway_sa.email}",
  ]
}


# -----------------------------------------------------------------------------
# Serverless Network Endpoint Group
#
# this is needed to allow the Load Balancer to talk to the API Gateway.
#

# Create the Network Endpoint Group
resource "google_compute_region_network_endpoint_group" "gateway_neg" {
  provider = google-beta
  name                  = "gateway-neg"
  network_endpoint_type = "SERVERLESS"
  region                = var.region

  serverless_deployment {
    platform = "apigateway.googleapis.com"
    resource = google_api_gateway_gateway.api_gw.gateway_id
  }
}

# Create the Backend Service
resource "google_compute_backend_service" "gateway_backend" {
  name        = "gateway-backend-service"
  protocol    = "HTTPS" # Gateways are always HTTPS
  timeout_sec = 30

  backend {
    group = google_compute_region_network_endpoint_group.gateway_neg.id
  }
}

# -----------------------------------------------------------------------
# API Gateway
#

# Create a Service Account for the API Gateway
resource "google_service_account" "gateway_sa" {
  account_id   = "api-gateway-sa"
  display_name = "Service Account for API Gateway"
}

# Create the API
resource "google_api_gateway_api" "api" {
  provider = google-beta
  api_id   = "my-secure-api"
  project  = var.project_id
}

# Create the API Config
# this references the openapi yml, which defines our endpoints
resource "google_api_gateway_api_config" "api_cfg" {
  provider      = google-beta
  api           = google_api_gateway_api.api.api_id
  api_config_id_prefix = "my-config-"

  openapi_documents {
    document {
      path     = "spec.yml"
      contents = base64encode(
        templatefile(
          "../../bundled-openapi.yml",
          { backend_url = google_cloud_run_v2_service.proxy.uri }
        )
      )
    }
  }

  lifecycle {
    create_before_destroy = true
  }

  gateway_config {
    backend_config {
      google_service_account = google_service_account.gateway_sa.email
    }
  }
}

# Wait for the API Gateway Managed Service to propagate
resource "time_sleep" "wait_for_api_service_propagation" {
  create_duration = "60s"

  depends_on = [google_api_gateway_api.api]
}

# Explicitly enable the service that the API created
resource "google_project_service" "api_gateway_service" {
  project = var.project_id

  # This dynamically reads the long "cloud.goog" name from the resource above
  service = google_api_gateway_api.api.managed_service

  # Don't disable this on destroy, or you might get stuck in a dependency loop
  disable_on_destroy = false

  # Wait for the timer to give time for the service to appear
  depends_on = [time_sleep.wait_for_api_service_propagation]
}

# Create the API Gateway
resource "google_api_gateway_gateway" "api_gw" {
  provider   = google-beta
  api_config = google_api_gateway_api_config.api_cfg.id
  gateway_id = "my-gateway"
  region     = var.region
}


# -----------------------------------------------------------------------------
# API Key
#
# The client must provide this key in their requests as a URL parameter
# called "key". The API Gateway enforces that the key is provided correctly.
# The key may be accessed by running `terraform output api_key` after a
# successful `terraform apply`.
#
# TODO: Generate separate keys for multiple users

resource "google_apikeys_key" "primary_key" {
  name         = "primary-key"
  display_name = "My Primary API Key"
  project      = var.project_id

  restrictions {
    api_targets {
      service = google_api_gateway_api.api.managed_service
    }
  }
}

output "api_key" {
  value     = google_apikeys_key.primary_key.key_string
  sensitive = true
}


# ------------------------------------------------------------------------------
# Load Balancer
#
# This is the client-facing component of the infrastructure. Clients will make
# requests directly to the Load Balancer's IP address.
# Benefits of using a Load Balancer here:
# - It is a global service, so worldwide traffic is efficiently directed to the
#   backend (vs. with a regional component like API Gateway, there is higher
#   latency for clients farther from our zone e.g. us-central1-a)
# - TODO: we can attach Cloud Armor to the Load Balancer

# URL Map - Routes incoming requests to the Backend Service
# "load-balancer-url-map" appears as a "Classic Application Load Balancer"
# in the console
resource "google_compute_url_map" "default" {
  name            = "load-balancer-url-map"
  default_service = google_compute_backend_service.gateway_backend.id
}

# Define the domain name pointing to the Load Balancer as a variable
variable "domain_name" {
  description = "The load balancer domain name, e.g. 'compute.naturalcapitalalliance.org'"
  type        = string
}

# Create a Google-managed SSL certificate for the load balancer
resource "google_compute_managed_ssl_certificate" "default" {
  provider = google-beta
  name     = "invest-compute-ssl-cert"

  managed {
    domains = [var.domain_name]
  }
}

# Create HTTPS Proxy using the Google-managed SSL certificate
resource "google_compute_target_https_proxy" "default" {
  provider         = google-beta
  name             = "https-proxy"
  url_map          = google_compute_url_map.default.id
  ssl_certificates = [google_compute_managed_ssl_certificate.default.name]
  depends_on = [google_compute_managed_ssl_certificate.default]
}

# Create a Forwarding Rule - Listens on HTTPS (443)
resource "google_compute_global_forwarding_rule" "default" {
  name       = "forwarding-rule"
  target     = google_compute_target_https_proxy.default.id
  port_range = "443"
  ip_address = google_compute_global_address.default.address
}

# Reserve a static external IP address for the load balancer
resource "google_compute_global_address" "default" {
  project      = var.project_id
  name         = "load-balancer-address"
  address_type = "EXTERNAL"
}

# -----------------------------------------------------------------------------
# Storage Bucket
#
# Job workspaces will be uploaded to this bucket. Users can download their
# results and logs from the bucket.
resource "google_storage_bucket" "invest-compute-workspaces" {
  name          = "invest-compute-workspaces"
  location      = "US"
  force_destroy = true

  # delete contents older than 3 days
  lifecycle_rule {
    condition {
      age = 3
    }
    action {
      type = "Delete"
    }
  }
}

# Make bucket public - anyone can view contents
resource "google_storage_bucket_iam_member" "member" {
  provider = google
  bucket   = google_storage_bucket.invest-compute-workspaces.name
  role     = "roles/storage.objectViewer"
  member   = "allUsers"
}

# -----------------------------------------------------------------------------
# Testing Infrastructure

# Create a Service Account for Github Actions to allow uploading to bucket
resource "google_service_account" "github_actions_sa" {
  account_id   = "github-actions-sa"  # this is referenced in the GHA workflow
  display_name = "Service Account for Github Actions"
}

# Give the Service Account permission to create bucket objects
resource "google_project_iam_member" "github_actions_uploader_binding" {
  project = var.project_id
  role    = "roles/storage.objectCreator"
  member  = "serviceAccount:${google_service_account.github_actions_sa.email}"
}

# Define the GitHub Organization name as a variable
variable "github_repo" {
  description = "The GitHub repo name, for example 'natcap/invest-compute'"
  type        = string
}

# Create Workload Identity Pool and Provider to authenticate GHA workflows
resource "google_iam_workload_identity_pool" "github_actions" {
  workload_identity_pool_id = "github-actions-pool"
}

resource "google_iam_workload_identity_pool_provider" "github_actions" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.github_actions.workload_identity_pool_id
  workload_identity_pool_provider_id = "github-actions"
  attribute_condition = <<EOT
    assertion.repository == "${var.github_repo}"
EOT

  # Default mappings copied from terraform google provider documentation
  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.actor"      = "assertion.actor"
    "attribute.aud"        = "assertion.aud"
    "attribute.repository" = "assertion.repository"
  }
  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

# Allow identities from the pool to impersonate the service account
resource "google_project_iam_member" "github_binding" {
  project = var.project_id
  role    = "roles/iam.workloadIdentityUser"
  member  = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github_actions.name}/attribute.repository/${var.github_repo}"
}

output "github_actions_workload_identity_provider_name" {
  description = "Workload identity provider name to be used in the github actions workflow"
  value = google_iam_workload_identity_pool_provider.github_actions.name
}

output "github_actions_service_account_email" {
  description = "Service account email to be used in the github actions workflow"
  value = google_service_account.github_actions_sa.email
}

output "load_balancer_ip" {
  description = "The public IP address of the global load balancer"
  value       = google_compute_global_forwarding_rule.default.ip_address
}
