"""Small source-coordinate overlays. This display never enters the locator or OCR."""
import argparse
from PIL import Image,ImageDraw,ImageFont
from common import *
def main():
    p=argparse.ArgumentParser();p.add_argument('--stage',required=True);a=p.parse_args();folder=OUT/a.stage
    objects=read(folder/'regions.json')['objects'];pred=read(folder/'readings.json')
    can=Image.new('RGB',(1700,200*len(objects)),(245,245,245));d=ImageDraw.Draw(can);font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',17)
    for i,o in enumerate(objects):
        im=Image.open(abs_path(o['parent']['source_image'])).convert('RGB').crop(o['parent']['parent_box']);scale=min(4,810/im.width,125/im.height)
        display=im.resize((round(im.width*scale),round(im.height*scale)),Image.Resampling.NEAREST);y=i*200
        d.text((10,y+3),o['source_object_id']+' | original detector parent / automatic proposals',fill='black',font=font)
        can.paste(display,(10,y+35));can.paste(display,(860,y+35))
        for r in o['geometry']['regions']:
            b=r['parent_box'];color={'whole':'#167ac6','numerator':'#d1242f','denominator':'#12813b'}[r['role']]
            box=[860+b[0]*scale,y+35+b[1]*scale,860+b[2]*scale,y+35+b[3]*scale];d.rectangle(box,outline=color,width=2)
            d.text((box[0],max(y+18,box[1]-17)),r['id']+':'+r['role'][0],fill=color,font=font)
        for r in o['geometry']['relations']:
            if r.get('separator_parent_box'):
                b=r['separator_parent_box'];d.rectangle([860+b[0]*scale,y+35+b[1]*scale,860+b[2]*scale,y+35+b[3]*scale],outline='#9a6700',width=2)
        raw=[r['region_id']+'='+repr(r.get('reader_raw')) for r in pred if r['source_object_id']==o['source_object_id']]
        d.text((10,y+168),' | '.join(raw)[:200],fill='black',font=font)
    path=folder/'evidence.png';can.save(path);print(str(path))
if __name__=='__main__':main()
