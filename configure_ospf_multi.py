#!/usr/bin/env python3
"""
configure_ospf_multi.py - Multi-device, idempotent OSPF deployment.

For each device:
  1. Connect.
  2. Read current OSPF state.
  3. If already configured as intended, skip (idempotent).
  4. Otherwise push the config and save.

Devices are configured in parallel via a thread pool. Network I/O is
mostly waiting on SSH, so threads give a real speedup over a serial loop
without the complexity of async.
"""

import yaml
import concurrent.futures
from netmiko import ConnectHandler


def needs_configuration(conn, device_params):
    """
    Cheap idempotency check: is OSPF running, and are all expected
    interfaces present in 'show ip ospf interface brief'?

    Returns True if configuration is needed, False if already in place.
    """
    ospf_status = conn.send_command("show ip ospf | include Routing Process")
    if "Routing Process" not in ospf_status:
        return True

    iface_brief = conn.send_command("show ip ospf interface brief")
    expected = [i["name"] for i in device_params["interfaces"] if "ospf_area" in i]

    for iface in expected:
        # IOS abbreviates: Ethernet0/0 -> Et0/0, Loopback0 -> Lo0.
        # Check both forms so the match works regardless of how IOS prints it.
        short = iface.replace("Ethernet", "Et").replace("Loopback", "Lo")
        if iface not in iface_brief and short not in iface_brief:
            return True

    return False


def build_commands(device_params):
    """Build the full interface + OSPF command list for one device."""
    cmds = []
    pid = device_params["ospf"]["process_id"]

    for iface in device_params["interfaces"]:
        cmds.append(f"interface {iface['name']}")
        if "description" in iface:
            cmds.append(f" description {iface['description']}")
        cmds.append(f" ip address {iface['ip']} {iface['mask']}")
        cmds.append(" no shutdown")
        if "ospf_area" in iface:
            cmds.append(f" ip ospf {pid} area {iface['ospf_area']}")
        cmds.append("exit")

    cmds.extend([
        f"router ospf {pid}",
        f" router-id {device_params['ospf']['router_id']}",
        "exit",
    ])
    return cmds


def find_ios_errors(output):
    """
    Scan device output for IOS error lines.

    send_config_set() does NOT raise when a device rejects a command - the
    device just prints a '% ...' line and moves on. Without this check a
    rejected command (e.g. 'Bad mask /30 for address ...') would be reported
    as a successful push. We treat any line starting with '%' as an error,
    skipping the benign 'OSPF will not operate' notice, which is a downstream
    symptom whose real cause (the bad address) is already captured.
    """
    errors = []
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith("%"):
            if "OSPF will not operate" in stripped:
                continue
            errors.append(stripped)
    return errors


def configure_one(name, params):
    """
    Configure OSPF on one device. Returns a (name, status) tuple and
    never raises - errors are caught and returned as status strings, so
    one failing device doesn't crash the whole parallel run.
    """
    # Skip devices with no OSPF section (SW1 is an L2 switch).
    if "ospf" not in params:
        return (name, "SKIPPED - no OSPF defined")

    conn_params = {
        "device_type": params["device_type"],
        "host":        params["host"],
        "username":    params["username"],
        "password":    params["password"],
    }

    try:
        with ConnectHandler(**conn_params) as conn:
            if not needs_configuration(conn, params):
                return (name, "OK - no changes (idempotent)")

            cmds = build_commands(params)
            output = conn.send_config_set(cmds)

            # send_config_set won't raise on a rejected command - the device
            # just prints '% ...' and continues. Scan for those so a silent
            # rejection is reported as REJECTED, not a misleading CONFIGURED.
            errors = find_ios_errors(output)
            if errors:
                return (name, f"REJECTED - device error: {errors[0]}")

            conn.save_config()
            return (name, f"CONFIGURED - {len(cmds)} commands sent")

    except Exception as e:
        return (name, f"ERROR - {e}")


def main():
    with open("inventory.yaml") as f:
        inventory = yaml.safe_load(f)

    # Configure all devices in parallel. Each device runs in its own
    # thread; SSH is I/O-bound, so threads overlap the waiting and the
    # whole run finishes in about the time of the slowest single device.
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
