"""CLI read-only prototype: source image -> model -> supplied OCR -> risk decision."""
import argparse
import json
import time
import numpy as np
import torch
from PIL import Image
from common import OUT, load_model, prepare, probabilities, read_json, decision
from risk import risk_decision

def main():
    parser=argparse.ArgumentParser();parser.add_argument('image');parser.add_argument('--ocr-text',required=True)
    parser.add_argument('--weights',default=str(OUT/'final-model.pt'))
    parser.add_argument('--thresholds',default=str(OUT/'thresholds.json'));args=parser.parse_args()
    torch.set_num_threads(6);model=load_model(args.weights);thresholds=read_json(args.thresholds)
    t=time.perf_counter();array=prepare(Image.open(args.image));p=float(probabilities(model,np.array([array]))[0])
    state=decision(p,thresholds)
    print(json.dumps(dict(image=args.image,task='SOURCE_FRACTION_PRESENT',probability=p,state=state,
                    seconds=time.perf_counter()-t,**risk_decision(state,args.ocr_text)),ensure_ascii=False,indent=2))

if __name__=='__main__':main()
