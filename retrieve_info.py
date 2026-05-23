#!/usr/bin/env python3
"""
retrieve_info.py - Read-only audit. Connects to every device, gathers
state, prints a structured report. Touches no configuration.

Used as the 'before' photograph of the network on Day 3, and as a
sanity check throughout the project.
"""

import yaml
from netmiko import ConnectHandler

with open("inventory.yaml") as f:
    inventory = yaml.safe_load(f)

for name, params in inventory["devices"].items():
    print(f"\n{'=' * 60}")
    print(f"  {name}  ({params['host']})")
    print(f"{'=' * 60}")

    conn_params = {
        "device_type": params["device_type"],
        "host":        params["host"],
        "username":    params["username"],
        "password":    params["password"],
    }

    try:
        with ConnectHandler(**conn_params) as conn:
            version    = conn.send_command("show version | include IOS|uptime")
            interfaces = conn.send_command("show ip interface brief")
            ospf       = conn.send_command("show ip ospf | include Routing Process|Router ID")
            static     = conn.send_command("show ip route static")
            hsrp       = conn.send_command("show standby brief")

            print(f"\n--- Version ---\n{version}")
            print(f"\n--- Interfaces ---\n{interfaces}")
            print(f"\n--- OSPF ---\n{ospf if ospf.strip() else '(OSPF not running)'}")
            print(f"\n--- Static routes ---\n{static if static.strip() else '(no static routes)'}")
            print(f"\n--- HSRP ---\n{hsrp if hsrp.strip() else '(no HSRP groups)'}")

    except Exception as e:
        print(f"  [ERROR] {e}")
