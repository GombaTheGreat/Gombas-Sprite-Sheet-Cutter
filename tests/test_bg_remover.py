import unittest
from unittest.mock import patch

from PIL import Image

import bg_remover


class LucidaTests(unittest.TestCase):
    def test_remove_bg_lucida_uses_shared_birefnet_inference(self):
        image = Image.new("RGB", (2, 2), "white")
        expected = Image.new("RGBA", (2, 2), (1, 2, 3, 4))
        model = object()

        with (
            patch.object(bg_remover, "_load_lucida", return_value=(model, "cpu")) as load,
            patch.object(bg_remover, "_run_birefnet", return_value=expected) as run,
        ):
            result = bg_remover.remove_bg_lucida(image)

        self.assertIs(result, expected)
        load.assert_called_once_with()
        run.assert_called_once_with(image, model, "cpu")


if __name__ == "__main__":
    unittest.main()
