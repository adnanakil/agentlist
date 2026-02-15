import ipaddress
from agentgate_sdk import AgentHandler, run_agent


class IpLookupAgent(AgentHandler):
    def handle(self, input_data):
        ip_str = input_data["ip"].strip()

        # Check if CIDR notation is used
        if "/" in ip_str:
            return self._analyze_network(ip_str)
        else:
            return self._analyze_address(ip_str)

    def _analyze_address(self, ip_str):
        try:
            addr = ipaddress.ip_address(ip_str)
        except ValueError:
            raise ValueError(f"Invalid IP address: {ip_str}")

        result = {
            "ip": str(addr),
            "version": addr.version,
            "is_private": addr.is_private,
            "is_global": addr.is_global,
            "is_loopback": addr.is_loopback,
            "is_multicast": addr.is_multicast,
            "is_reserved": addr.is_reserved,
            "is_link_local": addr.is_link_local,
        }

        if addr.version == 4:
            result["is_unspecified"] = addr.is_unspecified
            # Determine the class for IPv4
            first_octet = int(ip_str.split(".")[0])
            if first_octet < 128:
                result["class"] = "A"
            elif first_octet < 192:
                result["class"] = "B"
            elif first_octet < 224:
                result["class"] = "C"
            elif first_octet < 240:
                result["class"] = "D (multicast)"
            else:
                result["class"] = "E (reserved)"

            # Binary representation
            result["binary"] = format(int(addr), "032b")
            result["integer"] = int(addr)

        elif addr.version == 6:
            result["is_unspecified"] = addr.is_unspecified
            result["exploded"] = addr.exploded
            result["compressed"] = addr.compressed
            result["ipv4_mapped"] = str(addr.ipv4_mapped) if addr.ipv4_mapped else None
            result["integer"] = int(addr)

        return result

    def _analyze_network(self, cidr_str):
        try:
            network = ipaddress.ip_network(cidr_str, strict=False)
        except ValueError:
            raise ValueError(f"Invalid CIDR notation: {cidr_str}")

        result = {
            "network": str(network),
            "version": network.version,
            "network_address": str(network.network_address),
            "broadcast_address": str(network.broadcast_address),
            "netmask": str(network.netmask),
            "hostmask": str(network.hostmask),
            "prefix_length": network.prefixlen,
            "num_addresses": network.num_addresses,
            "is_private": network.is_private,
            "is_global": network.is_global,
            "is_loopback": network.is_loopback,
            "is_multicast": network.is_multicast,
            "is_reserved": network.is_reserved,
            "is_link_local": network.is_link_local,
        }

        # For smaller networks, include the usable host range
        if network.version == 4 and network.prefixlen < 31:
            hosts = list(network.hosts())
            if hosts:
                result["first_host"] = str(hosts[0])
                result["last_host"] = str(hosts[-1])
                result["usable_hosts"] = len(hosts)
        elif network.version == 4:
            result["usable_hosts"] = network.num_addresses

        return result


if __name__ == "__main__":
    run_agent(IpLookupAgent())
