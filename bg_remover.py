from __future__ import annotations

import cv2
import numpy as np
from PIL import Image
from scipy.ndimage import label

REMBG_MODELS = [
    "isnet-anime",
    "isnet-general-use",
    "birefnet-general",
    "birefnet-general-lite",
    "birefnet-portrait",
    "birefnet-dis",
    "birefnet-hrsod",
    "birefnet-cod",
    "birefnet-massive",
    "bria-rmbg",
    "u2net",
    "u2netp",
    "u2net_human_seg",
    "silueta",
    "sam",
]


def _to_rgba(img: Image.Image) -> np.ndarray:
    return np.array(img.convert("RGBA"), dtype=np.uint8)


def remove_bg_floodfill(pil_image: Image.Image, tolerance: int = 30) -> Image.Image:
    """Remove background by flood-filling from all four corners.

    Works because the background white is reachable from image edges while
    sticker border white is enclosed by character art and unreachable.
    """
    arr = _to_rgba(pil_image)
    h, w = arr.shape[:2]

    thresh = 255 - tolerance
    candidate = (
        (arr[:, :, 0] >= thresh) &
        (arr[:, :, 1] >= thresh) &
        (arr[:, :, 2] >= thresh)
    )

    labeled, _ = label(candidate)
    bg_labels: set[int] = set()

    edge_coords = (
        list(zip([0] * w, range(w))) +
        list(zip([h - 1] * w, range(w))) +
        list(zip(range(h), [0] * h)) +
        list(zip(range(h), [w - 1] * h))
    )
    for ey, ex in edge_coords:
        lbl = int(labeled[ey, ex])
        if lbl != 0:
            bg_labels.add(lbl)

    if not bg_labels:
        return Image.fromarray(arr, "RGBA")

    bg_mask = np.zeros((h, w), dtype=bool)
    for lbl in bg_labels:
        bg_mask |= labeled == lbl

    result = arr.copy()
    result[bg_mask, 3] = 0
    return Image.fromarray(result, "RGBA")


def _normalize_alpha(rgba_image: Image.Image) -> Image.Image:
    """Scale alpha channel so its maximum value = 255.

    AI models output soft/low-confidence masks (e.g. max alpha = 80) on complex
    sprite sheets. Without normalization, the binarization threshold in
    refine_alpha_mask (alpha > 0.5 = 127.5) wipes out all sprite pixels.
    """
    arr = np.array(rgba_image.convert("RGBA"), dtype=np.uint8).copy()
    alpha = arr[:, :, 3].astype(np.float32)
    max_a = alpha.max()
    if 0 < max_a < 255:
        alpha = (alpha / max_a * 255.0).clip(0, 255)
        arr[:, :, 3] = alpha.astype(np.uint8)
    return Image.fromarray(arr, "RGBA")


def remove_bg_ai(pil_image: Image.Image, model_name: str = "isnet-anime") -> Image.Image:
    """Remove background using a rembg neural-network model.

    Model is downloaded on first use (~50–200 MB depending on model).
    Recommended for anime/cartoon sprites: isnet-anime
    """
    try:
        from rembg import new_session, remove as rembg_remove
    except (ImportError, SystemExit) as e:
        raise RuntimeError(
            "rembg failed to load — onnxruntime is probably missing.\n"
            "Run:  pip install \"rembg[cpu]\"  (or rembg[gpu] for CUDA)"
        ) from e

    # Normalise to RGB first — rembg can silently produce empty masks for
    # palette-mode (P), greyscale (L) or other non-standard input modes.
    img = pil_image.convert("RGB")
    # Force CPU execution provider so onnxruntime-gpu doesn't try to load
    # cudnn64_9.dll (which errors if cuDNN 9 isn't installed).
    # ToonOut handles GPU via PyTorch separately.
    session = new_session(model_name, providers=["CPUExecutionProvider"])
    result = rembg_remove(img, session=session)
    return _normalize_alpha(result.convert("RGBA"))


# --------------------------------------------------------------------------- #
# ToonOut (BiRefNet fine-tuned for anime)                                       #
# --------------------------------------------------------------------------- #

# Module-level cache so the 885 MB model loads only once per session
_toonout_model = None
_toonout_device: str | None = None
_birefnet_patched = False


def _apply_birefnet_compat_patch() -> None:
    """One-time compatibility patch for BiRefNet with newer transformers."""
    global _birefnet_patched
    if _birefnet_patched:
        return
    try:
        import transformers.configuration_utils
        _orig = transformers.configuration_utils.PretrainedConfig.__getattribute__

        def _patched(self, key):
            if key == "is_encoder_decoder":
                return False
            return _orig(self, key)

        transformers.configuration_utils.PretrainedConfig.__getattribute__ = _patched
        _birefnet_patched = True
    except Exception:
        pass


def _load_toonout() -> tuple:
    """Download (once) and load the ToonOut model into memory."""
    global _toonout_model, _toonout_device
    if _toonout_model is not None:
        return _toonout_model, _toonout_device

    import torch
    from huggingface_hub import hf_hub_download
    from transformers import AutoModelForImageSegmentation

    _apply_birefnet_compat_patch()

    # Download fine-tuned weights (~885 MB, cached by huggingface_hub after first run)
    weights_path = hf_hub_download(
        repo_id="joelseytre/toonout",
        filename="birefnet_finetuned_toonout.pth",
    )

    # Load base BiRefNet architecture
    model = AutoModelForImageSegmentation.from_pretrained(
        "ZhengPeng7/BiRefNet",
        trust_remote_code=True,
    )

    # Apply ToonOut fine-tuned weights, stripping DDP/compiled-model prefixes
    raw = torch.load(weights_path, map_location="cpu")
    clean: dict = {}
    for k, v in raw.items():
        if k.startswith("module._orig_mod."):
            clean[k[len("module._orig_mod."):]] = v
        elif k.startswith("module."):
            clean[k[len("module."):]] = v
        else:
            clean[k] = v
    model.load_state_dict(clean)

    _toonout_device = "cuda" if torch.cuda.is_available() else "cpu"
    model.to(_toonout_device)
    model.float()   # weights are saved as float16; cast to float32 to match input tensor
    model.eval()
    _toonout_model = model
    return _toonout_model, _toonout_device


def remove_bg_toonout(pil_image: Image.Image) -> Image.Image:
    """Remove background using ToonOut — BiRefNet fine-tuned for anime characters.

    Downloads ~885 MB weights from HuggingFace on first use (cached afterwards).
    Requires: torch, torchvision, transformers  (already in requirements.txt)
    """
    try:
        import torch
        from torchvision import transforms
    except ImportError as e:
        raise ImportError(
            "ToonOut requires PyTorch. Run: pip install torch torchvision"
        ) from e

    model, device = _load_toonout()

    transform = transforms.Compose([
        transforms.Resize((1024, 1024)),
        transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
    ])

    image = pil_image.convert("RGB")
    input_tensor = transform(image).unsqueeze(0).to(device)

    with torch.no_grad():
        preds = model(input_tensor)[-1].sigmoid().cpu()

    mask = transforms.ToPILImage()(preds[0].squeeze())
    mask = mask.resize(image.size, Image.LANCZOS)

    result = image.copy()
    result.putalpha(mask)
    return _normalize_alpha(result.convert("RGBA"))


# --------------------------------------------------------------------------- #

def defringe(
    rgba_image: Image.Image,
    bg_color: tuple[int, int, int] = (255, 255, 255),
    strength: float = 1.0,
    spread: int = 0,
) -> Image.Image:
    """Remove background color contamination from semi-transparent edge pixels.

    When a white background is cut out, edge pixels are a blend of the sprite
    color and white. This reverses that blend to recover the true foreground color:
        composite = alpha * fg + (1 - alpha) * bg
        fg = (composite - (1 - alpha) * bg) / alpha

    strength — amplifies the correction (>1.0 = more aggressive, useful for heavy fringe)
    spread   — extends correction into the ring of fully-opaque pixels at the alpha border,
               catching BG contamination that flood-fill left at alpha=1 edges
    """
    arr = np.array(rgba_image.convert("RGBA"), dtype=np.float32)
    alpha = arr[:, :, 3] / 255.0
    bg = np.array(bg_color, dtype=np.float32)

    mask = alpha > 0.01
    rgb = arr[:, :, :3].copy()
    a3 = alpha[:, :, np.newaxis]

    # Reconstruct true foreground color where alpha > 0, then scale the correction
    fg_pure = np.where(
        np.broadcast_to(mask[:, :, np.newaxis], rgb.shape),
        (rgb - (1.0 - a3) * bg) / np.where(a3 > 0, a3, 1.0),
        rgb,
    )
    fg = rgb + (fg_pure - rgb) * strength
    fg = np.clip(fg, 0.0, 255.0)

    result = arr.copy()
    result[:, :, :3] = fg

    # Spread: extend defringe into opaque pixels adjacent to the alpha border
    if spread > 0:
        binary = (alpha > 0.5).astype(np.uint8)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (spread * 2 + 1, spread * 2 + 1))
        dilated = cv2.dilate(binary, kernel)
        # ring = opaque pixels just outside the current alpha edge
        ring_mask = (dilated - binary).astype(bool)
        # distance of each ring pixel from the nearest transparent pixel
        dist = cv2.distanceTransform(binary, cv2.DIST_L2, 3)
        # virtual alpha fades from 1 at the edge inward; use it to estimate BG contribution
        virtual_a = np.clip(1.0 - dist / max(spread, 1) * 0.45, 0.55, 1.0)
        va3 = virtual_a[:, :, np.newaxis]
        spread_fg = (rgb - (1.0 - va3) * bg) / va3
        spread_fg = rgb + (spread_fg - rgb) * strength
        spread_fg = np.clip(spread_fg, 0.0, 255.0)
        result[:, :, :3] = np.where(
            np.broadcast_to(ring_mask[:, :, np.newaxis], rgb.shape),
            spread_fg,
            result[:, :, :3],
        )

    return Image.fromarray(result.astype(np.uint8), "RGBA")


def refine_alpha_mask(
    rgba_image: Image.Image,
    smooth: int = 0,
    expand: int = 0,
    feather: float = 0.0,
) -> Image.Image:
    """Post-process the alpha mask for cleaner edges.

    smooth  — morphological opening radius (removes speckles, smooths jagged edges)
    expand  — positive = grow selection outward, negative = shrink inward (removes white fringe)
    feather — Gaussian blur radius on the alpha channel (soft, anti-aliased edge)
    """
    arr = np.array(rgba_image.convert("RGBA"), dtype=np.uint8)
    alpha = arr[:, :, 3].astype(np.float32) / 255.0

    # Smooth: morphological opening (erode then dilate) to clean noisy edges
    if smooth > 0:
        k = smooth * 2 + 1
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
        binary = (alpha > 0.1).astype(np.uint8)
        binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)
        alpha = binary.astype(np.float32)

    # Expand / Contract: dilate (positive) or erode (negative)
    if expand != 0:
        k = abs(expand) * 2 + 1
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
        binary = (alpha > 0.1).astype(np.uint8)
        if expand > 0:
            binary = cv2.dilate(binary, kernel)
        else:
            binary = cv2.erode(binary, kernel)
        alpha = binary.astype(np.float32)

    # Feather: Gaussian blur for smooth semi-transparent edge
    if feather > 0:
        sigma = feather
        ksize = int(sigma * 6) | 1  # must be odd
        alpha = cv2.GaussianBlur(alpha, (ksize, ksize), sigma)
        alpha = np.clip(alpha, 0.0, 1.0)

    result = arr.copy()
    result[:, :, 3] = (alpha * 255).astype(np.uint8)
    return Image.fromarray(result, "RGBA")
