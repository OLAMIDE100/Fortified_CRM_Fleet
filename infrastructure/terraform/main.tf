terraform {
  required_providers {
    google = {
      version = "7.45.0"
    }
  }
}



terraform {
  backend "gcs" {
    bucket = "agentic-hackerton-terraform-backend"
    prefix = "fortified-crm-fleet/state"
  }
}

provider "google" {

  project = var.gcp_project_name
  region  = var.region
}

data "google_project" "project" {}
