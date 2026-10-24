"""Small visual fraction detector, independent from the production OCR application."""
import json
from pathlib import Path
import numpy as np
from PIL import Image
import torch
from torch import nn

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'local-artifacts/product-p21c-fraction-learning-20261020'
CFG_PATH = Path(__file__).with_name('config.json')

def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))

def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')

class FractionCNN(nn.Module):
    def __init__(self):
        super().__init__()
        layers = []
        channels = [1, 8, 16, 32, 64]
        for a, b in zip(channels, channels[1:]):
            layers += [nn.Conv2d(a, b, 3, stride=2, padding=1), nn.ReLU()]
        self.features = nn.Sequential(*layers)
        self.classifier = nn.Sequential(nn.Linear(128, 32), nn.ReLU(), nn.Linear(32, 1))

    def forward(self, x):
        x = self.features(x)
        x = torch.cat([x.amax(dim=(2, 3)), x.mean(dim=(2, 3))], 1)
        return self.classifier(x).squeeze(1)

def prepare(image, height=48, width=384):
    image = image.convert('L')
    scale = min(height / image.height, width / image.width)
    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    resized = image.resize(size, Image.Resampling.BILINEAR)
    canvas = Image.new('L', (width, height), 255)
    canvas.paste(resized, ((width - size[0]) // 2, (height - size[1]) // 2))
    return np.asarray(canvas, dtype=np.uint8).copy()

def tensor(array):
    return (255.0 - torch.as_tensor(array).float()).unsqueeze(1) / 255.0

def load_model(path):
    model = FractionCNN()
    state = torch.load(path, map_location='cpu', weights_only=True)
    model.load_state_dict(state['model_state'])
    model.eval()
    return model

@torch.inference_mode()
def probabilities(model, array, batch_size=96):
    return np.concatenate([torch.sigmoid(model(tensor(array[i:i+batch_size]))).numpy()
                           for i in range(0, len(array), batch_size)])

def binary_metrics(y, p, threshold):
    y, pred = np.asarray(y).astype(bool), np.asarray(p) >= threshold
    tp, fp = int((y & pred).sum()), int((~y & pred).sum())
    tn, fn = int((~y & ~pred).sum()), int((y & ~pred).sum())
    precision, recall = tp / max(1, tp+fp), tp / max(1, tp+fn)
    return dict(n=len(y), tp=tp, fp=fp, tn=tn, fn=fn, precision=precision, recall=recall,
                f1=2*precision*recall/max(1e-12, precision+recall))

def decision(p, thresholds):
    if p >= thresholds['positive_cutoff']:
        return 'FRACTION_PRESENT'
    if p < thresholds['negative_cutoff']:
        return 'FRACTION_ABSENT'
    return 'ABSTAIN'
