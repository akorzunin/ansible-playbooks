# My collection of ansible playbooks

## Setup

Sync files from Dropbox

    ln -s ~/Dropbox/ssh/hosts ./hosts
    ln -s ~/Dropbox/ssh/external_vars.yml ./external_vars.yml

On Termux(Android)

    ln -s ~/storage/shared/Dropbox/ssh/hosts ./hosts
    ln -s ~/storage/shared/Dropbox/ssh/external_vars.yml ./external_vars.yml

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
