#!/bin/bash

# Find all playbook files starting with 'deploy' and with.yml or.yaml extension
playbooks=$(find . -type f \( -iname "deploy*.yml" -o -iname "deploy*.yaml" \))

# Use fzf to select a playbook
selected_playbook=$(echo "$playbooks" | fzf --height 40% --reverse)

# Check if a playbook was selected
if [ -n "$selected_playbook" ]; then
    # Run the selected playbook with Ansible
    echo ansible-playbook "$selected_playbook" "$@"
    ansible-playbook "$selected_playbook" "$@"
else
    echo "No playbook selected."
fi
