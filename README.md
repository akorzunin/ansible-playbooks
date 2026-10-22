# My collection of ansible playbooks

## Monitoring as code

See [the monitoring migration and deployment guide](playbooks/ws-logs/README.md).
Load `monitoring.inventory.yml` alongside the private `hosts` inventory to generate
scrape targets, provision shared dashboards/alerts, and configure Telegram routing.

## Budget VPN experiment

See [the Cherry Servers/OpenTofu trial guide](infra/cherry-vpn/README.md) for
credential setup, price guardrails, a disposable SSH proxy and regional probes.
The trial is paused: Cherry identity verification blocked VM creation. See the
[checkpoint and resume checklist](infra/cherry-vpn/README.md#paused-checkpoint--2026-10-22).
Further provisioning requires a fresh reviewed plan and explicit approval.

## Setup

Link `hosts` and `external_vars.yml` from Dropbox:

    ./install.sh

The script checks `~/Dropbox/ssh` and the Termux path
`~/storage/shared/Dropbox/ssh`. Set `DROPBOX_SSH_DIR` to use another path.

Create password file

    ansible-vault create .ansible_pass

Check connection to all hosts

    ansible all -i ./hosts -m ping --vault-password-file=.ansible_pass

## Create new secret

    ansible-vault encrypt_string --vault-password-file .ansible_pass "amogus"

    caddy hash-password --algo=argon2 --plaintext=amogus

## Run playbook

    ansible-playbook --vault-password-file=.ansible_pass ./playbooks/playbook_name.yaml -i ./hosts -l host_name

Run playbook locally

    ```sh
    ansible-playbook --vault-password-file=.ansible_pass ./playbooks/playbook_name.yaml -i localhost, -c local
    ```

Run all checks locally

    ```sh
    pre-commit run --all-files
    ```
