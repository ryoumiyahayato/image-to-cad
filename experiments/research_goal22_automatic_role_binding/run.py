"""Freeze pixel-only regions first; then read them once. No labels or candidates loaded."""
import argparse,time,shutil
from PIL import Image
import numpy as np
from common import *
import locator

def main():
    p=argparse.ArgumentParser();p.add_argument('--split',choices=['A','B','SYNTHETIC'],required=True);args=p.parse_args()
    start=time.perf_counter()
    if args.split=='B':
        frozen=read(OUT/'B-freeze.json');assert frozen['A_minimum_conditions_met']
        for name in frozen['source_files']:
            assert (HERE/name).read_bytes()==(OUT/'frozen-for-B'/name).read_bytes(),'post-freeze source change'
    group='synthetic' if args.split=='SYNTHETIC' else 'real-local'
    folder=OUT/group/(args.split+'-'+locator.VERSION);folder.mkdir(exist_ok=False)
    inputs=read(OUT/'synthetic/examples.json') if args.split=='SYNTHETIC' else [r for r in read(OUT/'real-local/input-manifest.json') if r['partition']==args.split]
    # Only the listed keys reach locate; example labels and all identities stay outside it.
    output=[];parents=[];location_seconds=0.
    for item in inputs:
        pixels=np.array(Image.open(abs_path(item['source_image'])).convert('RGB').crop(item['parent_box']))
        t=time.perf_counter();located=locator.locate(pixels,item['parent_to_source'],'PAGE_AXIS');location_seconds+=time.perf_counter()-t
        output.append(dict(source_object_id=item['source_object_id'],parent=item,geometry=located));parents.append(pixels)
    # Exclude synthetic truth from runtime output even though generated example metadata carries it.
    for item in output:item['parent']={k:v for k,v in item['parent'].items() if k!='roles'}
    write(folder/'regions.json',dict(utc=utc(),phase='REGIONS_FROZEN_BEFORE_REC_AND_CANDIDATES',objects=output))
    crops_index=read(OUT/'real-local/crop-index.json') if (OUT/'real-local/crop-index.json').exists() else []
    from fixed_ocr import FixedOCR
    ocr=FixedOCR();readings=[]
    for item,pixels in zip(output,parents):
        for region in sorted(item['geometry']['regions'],key=lambda r:(r['parent_box'][0],r['parent_box'][1],r['id'])):
            record=dict(source_object_id=item['source_object_id'],region_id=region['id'],state=region['state'])
            if region['state']!='USABLE':record.update(status='NOT_READ_UNCERTAIN',reader_raw=None)
            else:
                x0,y0,x1,y1=region['parent_box'];crop=pixels[y0:y1,x0:x1]
                old=next((c for c in crops_index if c['source_image']==item['parent']['source_image'] and c['source_box']==region['source_box']),None)
                if old is None:
                    path=OUT/group/'crops'/('region-'+str(len(crops_index)).zfill(3)+'.png');path.parent.mkdir(parents=True,exist_ok=True);Image.fromarray(crop).save(path)
                    old=dict(source_image=item['parent']['source_image'],source_box=region['source_box'],crop=rel(path));crops_index.append(old)
                record.update(crop=old['crop'],**ocr.read_pixels(crop,group))
            readings.append(record)
    write(OUT/'real-local/crop-index.json',crops_index);write(folder/'readings.json',readings)
    write(folder/'runtime.json',dict(utc=utc(),version=locator.VERSION,split=args.split,locator_seconds=location_seconds,
        ocr_init_seconds=ocr.init_seconds,ocr_new_calls=len(ocr.new),ocr_cache_hits=ocr.cache_hits,ocr_forward_seconds=ocr.forward_seconds,
        total_goal22_new_rec_calls=len(ocr.records),operation_seconds=time.perf_counter()-start,training_updates=0,new_detector_calls=0,
        candidate_input_to_locator=False,manual_role_input_to_locator=False))
    print('STAGE_COMPLETE',args.split,locator.VERSION,'regions',sum(len(o['geometry']['regions']) for o in output),'REC_NEW',len(ocr.new),'CACHE',ocr.cache_hits,flush=True)
if __name__=='__main__':main()
