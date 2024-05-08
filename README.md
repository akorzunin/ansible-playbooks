# My collection of ansible playbooks

Shell script to run playbooks (fzf required)
example:
```sh
sh deploy.sh --step --extra-vars "var_host=localhost"
```

Run all checks locally

```sh
pre-commit run --all-files
```

dependencies

```sh
ansible-galaxy install -r requirements.yml
```
