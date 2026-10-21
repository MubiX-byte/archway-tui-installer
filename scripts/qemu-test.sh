#!/usr/bin/env bash
# Manual end-to-end QA harness: only a newly-created QCOW2 image is attached.
set -euo pipefail
if [[ $# -lt 1 || $# -gt 2 ]]; then
    echo 'Usage: bash scripts/qemu-test.sh /absolute/path/archlinux.iso [uefi|bios]' >&2
    exit 2
fi
iso=$(realpath -- "$1")
mode=${2:-uefi}
[[ -f "$iso" ]] || { echo 'ISO not found' >&2; exit 1; }
[[ "$mode" == uefi || "$mode" == bios ]] || { echo 'Expected uefi or bios' >&2; exit 1; }
command -v qemu-system-x86_64 >/dev/null
command -v qemu-img >/dev/null
scratch=$(mktemp -d "${TMPDIR:-/tmp}/archway-vm.XXXXXXXX")
echo "VM assets are retained for reboot verification: $scratch"
qemu-img create -f qcow2 "$scratch/disk.qcow2" 64G
firmware=()
if [[ "$mode" == uefi ]]; then
    code=${OVMF_CODE:-/usr/share/edk2/x64/OVMF_CODE.4m.fd}
    vars=${OVMF_VARS:-/usr/share/edk2/x64/OVMF_VARS.4m.fd}
    [[ -r "$code" && -r "$vars" ]] || { echo 'Set OVMF_CODE and OVMF_VARS to your firmware files' >&2; exit 1; }
    cp -- "$vars" "$scratch/vars.fd"
    firmware=(-drive "if=pflash,format=raw,readonly=on,file=$code" -drive "if=pflash,format=raw,file=$scratch/vars.fd")
fi
accel=tcg
[[ -r /dev/kvm && -w /dev/kvm ]] && accel=kvm
# Print a reboot command before entering QEMU. It excludes the ISO entirely.
printf 'Reboot test command: '
printf '%q ' qemu-system-x86_64 -m 4096 -smp 2 -accel "$accel" "${firmware[@]}" -drive "file=$scratch/disk.qcow2,format=qcow2,if=virtio" -nic user,model=virtio-net-pci
printf '\n'
exec qemu-system-x86_64 -m 4096 -smp 2 -accel "$accel" "${firmware[@]}" \
    -drive "file=$scratch/disk.qcow2,format=qcow2,if=virtio" \
    -cdrom "$iso" -boot d -nic user,model=virtio-net-pci
