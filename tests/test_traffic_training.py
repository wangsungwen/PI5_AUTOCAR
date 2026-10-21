import tempfile
import unittest
from pathlib import Path
from PIL import Image
from training.train_traffic import check_dataset


class TrafficDatasetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.yaml = self.root / 'data.yaml'
        self.yaml.write_text('path: .\ntrain: images/train\nval: images/val\nnames: [red_light, yellow_light, green_light]\n')
        for split, offset in [('train', 0), ('val', 50)]:
            (self.root / 'images' / split).mkdir(parents=True)
            (self.root / 'labels' / split).mkdir(parents=True)
            for cls in range(3):
                Image.new('RGB', (20, 20), (offset+cls, 100, 200)).save(self.root / 'images' / split / f'{cls}.png')
                (self.root / 'labels' / split / f'{cls}.txt').write_text(f'{cls} 0.5 0.5 0.2 0.2\n')

    def test_resolves_paths_and_counts(self):
        resolved, stats = check_dataset(self.yaml)
        self.assertEqual(resolved['train'], str(self.root / 'images/train'))
        self.assertEqual(stats['val']['boxes']['green_light'], 1)

    def test_rejects_missing_label(self):
        (self.root / 'labels/train/0.txt').unlink()
        with self.assertRaisesRegex(ValueError, 'Missing label'):
            check_dataset(self.yaml)

    def test_rejects_invalid_boxes(self):
        label = self.root / 'labels/train/0.txt'
        for line in ['0 nan .5 .2 .2', '0 .99 .5 .4 .2', '3 .5 .5 .2 .2', '0 .5 .5 0 .2', '0 .5 .5']:
            with self.subTest(line=line):
                label.write_text(line)
                with self.assertRaisesRegex(ValueError, 'Invalid YOLO box'):
                    check_dataset(self.yaml)

    def test_rejects_data_leakage(self):
        (self.root / 'images/val/0.png').write_bytes((self.root / 'images/train/0.png').read_bytes())
        with self.assertRaisesRegex(ValueError, 'Duplicate image'):
            check_dataset(self.yaml)

    def test_background_requires_empty_label(self):
        Image.new('RGB', (21, 20)).save(self.root / 'images/train/bg.png')
        (self.root / 'labels/train/bg.txt').write_text('')
        _, stats = check_dataset(self.yaml)
        self.assertEqual(stats['train']['backgrounds'], 1)

    def test_rejects_missing_class(self):
        (self.root / 'labels/train/0.txt').write_text('')
        with self.assertRaisesRegex(ValueError, 'every declared class'):
            check_dataset(self.yaml)


if __name__ == '__main__':
    unittest.main()
