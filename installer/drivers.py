"""Conservative GPU selection, verified again against current repository metadata."""
from .command import InstallError


def recommend(hw: dict, kernel: str, choice="auto") -> tuple[list[str], str]:
    names = " ".join(hw["gpus"]).lower()
    packages = ["mesa"]
    reasons = []
    if "intel" in names:
        packages.append("vulkan-intel")
        reasons.append("Intel Mesa/Vulkan; very old GPUs may lack Vulkan support")
    if "amd" in names or "radeon" in names or "1002:" in names:
        packages.append("vulkan-radeon")
        reasons.append("AMD Mesa/RADV; legacy pre-GCN cards have no Vulkan")
    nvidia = "nvidia" in names or "10de:" in names
    if choice == "nvidia-open":
        # Do not infer architecture from marketing names or ranges of PCI IDs.
        # Require an explicit architecture codename reported by lspci.
        import re
        supported = re.search(r"\b(?:TU|GA|AD|GB)\d{3}\b", " ".join(hw["gpus"]), re.I)
        if not nvidia or not supported:
            raise InstallError("nvidia-open requires an identified Turing/Ampere/Ada/Blackwell codename. Use Nouveau for unknown/older GPUs.")
        packages += ["nvidia-open-dkms", "nvidia-utils", f"{kernel}-headers"]
        reasons.append("Identified supported NVIDIA architecture; DKMS for selected kernel. Package/build verification required.")
    elif nvidia and choice != "mesa":
        packages += ["xf86-video-nouveau"]
        reasons.append("Conservative Nouveau default for NVIDIA, including unknown/legacy generations. Performance and Wayland support vary. No AUR legacy drivers installed.")
    else:
        reasons.append("Mesa with kernel modesetting")
    if nvidia and len(hw["gpus"]) > 1:
        reasons.append("Hybrid GPU detected; no forced primary GPU or Xorg configuration")
    return sorted(set(packages)), "; ".join(reasons)
