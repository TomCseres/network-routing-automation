# Network Routing Automation

Python toolkit that deploys three layers of routing redundancy across a multi-router Cisco network: **OSPF** as the primary routing protocol, **floating static routes** as backup paths if OSPF fails, and **HSRP** for first-hop gateway redundancy. Designed to be idempotent, parallel, and operationally verified end-to-end.

Built as a portfolio project against a Cisco Modeling Labs (CML) topology of three IOL-XE routers, one IOLL2-XE switch, and an Alpine Linux jump host running the automation.

## Status

- Day 1 — project skeleton, dependencies pinned ✓
- Day 2 — first netmiko connection (`hello_router.py`) ✓
- Day 3 — inventory.yaml + multi-device audit (`retrieve_info.py`) ✓
- Day 4 — `configure_ospf.py` (single-device OSPF push) ✓
- Day 5 — `configure_ospf_multi.py` (parallel, idempotent across all routers) ✓
- Day 6 — `configure_floating_routes.py` (AD 120 backup paths) *(planned)*
- Day 7 — `configure_hsrp.py` (first-hop redundancy) *(planned)*
- Day 8 — `verify_routing.py` + comprehensive documentation *(planned)*

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
  HSRP segment: 192.168.10.0/24 (planned, Day 7)
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

Days 6 onward add floating static routes (OSPF backup) and HSRP (first-hop redundancy).

## Releases

- **v0.1.0** — OSPF deployed and verified across all routers (end of Day 5)

## License

MIT — to be added on Day 8 alongside the v1.0 release.
