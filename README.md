# My collection of ansible playbooks

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
