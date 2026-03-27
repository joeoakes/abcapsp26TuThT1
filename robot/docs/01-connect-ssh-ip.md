## Connect, find IP, and SSH (Mini Pupper 1)

This guide covers: **power + SD card basics**, **finding the Mini Pupper IP**, and **SSH login**.

Note: This document is written for **Mini Pupper 1** in our class setup (e.g., SSH user `minipupper1`). If you have **Mini Pupper 2**, start from the official docs: [Mini Pupper ROS2 Guide](https://minipupperdocs.readthedocs.io/en/latest/guide/ROS2Guide.html).

---

## Hardware + Safety checklist

- **Power**:
  - Plug in the **USB‑C power cable** on the **right side** of the Mini Pupper to charge (and/or power) Mini Pupper 1.
  - The **battery** itself charges via **micro‑USB** on the **bottom**, near the **back legs**.
  - Turn the robot **on** using its power switch/button.
- **Battery / boot indicators (helpful sanity checks)**:
  - **Charge time**: roughly **30–60 minutes** for a full charge (battery LED turns **green** when fully charged).
  - **Blinking red** battery LED: battery is **drained** → charge it.
  - **When powered on**: battery LED should be **blue** and the robot’s **power light** should be lit.
  - **Boot time**: allow **30–60 seconds** for the Mini Pupper’s screen to turn on.
  - **microSD card required**: the slot takes a **microSD** (a full-size “big” SD card won’t fit). In practice, the robot often **won’t boot without the microSD inserted** (plugging in power with no card may appear “dead” even if the battery is charged). Capacity isn’t usually the limiting factor as long as it fits the image.
- **SD card: safe removal + physical access**:
  - **Safest**: shutdown fully, then remove the SD card.

    ```bash
    sudo shutdown -h now
    ```

  - **If you absolutely must remove while powered** (not recommended): at minimum flush writes first.

    ```bash
    sync
    ```

  - **Physical removal tip**: instead of unscrewing/removing the cube head (Apriltags/camera assembly), you can use a **clamp-like tool** (scissor-like but not sharp) to gently pull the SD card out from the **front opening** where it’s visible/sticking out a bit.
  - For photos/assembly context, see the official docs: [Mini Pupper cover assembly](https://minipupperdocs.readthedocs.io/en/latest/guide/Assembly/MiniPupper.html#cover-assembly)
- **Clear space**: Put the robot on the floor with room to move.
- **Emergency stop**: Be ready to **power off** quickly if wheels/legs behave unexpectedly.
- **Network**: Ensure your laptop and Mini Pupper are on the **same Wi‑Fi** (same subnet) for easiest SSH/ROS 2.

---

## Find the Mini Pupper IP Address

You can use any of these methods. Start with **mDNS/hostname** first (it’s the fastest when enabled), then try router/ARP scans.

### Option 0: Check the IP from the robot itself (Ubuntu)

If you already have a keyboard/monitor on the robot, or you’re already SSH’d in, these commands are the quickest.

- **Using a monitor/keyboard (local console)**:
  - Plug the Mini Pupper into power, then connect it to an external display + keyboard (so you can log into Ubuntu locally).
  - Once you’re at a terminal, run `ip a` (or `ifconfig`) and read the Wi‑Fi interface IPv4 address.
  - If the IP address isn’t showing up / Wi‑Fi isn’t connected yet, **rebooting** is usually safer than unplugging power:

```bash
sudo reboot
```

  - Power-cycling (unplug/replug) can work, but treat it as a **last resort** compared to a clean reboot/shutdown.

- Using `ip` (recommended; typically installed by default):

```bash
ip a
```

- Using `ifconfig` (works if `net-tools` is installed):

```bash
ifconfig
```

If `ifconfig` is missing:

```bash
sudo apt update
sudo apt install -y net-tools
```

Note: `ipconfig` is the Windows equivalent; on Ubuntu you’ll usually use `ip a` or `ifconfig`.

### Option A: mDNS hostname (works on macOS/Linux; Windows if Bonjour is installed)

Many robots advertise a `.local` name (mDNS/Avahi). Try these (adjust if your class has a different hostname):

- `minipupper1.local`
- `minipupper.local`
- `ubuntu.local` (less likely for this robot, but common on some images)

From your laptop:

```bash
ping minipupper1.local
```

If it resolves, you can SSH using the hostname (no IP needed):

```bash
ssh minipupper1@minipupper1.local
```

### Option B: Check your router / Wi‑Fi admin page (most reliable)

- Open your router’s “Connected devices / DHCP clients” list.
- Look for a device named something like **minipupper**, **ubuntu**, **raspberrypi**, or unknown device with a recent timestamp.
- Note the **IPv4 address** (e.g., `192.168.1.42`).

### Option C: ARP table (quick if you already “see” it on the network)

1) Get your laptop onto the same Wi‑Fi as the robot.
2) Populate ARP by pinging the broadcast range (optional), then list ARP entries.

**macOS / Linux**

```bash
arp -a
```

**Windows (PowerShell)**

```powershell
arp -a
```

Look for an IP you don’t recognize with a vendor that matches the robot’s compute board (often Raspberry Pi / Radxa / etc.).

### Option D: Scan the subnet (when you can’t find it otherwise)

If you know your subnet (commonly `192.168.0.x` or `192.168.1.x`), scan for live hosts.

**macOS (Homebrew)**

```bash
brew install nmap
nmap -sn 192.168.1.0/24
```

**Ubuntu / Debian**

```bash
sudo apt update
sudo apt install -y nmap
nmap -sn 192.168.1.0/24
```

**Windows**

- Install nmap: [nmap.org](https://nmap.org/download.html)
- Then in PowerShell:

```powershell
nmap -sn 192.168.1.0/24
```

Tip: once you have a candidate IP, confirm it answers SSH:

```bash
nc -vz 192.168.1.42 22
```

(On Windows you can use `Test-NetConnection 192.168.1.42 -Port 22`.)

---

## SSH into Mini Pupper 1

### Prerequisites

- Mini Pupper is powered on and connected to Wi‑Fi.
- You have either its **IP address** (e.g., `192.168.1.42`) or a working `.local` hostname.
- If prompted for a password, the current/default password is: `mangdang`

### macOS / Linux

```bash
ssh minipupper1@minipupper1.local
# or
ssh minipupper1@192.168.1.42

# example from our current network (may change):
ssh minipupper1@10.170.8.209
```

### Windows (PowerShell)

Modern Windows includes OpenSSH:

```powershell
ssh minipupper1@minipupper1.local
# or
ssh minipupper1@192.168.1.42

# example from our current network (may change):
ssh minipupper1@10.170.8.209
```

If `ssh` is not found, install “OpenSSH Client” in Windows Optional Features, or use PuTTY.

### Once you’re in

Confirm you’re on the robot:

```bash
hostname
uname -a
ip a
```

To find the robot’s IP from the robot itself:

```bash
hostname -I
```

If this is a shared/default password, change it after you log in:

```bash
passwd
```

### Keeping the IP Stable (Recommended)

The IP can change any time Wi‑Fi reconnects (DHCP). The most cross‑OS way to keep it stable is to set a **DHCP reservation** on the router:

- Find the robot in the router’s DHCP/clients list
- Copy its **MAC address**
- Create a **DHCP reservation** mapping that MAC → a fixed IP (e.g., keep it in the `10.170.8.x` range if that’s what your network uses)

This avoids per-OS static IP setup and works for macOS/Windows/Linux clients.
