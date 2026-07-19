import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image, ImageDraw

import app


class MethodControlsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.toggle = staticmethod(
            next(
                block_fn.fn
                for block_fn in app.demo.fns.values()
                if getattr(block_fn.fn, "__name__", "") == "toggle_method_controls"
            )
        )
        cls.toggle_defringe = staticmethod(
            next(
                block_fn.fn
                for block_fn in app.demo.fns.values()
                if getattr(block_fn.fn, "__name__", "") == "toggle_defringe_controls"
            )
        )

    def test_switching_method_hides_and_resets_all_defringe_controls(self):
        updates = self.toggle("Lucida")

        self.assertEqual(len(updates), 8)
        self.assertFalse(updates[0]["visible"])
        self.assertFalse(updates[1]["value"])
        self.assertFalse(updates[2]["visible"])
        self.assertFalse(updates[3]["visible"])
        self.assertFalse(updates[4]["visible"])
        self.assertFalse(updates[5]["visible"])
        self.assertIs(updates[6], False)
        self.assertEqual(updates[7]["value"], 0)

    def test_ai_method_shows_model_dropdown(self):
        updates = self.toggle("AI / rembg")
        self.assertTrue(updates[0]["visible"])

    def test_disabling_defringe_hides_custom_sampler_and_resets_state(self):
        updates = self.toggle_defringe(False, "Custom")

        self.assertFalse(updates[0]["visible"])
        self.assertFalse(updates[1]["visible"])
        self.assertFalse(updates[2]["visible"])
        self.assertFalse(updates[3]["visible"])
        self.assertIs(updates[4], False)

    def test_enabling_custom_defringe_shows_sampler_button_but_not_image(self):
        updates = self.toggle_defringe(True, "Custom")

        self.assertTrue(updates[0]["visible"])
        self.assertTrue(updates[1]["visible"])
        self.assertTrue(updates[2]["visible"])
        self.assertFalse(updates[3]["visible"])
        self.assertIs(updates[4], False)

    def test_auto_merge_slider_reaches_400_pixels(self):
        self.assertEqual(app.merge_distance_slider.maximum, 400)

    def test_minimum_size_controls_use_width_and_height(self):
        self.assertEqual(app.min_width_slider.label, "Minimum sprite width (px)")
        self.assertEqual(app.min_height_slider.label, "Minimum sprite height (px)")
        self.assertEqual(app.min_width_slider.maximum, 512)
        self.assertEqual(app.min_height_slider.maximum, 512)

    def test_process_status_lists_detected_crop_dimensions_before_resize(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sheet.png"
            image = Image.new("RGBA", (64, 40), (0, 0, 0, 0))
            draw = ImageDraw.Draw(image)
            draw.rectangle((2, 2, 21, 31), fill=(255, 0, 0, 255))
            draw.rectangle((40, 7, 49, 26), fill=(0, 255, 0, 255))
            image.save(path)

            _, status, zip_path, _ = app.process(
                [str(path)],
                bg_method="Skip (already transparent)",
                ai_model="isnet-anime",
                do_defringe=False,
                defringe_hex="#ffffff",
                defringe_strength=1.0,
                defringe_spread=0,
                refine_smooth=0,
                refine_expand=0,
                refine_feather=0.0,
                min_width=1,
                min_height=1,
                padding=0,
                merge_distance=0,
                do_resize=True,
                target_size=32,
                preview_bg="black",
            )

            if zip_path is not None:
                Path(zip_path).unlink()

        self.assertIn(
            "Detected crop sizes before resize (W×H px): #1 20×30, #2 10×20",
            status,
        )


if __name__ == "__main__":
    unittest.main()
