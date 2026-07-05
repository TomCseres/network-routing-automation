#!/usr/bin/env python3
"""
verify_routing.py - End-to-end health check for all three redundancy layers.

Read-only. Connects to every device in parallel and asserts:
  1. OSPF   - the expected number of neighbors are FULL
  2. STATIC - all floating static routes are present in the config
  3. HSRP   - the device holds its expected Active/Standby role with the right VIP

Prints a PASS/FAIL table and exits 0 if everything passes, 1 if anything
fails - so the whole stack can be validated with one command and the exit
code can gate a CI pipeline or a change-window sign-off.

The expected OSPF neighbor count and HSRP roles are DERIVED from
inventory.yaml, not hard-coded: HSRP roles come from comparing priorities
within each group, so the check has no built-in assumption about which
router "should" be Active.
"""

import sys
import yaml
import concurrent.futures
from netmiko import ConnectHandler


def load_inventory(path="inventory.yaml"):
    with open(path) as f:
        return yaml.safe_load(f)


def expected_hsrp_roles(inventory):
    """
    Work out which device should be Active for each HSRP group by comparing
    priorities: the highest priority in a group is Active, the rest Standby.
    Returns {device_name: {'state': 'Active'|'Standby', 'vip': ...}}.
    """
    members = {}  # (group, vip) -> [(device, priority), ...]
    for name, params in inventory["devices"].items():
        for iface in params.get("hsrp_interfaces", []):
            h = iface["hsrp"]
            members.setdefault((h["group"], h["vip"]), []).append((name, h["priority"]))

    roles = {}
    for (group, vip), devs in members.items():
        active_dev = max(devs, key=lambda d: d[1])[0]
        for dev, _pri in devs:
            roles[dev] = {
                "state": "Active" if dev == active_dev else "Standby",
                "vip": vip,
            }
    return roles


def check_ospf(conn, params):
    """FULL neighbor count should equal the number of non-loopback OSPF
    interfaces (each inter-router link forms exactly one adjacency)."""
    if "ospf" not in params:
        return None

    expected = sum(
        1 for i in params["interfaces"]
        if "ospf_area" in i and not i["name"].lower().startswith("loop")
    )
    out = conn.send_command("show ip ospf neighbor")
    full = out.count("FULL")
    return ("OSPF", full == expected, f"{full}/{expected} neighbors FULL")


def check_static(conn, params):
    """Every floating static route must be present in the running-config."""
    routes = params.get("floating_static_routes")
    if not routes:
        return None

    running = conn.send_command("show running-config | include ip route")
    missing = 0
    for r in routes:
        sig = f"ip route {r['destination']} {r['mask']} {r['next_hop']} {r['ad']}"
        if sig not in running:
            missing += 1
    ok = missing == 0
    detail = "all present" if ok else f"{missing} missing"
    return ("STATIC", ok, f"{len(routes)} route(s): {detail}")


def check_hsrp(conn, params, expected_role):
    """Device must be in its expected Active/Standby state with the right VIP.

    Uses verbose 'show standby' and matches 'State is <role>' - NOT the brief
    output, whose 'Active'/'Standby' column headers would match either role
    and give false passes.
    """
    if not params.get("hsrp_interfaces") or expected_role is None:
        return None

    out = conn.send_command("show standby")
    state_ok = f"State is {expected_role['state']}" in out
    vip_ok = expected_role["vip"] in out
    ok = state_ok and vip_ok
    detail = f"expected {expected_role['state']}, VIP {expected_role['vip']}"
    if not ok:
        detail += " - MISMATCH"
    return ("HSRP", ok, detail)


def verify_one(name, params, expected_role):
    """Run all applicable checks on one device. Returns (name, [results])."""
    conn_params = {k: params[k] for k in ("device_type", "host", "username", "password")}
    results = []
    try:
        with ConnectHandler(**conn_params) as conn:
            for check in (
                check_ospf(conn, params),
                check_static(conn, params),
                check_hsrp(conn, params, expected_role),
            ):
                if check is not None:
                    results.append(check)
    except Exception as e:
        results.append(("CONNECT", False, str(e)))
    return name, results


def main():
    inventory = load_inventory()
    roles = expected_hsrp_roles(inventory)

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        futures = {
            pool.submit(verify_one, name, params, roles.get(name)): name
            for name, params in inventory["devices"].items()
        }
        results = {name: checks for name, checks in
                   (f.result() for f in concurrent.futures.as_completed(futures))}

    all_ok = True
    print(f"\n{'Device':<8} {'Check':<8} {'Result':<6} Detail")
    print("-" * 60)
    for name in sorted(results):
        checks = results[name]
        if not checks:
            print(f"{name:<8} {'-':<8} {'-':<6} no checks applicable")
            continue
        for check_name, ok, detail in checks:
            all_ok = all_ok and ok
            print(f"{name:<8} {check_name:<8} {'PASS' if ok else 'FAIL':<6} {detail}")
    print("-" * 60)

    if all_ok:
        print("RESULT: all checks passed\n")
        sys.exit(0)
    print("RESULT: one or more checks FAILED\n")
    sys.exit(1)


if __name__ == "__main__":
    main()
