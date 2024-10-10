# My collection of ansible playbooks

## Create new secret

    ansible-vault encrypt_string --vault-password-file .ansible_pass "amogus"

## Run playbook

    ansible-playbook --vault-password-file=.ansible_pass ./playbooks/deploy_portainer.yaml  -l local_workstation

Run all checks locally

```sh
pre-commit run --all-files
```

dependencies

```sh
ansible-galaxy install -r requirements.yml
```
