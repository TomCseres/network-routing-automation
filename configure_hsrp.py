#!/usr/bin/env python3
"""
configure_hsrp.py - Deploy HSRP first-hop gateway redundancy.

HSRP (Hot Standby Router Protocol) gives hosts a single virtual gateway
IP that is always answered by whichever router is currently Active. On the
192.168.10.0/24 segment, R2 (priority 110) is Active and R3 (priority 100)
is Standby; both share the virtual IP 192.168.10.1. If the Active router
fails, the Standby takes over the virtual IP within seconds, so hosts keep
the same default gateway with no reconfiguration on their end.

Same parallel + idempotent pattern as the earlier scripts: read current
state, change only what's needed, and surface device errors instead of
reporting a silent rejection as success.
"""

import yaml
import concurrent.futures
from netmiko import ConnectHandler


def build_hsrp_commands(hsrp_interfaces):
    """Translate hsrp_interfaces entries into IOS commands."""
    cmds = []
    for iface in hsrp_interfaces:
        h = iface["hsrp"]
        grp = h["group"]
        cmds.append(f"interface {iface['name']}")
        if "description" in iface:
            cmds.append(f" description {iface['description']}")
        cmds.append(f" ip address {iface['ip']} {iface['mask']}")
        cmds.append(" no shutdown")
        # The virtual IP is the gateway hosts point at - owned by the group,
        # not by either physical interface.
        cmds.append(f" standby {grp} ip {h['vip']}")
        # Higher priority wins Active. R2=110, R3=100 -> R2 is Active.
        cmds.append(f" standby {grp} priority {h['priority']}")
        # preempt lets a recovered higher-priority router reclaim Active.
        if h.get("preempt"):
            cmds.append(f" standby {grp} preempt")
        cmds.append("exit")
    return cmds


def needs_configuration(conn, hsrp_interfaces):
    """
    Idempotency: is HSRP already configured on each interface with the
    right virtual IP? Match against the interface's running-config (the
    standby group won't be 'missing' from a table the way OSPF/routes are,
    but matching config is the consistent, intent-based check).
    """
    for iface in hsrp_interfaces:
        h = iface["hsrp"]
        running = conn.send_command(
            f"show running-config interface {iface['name']}"
        )
        vip_line = f"standby {h['group']} ip {h['vip']}"
        if vip_line not in running:
            return True
    return False


def find_ios_errors(output):
    """Scan device output for IOS '%' error lines (Day 5 lesson: send_config_set
    does not raise on a rejected command, so we must inspect the output)."""
    errors = []
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith("%"):
            errors.append(stripped)
    return errors


def configure_one(name, params):
    """
    Configure HSRP on one device. Returns a (name, status) tuple and never
    raises, so one failing device doesn't crash the batch.
    """
    hsrp_interfaces = params.get("hsrp_interfaces")
    if not hsrp_interfaces:
        return (name, "SKIPPED - no HSRP defined")

    conn_params = {
        "device_type": params["device_type"],
        "host":        params["host"],
        "username":    params["username"],
        "password":    params["password"],
    }

    try:
        with ConnectHandler(**conn_params) as conn:
            if not needs_configuration(conn, hsrp_interfaces):
                return (name, "OK - no changes (idempotent)")

            cmds = build_hsrp_commands(hsrp_interfaces)
            output = conn.send_config_set(cmds)

            errors = find_ios_errors(output)
            if errors:
                return (name, f"REJECTED - device error: {errors[0]}")

            conn.save_config()
            return (name, "CONFIGURED - HSRP group set")

    except Exception as e:
        return (name, f"ERROR - {e}")


def main():
    with open("inventory.yaml") as f:
        inventory = yaml.safe_load(f)

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        futures = {
            pool.submit(configure_one, name, params): name
            for name, params in inventory["devices"].items()
        }

        print(f"\n{'Device':<10} Status")
        print("-" * 60)

        for future in concurrent.futures.as_completed(futures):
            name, status = future.result()
            print(f"{name:<10} {status}")

        print("-" * 60)


if __name__ == "__main__":
    main()
