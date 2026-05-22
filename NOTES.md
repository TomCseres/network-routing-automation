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
