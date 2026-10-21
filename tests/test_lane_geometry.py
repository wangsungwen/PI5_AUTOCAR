import unittest
import importlib.util
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
from autocar.perception import YoloLaneDetector


@unittest.skipUnless(importlib.util.find_spec("cv2"), "Install requirements-autonomy.txt for geometry tests")
class LaneGeometryTests(unittest.TestCase):
    def test_original_image_polygons_respect_lower_roi(self):
        detector = YoloLaneDetector.__new__(YoloLaneDetector)
        detector.image_size, detector.confidence = 416, .3
        detector.roi_start, detector.class_name = .55, 'road'
        result = SimpleNamespace(
            boxes=[SimpleNamespace(cls=[0], conf=[.9])],
            masks=SimpleNamespace(xy=[np.array([[400, 250], [600, 250],
                                               [600, 359], [400, 359]])]))
        detector.model = Mock(names={0: 'road'})
        detector.model.predict.return_value = [result]
        observation = detector.detect(np.zeros((360, 640, 3), dtype=np.uint8))
        self.assertEqual(observation.lane_center, 500)
        self.assertEqual(observation.error, 180)
        self.assertAlmostEqual(observation.confidence, .9)

    def test_wrong_class_is_an_error_not_clear_road(self):
        detector = YoloLaneDetector.__new__(YoloLaneDetector)
        detector.image_size, detector.confidence = 416, .3
        detector.roi_start, detector.class_name = .55, 'lane'
        detector.model = Mock(names={0: 'road'})
        detector.model.predict.return_value = [SimpleNamespace(masks=None)]
        with self.assertRaisesRegex(ValueError, 'absent'):
            detector.detect(np.zeros((360, 640, 3), dtype=np.uint8))


if __name__ == '__main__':
    unittest.main()
