variable "state_encryption_passphrase" {
  description = "Shared random Vault-backed passphrase; supplied only through the wrapper environment. Back it up separately from state."
  type        = string
  sensitive   = true

  validation {
    condition     = length(var.state_encryption_passphrase) >= 32
    error_message = "Use the shared random bootstrap encryption secret, not a short password."
  }
}

variable "ssh_host_key" {
  description = "Pre-generated Ed25519 server identity from shared Vault, installed by cloud-init. Host private material is retained only in encrypted plans/state."
  type = object({
    private = string
    public  = string
  })
  sensitive = true

  validation {
    condition = (
      startswith(var.ssh_host_key.private, "-----BEGIN OPENSSH PRIVATE KEY-----") &&
      startswith(var.ssh_host_key.public, "ssh-ed25519 ")
    )
    error_message = "Prepare an Ed25519 SSH host identity with prepare-bootstrap.py first."
  }
}

# Null preserves the applied dyn1 hostname/SSH registration without an update.
variable "node_name" {
  description = "Provider-independent identity for newly initialized dynamic nodes."
  type        = string
  default     = null

  validation {
    condition     = var.node_name == null ? true : can(regex("^dyn[1-9][0-9]*$", var.node_name))
    error_message = "Use dyn1, dyn2, etc."
  }
}

variable "project_id" {
  description = "Existing dedicated, disposable Cherry Servers project; never the applications project."
  type        = number

  validation {
    condition     = var.project_id > 0 && floor(var.project_id) == var.project_id
    error_message = "project_id must be a positive integer."
  }
}

variable "plan" {
  description = "Only the two smallest shared x86 VM generations are permitted in this experiment."
  type        = string
  default     = "B1-1-1gb-20s-shared"

  validation {
    condition     = contains(["B1-1-1gb-20s-shared", "B2-1-1gb-20s-shared"], var.plan)
    error_message = "Budget test permits only 1 vCPU / 1 GB RAM / 20 GB shared VPS plans."
  }
}

variable "allocation_checks" {
  description = "Check live price/stock for VM creation. Lifecycle skips these for existing nodes and rejects unchecked creation."
  type        = bool
  default     = true
}

variable "region" {
  description = "Explicit region selection after checking stock and regional reachability."
  type        = string

  validation {
    condition     = length(trimspace(var.region)) > 0
    error_message = "Choose a region from the live plan catalogue."
  }
}

variable "ssh_public_key_path" {
  description = "Local path to the dedicated administrator PUBLIC key. Administrator/probe private keys stay outside OpenTofu."
  type        = string
}
