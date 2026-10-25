# Local state supports one active controller; use a locked remote backend before
# allowing concurrent provisioning from multiple machines.
terraform {
  required_version = ">= 1.9.0, < 2.0.0"

  encryption {
    key_provider "pbkdf2" "vpn" {
      passphrase = var.state_encryption_passphrase
    }
    method "aes_gcm" "vpn" {
      keys = key_provider.pbkdf2.vpn
    }
    state {
      method   = method.aes_gcm.vpn
      enforced = true
    }
    plan {
      method   = method.aes_gcm.vpn
      enforced = true
    }
  }

  required_providers {
    cherryservers = {
      source  = "cherryservers/cherryservers"
      version = "1.6.1"
    }
  }
}

# Authentication comes only from CHERRY_API_KEY, never tfvars or state inputs.
provider "cherryservers" {}

data "cherryservers_plan" "vpn" {
  slug = var.plan
}

locals {
  hourly_prices = [
    for price in data.cherryservers_plan.vpn.pricing : price
    if lower(price.unit) == "hourly"
  ]
  hourly_price = try(one(local.hourly_prices), null)
}

resource "cherryservers_ssh_key" "admin" {
  name       = "vpn-test-admin"
  public_key = trimspace(file(pathexpand(var.ssh_public_key_path)))
}

# One disposable node only. No extra IPv4 orders, disks, backups or paid services.
resource "cherryservers_server" "vpn" {
  project_id      = var.project_id
  plan            = var.plan
  region          = var.region
  hostname        = "vpn-test"
  image           = "debian_13_64bit"
  cycle           = "hourly"
  spot_instance   = false
  allow_reinstall = false
  ssh_key_ids     = [cherryservers_ssh_key.admin.id]
  # JSON is valid cloud-config YAML and lets the wrapper inspect applied pins
  # without a separate YAML dependency. The host private key is sensitive and
  # necessarily reaches Cherry/cloud-init; state and saved plans are encrypted.
  user_data = base64encode("#cloud-config\n${jsonencode({
    package_update = true
    packages       = ["python3"]
    ssh_pwauth     = false
    ssh_keys = {
      ed25519_private = var.ssh_host_key.private
      ed25519_public  = var.ssh_host_key.public
    }
  })}\n")

  tags = {
    purpose    = "vpn-budget-test"
    managed_by = "opentofu"
  }

  lifecycle {
    # One-node spending ceiling: accept downtime, rather than overlapping VMs.
    # Add health-gated overlap only when redundant capacity/spend is approved.
    create_before_destroy = false

    precondition {
      condition = try(
        local.hourly_price.currency == "EUR" &&
        local.hourly_price.price > 0 && local.hourly_price.price <= 0.015,
        false
      )
      error_message = "Refusing allocation: expected a single EUR hourly price in (0, 0.015]. Review current account pricing. This ceiling excludes taxes and other charges."
    }

    precondition {
      condition = anytrue([
        for region in data.cherryservers_plan.vpn.available_regions :
        region.slug == var.region && region.stock_qty > 0
      ])
      error_message = "The selected smallest plan has no stock in this region. Do not upgrade automatically."
    }
  }
}
