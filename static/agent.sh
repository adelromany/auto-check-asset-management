#!/usr/bin/env bash
# ==============================================================================
# Snipe-IT Onboarding Agent — macOS & Linux
# Collects hardware info and POSTs it to the onboarding server.
#
# Usage (populated and shown by the web page):
#   curl -sL http://SERVER/static/agent.sh | ONBOARD_URL=http://SERVER ONBOARD_CODE=A7-X3-Q9 bash
# ==============================================================================

set -euo pipefail

SERVER_URL="${ONBOARD_URL:-}"
CODE="${ONBOARD_CODE:-}"

if [[ -z "$SERVER_URL" || -z "$CODE" ]]; then
    echo "ERROR: ONBOARD_URL and ONBOARD_CODE must be set."
    echo "Run the command shown on the onboarding web page."
    exit 1
fi

echo ""
echo "  Snipe-IT Onboarding Agent ($(uname -s))"
echo "  Session code: $CODE"
echo ""
echo "  Collecting hardware information..."

# ── helpers ──────────────────────────────────────────────────────────────────

safe() { "$@" 2>/dev/null || true; }

json_str()  { local v="${1//\\/\\\\}"; v="${v//\"/\\\"}"; v="${v//$'\n'/ }"; printf '"%s"' "$v"; }
json_num()  { printf '%s' "${1:-null}"; }
json_null() { printf 'null'; }

OS_TYPE="$(uname -s)"   # Darwin | Linux

# ── OS & hostname ─────────────────────────────────────────────────────────────

HOSTNAME_VAL="$(hostname -f 2>/dev/null || hostname)"
OS_ARCH="$(uname -m)"
COLLECTED_AT="$(date -u '+%Y-%m-%dT%H:%M:%S' 2>/dev/null || date '+%Y-%m-%dT%H:%M:%S')"

if [[ "$OS_TYPE" == "Darwin" ]]; then
    OS_NAME="macOS"
    OS_VERSION="$(sw_vers -productVersion 2>/dev/null || echo "")"
    AGENT_OS="macos"
    CURRENT_USER="$(stat -f%Su /dev/console 2>/dev/null || true)"
    if [[ -z "$CURRENT_USER" || "$CURRENT_USER" == "root" || "$CURRENT_USER" == "loginwindow" ]]; then
        CURRENT_USER="$(id -un)"
    fi
else
    OS_NAME="$(safe grep -oP '(?<=^PRETTY_NAME=").+(?=")' /etc/os-release || uname -s)"
    OS_VERSION="$(safe grep -oP '(?<=^VERSION_ID=").+(?=")' /etc/os-release || uname -r)"
    AGENT_OS="linux"
    CURRENT_USER="${SUDO_USER:-$(id -un)}"
fi

# ── Serial number ─────────────────────────────────────────────────────────────

if [[ "$OS_TYPE" == "Darwin" ]]; then
    SERIAL="$(safe system_profiler SPHardwareDataType | awk '/Serial Number/{print $NF}')"
else
    SERIAL="$(safe cat /sys/class/dmi/id/product_serial)"
    if [[ -z "$SERIAL" ]] && command -v dmidecode &>/dev/null; then
        SERIAL="$(safe dmidecode -s system-serial-number)"
    fi
fi

# ── Manufacturer & Model ──────────────────────────────────────────────────────

if [[ "$OS_TYPE" == "Darwin" ]]; then
    MODEL="$(safe system_profiler SPHardwareDataType | awk -F': ' '/Model Name/{print $2}')"
    MANUFACTURER="Apple"
else
    MANUFACTURER="$(safe cat /sys/class/dmi/id/sys_vendor)"
    MODEL="$(safe cat /sys/class/dmi/id/product_name)"
fi

# ── CPU ───────────────────────────────────────────────────────────────────────

if [[ "$OS_TYPE" == "Darwin" ]]; then
    CPU_NAME="$(safe sysctl -n machdep.cpu.brand_string)"
    CPU_CORES="$(safe sysctl -n hw.physicalcpu)"
else
    CPU_NAME="$(safe grep -m1 'model name' /proc/cpuinfo | cut -d: -f2 | xargs)"
    CPU_CORES="$(safe grep -c '^processor' /proc/cpuinfo)"
fi

# ── RAM ───────────────────────────────────────────────────────────────────────

if [[ "$OS_TYPE" == "Darwin" ]]; then
    RAM_BYTES="$(safe sysctl -n hw.memsize)"
    RAM_GB="$(awk "BEGIN{printf \"%.1f\", ${RAM_BYTES:-0}/1073741824}")"
else
    RAM_KB="$(safe awk '/MemTotal/{print $2}' /proc/meminfo)"
    RAM_GB="$(awk "BEGIN{printf \"%.1f\", ${RAM_KB:-0}/1048576}")"
fi

# ── Disks ─────────────────────────────────────────────────────────────────────

DISKS_JSON="[]"

if [[ "$OS_TYPE" == "Darwin" ]]; then
    # diskutil list -plist + parsing is complex; use system_profiler
    DISK_RAW="$(safe system_profiler SPStorageDataType 2>/dev/null)"
    # Build a minimal single-disk entry from df
    DISK_SIZE_KB="$(df -k / 2>/dev/null | awk 'NR==2{print $2}')"
    DISK_SIZE_GB="$(awk "BEGIN{printf \"%.0f\", ${DISK_SIZE_KB:-0}/1048576}")"
    DISKS_JSON='[{"name":"Internal","size_gb":'"$DISK_SIZE_GB"',"type":"SSD"}]'
else
    # lsblk is available on all modern Linux
    if command -v lsblk &>/dev/null; then
        DISKS_JSON="["
        FIRST=1
        while IFS= read -r line; do
            NAME="$(echo "$line" | awk '{print $1}')"
            SIZE="$(echo "$line" | awk '{print $2}')"
            ROTA="$(echo "$line" | awk '{print $3}')"  # 0=SSD, 1=HDD
            TYPE_VAL="$([ "$ROTA" = "0" ] && echo SSD || echo HDD)"
            [[ $FIRST -eq 0 ]] && DISKS_JSON+=","
            DISKS_JSON+='{"name":'"$(json_str "$NAME")"',"size_gb":'"$(json_str "$SIZE")"',"type":"'"$TYPE_VAL"'"}'
            FIRST=0
        done < <(lsblk -dno NAME,SIZE,ROTA 2>/dev/null | grep -v '^loop')
        DISKS_JSON+="]"
    fi
fi

# ── Network: Wi-Fi/Ethernet IPv4 addresses only ────────────────────────────────

IPS_JSON="[]"

if [[ "$OS_TYPE" == "Darwin" ]]; then
    TARGET_IFACES="$(networksetup -listallhardwareports 2>/dev/null | awk -F': ' '
        /^Hardware Port: / { allowed = ($2 ~ /^(Wi-Fi|AirPort|Ethernet|.* Ethernet|.* LAN)( |$)/) }
        /^Device: / && allowed { print $2 }
    ')"
elif command -v ip &>/dev/null; then
    TARGET_IFACES="$(ip link show 2>/dev/null | awk -F': ' '/^[0-9]+:/{print $2}' | cut -d@ -f1 | while IFS= read -r iface; do
        if [[ -d "/sys/class/net/$iface/wireless" ]] ||
           { [[ -e "/sys/class/net/$iface/device" ]] && [[ "$(cat "/sys/class/net/$iface/type" 2>/dev/null)" == "1" ]]; }; then
            printf '%s\n' "$iface"
        fi
    done)"
else
    TARGET_IFACES=""
fi

if command -v ip &>/dev/null; then
    IPS_JSON="["
    FIRST_IP=1
    while IFS= read -r iface; do
        [[ -n "$iface" ]] || continue
        while IFS= read -r IP; do
            [[ -n "$IP" ]] || continue
            [[ $FIRST_IP -eq 0 ]] && IPS_JSON+=","
            IPS_JSON+='{"iface":'"$(json_str "$iface")"',"ip":'"$(json_str "$IP")"'}'
            FIRST_IP=0
        done < <(ip -4 -o addr show dev "$iface" scope global 2>/dev/null | awk '{split($4, address, "/"); print address[1]}')
    done <<< "$TARGET_IFACES"
    IPS_JSON+="]"
elif command -v ifconfig &>/dev/null; then
    IPS_JSON="["
    FIRST_IP=1
    while IFS= read -r iface; do
        [[ -n "$iface" ]] || continue
        while IFS= read -r IP; do
            [[ $FIRST_IP -eq 0 ]] && IPS_JSON+=","
            IPS_JSON+='{"iface":'"$(json_str "$iface")"',"ip":'"$(json_str "$IP")"'}'
            FIRST_IP=0
        done < <(ifconfig "$iface" 2>/dev/null | awk '/inet /{print $2}')
    done <<< "$TARGET_IFACES"
    IPS_JSON+="]"
fi

# ── Assemble JSON ─────────────────────────────────────────────────────────────

PAYLOAD="$(cat <<JSON
{
  "hostname":      $(json_str  "$HOSTNAME_VAL"),
  "username":      $(json_str  "$CURRENT_USER"),
  "serial":        $(json_str  "${SERIAL:-}"),
  "manufacturer":  $(json_str  "${MANUFACTURER:-}"),
  "model":         $(json_str  "${MODEL:-}"),
  "cpu":           $(json_str  "${CPU_NAME:-}"),
  "cpu_cores":     $(json_num  "${CPU_CORES:-null}"),
  "ram_gb":        $(json_num  "${RAM_GB:-null}"),
  "disks":         $DISKS_JSON,
  "os_name":       $(json_str  "$OS_NAME"),
  "os_version":    $(json_str  "${OS_VERSION:-}"),
  "os_arch":       $(json_str  "$OS_ARCH"),
  "ip_addresses":  $IPS_JSON,
  "agent_os":      $(json_str  "$AGENT_OS"),
  "collected_at":  $(json_str  "$COLLECTED_AT")
}
JSON
)"

# ── POST ──────────────────────────────────────────────────────────────────────

ENDPOINT="$SERVER_URL/api/session/$CODE/submit"
echo "  Sending to $ENDPOINT ..."

HTTP_STATUS="$(curl -s -o /tmp/agent_resp.json -w "%{http_code}" \
    -X POST "$ENDPOINT" \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD")"

if [[ "$HTTP_STATUS" == "200" ]]; then
    echo ""
    echo "  Done! Switch back to the web browser."
    echo ""
else
    echo ""
    echo "  ERROR: Server returned HTTP $HTTP_STATUS"
    echo "  $(cat /tmp/agent_resp.json 2>/dev/null)"
    echo ""
    exit 1
fi
