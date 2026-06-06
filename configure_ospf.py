#!/usr/bin/env python3
"""
configure_ospf.py - Configure interfaces and OSPF on R1 only.

Walk-before-run: prove the config-push logic on a single device before
extending it to all three routers (Day 5). This is the first script that
*changes* a device rather than just reading it.
"""

import yaml
from netmiko import ConnectHandler

with open("inventory.yaml") as f:
    inventory = yaml.safe_load(f)

device = inventory["devices"]["R1"]


def build_interface_commands(interfaces, ospf_pid):
    """Translate interface dicts from inventory.yaml into IOS commands."""
    cmds = []
    for iface in interfaces:
        cmds.append(f"interface {iface['name']}")
        if "description" in iface:
            cmds.append(f" description {iface['description']}")
        cmds.append(f" ip address {iface['ip']} {iface['mask']}")
        cmds.append(" no shutdown")
        if "ospf_area" in iface:
            # Per-interface OSPF assignment - cleaner than network statements
            # with wildcard masks, and easier to grep in running-config.
            cmds.append(f" ip ospf {ospf_pid} area {iface['ospf_area']}")
        cmds.append("exit")
    return cmds


def build_ospf_commands(ospf_settings):
    """Configure the OSPF process itself (router-id)."""
    return [
        f"router ospf {ospf_settings['process_id']}",
        f" router-id {ospf_settings['router_id']}",
        "exit",
    ]


print(f"Connecting to R1 ({device['host']})...")

conn_params = {
    "device_type": device["device_type"],
    "host":        device["host"],
    "username":    device["username"],
    "password":    device["password"],
}

with ConnectHandler(**conn_params) as conn:
    # Order matters: bring up interfaces and tag them into OSPF first,
    # then configure the OSPF process.
    cmds = (
        build_interface_commands(device["interfaces"], device["ospf"]["process_id"])
        + build_ospf_commands(device["ospf"])
    )

    print("Sending these commands:")
    for c in cmds:
        print(f"  {c}")

    # send_config_set enters config mode, sends every command, then exits.
    output = conn.send_config_set(cmds)
    print(f"\n--- Device output ---\n{output}")

    # save_config is netmiko's 'write memory' - persists to startup-config.
    print("\nSaving to startup-config...")
    conn.save_config()

    # Verify: this should now list Lo0, Et0/1, Et0/2 in OSPF.
    ospf_check = conn.send_command("show ip ospf interface brief")
    print(f"\n--- OSPF interfaces on R1 ---\n{ospf_check}")
