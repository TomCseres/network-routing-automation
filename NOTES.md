# Engineering Notes

Lessons, gotchas, and design decisions encountered during the project. Written as I go — some entries are mid-debugging notes, some are post-mortem learnings. Day 8's README "Lessons Learned" section will pick the best 3–5 from this file.

---

## Day 1 — Foundation

### Alpine in CML uses `/dev/vda`, not `/dev/sda`

CML attaches the Alpine node's virtual disk via virtio (paravirtualized), which Linux exposes as `/dev/vda` rather than the more familiar `/dev/sda`. The default `setup-alpine` script suggests `sda`, which doesn't exist on this image, and the resulting error message ("not a block device") sent me looking for hardware problems that weren't there.

Diagnostic that should have come first: `lsblk`. It showed `vda` clearly, and the 16 GiB Boot Disk Size set in CML's UI was working all along.

**Lesson:** when something looks like a missing disk, run `lsblk` before assuming the disk isn't attached. Device names aren't universal.

### Cisco Genie/pyATS is incompatible with Alpine (musl libc)

The original Day 1 plan included `pip install genie` for parsing Cisco show command output. Pip rejected it with:

```
ERROR: Could not find a version that satisfies the requirement genie.metaparser
```

Root cause: Cisco only ships pre-built wheels for **glibc-based Linux** (Ubuntu, Debian, RHEL). Alpine uses **musl libc**, which is binary-incompatible. No fallback to source builds because the underlying C dependencies also assume glibc.

Workaround: dropped Genie from the dependencies entirely. None of the scripts actually needed it — substring matching on netmiko output (`"FULL" in line`, etc.) is sufficient for the verification logic in this project.

**Lesson:** check libc compatibility before adding heavyweight vendor SDKs to minimal-distro environments. Or skip the SDK if a simpler approach suffices.

### Git strips credentials from clone URLs on Alpine

Cloned the repo as `git clone https://user:token@github.com/...` expecting git to store the credentials in the remote URL for later push. The push failed with `Invalid username or token. Password authentication is not supported`. Inspecting with `git remote -v` showed the URL had been stored *without* the credentials.

Fix: `git remote set-url origin https://user:token@github.com/...` writes the URL verbatim and keeps the auth embedded.

**Lesson:** modern git deliberately strips credentials to prevent token leaks via `git remote -v` to anyone with shell access. For an ephemeral host where credentials won't persist anyway, explicit `set-url` is the right pattern.

### GitHub URLs are case-sensitive in their paths

Created the repo on GitHub under the canonical username `TomCseres` but used lowercase `tomcseres` in the clone URL. Push succeeded — but with a redirect notice on every operation:

```
remote: This repository moved. Please use the new location:
remote:   https://github.com/TomCseres/network-routing-automation.git
```

Fixed by updating the remote URL to use the canonical casing.

**Lesson:** GitHub usernames are case-insensitive for *authentication* but case-sensitive in URL *paths*. Use canonical casing to avoid redirects on every push.

### Alpine in CML is functionally ephemeral — built a bootstrap script

Even with the disk install ostensibly working, lab restart still appeared to lose state. Rather than continue fighting CML persistence, I built `alpine-bootstrap.sh` to automate every session's setup:

- `apk add` Python, pip, openssh-client, git
- Configure git identity
- Clone the repo (or `git pull` if present)
- Create `.gitignore` if missing
- Set up Python venv
- Install pinned dependencies from `requirements.txt`
- Pre-accept SSH host keys for all four Cisco devices
- Ping-test reachability

Paste-and-go at the start of each session. Reduces ~30 minutes of manual setup to ~60 seconds.

**Lesson:** when you can't make state persist, automate the rebuild. The script *is* the state.

### CML Extract Configuration is flaky on IOL images

Tried CML's "Extract Configuration" feature on R2 and SW1 to embed their running-configs into the lab YAML. Got `The API encountered an unexpected error` on both. The extraction handler doesn't gracefully cope with certain IOL prompt states (config mode, paging, transient prompt issues).

Workaround: not strictly needed for this project. Bootstrap configs already live in a separate text file in the repo; running-configs can be captured manually by SSHing from Alpine and saving `show running-config` output. The lab YAML doesn't need configs embedded for the project to function.

**Lesson:** know which CML features are reliable. Don't waste time on optional features that have known quirks when the manual path is straightforward.

### `crypto key generate rsa modulus 2048` must run in EXEC mode

When enabling SSH on Cisco devices, RSA keys must be generated from the exec prompt (`R1#`), **not** from config mode (`R1(config)#`). Generated keys are saved to NVRAM via `write memory`, but only if `write memory` is run *after* generation. Skip the `write memory` and the keys vanish on the next reboot, leaving SSH unreachable.

**Lesson:** SSH setup on Cisco isn't just the `ip ssh version 2` line in config. Three things have to happen: VTY lines configured for SSH, RSA keys generated in exec mode, and `write memory` after generation. Miss any one and SSH breaks silently after reload.

---

## Day 2 — First Python Contact

### netmiko's `cisco_xe` vs `cisco_ios` driver

IOL-XE images run IOS-XE under the hood, even though they look superficially like IOS. The `cisco_xe` netmiko driver handles their quirks (prompt detection, paging behavior, certain escape sequences) more reliably than the older `cisco_ios` driver. Used `cisco_xe` throughout the inventory.

**Lesson:** `device_type` isn't just nominal labeling — picking the right driver matters for behavior, not just naming.

### Smart-quote SyntaxError from copy-pasting code out of a Word doc

Pasted `hello_router.py` content from a Word document into a file on Alpine. Python rejected it with:

```
SyntaxError: unterminated triple-quoted string literal (detected at line 23)
```

Root cause: Word's auto-correct had silently converted the straight `"` in the docstring delimiters into curly smart quotes (`“` and `”`). Python parsers only accept straight quotes.

Fix: re-created the file via shell heredoc paste (`cat > file.py <<'PYEOF' ... PYEOF`), which preserves bytes literally. Cleaner long-term fix: download `.py` files directly and `git pull` them on Alpine instead of any copy-paste.

**Lesson:** code goes into version control as plain text. Never copy out of rich-text formats — the conversion is silent, easy to miss, and breaks the file in ways Python's error messages don't pinpoint clearly.

### SSH stopped responding between lab sessions

Day 2's first run of `python3 hello_router.py` failed with:

```
paramiko.ssh_exception.NoValidConnectionsError:
Unable to connect to port 22 on 192.168.255.10
```

Day 1 had verified SSH was working. Cause: the lab had been stopped and restarted, and either RSA keys hadn't been persisted via `write memory`, or the device hadn't completed its boot sequence when the script ran.

Fix: opened R1's console, ran `show ip ssh` (returned "SSH is disabled"), then re-ran `crypto key generate rsa modulus 2048` followed by `write memory`. SSH came back immediately.

**Lesson:** persistence on Cisco devices is explicit. NVRAM only contains what was there at the last `write memory`. Always verify SSH is up after a reload, not just that the device pings.

### `with ConnectHandler(...) as conn:` — context manager pattern

Used Python's context manager idiom for SSH connections instead of the manual `conn = ConnectHandler(...)` / `conn.disconnect()` pattern. The `with` statement guarantees the SSH session closes cleanly even when an exception interrupts execution mid-script. Reduces stale connection risk and is cleaner to read.

**Lesson:** any resource with a paired open/close lifecycle — SSH, files, sockets, database connections — gets a context manager unless there's a specific reason it can't. Default to safety.

### Two-host workflow: edit on laptop, run on Alpine

Settled on a clean separation:

- **Laptop:** real editor, persistent git credentials, comfortable shell. All file editing and commits happen here.
- **Alpine:** ephemeral execution environment. Pulls latest from GitHub each session. Runs scripts. No editing of project files in-place.

This eliminates the smart-quote pasting problem (no copy-paste needed at all), keeps every change version-controlled automatically, and uses each machine for what it's good at.

**Lesson:** choose your editing environment intentionally. Pick the machine with the best tools, and use Git as the bridge.

### GitHub credential strategies differ for ephemeral vs persistent hosts

- **Alpine (ephemeral):** URL-embedded Personal Access Token in `alpine-bootstrap.sh`. Token lives in the script on the laptop and gets pasted into Alpine each session. Sensitive but contained.
- **Laptop (persistent):** real Git credential helper (`credential.helper store` or libsecret-backed). PAT entered once, cached securely, no need to embed in URLs.

**Lesson:** ephemeral and persistent storage need different credential patterns. URL-embedded for one-shot use; credential helpers for durable workstations. Don't use the same pattern on both — the laptop deserves better than what Alpine has to settle for.

---

## Day 3 — Inventory and Multi-Device Audit

### Why YAML for the inventory

Chose YAML over JSON or TOML for `inventory.yaml`. YAML allows inline comments (so the AD-120 rationale lives right next to the routes it explains), produces clean git diffs (one changed value = one changed line), and has minimal syntax noise compared to JSON's brackets and quotes. The whole network design — devices, interfaces, OSPF areas, floating statics, HSRP groups — is declared as data in one human-readable file.

**Lesson:** the inventory file *is* the design. Every script in Days 4–8 reads from it; change a value once and every script picks it up. Picking a format that humans can read and review pays off across the whole project.

### Floating static AD 120 — close backup, not deep backup

Configured the floating static routes with administrative distance 120, just above OSPF's 110. This keeps them dormant while OSPF is healthy (lower AD wins) but activates them the instant OSPF withdraws a route. AD 200 would be a more conservative "deep backup"; AD 120 is a deliberate "close backup" choice so failover is near-immediate. Worth noting: 120 happens to be RIP's default AD too — irrelevant here since there's no RIP, but the kind of overlap an interviewer might probe.

**Lesson:** administrative distance is a design lever, not a fixed value. The number you pick encodes how aggressively the backup takes over.

### The empty-output idiom in retrieve_info.py

Used `(output if output.strip() else '(default message)')` so that a device returning nothing prints `(OSPF not running)` rather than a confusing blank section. Small touch, big difference in readability — especially when comparing the Day 3 "before" snapshot to the Day 8 "after."

**Lesson:** scripts that print state should make "nothing here" explicit, not silent. A blank section looks like a bug; "(no HSRP groups)" looks like an answer.

### `rm -rf *` then `git pull` does not restore deleted files

Wiped the working directory with `rm -rf *` (the glob doesn't match `.git/`, so history survived) expecting `git pull` to re-download everything. It didn't — pull only applied the diff of the latest commit (two new files), leaving the rest deleted. `git status` showed them all as `deleted`.

Fix: `git restore .` reconciles the working directory back to HEAD, bringing every tracked file back.

**Lesson:** the working directory and git history are two separate things. `git pull` adds *changes*; it doesn't re-checkout missing files. `git restore .` is the tool to make the working directory match HEAD again.

### venv activation does not survive a subshell

Ran `retrieve_info.py` and hit `ModuleNotFoundError: No module named 'yaml'` even though the bootstrap script had installed PyYAML. Cause: the bootstrap script had been *executed* (`./alpine-bootstrap.sh`), so its `. .venv/bin/activate` ran in a subshell that died when the script ended. The interactive shell never had the venv active. `which python3` confirmed it was pointing at `/usr/bin/python3`, not the venv.

Fix: activate the venv in the current shell (`. .venv/bin/activate`), or source the bootstrap script (`. ./alpine-bootstrap.sh`) instead of executing it.

**Lesson:** when a script needs to change the parent shell's environment (cd, export, activating a venv), it must be *sourced* (`. ./script.sh`), not *executed* (`./script.sh`). Execution runs in a subshell that can't reach back into the parent.

### The read-only audit doubles as a pre-flight health check

The first full run of `retrieve_info.py` returned `[ERROR] TCP connection to device failed` for R2 while the other three devices responded cleanly. R2 pinged fine (ICMP) but its SSH was dead (TCP 22) — the same unsaved-crypto-keys issue from Day 2, this time on R2. Regenerating the keys and `write memory` fixed it; the re-run returned clean output for all four.

**Lesson:** a read-only audit script isn't just for snapshots — it's a pre-flight health check. It surfaced a broken device *before* any configuration automation ran against it. Catching that with a safe read-only tool is far better than discovering it mid-config-push.

---

## Day 4 — First OSPF Push (Single Router)

### send_config_set (config mode) vs send_command (exec mode)

`configure_ospf.py` was the first script to *change* a device rather than just read it. It uses netmiko's `send_config_set(cmds)`, which enters config mode, sends every command in order, and exits config mode automatically. This is a different method from `send_command()` (used in Days 2–3), which runs a single command in exec mode. Mixing them up fails: `send_command("interface Ethernet0/1")` does nothing useful from exec mode, and `send_config_set(["show version"])` errors inside config mode.

**Lesson:** netmiko has two distinct entry points for two distinct IOS modes. Match the method to the mode — config changes go through `send_config_set`, show commands through `send_command`.

### save_config() is netmiko's "write memory"

After the push, the script calls `conn.save_config()` — netmiko's equivalent of `write memory`. Without it, the config lands in the running-config (active now) but never reaches the startup-config (gone on reload). Given how many times unsaved state has already bitten this project (SSH keys on Days 2 and 3), saving after every config push is non-negotiable.

**Lesson:** a config push isn't finished until it's saved. running-config != startup-config. The automation must save explicitly, every time.

### OSPF WAIT -> DR transition with no neighbors

Immediately after the push, `show ip ospf interface brief` showed Et0/1 and Et0/2 in State WAIT. A few minutes later (from R1's console) the same interfaces showed State DR, still with Nbrs 0/0. With no OSPF neighbors yet (R2/R3 don't run OSPF until Day 5), R1's wait timer expired and it elected itself Designated Router on each multi-access segment. Loopback0 stayed LOOP (loopbacks don't form adjacencies).

**Lesson:** OSPF interface states progress on their own timers even with zero neighbors. WAIT is the initial wait for the dead interval; DR is self-election when no higher-priority neighbor shows up. Reading these states tells you exactly where in the OSPF state machine an interface is.

### The management interface is deliberately excluded from the push

R1's Ethernet0/0 (mgmt, 192.168.255.10) is intentionally absent from inventory.yaml's `interfaces` block, so `configure_ospf.py` never touches it. This matters because the script connects *over* that interface. Re-IPing or shutting it mid-push would sever the SSH session and strand the device. Only the OSPF-participating interfaces — Loopback0, Ethernet0/1, Ethernet0/2 — get configured.

**Lesson:** never let automation reconfigure the path it's riding on. Exclude the management interface from any bulk interface push, or you'll cut your own connection and lock yourself out.

### The audit script doubles as before/after evidence

Re-ran the unchanged Day 3 `retrieve_info.py` after the OSPF push. R1's OSPF section flipped from `(OSPF not running)` to `Routing Process "ospf 1" with ID 1.1.1.1`. Same script, same command, different output — because the network changed in between.

**Lesson:** a good read-only audit tool is also the before/after proof. No separate verification tooling needed — the same script tells the whole story across the project timeline.

---

## Day 5 — Multi-Device OSPF + Idempotency

### Idempotency: read state first, change only if needed

`configure_ospf_multi.py` checks each device's current OSPF state before touching it. `needs_configuration()` returns False if OSPF is already running and every expected interface is already in OSPF, so a second run is a no-op. This is the behavior that separates a script from a tool: it's safe to run repeatedly, the way Ansible or Terraform reconcile to a desired state rather than blindly re-applying.

**Lesson:** idempotency isn't a nice-to-have — it's what makes automation safe to run in production. "Check, then change" beats "always change."

### The Et0/0 vs Ethernet0/0 abbreviation trap

The idempotency check compares expected interface names against `show ip ospf interface brief`, but IOS prints names abbreviated (Ethernet0/0 -> Et0/0, Loopback0 -> Lo0). The check has to compare both forms; matching only the full name would make it think every interface was missing and re-push on every run — silently defeating the idempotency it was meant to provide.

**Lesson:** when matching against device output, account for how the device actually formats it. Vendor abbreviations are a classic source of "why does my check always fail?" bugs.

### The invalid /30 broadcast address that hid behind a "successful" push

R3 reconfigured on every run even though the script reported "20 commands sent" each time. Root cause: inventory had R3's inter-router link IPs as `.3` — the broadcast address of each /30 — which IOS rejects with `Bad mask /30 for address 10.0.13.3`. The interface stayed `unassigned`, OSPF never came up on it (`% OSPF will not operate on this interface until IP is configured on it`), and the idempotency check correctly kept flagging R3 as needing configuration. Fixed to the two usable host addresses: 10.0.13.2 (To R1) and 10.0.23.1 (To R2).

A /30 has 4 addresses, only 2 usable: network (.0), host, host, broadcast (.3). Assigning .0 or .3 to an interface is always invalid.

**Lesson 1:** in a /30, only 2 of the 4 addresses are assignable. Network and broadcast are off-limits.
**Lesson 2:** the idempotency check doubled as a *correctness* check. A fire-and-forget script would have reported success forever and shipped a topology where R3 silently wasn't in OSPF. Because the script re-evaluated real device state each run, it refused to go quiet about a device whose config "succeeded" but didn't take.

### send_config_set does not raise on rejected commands

The bug above stayed hidden because `send_config_set()` does not raise when a device rejects a command — IOS just prints a `% ...` line and continues. The script captured that output but only reported the command count, so "Bad mask /30" was invisible. Added a `find_ios_errors()` helper that scans the device output for lines starting with `%` and reports `REJECTED - device error: ...` instead of a misleading `CONFIGURED`. Now a silent rejection surfaces immediately in the status table.

**Lesson:** a config-push tool that ignores device error output is lying to you. Always inspect what the device said back — netmiko hands you the output for a reason. Treating `%` lines as failures turns silent rejections into loud ones.

### Errors as data: the (name, status) tuple in a parallel run

`configure_one()` never raises — every outcome (skipped, no-change, configured, rejected, connection error) comes back as a `(name, status)` tuple. In a thread-pool run this is essential: one unreachable router returns an ERROR row instead of crashing the whole batch and leaving you unsure which devices actually got configured.

**Lesson:** in concurrent code, let each worker return its outcome as data rather than throwing. One failure shouldn't take down the whole run or hide which units succeeded.

### ThreadPoolExecutor for I/O-bound SSH work

Devices are configured in parallel via `concurrent.futures.ThreadPoolExecutor`. SSH is I/O-bound — mostly waiting on the network — so threads overlap the waiting and the whole run finishes in about the time of the slowest single device, not the sum. Results print out of inventory order (whichever device finishes first prints first), which is itself visible proof the work ran in parallel. Threads (not asyncio) are the right tool here: netmiko is synchronous, and the GIL doesn't hurt when the threads spend their time blocked on network I/O.

**Lesson:** match the concurrency model to the workload. I/O-bound + a synchronous library = threads. CPU-bound would want processes; neither needs the complexity of async here.

### The WAIT/DR -> FULL transition, completed

On Day 4, R1's OSPF interfaces sat in WAIT then self-elected DR with `Nbrs 0/0` — no one to talk to. After Day 5 brought R2 and R3 into OSPF (and after the /30 fix let R3's interfaces come up), `show ip ospf neighbor` showed both as FULL, and `show ip route ospf` showed R1 learning 2.2.2.2 and 3.3.3.3 dynamically, plus an equal-cost (ECMP) pair of paths to the R2-R3 link. The state machine I watched stall on Day 4 completed on its own once the topology was correct.

**Lesson:** OSPF interface states tell a story across time. Reading them (WAIT -> DR -> FULL) turns "is it working?" into a precise diagnosis of exactly how far the protocol got.
