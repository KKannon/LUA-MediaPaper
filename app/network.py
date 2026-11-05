"""Local network addresses used to expose the app to other devices."""
import ipaddress
import socket

def local_addresses():
    """IPv4 addresses of this computer that other devices on the network can reach."""
    found = []
    def add(value):
        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            return
        if address.version == 4 and not address.is_loopback and not address.is_link_local and not address.is_unspecified and value not in found:
            found.append(value)
    try:
        # No packet is sent: connecting a UDP socket only selects the outgoing interface.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(('10.255.255.255', 1))
            add(probe.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            add(info[4][0])
    except OSError:
        pass
    return found

def allowed_hosts(host):
    """Host names accepted by Django for the address the server listens on."""
    hosts = ['localhost', '127.0.0.1', '[::1]']
    if host in ('0.0.0.0', '::', ''):
        hosts += local_addresses()
        name = socket.gethostname()
        if name:
            hosts += [name, name + '.local']
    elif host not in hosts:
        hosts.append(host)
    return ','.join(dict.fromkeys(hosts))

def network_urls(host, port):
    if host in ('0.0.0.0', '::', ''):
        return [f'http://{address}:{port}/' for address in local_addresses()]
    if host in ('127.0.0.1', 'localhost', '::1'):
        return []
    return [f'http://{host}:{port}/']
