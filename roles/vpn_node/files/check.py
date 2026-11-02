#!/usr/bin/env python3
"""Finite authenticated VPN checks in isolated cores; never change an active client."""
import argparse
import copy
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import struct
import subprocess
import tempfile
import time


def connections(data, node):
    outbounds = copy.deepcopy(data if isinstance(data, list) else data['outbounds'])
    tags = {o['tag'] for o in outbounds}
    if node + '-vless-via-naive' not in tags and {node + '-vless', node + '-naive'} <= tags:
        vless = next(o for o in outbounds if o['tag'] == node + '-vless')
        outbounds.append({**copy.deepcopy(vless), 'tag': node + '-vless-via-naive', 'detour': node + '-naive'})
    return [o for o in outbounds if o['type'] not in ('selector', 'direct', 'urltest')]


def receive(sock, size):
    data = b''
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise OSError('SOCKS control connection closed')
        data += chunk
    return data


def stun(proxy_port, host, port, expected_ip):
    with socket.create_connection(('127.0.0.1', proxy_port), timeout=5) as control, \
            socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
        control.sendall(b'\x05\x01\x00')
        if receive(control, 2) != b'\x05\x00':
            return False
        control.sendall(b'\x05\x03\x00\x01' + b'\x00' * 6)
        if receive(control, 4) != b'\x05\x00\x00\x01':
            return False
        relay_ip = socket.inet_ntoa(receive(control, 4))
        relay_port = struct.unpack('!H', receive(control, 2))[0]
        udp.settimeout(5)
        transaction = os.urandom(12)
        cookie = bytes.fromhex('2112a442')
        request = b'\x00\x01\x00\x00' + cookie + transaction
        domain = host.encode()
        packet = b'\x00\x00\x00\x03' + bytes([len(domain)]) + domain + struct.pack('!H', port) + request
        udp.sendto(packet, ('127.0.0.1' if relay_ip == '0.0.0.0' else relay_ip, relay_port))
        response = udp.recv(4096)
        if len(response) < 4 or response[:3] != b'\x00\x00\x00':
            return False
        kind = response[3]
        if kind not in (1, 3, 4) or (kind == 3 and len(response) < 5):
            return False
        offset = 10 if kind == 1 else 22 if kind == 4 else 7 + response[4]
        body = response[offset:]
        if len(body) < 20 or body[:2] != b'\x01\x01' or body[4:8] != cookie or body[8:20] != transaction:
            return False
        end = 20 + struct.unpack('!H', body[2:4])[0]
        if end > len(body):
            return False
        position = 20
        while position + 4 <= end:
            kind, size = struct.unpack('!HH', body[position:position + 4])
            if position + 4 + size > end:
                return False
            value = body[position + 4:position + 4 + size]
            if kind == 0x0020 and len(value) >= 8 and value[1] == 1:
                return socket.inet_ntoa(bytes(a ^ b for a, b in zip(value[4:8], cookie))) == expected_ip
            position += 4 + (size + 3) // 4 * 4
        return False


def check(outbounds, tag, expected_ip, udp=False):
    with tempfile.TemporaryDirectory(prefix='vpn-node-check-') as work:
        directory = Path(work)
        config = directory / 'config.json'
        config.write_text(json.dumps({
            'log': {'level': 'info'},
            'inbounds': [{'type': 'mixed', 'tag': 'check', 'listen': '127.0.0.1', 'listen_port': 0}],
            'outbounds': outbounds,
            'route': {'final': tag},
        }))
        with (directory / 'core.log').open('w') as log:
            core = subprocess.Popen(['sing-box', 'run', '-c', str(config)], stdout=log, stderr=log)
            try:
                for _ in range(100):
                    if core.poll() is not None:
                        return False
                    match = re.search(r'tcp server started at 127\.0\.0\.1:(\d+)', (directory / 'core.log').read_text())
                    if match:
                        break
                    time.sleep(.1)
                else:
                    return False
                proxy = 'http://127.0.0.1:' + match[1]
                for url, status in [('https://www.gstatic.com/generate_204', '204'),
                                    ('https://www.cloudflare.com/cdn-cgi/trace', '200')]:
                    response = subprocess.run([
                        'curl', '--disable', '--silent', '--show-error', '--noproxy', '', '--proxy', proxy,
                        '--connect-timeout', '10', '--max-time', '20', '--max-filesize', '16384',
                        '--write-out', '\n%{http_code}', url,
                    ], capture_output=True, text=True, timeout=25)
                    body, _, code = response.stdout.rpartition('\n')
                    good = response.returncode == 0 and code == status
                    if status == '200':
                        good = good and 'ip=' + expected_ip in body.splitlines()
                    print(f'{tag}: HTTPS {code or "unavailable"}, expected egress {"PASS" if good else "FAIL"}', flush=True)
                    if not good:
                        return False
                if udp and next(o['type'] for o in outbounds if o['tag'] == tag) in ('vless', 'hysteria2'):
                    for host, port in [('stun.cloudflare.com', 3478), ('stun.l.google.com', 19302)]:
                        try:
                            good = stun(int(match[1]), host, port, expected_ip)
                        except OSError:
                            good = False
                        print(f'{tag}: UDP/STUN {host} {"PASS" if good else "FAIL"}', flush=True)
                        if not good:
                            return False
                return True
            finally:
                core.terminate()
                try:
                    core.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    core.kill()
                    core.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--node', required=True)
    parser.add_argument('--expected-ip', required=True)
    parser.add_argument('--udp', action='store_true', help='Also check VLESS/Hysteria UDP relay with two STUN servers')
    args = parser.parse_args()
    os.umask(0o077)
    ipaddress.ip_address(args.expected_ip)
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,62}', args.node):
        parser.error('Invalid node name')
    outbounds = connections(json.loads(args.input.read_text()), args.node)
    managed = {args.node + '-' + kind for kind in
               ('ssh', 'naive', 'vless', 'hysteria2', 'vless-via-naive', 'ssh-via-workstation')}
    routes = [o['tag'] for o in outbounds if o['tag'] in managed]
    if not routes:
        parser.error('No node connections to check')
    results = [check(outbounds, tag, args.expected_ip, args.udp) for tag in routes]
    return 0 if all(results) else 1


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        raise SystemExit('VPN checks failed; inspect private inputs locally, no credentials were printed.')
