## Troubleshooting

Note: These notes are written for **Mini Pupper 1** in our class setup. For **Mini Pupper 2**, start from the official docs: [Mini Pupper ROS2 Guide](https://minipupperdocs.readthedocs.io/en/latest/guide/ROS2Guide.html).

---

## Recommended: Update the System (packages)

Before troubleshooting anything, it’s a good idea to update packages on the Mini Pupper.

On the **robot** (Ubuntu):

```bash
sudo apt update
sudo apt upgrade -y
sudo apt autoremove -y
```

If you’re running tools on your **laptop**:

- **macOS (Homebrew)**: `brew update && brew upgrade`
- **Windows**: use your package manager (e.g., `winget upgrade --all`) if you installed ROS/tools that way

---

## Quick Hits

- **SSH times out**: robot not on Wi‑Fi, wrong IP, or it’s on a different subnet.
- **Hostname `.local` doesn’t resolve**: mDNS not enabled on robot, or Windows lacks Bonjour; use router/IP scan.
- **ROS 2 topics don’t show up on laptop**: confirm same Wi‑Fi, `ROS_DOMAIN_ID`, and firewall rules.
- **Robot moves then “keeps going”**: always send a zero `/cmd_vel` stop message before closing teleop.
