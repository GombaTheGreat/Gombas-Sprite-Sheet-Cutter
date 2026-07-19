import unittest

from PIL import Image, ImageDraw

from sprite_detector import detect_sprites, merge_nearby_bboxes


class DetectSpritesTests(unittest.TestCase):
    def test_component_must_meet_minimum_width_and_height(self):
        image = Image.new("RGBA", (140, 90), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, 28, 31), fill=(255, 0, 0, 255))
        draw.rectangle((70, 0, 139, 69), fill=(0, 255, 0, 255))

        self.assertEqual(
            detect_sprites(image, min_width=70, min_height=70, padding=0),
            [(70, 0, 140, 70)],
        )


class MergeNearbyBboxesTests(unittest.TestCase):
    def test_adjacent_full_sprites_do_not_merge_from_small_edge_gap(self):
        boxes = [(0, 0, 100, 100), (105, 0, 205, 100)]
        self.assertEqual(merge_nearby_bboxes(boxes, 20), boxes)

    def test_nearby_centers_merge(self):
        boxes = [(0, 0, 20, 20), (40, 0, 60, 20)]
        self.assertEqual(merge_nearby_bboxes(boxes, 40), [(0, 0, 60, 20)])

    def test_diagonal_distance_is_euclidean(self):
        boxes = [(0, 0, 20, 20), (30, 40, 50, 60)]
        self.assertEqual(merge_nearby_bboxes(boxes, 49), boxes)
        self.assertEqual(merge_nearby_bboxes(boxes, 50), [(0, 0, 50, 60)])

    def test_transitive_center_groups_still_merge(self):
        boxes = [(0, 0, 20, 20), (30, 0, 50, 20), (60, 0, 80, 20)]
        self.assertEqual(merge_nearby_bboxes(boxes, 30), [(0, 0, 80, 20)])

    def test_zero_distance_leaves_boxes_unchanged(self):
        boxes = [(0, 0, 20, 20), (10, 0, 30, 20)]
        self.assertEqual(merge_nearby_bboxes(boxes, 0), boxes)


if __name__ == "__main__":
    unittest.main()
