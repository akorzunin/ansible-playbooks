"""Check explicitly selected backup paths against Docker storage; never print secrets."""

import json
import os
import stat
import subprocess
import sys


def covered(path, roots):
    path = os.path.realpath(path)
    return any(os.path.commonpath([path, root]) == root for root in roots)


def inspect(paths, containers):
    if not paths or not all(os.path.isabs(path) for path in paths):
        raise ValueError('Backup paths must be a nonempty list of absolute paths')
    roots = [os.path.realpath(path) for path in paths]
    for path in roots:
        if path == '/' or not os.path.exists(path):
            raise ValueError(f'Unsafe or missing backup path: {path}')
    selected = []
    for container in containers:
        labels = container['Config'].get('Labels') or {}
        workdir = labels.get('com.docker.compose.project.working_dir', '')
        mounts = container['Mounts']
        if not (workdir and covered(workdir, roots)) and not any(
            covered(mount['Source'], roots) for mount in mounts
        ):
            continue
        # Writable external volumes must be explicitly included, not silently missed.
        for mount in mounts:
            if mount['RW'] and not stat.S_ISSOCK(os.stat(mount['Source']).st_mode):
                if not covered(mount['Source'], roots):
                    raise ValueError(f"Include external storage for {container['Name']}: {mount['Source']}")
        selected.append(container)
    return {
        'paths': roots,
        'containers': selected,
        'running_ids': [c['Id'] for c in selected if c['State']['Running']],
    }


def main():
    ids = subprocess.check_output(['docker', 'ps', '-aq'], text=True).split()
    containers = json.loads(subprocess.check_output(['docker', 'inspect', *ids])) if ids else []
    result = inspect(json.loads(sys.argv[1]), containers)
    if covered(sys.argv[2], result['paths']):
        raise ValueError('Backup staging must be outside the source trees')
    # Full inspection includes environment credentials: only write into private staging.
    with open(sys.argv[2], 'w', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2)
    print(json.dumps({'paths': result['paths'], 'running_ids': result['running_ids']}))


if __name__ == '__main__':
    main()
