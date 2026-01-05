# Node init

## Install python-passlib on local machine

```sh
yay python-passlib
```

## Deploy node steps

- Add node to hosts file (use this to encrypt passwords `ansible-vault encrypt_string --vault-password-file .ansible_pass "amogus"`)

```sh
ansible-playbook --vault-password-file=.ansible_pass -i ./hosts ./node/init_node.playbook.yaml -e "nn=nodename"
```

- specify roles for infrastructure deployment in node/{NODE_NAME}/services.deploy.yaml

```sh
ansible-playbook --vault-password-file=.ansible_pass ./node/{NODE_NAME}/services.deploy.yaml -i ./hosts -l nodename
```

- deploy caddy separately

```sh
ansible-playbook --vault-password-file=.ansible_pass ./node/{NODE_NAME}/caddy/caddy.deploy.yaml -i ./hosts -l nodename
```
