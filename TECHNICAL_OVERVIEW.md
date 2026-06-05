# Technical Overview — Gomba's Sprite Sheet Cutter

## Project Purpose & Scope

Gomba's Sprite Sheet Cutter is a local web app that automates the extraction of individual sprites from multi-sprite PNG/JPEG/WEBP sheets. It is aimed at artists and game developers who need clean, consistently-sized sprite PNGs — Discord/Twitch emoji creators, pixel artists, and game devs who receive sprite sheets from collaborators and need individual files numbered for import into engines or emoji upload portals.

The app runs entirely on the user's machine (served at `http://127.0.0.1:7860`). There is no authentication, no database, no user accounts, and no network calls during normal operation — the only outbound traffic is one-time model weight downloads the first time an AI background-removal method is used.

---

## Architecture

### Layer Diagram

```
┌─────────────────────────────────────────────┐
│         User Browser  (localhost:7860)       │
└───────────────────┬─────────────────────────┘
                    │  HTTP / WebSocket (Gradio)
                    ▼
┌─────────────────────────────────────────────┐
│                  app.py                     │
│  Gradio UI layout + event handlers +        │
│  top-level processing pipeline              │
└──────┬───────────────┬──────────────────────┘
       │               │               │
       ▼               ▼               ▼
bg_remover.py   sprite_detector.py   sprite_cutter.py
(BG removal +   (detection + merge)  (crop + packaging)
 edge cleanup)
       │               │
       ▼               ▼
rembg / PyTorch    OpenCV / SciPy
(AI model weights) (connected components)
```

### In-Memory Data Flow

```
Uploaded file (disk)
   └─► PIL Image (RGB / RGBA)
           │  bg_remover  — remove_bg_*
           ▼
       RGBA Image (foreground isolated)
           │  bg_remover  — defringe
           ▼
       RGBA Image (edge colors corrected)
           │  bg_remover  — refine_alpha_mask
           ▼
       RGBA Image (mask smoothed / expanded / feathered)
           │  sprite_detector  — detect_sprites
           ▼
       list[bbox tuples]  (x1, y1, x2, y2)
           │  sprite_detector  — merge_nearby_bboxes
           ▼
       list[bbox tuples]  (merged)
           │  sprite_cutter  — cut_sprites → _letterbox
           ▼
       list[PIL Images]  (letterboxed sprites)
           │  sprite_cutter  — pack_to_zip
           ▼
       bytes (in-memory ZIP)
           │  app.py  — written to tempfile
           ▼
       gr.File  (downloadable by user)
```

**Key caching design:** After processing, `app.py` stores `(rgba_image, bboxes)` per sheet in a `gr.State` list (`sheet_data`). This cache makes two operations instant without re-running background removal:
- **Preview background switching** (`redraw_previews`) — re-composites the stored RGBA onto black/white/checker.
- **Manual merge** (`apply_merges`) — re-runs only `apply_manual_merges` + `cut_sprites` + `pack_to_zip` on the cached data.

---

## Module Reference

### app.py — UI, Event Wiring, Top-Level Pipeline

The application entry point. Defines the Gradio interface, all event callbacks, and the main processing pipeline. All imports from the other three modules pass through here.

**State variables**
- `sheet_state = gr.State([])` — list of `(rgba_image, bboxes)` tuples, one per uploaded sheet.
- `sampler_visible = gr.State(False)` — tracks open/closed state of the pixel color sampler.

**Core pipeline**

`_process_one(img, bg_method, tolerance, ai_model, do_defringe, defringe_hex, defringe_strength, defringe_spread, refine_smooth, refine_expand, refine_feather, min_area, padding, merge_distance, do_resize, target_size, preview_bg) -> (preview_img, sprites, rgba, bboxes)`

Single-sheet pipeline. Executes stages in order: BG removal → defringe → refine → detect → proximity-merge → draw_bboxes → cut_sprites. Returns the gallery preview image, sprite list, and the RGBA + bbox pair for caching.

`process(input_files, ...) -> (gallery_images, status_str, zip_path, sheet_data)`

Batch wrapper — iterates uploaded files, calls `_process_one` for each, aggregates all sprites, writes a temp ZIP, returns Gradio outputs. The `sheet_data` return populates `sheet_state`.

`process_with_preset(...)`

Thin wrapper around `process`. Resolves the defringe preset radio (White / Black / Custom) to a hex string before forwarding all parameters.

`redraw_previews(sheet_data, bg) -> list[Image]`

Fired by the Preview BG radio. Re-calls `draw_bboxes` on every cached RGBA with the new background — no BG removal involved.

`apply_merges(sheet_data, merge_spec, do_resize, target_size, preview_bg) -> (gallery, status, zip_path, sheet_data)`

Fired by the Apply Merge button. Calls `apply_manual_merges` → `cut_sprites` → `pack_to_zip` on cached data. Does not re-run BG removal or detection.

`sample_color_from_image(img, evt) -> str`

Handles `gr.SelectData` pixel-click events on the color sampler. Extracts the RGB value at the clicked coordinate and returns it as a CSS hex string for the color picker.

`show_upload_preview(files)`, `update_sampler_image(files)`

UI helpers that fire on file upload to populate the input gallery and sampler image immediately.

`toggle_method_controls(method)`

Shows/hides the tolerance slider (Flood-fill), AI model dropdown (AI/rembg), or neither (ToonOut / Skip) based on the selected method.

`on_defringe_preset(preset)`

Shows/hides the hex color picker and updates `defringe_strength` and `defringe_spread` to sensible defaults when the preset changes.

**Theme**

A custom dark bronze aesthetic is applied via a `gr.themes.Soft` instance (`_THEME`). Two custom `gr.themes.Color` palettes are defined: `_bronze` (warm amber/copper) and `_graphite` (neutral dark grays). All component color tokens, button styles, input backgrounds, and tab styles are overridden to achieve a cohesive dark UI.

---

### bg_remover.py — Background Removal & Alpha Refinement

Handles all operations that modify the alpha channel: initial background removal by three different methods, color defringing at semi-transparent edges, and alpha mask refinement.

**Constants**

`REMBG_MODELS: list[str]` — 15 model names exposed to `app.py` for the AI model dropdown.

**Background removal**

`remove_bg_floodfill(pil_image, tolerance=30) -> Image`

Connected-component flood-fill approach. Converts to RGB, thresholds white pixels (`channel >= 255 - tolerance`), uses `scipy.ndimage.label` to label connected regions, then identifies which components touch the image border (these are background). Sets their alpha to 0. Does not require any model weights.

`remove_bg_ai(pil_image, model_name="isnet-anime") -> Image`

rembg wrapper. Forces `CPUExecutionProvider` to avoid DLL conflicts with CUDA 12 / cuDNN 9 on Windows. Converts to RGB before calling rembg (avoids palette-mode input bugs). Calls `_normalize_alpha` on the result because some rembg models produce soft masks where the maximum alpha is well below 255, which would cause all pixels to be discarded by the `alpha > 10` detection threshold.

`_load_toonout() -> (model, device)`

Downloads `birefnet_finetuned_toonout.pth` from `joelseytre/toonout` on Hugging Face (~885 MB) on first call. Loads the base BiRefNet architecture from `ZhengPeng7/BiRefNet`, strips `module._orig_mod.` and `module.` prefixes from state-dict keys (artifact of how the weights were saved), casts to float32, moves to CUDA if available. Result is cached in module-level `_toonout_model` / `_toonout_device` so subsequent calls are instant.

`remove_bg_toonout(pil_image) -> Image`

Calls `_load_toonout`, resizes input to 1024×1024, normalizes with ImageNet mean/std via `torchvision.transforms`, runs inference, resizes the predicted mask back to the original image dimensions, composites as the alpha channel, normalizes alpha.

`_apply_birefnet_compat_patch()`

Monkey-patches `PretrainedConfig.__getattribute__` to return `False` for `is_encoder_decoder`. Fixes a `transformers` version incompatibility where BiRefNet's config class triggers incorrect encoder-decoder initialization paths.

**Edge cleanup**

`defringe(rgba_image, bg_color=(255,255,255), strength=1.0, spread=0) -> Image`

Removes background color bleed from semi-transparent edges using the inverse alpha-compositing formula:

```
fg = (composite − (1 − α) × bg) / α
```

`strength` amplifies the correction (values > 1.0 over-correct, useful for stubborn fringing). `spread > 0` extends the correction ring into a band of fully-opaque border pixels, using a distance transform to create a virtual alpha ramp that decays toward the interior.

`refine_alpha_mask(rgba_image, smooth=0, expand=0, feather=0.0) -> Image`

Three independent passes on the extracted alpha channel:
- `smooth`: morphological opening (erode then dilate) to remove specks and jagged single-pixel artifacts.
- `expand`: positive = dilation (grow mask), negative = erosion (shrink mask). Negative values remove white halos by contracting the mask edge inward.
- `feather`: Gaussian blur on alpha for soft, anti-aliased edges.

**Private utilities**

`_to_rgba(img) -> np.ndarray` — Converts PIL Image to RGBA numpy array.

`_normalize_alpha(rgba_image) -> Image` — Scales the alpha channel so its maximum value is 255. Prevents soft AI masks from being silently discarded.

---

### sprite_detector.py — Detection & Merging

Finds individual sprites within an RGBA image using connected-component analysis and provides tools to merge nearby or manually specified sprites.

`detect_sprites(rgba_image, min_area=500, padding=4) -> list[tuple]`

Binarizes the alpha channel (threshold: `alpha > 10`), runs `cv2.connectedComponentsWithStats` with 8-connectivity, filters components below `min_area` pixels, adds `padding` px to all sides of each bounding box, and sorts results row-major (by vertical center band first, then horizontal center). Returns `list[(x1, y1, x2, y2)]`.

`merge_nearby_bboxes(bboxes, distance) -> list[tuple]`

O(n²) pairwise edge-gap test: two boxes are "nearby" if the gap between their nearest edges is ≤ `distance` pixels in both horizontal and vertical directions. Uses Union-Find (`_union_find_groups`) to build connected groups, then merges each group to its bounding hull (`_merge_groups`).

`apply_manual_merges(bboxes, merge_spec) -> list[tuple]`

Parses a user string like `"1+3, 5+7+8"` (comma-separated groups of `+`-joined 1-based indices). Builds a pair list from each group, applies the same Union-Find merge as `merge_nearby_bboxes`. Returns a new sorted bbox list with merged groups replaced by their bounding hulls.

`draw_bboxes(rgba_image, bboxes, bg="black") -> Image`

Alpha-composites the RGBA sprite sheet onto a background (black solid / white solid / checkerboard built with numpy broadcasting at 220/160 grey tones). Draws red rectangles and 1-based index numbers using OpenCV. Returns an RGB PIL Image for the Gradio gallery.

`_union_find_groups(n, pairs) -> dict[int, list[int]]` — Path-compressed Union-Find; groups overlapping pair indices into clusters.

`_merge_groups(bboxes, groups) -> list[tuple]` — Computes bounding hull (`min x1, min y1, max x2, max y2`) for each group.

`_bbox_sort(bboxes)` — Sorts by row-major center (y-center divided into row bands, then x-center within each band).

`_make_checkerboard(w, h, square=16) -> np.ndarray` — Generates a grey checkerboard pattern via numpy broadcasting.

---

### sprite_cutter.py — Cropping & Packaging

Handles the final stage: cropping individual sprites from the processed RGBA sheet and packaging them into a ZIP.

`cut_sprites(rgba_image, bboxes, target_size=None) -> list[Image]`

PIL crop loop over the bbox list. If `target_size` is provided, each crop is passed to `_letterbox`.

`_letterbox(img, size) -> Image`

Scales the sprite to fit within a `size × size` canvas while preserving aspect ratio (LANCZOS resampling), then centers it on a fully-transparent RGBA canvas of exactly `size × size`. This ensures all output sprites share the same canvas dimensions — required for consistent Discord emoji uploads and game engine sprite atlases.

`pack_to_zip(sprites, prefix="sprite", start_index=1) -> bytes`

Writes each PIL Image as a numbered PNG (`sprite_001.png`, `sprite_002.png`, …) into an in-memory `io.BytesIO` ZIP using `ZIP_DEFLATED` compression. Returns raw bytes that `app.py` writes to a `tempfile.NamedTemporaryFile`.

> **Note:** `pack_to_zip` currently places files at the zip root (e.g. `sprite_001.png`). The distribution policy for the app's *own* output zip is flat — users receive individual numbered PNGs. If a named subfolder is ever desired in the sprite output ZIP, change the `zf.writestr` path from `f"{prefix}_{i:03d}.png"` to `f"sprites/{prefix}_{i:03d}.png"`.

---

## End-to-End Data Flow Walkthrough

1. **User uploads files.** Gradio fires `show_upload_preview` and `update_sampler_image` immediately via `inp_files.change`, displaying thumbnails in the input gallery and populating the color sampler.

2. **User adjusts controls and clicks "Process All Sheets".** Gradio calls `process_with_preset` with all widget values as arguments.

3. **`process_with_preset`** resolves the defringe preset (`White` → `#ffffff`, `Black` → `#000000`, `Custom` → pass-through from hex picker), then calls `process`.

4. **`process`** opens each uploaded file with `PIL.Image.open(...).load()` and calls `_process_one` for each.

5. **BG removal branch** in `_process_one`:
   - `Flood-fill (fast)` → `remove_bg_floodfill(img, tolerance)`
   - `AI / rembg` → `remove_bg_ai(img, ai_model)`
   - `ToonOut (recommended) ⭐` → `remove_bg_toonout(img)` (downloads 885 MB weights on first use)
   - `Skip (already transparent)` → `img.convert("RGBA")` only

6. **Defringe** (if enabled): `defringe(rgba, bg_color, strength, spread)` reverses compositing artifacts at semi-transparent edges.

7. **Alpha refinement** (if any slider is non-default): `refine_alpha_mask(rgba, smooth, expand, feather)` cleans up the mask.

8. **Sprite detection:** `detect_sprites(rgba, min_area, padding)` binarizes alpha, runs `cv2.connectedComponentsWithStats`, filters, pads, and sorts.

9. **Proximity merge** (if `merge_distance > 0`): `merge_nearby_bboxes(bboxes, merge_distance)` groups nearby components.

10. **Preview render:** `draw_bboxes(rgba, bboxes, preview_bg)` composites the sheet onto the chosen background with numbered red bounding boxes. This image is appended to the gallery.

11. **Sprite cutting:** `cut_sprites(rgba, bboxes, target_size if do_resize else None)` crops and optionally letterboxes each sprite. Sprites are appended to `all_sprites`.

12. **State caching:** `(rgba, bboxes)` is stored in `sheet_data`. After all sheets are processed, `sheet_data` is returned as the new value of `gr.State sheet_state`.

13. **ZIP packaging:** `pack_to_zip(all_sprites)` writes all sprites from all sheets into one in-memory ZIP. `app.py` writes the bytes to a `tempfile.NamedTemporaryFile(.zip)` and returns the path as `gr.File`.

14. **User switches Preview BG radio:** `redraw_previews(sheet_data, bg)` fires. Re-calls `draw_bboxes` on each cached RGBA — no model inference, no detection.

15. **User types merge spec and clicks Apply Merge:** `apply_merges(sheet_data, merge_spec, ...)` calls `apply_manual_merges` → `cut_sprites` → `pack_to_zip` on the cached data. Returns an updated gallery and a new ZIP with the merged sprite layout.

---

## Configuration Parameters Reference

| UI Label | Code Parameter | Type | Default | Effect |
|---|---|---|---|---|
| Method | `bg_method` | str | `"Flood-fill (fast)"` | Selects BG removal path |
| Flood-fill Tolerance | `tolerance` | int | `30` | `thresh = 255 − tolerance`; visible only for Flood-fill |
| AI Model | `ai_model` | str | `"isnet-anime"` | rembg session model; visible only for AI/rembg |
| Enable Defringe | `do_defringe` | bool | `True` | Enables the defringe pass |
| Defringe BG Color (preset) | `defringe_preset` | str | `"White"` | White/Black/Custom; resolves to hex string |
| Custom color picker | `defringe_picker` | str | `"#ffffff"` | Active only when preset = Custom |
| Defringe Strength | `defringe_strength` | float | `1.0` | Amplification of color correction (>1 = stronger) |
| Defringe Spread (px) | `defringe_spread` | int | `0` | Extends correction ring into opaque border pixels |
| Contract / Expand | `refine_expand` | int | `−1` | Negative = erode mask (shrink); positive = dilate |
| Smooth | `refine_smooth` | int | `0` | Morphological opening radius (removes speckles) |
| Feather | `refine_feather` | float | `0.0` | Gaussian sigma on alpha for soft edges |
| Min Sprite Area (px²) | `min_area` | int | `50` | Filters connected components smaller than this |
| Padding around sprite | `padding` | int | `4` | Adds px to all sides of each detected bbox |
| Auto-merge proximity | `merge_distance` | int | `0` | 0 = off; >0 = merge bboxes within this edge gap |
| Resize sprites | `do_resize` | bool | `True` | Enables letterbox resize to target canvas |
| Target size (px) | `target_size` | int | `128` | Output canvas width & height; 128 = Discord emoji |
| Preview background | `preview_bg` | str | `"black"` | `"black"` / `"white"` / `"checker"` |
| Merge spec | `merge_spec` | str | `""` | e.g. `"1+3, 5+7+8"`; 1-based sprite indices |

**Smart defaults when switching BG method:**
- Switching to **AI / rembg** or **ToonOut**: `do_defringe` → `False`, `refine_expand` → `0` (AI models produce clean masks that don't need edge correction).
- Switching to **Flood-fill**: `do_defringe` → `True`, `refine_expand` → `−1` (flood-fill tends to leave white halos; defringe + contract corrects them).

---

## Tech Stack

| Package | Version Spec | Purpose |
|---|---|---|
| `gradio` | `>=4.0` | Web UI framework; WebSocket event loop, component library |
| `opencv-python-headless` | latest | Connected-component analysis (`connectedComponentsWithStats`), morphological ops, bbox drawing |
| `Pillow` | latest | Image open/save, crop, resize, RGBA compositing |
| `numpy` | latest | Array-level alpha manipulation, checkerboard generation, defringe arithmetic |
| `scipy` | latest | `scipy.ndimage.label` for flood-fill connected-component labeling |
| `rembg[gpu]` | latest | 15 AI background-removal models via ONNX Runtime |
| `torch` | latest | ToonOut inference runtime; CUDA device selection |
| `torchvision` | latest | `transforms.Compose` pipeline for ToonOut preprocessing |
| `transformers` | latest | `AutoModelForImageSegmentation` for BiRefNet architecture loading |
| `einops` | latest | Tensor rearrangement (required internally by BiRefNet) |
| `kornia` | latest | Image geometry utilities (required internally by BiRefNet) |
| `timm` | latest | Backbone model registry (required internally by BiRefNet) |
| `huggingface_hub` | (transitive) | `hf_hub_download` used in `_load_toonout` for ToonOut weights |

---

## Model Download Notes

AI model weights are **downloaded lazily** — nothing is fetched during `install.bat` or `launch.bat`. Downloads happen the first time a method is used in a session.

| Model / Weights | Size | Cache Location | Trigger |
|---|---|---|---|
| ToonOut (`birefnet_finetuned_toonout.pth`) | ~885 MB | `%USERPROFILE%\.cache\huggingface\hub` | First click of "ToonOut ⭐" |
| BiRefNet base architecture (`ZhengPeng7/BiRefNet`) | ~150 MB | `%USERPROFILE%\.cache\huggingface\hub` | First click of "ToonOut ⭐" |
| rembg `isnet-anime` | ~176 MB | `%USERPROFILE%\.u2net\` | First click with "AI / rembg" + isnet-anime |
| rembg `u2net` | ~176 MB | `%USERPROFILE%\.u2net\` | First click with "AI / rembg" + u2net |
| rembg `u2netp` | ~4 MB | `%USERPROFILE%\.u2net\` | First click with "AI / rembg" + u2netp |
| rembg BiRefNet variants | ~150–200 MB each | `%USERPROFILE%\.u2net\` | First click with matching model |

**Worst-case total (all models):** approximately 2–3 GB. After the first session, all weights are cached and no further downloads occur.

The ToonOut model is loaded into a module-level variable (`_toonout_model`) and reused for every subsequent sheet in the same session — the 885 MB weight file is only parsed once per run.
