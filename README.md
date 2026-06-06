# Network Routing Automation

Python toolkit that deploys three layers of routing redundancy across a multi-router Cisco network: **OSPF** as the primary routing protocol, **floating static routes** as backup paths if OSPF fails, and **HSRP** for first-hop gateway redundancy. Designed to be idempotent, parallel, and operationally verified end-to-end.

Built as a portfolio project against a Cisco Modeling Labs (CML) topology of three IOL-XE routers, one IOLL2-XE switch, and an Alpine Linux jump host running the automation.

## Status

- Day 1 — project skeleton, dependencies pinned ✓
- Day 2 — first netmiko connection (`hello_router.py`) ✓
- Day 3 — inventory.yaml + multi-device audit (`retrieve_info.py`) ✓
- Day 4 — `configure_ospf.py` (single-device OSPF push) *(planned)*
- Day 5 — `configure_ospf_multi.py` (parallel, idempotent across all routers) *(planned)*
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
| `requirements.txt` | Pinned Python dependencies |
| `.gitignore` | venv and bytecode exclusions |
| `NOTES.md` | Engineering journal — design choices, gotchas, lessons |

(More files arrive on Days 4 through 8.)

## How to run (current state)

1. Import the CML topology and start all nodes.
2. Console into each Cisco device and paste the matching block from `cisco-lab-bootstrap-configs.txt`. On each device, generate SSH keys (`crypto key generate rsa modulus 2048`) and save (`write memory`).
3. Console into Alpine, paste `alpine-bootstrap.sh` in one block (after editing the CONFIG section with your GitHub PAT).
4. From Alpine, verify connectivity to one device:
   ```
   cd ~/network-routing-automation && python3 hello_router.py
   ```
5. Run the full read-only audit across all four devices:
   ```
   python3 retrieve_info.py
   ```
   Expected (pre-automation) output: every device shows `(OSPF not running)` and `(no HSRP groups)` — the "before" baseline.

Days 4 onward extend this baseline with OSPF, floating static routes, and HSRP automation.

## License

MIT — to be added on Day 8 alongside the v1.0 release.
