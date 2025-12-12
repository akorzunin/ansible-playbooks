# Node init

## Install python-passlib on client

```sh
yay python-passlib
```

## Deploy node steps

- fill fields in node_config_vars.yaml
- run init_python.sh script on node

```sh
ansible-playbook ./node/generate_node_config.playbook
ansible-playbook ./node/init_node.playbook.yaml -i ./node/root_node_host.yaml -l node
```

- add node to hosts file (use this to encrypt passwords `ansible-vault encrypt_string --vault-password-file .ansible_pass "amogus"`)

```sh
ansible-playbook --vault-password-file=.ansible_pass ./node/setup_node.playbook.yaml -i ./hosts -l nodename
```

- specify roles for infrastructure deployment in node/{NODE_NAME}/services.deploy.yaml

```sh
ansible-playbook --vault-password-file=.ansible_pass ./node/{NODE_NAME}/services.deploy.yaml -i ./hosts -l nodename
````
