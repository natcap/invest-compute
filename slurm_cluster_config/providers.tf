# Explicitly set the billing (quota) project
# https://github.com/hashicorp/terraform-provider-google/issues/24500
provider "google" {
  project = var.project_id
  region  = var.region
  zone    = var.zone
  billing_project       = "sdss-sdss-invest-compute"
  user_project_override = true
}

provider "google-beta" {
  project = var.project_id
  region  = var.region
  zone    = var.zone
  billing_project       = "sdss-sdss-invest-compute"
  user_project_override = true
}
