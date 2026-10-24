import argparse
import json
from pathlib import Path
import numpy as np
from PIL import Image
from audit_saved import OUT,read,write
from mechanism import generate,CONFIG

def main():
    p=argparse.ArgumentParser();p.add_argument('--manifest',default=str(OUT/'input-rois.json'));p.add_argument('--output',default=str(OUT/'v1'));args=p.parse_args()
    dest=Path(args.output);dest.mkdir(exist_ok=False);manifest=read(Path(args.manifest));write(dest/'config.json',CONFIG)
    for row in manifest['rois']:
        rgb=np.array(Image.open(row['source']).convert('RGB'));stable=np.array(Image.open(row['stable']))==0
        for use_model in [False,True]:
            mode='with_model' if use_model else 'without_model';out=dest/row['key']/mode;out.mkdir(parents=True)
            # Ablation branch never opens model scores or model proposals.
            score=np.load(row['scores']) if use_model else None;result=generate(rgb,stable,score)
            for obj in result['adopted']:
                obj['source_id']=row['source_id'];obj['design']=row['design'];obj['source_roi']=row['box'];obj['source_image']=row['source']
                obj['points_source']=(np.array(obj['points'])+np.array(row['box'][:2])).tolist()
                obj['width_unit']='original source pixel';obj['stage']='DIAGNOSTIC_ONLY/STAGE_ONLY'
            Image.fromarray(result['mask'].astype(np.uint8)*255).save(out/'adopted-mask.png');np.save(out/'owner.npy',result['owner'],allow_pickle=False)
            Image.fromarray(result['field'].astype(np.uint8)*255).save(out/'field-evidence.png')
            write(out/'candidates.json',dict(stage='DIAGNOSTIC_ONLY/STAGE_ONLY',source=row,adopted=result['adopted'],proposals=result['proposals'],relations=result['relations'],field_evidence=result['field_records'],summary=result['summary']))
            print(row['key'],mode,result['summary'],flush=True)
if __name__=='__main__':main()
