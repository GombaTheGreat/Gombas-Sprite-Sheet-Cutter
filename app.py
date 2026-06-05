from __future__ import annotations

import tempfile

import gradio as gr
from PIL import Image

from bg_remover import (
    REMBG_MODELS,
    defringe,
    refine_alpha_mask,
    remove_bg_ai,
    remove_bg_floodfill,
    remove_bg_toonout,
)
from sprite_cutter import cut_sprites, pack_to_zip
from sprite_detector import (
    apply_manual_merges,
    detect_sprites,
    draw_bboxes,
    merge_nearby_bboxes,
)

# --------------------------------------------------------------------------- #
# Helpers                                                                       #
# --------------------------------------------------------------------------- #

def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


# --------------------------------------------------------------------------- #
# Processing pipeline                                                           #
# --------------------------------------------------------------------------- #

def _process_one(
    img: Image.Image,
    bg_method: str,
    tolerance: int,
    ai_model: str,
    do_defringe: bool,
    defringe_hex: str,
    defringe_strength: float,
    defringe_spread: int,
    refine_smooth: int,
    refine_expand: int,
    refine_feather: float,
    min_area: int,
    padding: int,
    merge_distance: int,
    do_resize: bool,
    target_size: int,
    preview_bg: str,
) -> tuple[Image.Image, list[Image.Image], Image.Image, list]:
    """Process one sheet. Returns (preview, sprites, rgba, bboxes)."""

    # 1. Background removal
    if bg_method == "Flood-fill (fast)":
        rgba = remove_bg_floodfill(img, tolerance=tolerance)
    elif bg_method == "AI / rembg":
        rgba = remove_bg_ai(img, model_name=ai_model)
    elif bg_method == "ToonOut (recommended) ⭐":
        rgba = remove_bg_toonout(img)
    else:
        rgba = img.convert("RGBA")

    # 2. Defringe
    if do_defringe:
        rgba = defringe(
            rgba,
            bg_color=_hex_to_rgb(defringe_hex),
            strength=defringe_strength,
            spread=defringe_spread,
        )

    # 3. Mask refinement
    if refine_smooth > 0 or refine_expand != 0 or refine_feather > 0:
        rgba = refine_alpha_mask(rgba, smooth=refine_smooth, expand=refine_expand, feather=refine_feather)

    # 4. Detect sprites
    bboxes = detect_sprites(rgba, min_area=min_area, padding=padding)
    if merge_distance > 0:
        bboxes = merge_nearby_bboxes(bboxes, merge_distance)

    # 5. Preview
    preview = draw_bboxes(rgba, bboxes, bg=preview_bg)

    # 6. Cut sprites
    resize_val = target_size if do_resize else None
    sprites = cut_sprites(rgba, bboxes, target_size=resize_val)

    return preview, sprites, rgba, bboxes


def redraw_previews(
    sheet_data: list[tuple],   # list of (rgba, bboxes)
    bg: str,
) -> list[Image.Image]:
    """Re-composite stored RGBA sheets onto a new background — no reprocessing."""
    if not sheet_data:
        return []
    return [draw_bboxes(rgba, bboxes, bg=bg) for rgba, bboxes in sheet_data]


def process(
    input_files,
    bg_method: str,
    tolerance: int,
    ai_model: str,
    do_defringe: bool,
    defringe_hex: str,
    defringe_strength: float,
    defringe_spread: int,
    refine_smooth: int,
    refine_expand: int,
    refine_feather: float,
    min_area: int,
    padding: int,
    merge_distance: int,
    do_resize: bool,
    target_size: int,
    preview_bg: str,
) -> tuple[list, str, str | None, list]:
    """Returns (gallery_images, status, zip_path, sheet_data_for_state)."""

    if not input_files:
        return [], "No images uploaded.", None, []

    all_sprites: list[Image.Image] = []
    previews: list[Image.Image] = []
    sheet_data: list[tuple] = []   # (rgba, bboxes) per sheet — stored in State
    sheet_counts: list[str] = []

    for i, f in enumerate(input_files, 1):
        # gr.File returns either an object with .name or a plain string path
        path = f.name if hasattr(f, "name") else str(f)
        try:
            img = Image.open(path)
            img.load()  # force full decode now so mode/palette errors surface here
        except Exception as e:
            sheet_counts.append(f"  ✗ Sheet {i} failed to open: {e}")
            continue

        try:
            preview, sprites, rgba, bboxes = _process_one(
                img, bg_method, tolerance, ai_model,
                do_defringe, defringe_hex, defringe_strength, defringe_spread,
                refine_smooth, refine_expand, refine_feather,
                min_area, padding, merge_distance, do_resize, target_size,
                preview_bg,
            )
        except BaseException as e:
            import traceback
            sheet_counts.append(f"  ✗ Sheet {i} processing error: {e}\n{traceback.format_exc()}")
            continue

        previews.append(preview)
        all_sprites.extend(sprites)
        sheet_data.append((rgba, bboxes))
        sheet_counts.append(f"  Sheet {i}: {len(sprites)} sprites detected")

    if not all_sprites:
        # Always show per-sheet detail so errors are visible even when total = 0
        detail = "\n".join(sheet_counts) if sheet_counts else "  (no sheets processed)"
        return previews, f"No sprites found.\n{detail}", None, sheet_data

    zip_bytes = pack_to_zip(all_sprites, start_index=1)
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    tmp.write(zip_bytes)
    tmp.close()

    size_label = f" → {target_size}×{target_size}px" if do_resize else ""
    lines = [f"{len(all_sprites)} total sprites across {len(previews)} sheet(s){size_label}:"]
    lines += sheet_counts
    lines.append(f"Named sprite_001 … sprite_{len(all_sprites):03d}.png")

    return previews, "\n".join(lines), tmp.name, sheet_data


# --------------------------------------------------------------------------- #
# Gradio UI                                                                     #
# --------------------------------------------------------------------------- #
# Theme                                                                         #
# --------------------------------------------------------------------------- #

_bronze = gr.themes.Color(
    c50="#fef5ee", c100="#fce0c0", c200="#f8bc83", c300="#f2944c",
    c400="#df7226", c500="#CC5803", c600="#a84500", c700="#843500",
    c800="#612600", c900="#3d1800", c950="#200c00",
)
_graphite = gr.themes.Color(
    c50="#f5f4f3", c100="#e8e6e3", c200="#d1cec9", c300="#b4b0aa",
    c400="#928d85", c500="#736e66", c600="#575249", c700="#453f38",
    c800="#3c3832", c900="#34312D", c950="#1c1a17",
)

_THEME = gr.themes.Soft(
    primary_hue=_bronze,
    secondary_hue=_bronze,
    neutral_hue=_graphite,
).set(
    # ── Backgrounds (force dark on both light/dark OS modes) ──────────────── #
    body_background_fill="#2a2724",           body_background_fill_dark="#2a2724",
    background_fill_primary="#34312D",        background_fill_primary_dark="#34312D",
    background_fill_secondary="#2e2b27",      background_fill_secondary_dark="#2e2b27",
    block_background_fill="#3d3a35",          block_background_fill_dark="#3d3a35",
    block_label_background_fill="#34312D",    block_label_background_fill_dark="#34312D",
    block_title_background_fill="#34312D",    block_title_background_fill_dark="#34312D",
    panel_background_fill="#2e2b27",          panel_background_fill_dark="#2e2b27",
    input_background_fill="#2a2724",          input_background_fill_dark="#2a2724",
    input_background_fill_hover="#302d2a",    input_background_fill_hover_dark="#302d2a",
    input_background_fill_focus="#302d2a",    input_background_fill_focus_dark="#302d2a",
    code_background_fill="#1e1c19",           code_background_fill_dark="#1e1c19",
    stat_background_fill="#34312D",           stat_background_fill_dark="#34312D",
    table_even_background_fill="#34312D",     table_even_background_fill_dark="#34312D",
    table_odd_background_fill="#3d3a35",      table_odd_background_fill_dark="#3d3a35",
    error_background_fill="#3d2525",          error_background_fill_dark="#3d2525",
    # ── Borders ───────────────────────────────────────────────────────────── #
    border_color_primary="#4a4640",           border_color_primary_dark="#4a4640",
    block_border_color="#4a4640",             block_border_color_dark="#4a4640",
    block_label_border_color="#4a4640",       block_label_border_color_dark="#4a4640",
    panel_border_color="#4a4640",             panel_border_color_dark="#4a4640",
    input_border_color="#4a4640",             input_border_color_dark="#4a4640",
    input_border_color_focus="#CC5803",       input_border_color_focus_dark="#CC5803",
    input_border_color_hover="#7a7470",       input_border_color_hover_dark="#7a7470",
    table_border_color="#4a4640",             table_border_color_dark="#4a4640",
    error_border_color="#7a3535",             error_border_color_dark="#7a3535",
    # ── Text ──────────────────────────────────────────────────────────────── #
    body_text_color="#e8e4de",                body_text_color_dark="#e8e4de",
    body_text_color_subdued="#9a9490",        body_text_color_subdued_dark="#9a9490",
    block_label_text_color="#d4cfc8",         block_label_text_color_dark="#d4cfc8",
    block_title_text_color="#e8e4de",         block_title_text_color_dark="#e8e4de",
    block_info_text_color="#9a9490",          block_info_text_color_dark="#9a9490",
    input_placeholder_color="#7a7470",        input_placeholder_color_dark="#7a7470",
    table_text_color="#e8e4de",               table_text_color_dark="#e8e4de",
    checkbox_label_text_color="#e8e4de",      checkbox_label_text_color_dark="#e8e4de",
    accordion_text_color="#e8e4de",           accordion_text_color_dark="#e8e4de",
    error_text_color="#f79090",               error_text_color_dark="#f79090",
    error_icon_color="#f79090",               error_icon_color_dark="#f79090",
    link_text_color="#CC5803",                link_text_color_dark="#CC5803",
    link_text_color_hover="#e06a10",          link_text_color_hover_dark="#e06a10",
    # ── Primary button (bronze) ───────────────────────────────────────────── #
    button_primary_background_fill="#CC5803",       button_primary_background_fill_dark="#CC5803",
    button_primary_background_fill_hover="#e06a10", button_primary_background_fill_hover_dark="#e06a10",
    button_primary_text_color="#ffffff",            button_primary_text_color_dark="#ffffff",
    button_primary_text_color_hover="#ffffff",      button_primary_text_color_hover_dark="#ffffff",
    button_primary_border_color="#CC5803",          button_primary_border_color_dark="#CC5803",
    button_primary_border_color_hover="#e06a10",    button_primary_border_color_hover_dark="#e06a10",
    # ── Secondary button ─────────────────────────────────────────────────── #
    button_secondary_background_fill="#4a4640",       button_secondary_background_fill_dark="#4a4640",
    button_secondary_background_fill_hover="#5a554f", button_secondary_background_fill_hover_dark="#5a554f",
    button_secondary_text_color="#e8e4de",            button_secondary_text_color_dark="#e8e4de",
    button_secondary_text_color_hover="#ffffff",      button_secondary_text_color_hover_dark="#ffffff",
    button_secondary_border_color="#4a4640",          button_secondary_border_color_dark="#4a4640",
    button_secondary_border_color_hover="#5a554f",    button_secondary_border_color_hover_dark="#5a554f",
    # ── Checkbox / radio ─────────────────────────────────────────────────── #
    checkbox_background_color="#2a2724",              checkbox_background_color_dark="#2a2724",
    checkbox_background_color_hover="#302d2a",        checkbox_background_color_hover_dark="#302d2a",
    checkbox_background_color_selected="#CC5803",     checkbox_background_color_selected_dark="#CC5803",
    checkbox_border_color="#4a4640",                  checkbox_border_color_dark="#4a4640",
    checkbox_border_color_hover="#7a7470",            checkbox_border_color_hover_dark="#7a7470",
    checkbox_border_color_selected="#CC5803",         checkbox_border_color_selected_dark="#CC5803",
    checkbox_border_color_focus="#CC5803",            checkbox_border_color_focus_dark="#CC5803",
    checkbox_label_background_fill="#3d3a35",         checkbox_label_background_fill_dark="#3d3a35",
    checkbox_label_background_fill_hover="#4a4640",   checkbox_label_background_fill_hover_dark="#4a4640",
    checkbox_label_background_fill_selected="#4a2800",checkbox_label_background_fill_selected_dark="#4a2800",
    checkbox_label_border_color="#4a4640",            checkbox_label_border_color_dark="#4a4640",
    checkbox_label_border_color_selected="#CC5803",   checkbox_label_border_color_selected_dark="#CC5803",
    checkbox_label_text_color_selected="#e8e4de",     checkbox_label_text_color_selected_dark="#e8e4de",
    # ── Slider / accent ───────────────────────────────────────────────────── #
    slider_color="#CC5803",                           slider_color_dark="#CC5803",
    color_accent="#CC5803",
    color_accent_soft="rgba(204,88,3,0.18)",          color_accent_soft_dark="rgba(204,88,3,0.18)",
    loader_color="#CC5803",                           loader_color_dark="#CC5803",
    # ── Shadows ───────────────────────────────────────────────────────────── #
    block_shadow="0 2px 8px rgba(0,0,0,0.45)",        block_shadow_dark="0 2px 8px rgba(0,0,0,0.45)",
)

# --------------------------------------------------------------------------- #

DESCRIPTION = """
## Gomba's Sprite Sheet Cutter
Upload one or more sprite sheets → remove background → detect & cut sprites → download all as one ZIP with sequential numbering.
"""

with gr.Blocks(title="Gomba's Sprite Sheet Cutter", theme=_THEME) as demo:
    gr.Markdown(DESCRIPTION)

    # Stores list of (rgba_image, bboxes) after each run — used for live BG switching
    sheet_state = gr.State([])
    # Tracks whether the color sampler image is currently visible
    sampler_visible = gr.State(False)

    with gr.Row():

        # ── Left column: inputs ──────────────────────────────────────────── #
        with gr.Column(scale=1):

            inp_files = gr.File(
                label="Sprite Sheets — drag & drop multiple files",
                file_count="multiple",
                file_types=[".png", ".jpg", ".jpeg", ".webp"],
            )
            inp_preview = gr.Gallery(
                label="Uploaded sheets",
                columns=2,
                object_fit="contain",
                height=300,
                interactive=False,
            )

            # ── Background removal ── #
            with gr.Group():
                gr.Markdown("### 1 · Background Removal")

                bg_method = gr.Radio(
                    label="Method",
                    choices=[
                        "Flood-fill (fast)",
                        "AI / rembg",
                        "ToonOut (recommended) ⭐",
                        "Skip (already transparent)",
                    ],
                    value="Flood-fill (fast)",
                )
                tolerance_slider = gr.Slider(
                    label="Flood-fill Tolerance — higher removes off-white backgrounds too",
                    minimum=5, maximum=100, step=1, value=30, visible=True,
                )
                ai_model_dropdown = gr.Dropdown(
                    label="AI Model",
                    choices=REMBG_MODELS,
                    value="isnet-anime",
                    visible=False,
                    info="📌 isnet-anime works well for single big anime images where you want the background removed.\n📌 birefnet-general and u2net generally work well for stickers and sprite sheets.\n📌 Models download automatically on first use.",
                )
                gr.Markdown(
                    "<small>⭐ **ToonOut** — BiRefNet fine-tuned specifically for anime characters. "
                    "Downloads ~885 MB on first use, then cached. Requires no extra config.</small>",
                    visible=True,
                )

            # ── Edge cleanup ── #
            with gr.Group():
                gr.Markdown("### 2 · Edge Cleanup  *(applied after BG removal)*")

                do_defringe = gr.Checkbox(
                    label="Defringe — remove background color bleed from semi-transparent edges",
                    value=True,
                )

                with gr.Row(visible=True) as defringe_row:
                    defringe_preset = gr.Radio(
                        ["White", "Black", "Custom"],
                        value="White",
                        label="Defringe BG color",
                        scale=2,
                    )
                    defringe_picker = gr.ColorPicker(
                        value="#ffffff",
                        label="Custom color",
                        visible=False,
                        scale=1,
                    )

                with gr.Row(visible=False) as defringe_sampler_row:
                    show_sampler_btn = gr.Button(
                        "🔬 Pick color from image",
                        size="sm",
                        scale=1,
                    )
                    gr.Markdown(
                        "<small>Click the button, then click any pixel on the sprite sheet below to set the defringe color.</small>",
                    )

                color_sampler_img = gr.Image(
                    label="Click a background pixel to sample its color",
                    type="pil",
                    interactive=False,
                    height=200,
                    visible=False,
                )

                with gr.Row(visible=True) as defringe_tuning_row:
                    defringe_strength = gr.Slider(
                        label="Defringe Strength — amplify correction (>1 for heavy fringe)",
                        minimum=0.5, maximum=3.0, step=0.1, value=1.0,
                        scale=1,
                    )
                    defringe_spread = gr.Slider(
                        label="Defringe Spread (px) — extend to opaque edge pixels",
                        minimum=0, maximum=5, step=1, value=0,
                        scale=1,
                    )

                refine_expand = gr.Slider(
                    label="Contract / Expand — negative shrinks inward to eliminate white halo",
                    minimum=-10, maximum=10, step=1, value=-1,
                )
                refine_smooth = gr.Slider(
                    label="Smooth — removes speckles and jagged pixel edges",
                    minimum=0, maximum=10, step=1, value=0,
                )
                refine_feather = gr.Slider(
                    label="Feather — soft anti-aliased edge blur",
                    minimum=0.0, maximum=5.0, step=0.5, value=0.0,
                )

            # ── Detection & export ── #
            with gr.Group():
                gr.Markdown("### 3 · Detection & Export")

                min_area_slider = gr.Slider(
                    label="Min Sprite Area (px²) — raise to filter noise dots",
                    minimum=0, maximum=100, step=1, value=50,
                )
                padding_slider = gr.Slider(
                    label="Padding around each sprite (px)",
                    minimum=0, maximum=40, step=1, value=4,
                )
                merge_distance_slider = gr.Slider(
                    label="Auto-merge proximity (px) — merges sprites whose edges are within this distance (good for sparkles / accessories near a character)",
                    minimum=0, maximum=200, step=1, value=0,
                )
                with gr.Row():
                    do_resize = gr.Checkbox(label="Resize sprites", value=True)
                    target_size = gr.Slider(
                        label="Target size (px)",
                        minimum=32, maximum=512, step=16, value=128,
                    )

            process_btn = gr.Button("Process All Sheets", variant="primary", size="lg")

            # ── Manual merge ── #
            with gr.Group():
                gr.Markdown(
                    "### 4 · Manual Merge  *(after processing)*\n"
                    "Look at the numbered preview, then type the sprite numbers you want joined.\n"
                    "Format: `1+3, 5+7+8` — comma-separated groups, `+` between sprites to merge."
                )
                manual_merge_input = gr.Textbox(
                    label="Merge spec",
                    placeholder="e.g.  3+14+15, 22+23",
                    lines=1,
                )
                apply_merge_btn = gr.Button("Apply Merge", variant="secondary")

        # ── Right column: outputs ─────────────────────────────────────────── #
        with gr.Column(scale=1):

            preview_bg = gr.Radio(
                ["black", "white", "checker"],
                value="black",
                label="Preview background — switch anytime, no reprocessing needed",
                info="Black/white reveal edge artifacts — checkerboard shows transparency",
            )
            out_gallery = gr.Gallery(
                label="Detected Sprites per Sheet",
                columns=2,
                object_fit="contain",
                height="auto",
            )
            out_status = gr.Textbox(label="Status", interactive=False, lines=6)
            out_zip = gr.File(label="Download ZIP (all sprites, sequential numbering)")

    # ── Interactivity ──────────────────────────────────────────────────────── #

    # Populate upload preview gallery as soon as files are dropped
    def show_upload_preview(files):
        if not files:
            return []
        images = []
        for f in files:
            path = f.name if hasattr(f, "name") else str(f)
            try:
                images.append(Image.open(path))
            except Exception:
                pass
        return images

    inp_files.change(show_upload_preview, inputs=inp_files, outputs=inp_preview)

    # Toggle method-specific controls AND auto-adjust edge cleanup defaults
    def toggle_method_controls(method: str):
        is_floodfill = method == "Flood-fill (fast)"
        is_ai        = method == "AI / rembg"
        is_toonout   = method == "ToonOut (recommended) ⭐"
        is_manual_ai = is_ai or is_toonout  # both do full BG removal themselves

        return (
            # show/hide method-specific controls
            gr.update(visible=is_floodfill),   # tolerance_slider
            gr.update(visible=is_ai),           # ai_model_dropdown
            # edge cleanup: defringe is only useful after flood-fill (white BG residue)
            gr.update(value=is_floodfill),      # do_defringe checkbox
            gr.update(visible=is_floodfill),    # defringe_row
            # contract default: -1 for flood-fill (trims white halo), 0 for AI (don't touch clean mask)
            gr.update(value=-1 if is_floodfill else 0),  # refine_expand
        )

    bg_method.change(
        toggle_method_controls,
        inputs=bg_method,
        outputs=[tolerance_slider, ai_model_dropdown, do_defringe, defringe_row, refine_expand],
    )

    # Toggle defringe row visibility (defringe_tuning_row handled below)
    do_defringe.change(
        lambda v: gr.update(visible=v),
        inputs=do_defringe,
        outputs=defringe_row,
    )

    # Defringe preset → update picker, sampler row, sampler image, and sampler_visible state
    def on_defringe_preset(preset: str):
        if preset == "White":
            return (
                gr.update(value="#ffffff", visible=False),
                gr.update(visible=False),
                gr.update(visible=False),
                False,
            )
        elif preset == "Black":
            return (
                gr.update(value="#000000", visible=False),
                gr.update(visible=False),
                gr.update(visible=False),
                False,
            )
        else:  # Custom
            return (
                gr.update(visible=True),
                gr.update(visible=True),
                gr.update(visible=False),  # sampler image stays hidden until button clicked
                False,
            )

    defringe_preset.change(
        on_defringe_preset,
        inputs=defringe_preset,
        outputs=[defringe_picker, defringe_sampler_row, color_sampler_img, sampler_visible],
    )

    # Toggle defringe tuning sliders with main checkbox
    do_defringe.change(
        lambda v: gr.update(visible=v),
        inputs=do_defringe,
        outputs=defringe_tuning_row,
    )

    # "Pick from image" button → toggle the sampler image visibility
    show_sampler_btn.click(
        fn=lambda vis: (gr.update(visible=not vis), not vis),
        inputs=sampler_visible,
        outputs=[color_sampler_img, sampler_visible],
    )

    # Populate sampler image when files are uploaded
    def update_sampler_image(files):
        if not files:
            return None
        path = files[0].name if hasattr(files[0], "name") else str(files[0])
        try:
            return Image.open(path)
        except Exception:
            return None

    inp_files.change(update_sampler_image, inputs=inp_files, outputs=color_sampler_img)

    # Click on sampler image → sample pixel color → update defringe picker
    def sample_color_from_image(img: Image.Image, evt: gr.SelectData):
        if img is None:
            return gr.update(), gr.update()
        x, y = evt.index
        x = max(0, min(x, img.width - 1))
        y = max(0, min(y, img.height - 1))
        r, g, b = img.convert("RGB").getpixel((x, y))
        hex_color = f"#{r:02x}{g:02x}{b:02x}"
        return gr.update(value="Custom"), gr.update(value=hex_color, visible=True)

    color_sampler_img.select(
        fn=sample_color_from_image,
        inputs=color_sampler_img,
        outputs=[defringe_preset, defringe_picker],
    )

    # Preview BG radio → instantly redraw gallery from stored state
    preview_bg.change(
        fn=redraw_previews,
        inputs=[sheet_state, preview_bg],
        outputs=[out_gallery],
    )

    # Process button — resolve defringe color, run pipeline, store state
    def process_with_preset(
        input_files, bg_method, tolerance, ai_model,
        do_defringe, defringe_preset_val, defringe_picker_val,
        defringe_strength_val, defringe_spread_val,
        refine_smooth, refine_expand, refine_feather,
        min_area, padding, merge_distance, do_resize, target_size, preview_bg,
    ):
        if defringe_preset_val == "White":
            hex_color = "#ffffff"
        elif defringe_preset_val == "Black":
            hex_color = "#000000"
        else:
            hex_color = defringe_picker_val

        return process(
            input_files, bg_method, tolerance, ai_model,
            do_defringe, hex_color, defringe_strength_val, defringe_spread_val,
            refine_smooth, refine_expand, refine_feather,
            min_area, padding, merge_distance, do_resize, target_size, preview_bg,
        )

    def apply_merges(sheet_data, merge_spec, do_resize, target_size, preview_bg):
        """Re-apply manual merges to already-processed sheets — no BG removal needed."""
        if not sheet_data:
            return [], "No processed sheets in memory — run Process All Sheets first.", None, sheet_data

        all_sprites: list[Image.Image] = []
        previews: list[Image.Image] = []
        new_sheet_data = []

        for rgba, bboxes in sheet_data:
            new_bboxes = apply_manual_merges(bboxes, merge_spec)
            preview = draw_bboxes(rgba, new_bboxes, bg=preview_bg)
            previews.append(preview)
            resize_val = target_size if do_resize else None
            sprites = cut_sprites(rgba, new_bboxes, target_size=resize_val)
            all_sprites.extend(sprites)
            new_sheet_data.append((rgba, new_bboxes))

        if not all_sprites:
            return previews, "No sprites after merge.", None, new_sheet_data

        zip_bytes = pack_to_zip(all_sprites, start_index=1)
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
        tmp.write(zip_bytes)
        tmp.close()

        size_label = f" → {target_size}×{target_size}px" if do_resize else ""
        return (
            previews,
            f"{len(all_sprites)} sprites after merge{size_label}. ZIP ready.",
            tmp.name,
            new_sheet_data,
        )

    process_btn.click(
        fn=process_with_preset,
        inputs=[
            inp_files,
            bg_method,
            tolerance_slider,
            ai_model_dropdown,
            do_defringe,
            defringe_preset,
            defringe_picker,
            defringe_strength,
            defringe_spread,
            refine_smooth,
            refine_expand,
            refine_feather,
            min_area_slider,
            padding_slider,
            merge_distance_slider,
            do_resize,
            target_size,
            preview_bg,
        ],
        outputs=[out_gallery, out_status, out_zip, sheet_state],
    )

    apply_merge_btn.click(
        fn=apply_merges,
        inputs=[sheet_state, manual_merge_input, do_resize, target_size, preview_bg],
        outputs=[out_gallery, out_status, out_zip, sheet_state],
    )


if __name__ == "__main__":
    demo.launch(inbrowser=True)
