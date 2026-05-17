#!/usr/bin/env python3
"""
hello_router.py - First contact with R1.

Connects via SSH using netmiko, runs 'show version', prints output.
The simplest possible script: prove the connection works end-to-end
before we try anything fancy.
"""

from netmiko import ConnectHandler

# Hard-coded only because this is a one-off connectivity test.
# Every other script reads from inventory.yaml.
device = {
    "device_type": "cisco_xe",
    "host":        "192.168.255.10",   # R1 mgmt IP
    "username":    "admin",
    "password":    "cisco123",
}

# Context manager guarantees SSH closes even on exception.
with ConnectHandler(**device) as conn:
    output = conn.send_command("show version")
    print(output)
