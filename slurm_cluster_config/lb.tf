# Enable the necessary APIs
resource "google_project_service" "enable_cloud_resource_manager_api" {
  service = "cloudresourcemanager.googleapis.com"
}

resource "google_project_service" "enable_secret_manager_api" {
  service = "secretmanager.googleapis.com"
}

resource "google_project_service" "enable_cloud_run_admin_api" {
  service = "run.googleapis.com"
}

# Cloud Run -----------------------------------------------------

# Create a Service Account for the API Gateway
resource "google_service_account" "gateway_sa" {
  account_id   = "api-gateway-sa"
  display_name = "Service Account for API Gateway"
}

# Create a Service Account for the Bridge
resource "google_service_account" "bridge_sa" {
  account_id   = "bridge-proxy-sa"
  display_name = "Cloud Run Bridge Service Account"
}

# Grant it access to the Nginx Secret
resource "google_secret_manager_secret_iam_member" "bridge_secret_access" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.nginx_config.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.bridge_sa.email}"
}

# Create the Cloud Run Service (The Bridge)
resource "google_cloud_run_v2_service" "bridge" {
  name     = "bridge-proxy"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL" # Accessible from Gateway (Public)

  template {
    service_account = google_service_account.bridge_sa.email

    containers {
      image = "nginx:alpine" # Lightweight proxy

      # We inject a simple Nginx config to proxy pass to the Internal LB
      # Note: Cloud Run listens on port 8080 by default
      env {
        name  = "NGINX_PORT"
        value = "8080"
      }

      # We mount the config file (defined below)
      volume_mounts {
        name       = "nginx-conf"
        mount_path = "/etc/nginx/conf.d"
      }
    }

    annotations = {
      # This acts as a trigger: whenever the secret version ID changes,
      # this value changes, forcing Terraform to redeploy the service.
      force-update-key = google_secret_manager_secret_version.nginx_config_data.name
    }

    # MOUNT THE CONFIG
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

    # CRITICAL: Enable Direct VPC Egress to reach Internal LB
    vpc_access {
      network_interfaces {
        network    = "hpc-slurm-net"
        subnetwork = "hpc-slurm-primary-subnet"
      }
      egress = "ALL_TRAFFIC"
    }
  }
}

# 3. Define the Nginx Config (Store as Secret for simplicity in TF)
resource "google_secret_manager_secret" "nginx_config" {
  secret_id = "bridge-nginx-config"
  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "nginx_config_data" {
  secret = google_secret_manager_secret.nginx_config.id

  # This config listens on 8080 and proxies to your INTERNAL LB IP
  secret_data = <<EOF
server {
    listen 8080;
    location / {
        # Replace this with your Internal LB IP or DNS
        proxy_pass http://10.0.0.3:5000/;
    }
}
EOF
}


# Allow the Gateway SA to invoke the Cloud Run service
resource "google_cloud_run_v2_service_iam_binding" "invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.bridge.name
  role     = "roles/run.invoker"

  members = [
    "serviceAccount:${google_service_account.gateway_sa.email}",
  ]
}


#############################################################################

resource "google_project_service" "gateway_services" {
  project = var.project_id
  for_each = toset([
    "apigateway.googleapis.com",
    "servicemanagement.googleapis.com",
    "servicecontrol.googleapis.com",
    "apikeys.googleapis.com"
  ])
  service            = each.key
  disable_on_destroy = false
}

# -------------------------------------------------------------------
# Serverless Network Endpoint Group
# this allows the Load Balancer to talk to the API Gateway

# 1. Serverless NEG (The Bridge)
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

# 2. Backend Service for the Gateway
resource "google_compute_backend_service" "gateway_backend" {
  name        = "gateway-backend-service"
  protocol    = "HTTPS" # Gateways are always HTTPS
  timeout_sec = 30

  backend {
    group = google_compute_region_network_endpoint_group.gateway_neg.id
  }
}

# -----------------------------------------------------------------------
# API Gateway #######################################################

# 1. Define the API Resource
resource "google_api_gateway_api" "api" {
  provider = google-beta
  api_id   = "my-secure-api"
  project  = var.project_id
}

# 3. Create the Gateway Config
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
          { backend_url = google_cloud_run_v2_service.bridge.uri }
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

# Explicitly enable the service that the API created
resource "google_project_service" "api_gateway_service" {
  project = var.project_id

  # This dynamically reads the long "cloud.goog" name from the resource above
  service = google_api_gateway_api.api.managed_service

  # Don't disable this on destroy, or you might get stuck in a dependency loop
  disable_on_destroy = false
}

# 4. Deploy the Gateway
resource "google_api_gateway_gateway" "api_gw" {
  provider   = google-beta
  api_config = google_api_gateway_api_config.api_cfg.id
  gateway_id = "my-gateway"
  region     = var.region
}


# ----------------------------------------------------------------
# API Key

resource "google_apikeys_key" "primary" {
  name         = "primary-api-key"
  display_name = "My Primary API Key"
  project      = var.project_id

  restrictions {
    api_targets {
      service = google_api_gateway_api.api.managed_service
    }
  }
}

output "api_key" {
  value     = google_apikeys_key.primary.key_string
  sensitive = true
}


# ------------------------------------------------------------------------------
# 1. GENERATE SELF-SIGNED CERTIFICATE (The "No Domain" Workaround)
# ------------------------------------------------------------------------------

resource "tls_private_key" "default" {
  algorithm = "RSA"
  rsa_bits  = 2048
}

resource "tls_self_signed_cert" "default" {
  private_key_pem = tls_private_key.default.private_key_pem

  # This subject is "fake" but required. It won't match your IP, causing the warning.
  subject {
    common_name  = "iap-protected-app.internal"
    organization = "My Organization"
  }

  validity_period_hours = 8760 # 1 Year

  allowed_uses = [
    "key_encipherment",
    "digital_signature",
    "server_auth",
  ]
}

# Upload the generated cert to Google Compute Engine
resource "google_compute_ssl_certificate" "default" {
  name_prefix = "self-signed-cert-"
  private_key = tls_private_key.default.private_key_pem
  certificate = tls_self_signed_cert.default.cert_pem

  lifecycle {
    create_before_destroy = true
  }
}

# ------------------------------------------------------------------------------
# 2. UNMANAGED INSTANCE GROUP
#    Collects the individual instances into a group the LB can target.
# ------------------------------------------------------------------------------

# variable "iap_client_name" {
#   description = "IAP client name"
#   type        = string
# }

# variable "iap_client_secret" {
#   description = "IAP client secret"
#   type        = string
# }


resource "google_compute_instance_group" "unmanaged_group" {
  name        = "my-unmanaged-ig"
  description = "Unmanaged instance group for Terraform LB"
  network = "https://www.googleapis.com/compute/v1/projects/${var.project_id}/global/networks/hpc-slurm-net"
  instances   = [
    "https://www.googleapis.com/compute/v1/projects/${var.project_id}/zones/${var.zone}/instances/hpcslurm-slurm-login-001"]

  # CRITICAL: The Load Balancer looks for this specific named port
  named_port {
    name = "http"
    port = 5000
  }

  zone = var.zone
}

# ------------------------------------------------------------------------------
# 3. LOAD BALANCER COMPONENTS
# ------------------------------------------------------------------------------

# # Health Check - Monitors if instances are responsive
# resource "google_compute_health_check" "default" {
#   name               = "http-health-check"
#   timeout_sec        = 1
#   check_interval_sec = 1

#   http_health_check {
#     port = 5000
#   }
# }

# URL Map - Routes incoming requests to the Backend Service
# "http-lb-url-map" appears as a "Classic Application Load Balancer"
# in the console
#
# TODO: use HTTPS
resource "google_compute_url_map" "default" {
  name            = "http-lb-url-map"
  default_service = google_compute_backend_service.gateway_backend.id
}

# # Target Proxy - Termination point for HTTP connections
# resource "google_compute_target_http_proxy" "default" {
#   name    = "http-lb-proxy"
#   url_map = google_compute_url_map.default.id
# }

# # Global Forwarding Rule - The Frontend IP Address
# resource "google_compute_global_forwarding_rule" "default" {
#   name       = "http-lb-forwarding-rule"
#   target     = google_compute_target_http_proxy.default.id
#   port_range = "80"
# }

# HTTPS Proxy - Uses the Self-Signed Cert
resource "google_compute_target_https_proxy" "default" {
  name             = "iap-https-proxy"
  url_map          = google_compute_url_map.default.id
  ssl_certificates = [google_compute_ssl_certificate.default.id]
}

# Forwarding Rule - Listens on HTTPS (443)
resource "google_compute_global_forwarding_rule" "default" {
  name       = "iap-forwarding-rule"
  target     = google_compute_target_https_proxy.default.id
  port_range = "443"
}

# ------------------------------------------------------------------------------
# 4. FIREWALL RULES
#    Required for the Google Load Balancer to talk to your instances.
# ------------------------------------------------------------------------------

# resource "google_compute_firewall" "allow_lb_health_check" {
#   name    = "allow-lb-health-check"
#   network = "hpc-slurm-net"

#   allow {
#     protocol = "tcp"
#     ports    = ["5000"]
#   }

#   # These are the specific IP ranges Google uses for health checks
#   source_ranges = ["130.211.0.0/22", "35.191.0.0/16"]
#   target_tags   = ["http-server"]
# }


# IAP #####################################

# resource "google_project_service" "iap_service" {
#   project = var.project_id
#   service = "iap.googleapis.com"
#   disable_on_destroy = false
# }

# resource "google_iap_web_backend_service_iam_member" "iap_access" {
#   project = var.project_id
#   web_backend_service = google_compute_backend_service.default.name

#   # Role required to access the app
#   role = "roles/iap.httpsResourceAccessor"

#   # The user you want to allow (change to your email)
#   member = "user:esoth@stanford.edu"
# }


# TODO:
# reserve a static external IP address for the load balancer




output "load_balancer_ip" {
  description = "The public IP address of the global load balancer"
  value       = google_compute_global_forwarding_rule.default.ip_address
}
