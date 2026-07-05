# Network Routing Automation

Python toolkit that deploys three layers of routing redundancy across a multi-router Cisco network: **OSPF** as the primary routing protocol, **floating static routes** as backup paths if OSPF fails, and **HSRP** for first-hop gateway redundancy. Designed to be idempotent, parallel, and operationally verified end-to-end.

Built as a portfolio project against a Cisco Modeling Labs (CML) topology of three IOL-XE routers, one IOLL2-XE switch, and an Alpine Linux jump host running the automation.

## Status

- Day 1 — project skeleton, dependencies pinned ✓
- Day 2 — first netmiko connection (`hello_router.py`) ✓
- Day 3 — inventory.yaml + multi-device audit (`retrieve_info.py`) ✓
- Day 4 — `configure_ospf.py` (single-device OSPF push) ✓
- Day 5 — `configure_ospf_multi.py` (parallel, idempotent across all routers) ✓
- Day 6 — `configure_floating_routes.py` (AD 120 backup paths) ✓
- Day 7 — `configure_hsrp.py` (first-hop redundancy) ✓
- Day 8 — `verify_routing.py` + comprehensive documentation ✓

## Architecture

```
                Internet (NAT)
                     |
              192.168.255.1
                     |
              +-------------+
              | mgmt subnet |  192.168.255.0/24
              +-------------+
                     |
        +------------+------------+
        |     |      |      |
       R1    R2     R3    SW1
      (.10) (.11)  (.12) (.13)
              |      |
              +--+---+
                 |
            SW1 (transparent L2 between R2 and R3 for HSRP)

  OSPF backbone (Area 0, AD 110):
    R1-R2 link: 10.0.12.0/30 (R1=.1, R2=.2)
    R1-R3 link: 10.0.13.0/30 (R1=.1, R3=.2)
    R2-R3 link: 10.0.23.0/30 (R2=.2, R3=.1)
  HSRP segment: 192.168.10.0/24 — R2 Active (pri 110), R3 Standby (pri 100), VIP .1
  Loopbacks:    R1 = 1.1.1.1, R2 = 2.2.2.2, R3 = 3.3.3.3
```

- **R1, R2, R3** — IOL-XE routers; run OSPF Area 0 across loopbacks and inter-router links
- **SW1** — IOLL2-XE switch; transparent Layer 2 for the HSRP segment
- **Alpine** — Linux jump host inside the lab, runs the Python automation (netmiko over SSH)

## Tech stack

| Component | Purpose |
|---|---|
| Cisco CML (Free) | Lab environment |
| Cisco IOL-XE / IOLL2-XE | Network device images |
| Alpine Linux | Jump host (in-lab automation runtime) |
| Python 3 | Automation language |
| netmiko | SSH-based Cisco automation library |
| concurrent.futures | Parallel multi-device execution |
| PyYAML | Inventory parsing |
| Jinja2 | Config templating *(future)* |
| Git + GitHub | Version control |

## Repo contents

| Item | Purpose |
|---|---|
| `cisco-lab-bootstrap-configs.txt` | Per-device bootstrap configs (paste into each device on first boot) |
| `alpine-bootstrap.sh` | Idempotent setup script for the ephemeral Alpine jump host |
| `inventory.yaml` | Source of truth — every device, interface, OSPF area, floating static, HSRP group |
| `hello_router.py` | First netmiko connectivity test (Day 2) |
| `retrieve_info.py` | Read-only multi-device audit (Day 3) |
| `configure_ospf.py` | Single-device OSPF push to R1 — proof of concept (Day 4) |
| `configure_ospf_multi.py` | Parallel, idempotent OSPF deployment across all routers (Day 5) |
| `configure_floating_routes.py` | Parallel, idempotent floating static routes — AD 120 OSPF backup (Day 6) |
| `configure_hsrp.py` | Parallel, idempotent HSRP first-hop redundancy — R2 Active / R3 Standby (Day 7) |
| `verify_routing.py` | End-to-end health check across all three layers, with a pass/fail exit code (Day 8) |
| `requirements.txt` | Pinned Python dependencies |
| `.gitignore` | venv and bytecode exclusions |
| `NOTES.md` | Engineering journal — design choices, gotchas, lessons |

(More files arrive on Days 6 through 8.)

## How to run (current state)

1. Import the CML topology and start all nodes.
2. Console into each Cisco device and paste the matching block from `cisco-lab-bootstrap-configs.txt`. On each device, generate SSH keys (`crypto key generate rsa modulus 2048`) and save (`write memory`).
3. Console into Alpine, paste `alpine-bootstrap.sh` in one block (after editing the CONFIG section with your GitHub PAT).
4. From Alpine, run the read-only audit across all four devices (the "before" baseline and a pre-flight health check):
   ```
   cd ~/network-routing-automation && python3 retrieve_info.py
   ```
5. Deploy OSPF to every router in parallel:
   ```
   python3 configure_ospf_multi.py
   ```
   First run configures the routers that need it; a second run reports `OK - no changes (idempotent)` for all of them. The script reads each device's state first and only changes what's needed.
6. Verify the backbone formed — on R1's console:
   ```
   show ip ospf neighbor      # R2 and R3 should be FULL
   show ip route ospf         # learned O routes to 2.2.2.2 and 3.3.3.3
   ```

All three layers are validated together by `verify_routing.py`, which returns exit code 0 when the whole stack is healthy and 1 when any check fails — one command to gate a change or a pipeline.

## Verified behaviors

This project is tested against real failures, not just deployed once and assumed working:

- **Idempotency** — re-running any `configure_*` script reports `OK - no changes` when a device already matches the inventory. State is read before anything is changed, so only real drift is acted on.

- **Failover (OSPF → floating static)** — while OSPF (AD 110) is healthy, the floating static (AD 120) stays dormant, configured but absent from the routing table. Disabling OSPF on R2 (which owns the 2.2.2.2 loopback) withdraws the OSPF route network-wide, and R1's floating static automatically floats up — the route to 2.2.2.2 changes from `ospf 1` / distance 110 to `static` / distance 120, with reachability preserved (100% ping through the failure). Restoring OSPF reclaims the route and the static returns to dormant. A full `O → S → O` round trip, driven entirely by administrative distance with no scripted decision-making.

- **Drift detection & self-healing** — the failover demo surfaced a real operational gotcha: `no router ospf 1` also strips the per-interface `ip ospf` tags, so re-adding the OSPF process alone does not fully restore a router (R2's process came back with zero interfaces and no adjacencies). The fix was to re-run `configure_ospf_multi.py`: the idempotency check detected that **only R2** had drifted from its desired state, reconfigured just R2 (`CONFIGURED - 20 commands sent`), and left R1 and R3 untouched (`OK - no changes`). The same "check, then change" logic that makes deployments safe also makes recovery safe — the tool is both a deployer and a targeted repair mechanism.

- **First-hop failover (HSRP)** — on the 192.168.10.0/24 segment, R2 (priority 110) is Active and R3 (priority 100) is Standby, sharing virtual gateway 192.168.10.1. Exactly one router is Active — confirming R2 and R3 exchange HSRP hellos through the transparent-L2 SW1. Shutting the Active router's interface promotes R3 from Standby to Active within the holdtime, and the virtual gateway keeps answering (100% ping to the VIP through the failure). Restoring R2 triggers preemption — because preempt is enabled and R2's priority is higher, it reclaims Active and R3 steps back to Standby. Hosts on the segment keep the same default gateway throughout, never seeing which physical router is answering.

- **End-to-end verification with a real exit code** — `verify_routing.py` checks all three layers on every device (OSPF neighbors FULL, floating statics present, HSRP role correct), prints a PASS/FAIL table, and exits 0 (healthy) or 1 (something's wrong). Expected values are derived from `inventory.yaml` — OSPF neighbor counts from the interface topology, HSRP roles from the group priorities — so nothing is hard-coded. Proven to catch real faults: shutting the R1–R2 link makes the check report `OSPF FAIL (1/2 neighbors)` on exactly the two affected routers and return exit 1, while the untouched R3 stays green. Restoring the link returns the whole board to pass / exit 0. The exit code is what makes it CI-gateable.

## Lessons learned

The problems worth remembering — most surfaced by the automation itself. Full detail in [NOTES.md](NOTES.md).

- **An invalid /30 broadcast address hid behind a "successful" push.** The inventory assigned a router's inter-router link the `.3` address of a /30 — the broadcast address, which IOS silently rejects. The interface stayed unconfigured, OSPF never came up on it, and the idempotency check kept flagging that router on every run. The idempotency check doubled as a *correctness* check: a fire-and-forget script would have reported success forever and shipped a broken topology.

- **`send_config_set` doesn't raise on a rejected command.** The device just prints a `%` line and moves on, so the bug above was invisible until a `find_ios_errors()` helper was added to scan the output and report `REJECTED` instead of a false `CONFIGURED`. A config-push tool that ignores device error output is lying to you.

- **`no router ospf 1` is more destructive than it looks.** Removing the OSPF process also strips the per-interface `ip ospf` tags, so re-adding the process alone leaves a router with zero OSPF interfaces. Re-running the idempotent deploy detected the drift and repaired only the affected device — configuration enforcement in practice.

- **In a /30, only 2 of the 4 addresses are usable.** Network and broadcast are off-limits. Obvious in hindsight; the source of a real outage in practice.

- **Dual-active HSRP is an L2 diagnostic, not an HSRP bug.** If both routers think they're Active, they aren't hearing each other's hellos — a Layer 2 problem on the switch between them. HSRP state doubles as a connectivity check.

## Releases

- **v0.1.0** — OSPF deployed and verified across all routers (end of Day 5)
- **v0.2.0** — Floating static backup layer deployed and failover-tested (end of Day 6)
- **v0.3.0** — HSRP first-hop redundancy deployed and failover-tested (end of Day 7)
- **v1.0.0** — All three redundancy layers deployed, failover-tested, and validated end-to-end by a single health check (end of Day 8)

## License

MIT — see [LICENSE](LICENSE).
