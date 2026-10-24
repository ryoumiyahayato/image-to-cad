"""Seven original geometry checks; no fitting or real data."""
from PIL import Image,ImageDraw,ImageFont
from common import *

def main():
    folder=OUT/'synthetic';folder.mkdir(exist_ok=False)
    fontpath=ROOT/'local-artifacts/product-p21c-fraction-learning-20261020/fonts/barlow/Barlow-Regular.ttf'
    big=ImageFont.truetype(str(fontpath),32);small=ImageFont.truetype(str(fontpath),20)
    records=[]
    for i,kind in enumerate(['integer','fraction','mixed','independent-neighbor','engineering-line','joined-separator','incomplete']):
        im=Image.new('RGB',(180,55),'white');d=ImageDraw.Draw(im);roles=[]
        def text(value,xy,font,role,group='target'):
            d.text(xy,value,font=font,fill='black',anchor='lt');b=d.textbbox(xy,value,font=font,anchor='lt')
            roles.append(dict(role=role,label=value,source_box=list(b),visibility='COMPLETE_VISIBLE',group=group))
        if kind=='integer':text('27',(12,14),big,'whole')
        elif kind=='engineering-line':
            text('24',(12,14),big,'whole');d.line((100,47,125,13),fill='black',width=2);d.line((88,49,164,49),fill='black',width=1)
        else:
            x=35 if kind!='independent-neighbor' else 100
            text('3',(x,7),small,'numerator');text('7',(x+33,33),small,'denominator')
            d.line((x+12,48,x+29,12),fill='black',width=2)
            if kind=='mixed':text('2',(12,20),big,'whole')
            if kind=='independent-neighbor':text('9',(12,14),big,'whole','independent')
            if kind=='joined-separator':d.line((x+9,20,x+25,20),fill='black',width=2);roles[0]['label']=None;roles[0]['visibility']='JOINED_SEPARATOR_UNCERTAIN'
            if kind=='incomplete':
                im=im.crop((0,0,180,44));roles[1]['label']=None;roles[1]['visibility']='TRUNCATED';roles[1]['source_box'][3]=44
        path=folder/(kind+'.png');im.save(path)
        records.append(dict(source_object_id='example-'+str(i),partition='SYNTHETIC',kind=kind,
            source_image=rel(path),parent_box=[0,0,im.width,im.height],parent_to_source=[1,0,0,0,1,0],
            parent_provenance='SYNTHETIC_DIAGNOSTIC',roles=roles))
    write(folder/'examples.json',records)
    (folder/'Barlow-OFL.txt').write_text(fontpath.with_name('OFL.txt').read_text('utf-8'),encoding='utf-8')
    print('ORIGINAL_EXAMPLES',len(records))
if __name__=='__main__':main()
