"""Réseau local : interfaces, adresses de diffusion, candidats pour la recherche de machines (sans dépendance)."""
import ipaddress
import re
import socket
import subprocess
from typing import Dict, List, Set

ADDR_RE = re.compile(r"^\d+:\s+(?P<if>\S+)\s+inet\s+(?P<ip>\d+\.\d+\.\d+\.\d+)/(?P<prefix>\d+)"
                     r"(?:\s+brd\s+(?P<brd>\d+\.\d+\.\d+\.\d+))?")


def local_ip() -> str:
    """Adresse IP locale principale (sans émettre aucun paquet)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def parse_ip_addr(text: str) -> List[Dict]:
    """Analyse la sortie de « ip -4 -o addr show » (interfaces IPv4 hors bouclage)."""
    out = []
    for line in text.splitlines():
        m = ADDR_RE.match(line.strip())
        if not m or m.group("if") == "lo":
            continue
        ip, prefix = m.group("ip"), int(m.group("prefix"))
        try:
            net = ipaddress.ip_network("%s/%d" % (ip, prefix), strict=False)
        except ValueError:
            continue
        out.append({"if": m.group("if"), "ip": ip, "prefix": prefix,
                    "brd": m.group("brd") or (str(net.broadcast_address) if prefix < 31 else "")})
    return out


def interfaces() -> List[Dict]:
    try:
        r = subprocess.run(["ip", "-4", "-o", "addr", "show"], capture_output=True, text=True, timeout=3)
        found = parse_ip_addr(r.stdout)
        if found:
            return found
    except Exception:
        pass
    ip = local_ip()
    if ip.startswith("127."):
        return []
    net = ipaddress.ip_network(ip + "/24", strict=False)
    return [{"if": "?", "ip": ip, "prefix": 24, "brd": str(net.broadcast_address)}]


def own_addresses() -> Set[str]:
    return {i["ip"] for i in interfaces()} | {"127.0.0.1", local_ip()}


def broadcast_targets() -> List[str]:
    """Une diffusion dirigée par interface (la diffusion générale ne part que par la route par défaut)."""
    out = []
    for i in interfaces():
        if i["brd"] and i["brd"] not in out:
            out.append(i["brd"])
    return out + ["255.255.255.255"]


def scan_candidates(limit: int = 1024) -> List[str]:
    """Adresses des réseaux locaux à sonder (jamais plus d'un /22, jamais Internet)."""
    own, seen, hosts = own_addresses(), set(), []
    for i in interfaces():
        net = ipaddress.ip_network("%s/%d" % (i["ip"], i["prefix"]), strict=False)
        if net.num_addresses > limit:
            net = ipaddress.ip_network(i["ip"] + "/24", strict=False)
        if not (net.is_private or not net.network_address.is_global):
            continue
        for h in net.hosts():
            s = str(h)
            if s not in own and s not in seen:
                seen.add(s)
                hosts.append(s)
    return hosts
