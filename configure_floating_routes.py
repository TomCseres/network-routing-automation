#!/usr/bin/env python3
"""
configure_floating_routes.py - Deploy floating static routes (AD 120).

Floating static routes are backup paths. They carry an administrative
distance (120) higher than OSPF's (110), so while OSPF is healthy the
OSPF route wins and the static stays dormant - it isn't even installed in
the routing table. The moment OSPF withdraws the matching route (a link
or protocol failure), the static becomes the best remaining path and
"floats up" into the table, preserving reachability. This is the second
redundancy layer, sitting underneath OSPF.

Same parallel + idempotent pattern as configure_ospf_multi.py:
read current state, change only what's needed, and surface device errors
instead of reporting a silent rejection as success.
"""

import yaml
import concurrent.futures
from netmiko import ConnectHandler


def build_route_commands(routes):
    """Translate floating_static_routes entries into IOS commands."""
    cmds = []
    for r in routes:
        # ip route <dest> <mask> <next_hop> <administrative_distance>
        cmds.append(
            f"ip route {r['destination']} {r['mask']} {r['next_hop']} {r['ad']}"
        )
    return cmds


def needs_configuration(conn, routes):
    """
    Idempotency check: are all expected floating static routes already in
    the running-config? Returns True if any are missing.

    We match against the running-config (not the routing table) on purpose:
    a dormant floating static is configured but NOT in 'show ip route', so
    checking the table would make us re-push every time.
    """
    running = conn.send_command("show running-config | include ip route")
    for r in routes:
        signature = (
            f"ip route {r['destination']} {r['mask']} "
            f"{r['next_hop']} {r['ad']}"
        )
        if signature not in running:
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
    Configure floating statics on one device. Returns a (name, status)
    tuple and never raises, so one failing device doesn't crash the batch.
    """
    routes = params.get("floating_static_routes")
    if not routes:
        return (name, "SKIPPED - no floating routes defined")

    conn_params = {
        "device_type": params["device_type"],
        "host":        params["host"],
        "username":    params["username"],
        "password":    params["password"],
    }

    try:
        with ConnectHandler(**conn_params) as conn:
            if not needs_configuration(conn, routes):
                return (name, "OK - no changes (idempotent)")

            cmds = build_route_commands(routes)
            output = conn.send_config_set(cmds)

            errors = find_ios_errors(output)
            if errors:
                return (name, f"REJECTED - device error: {errors[0]}")

            conn.save_config()
            return (name, f"CONFIGURED - {len(cmds)} route(s) added")

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
