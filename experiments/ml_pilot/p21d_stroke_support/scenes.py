"""Original object-identified scenes. Counterfactual rendering removes invisible labels."""
import argparse
import functools
import math
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw,ImageFilter,ImageFont
from common import HERE,config,write

@functools.lru_cache(maxsize=64)
def font(size):return ImageFont.truetype(str(HERE/'assets/Barlow-Regular.ttf'),size)
def scene_ids(split,cfg=None):
    c=cfg or config();n=c[f'{split}_scenes_per_family']
    return [(family,i) for family in c[f'{split}_families'] for i in range(n)]

def make_scene(family,index,augmentation=0):
    size=576;seed=21042026+family*100003+index*101
    g=np.random.default_rng(seed);a=np.random.default_rng(seed+augmentation*10000019+7)
    dark=bool(a.random()<.30);base=int(a.integers(25,70) if dark else a.integers(195,246))
    background=Image.new('RGB',(size,size),(base,)*3);bd=ImageDraw.Draw(background)
    # Material areas and edges are never stroke labels. They coexist with both polarities.
    gray=int(a.integers(95,165));bd.rectangle((50,170,315,290),fill=(gray,gray,int(np.clip(gray+a.integers(-12,12),0,255))))
    bd.rectangle((340,170,530,285),fill=(35,45,60))
    image=background.copy();ids=Image.new('I',(size,size),0);objects=[];gaps=[];pairs=[]
    alpha=np.zeros((size,size),dtype=np.float32)
    def ink_at(points,light=False):
        x,y=map(int,points[0]);b=np.array(background.getpixel((x,y)))
        light=light or float(b.mean())<105
        v=int(a.integers(205,250) if light else a.integers(0,40))
        return (v,v,v) if a.random()<.75 else ((v,v,min(255,v+20)) if light else (v,v,int(a.integers(35,80))))
    def stroke(points,width=1,kind='line',light=False):
        nonlocal alpha
        oid=len(objects)+1;points=[(int(x),int(y)) for x,y in points]
        mask=Image.new('L',(size,size));md=ImageDraw.Draw(mask);md.line(points,fill=255,width=width)
        image.paste(ink_at(points,light),mask=mask);ImageDraw.Draw(ids).line(points,fill=oid,width=width)
        alpha=np.maximum(alpha,np.asarray(mask)/255.)
        objects.append(dict(id=oid,kind=kind,points=points,width=width))
    shift=int(g.integers(-8,9));w=int(a.integers(1,4))
    # Complete group with a real opening. No hidden segment object is drawn across it.
    yy=70+shift;gap_left=int(g.integers(130,170));gap_right=gap_left+int(g.integers(24,42))
    stroke([(60,yy),(gap_left,yy)],w,'opening_left');stroke([(gap_right,yy),(275,yy)],w,'opening_right')
    stroke([(60,yy),(60,145),(275,145),(275,yy)],w,'boundary_group')
    gaps.append([gap_left+3,yy-4,gap_right-2,yy+5])
    # Parallel lines: finite width gap, natural ends, no desired fill between them.
    x=365+shift;distance=int(g.integers(7,15));stroke([(x,55),(x,145)],1,'parallel_a')
    stroke([(x+distance,55),(x+distance,145)],1,'parallel_b')
    pairs.append([x+2,60,x+distance-1,140])
    for k in range(3):
        y=195+k*25+shift;stroke([(75,y),(295,y+int(g.integers(-10,11)))],int(a.integers(1,3)),'gray_area_line')
        stroke([(355,y),(510,y+int(g.integers(-8,9)))],int(a.integers(1,3)),'dark_area_line',True)
    # Intersections, short fragments and curved support, all object identified.
    stroke([(65,340),(285,405)],w,'diagonal');stroke([(80,405),(265,335)],1,'crossing')
    for k in range(5):
        x0=int(g.integers(320,505));y0=int(g.integers(325,405));stroke([(x0,y0),(x0+int(g.integers(8,30)),y0+int(g.integers(-8,9)))],1,'short_segment')
    points=[(430+int(56*math.cos(t)),470+int(33*math.sin(t))) for t in np.linspace(.12,5.9,80)]
    stroke(points,1,'curve')
    stroke([(65,468),(275,468)],1,'dimension_leader');stroke([(65,468),(75,463),(75,473),(65,468)],1,'arrow')
    stroke([(275,468),(265,463),(265,473),(275,468)],1,'arrow')
    # Licensed font rendering is stroke support, not an OCR label.
    for k,text in enumerate(['4 x 6  TYP.', '1/4 IN.  #4']):
        mask=Image.new('L',(size,size));ImageDraw.Draw(mask).text((88,487+k*25),text,font=font(int(a.integers(13,20))),fill=255)
        image.paste((235,235,235) if dark else (15,20,30),mask=mask)
        ma=np.asarray(mask)/255.;alpha=np.maximum(alpha,ma)
        ia=np.asarray(ids).copy();ia[ma>.2]=len(objects)+1;ids=Image.fromarray(ia.astype(np.int32))
        objects.append(dict(id=len(objects)+1,kind='text',points=[],width=None))
    # Same fold/noise/occlusion applied to observed image and no-stroke counterfactual.
    damage=Image.new('L',(size,size));dd=ImageDraw.Draw(damage)
    ox=int(g.integers(125,220));oy=int(g.integers(325,390))
    dd.polygon([(ox,oy),(ox+30,oy-8),(ox+42,oy+24),(ox+6,oy+31)],fill=255)
    paper=(225,225,220) if not dark else (50,50,45)
    for im in [image,background]:
        im.paste(paper,mask=damage);draw=ImageDraw.Draw(im)
        # Fold is an unlabelled nuisance boundary, not a reconstructed engineering stroke.
        draw.line([(28,300),(548,310)],fill=(max(0,base-15),)*3,width=3)
    for _ in range(24):
        xx,yy=map(int,a.integers(35,541,2));v=int(a.integers(0,255))
        for im in [image,background]:ImageDraw.Draw(im).ellipse((xx,yy,xx+1,yy+1),fill=(v,)*3)
    blur=float(a.choice([0.,0.,.35,.55]));image=image.filter(ImageFilter.GaussianBlur(blur));background=background.filter(ImageFilter.GaussianBlur(blur))
    obs=np.asarray(image).astype(np.float32);counter=np.asarray(background).astype(np.float32)
    contrast=np.max(np.abs(obs-counter),axis=2)/255.
    target=((alpha>=.2)&(contrast>=.035)).astype(np.uint8)
    ignore=((alpha>.01)&(contrast>.008)&((alpha<.2)|(contrast<.035)))
    dm=np.asarray(damage)>0;boundary=np.asarray(damage.filter(ImageFilter.MaxFilter(5)))!=np.asarray(damage.filter(ImageFilter.MinFilter(5)))
    ignore|=boundary;target[dm]=0
    noise=a.normal(0,float(a.uniform(0,4)),obs.shape[:2])[:,:,None]
    obs=np.clip(obs+noise,0,255).astype(np.uint8)
    valid=np.zeros((size,size),bool);valid[32:544,32:544]=True;ignore|=~valid
    oid=np.asarray(ids).copy();oid[target==0]=0
    # Random placement/orientation shared by all object and nuisance classes.
    # Integer transforms preserve one-pixel strokes; coordinates follow the same map.
    turns=int(a.integers(0,4));flip=bool(a.integers(0,2));dx,dy=map(int,a.integers(-24,25,2))
    def point(p):
        x,y=p
        for _ in range(turns):x,y=y,size-1-x
        if flip:x=size-1-x
        return int(x+dx),int(y+dy)
    def transform(arr,fill):
        arr=np.rot90(arr,turns)
        if flip:arr=np.fliplr(arr)
        result=np.full_like(arr,fill)
        sx0,sy0=max(0,-dx),max(0,-dy);sx1,sy1=min(size,size-dx),min(size,size-dy)
        result[sy0+dy:sy1+dy,sx0+dx:sx1+dx]=arr[sy0:sy1,sx0:sx1]
        return result
    obs=transform(obs,base);target=transform(target,0);ignore=transform(ignore.astype(np.uint8),1);oid=transform(oid,0)
    ignore[:32]=1;ignore[544:]=1;ignore[:,:32]=1;ignore[:,544:]=1
    for obj in objects:obj['points']=[point(p) for p in obj['points']]
    def region(box):
        ps=[point((x,y)) for x,y in [(box[0],box[1]),(box[2],box[3])]]
        return dict(box=[min(p[0] for p in ps),min(p[1] for p in ps),max(p[0] for p in ps),max(p[1] for p in ps)],axis=turns%2)
    gaps=[region(b) for b in gaps];pairs=[region(b) for b in pairs]
    return obs,target,ignore.astype(np.uint8),dict(family=family,scene=index,augmentation=augmentation,
        seed=seed,objects=objects,openings=gaps,parallel_gaps=pairs,object_ids=oid,
        integer_transform=dict(turns_ccw=turns,flip=flip,translation=[dx,dy]),
        source_type='ORIGINAL_PROGRAMMATIC_VECTOR_RENDER',fully_occluded_positive_pixels=int(((alpha>.2)&dm).sum()),
        features=['opening','parallel','gray','dark','text','damage','short','curve','leader','fold','material'])

def preview(out):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    sheet=Image.new('RGB',(576*3,608*6),'white');d=ImageDraw.Draw(sheet);records=[]
    for k in range(6):
        image,target,ignore,meta=make_scene(k,k,0)
        for j,arr in enumerate([image,np.repeat((target*255)[:,:,None],3,2),np.repeat((ignore*255)[:,:,None],3,2)]):
            sheet.paste(Image.fromarray(arr.astype(np.uint8)),(j*576,k*608+30))
        d.text((5,k*608+4),f'scene{k} IMAGE / visible LABEL / IGNORE; opening parallel gray dark text damage',fill='black')
        Image.fromarray(image).save(out/f'scene{k}-image.png');Image.fromarray(target*255).save(out/f'scene{k}-label.png')
        Image.fromarray(ignore*255).save(out/f'scene{k}-ignore.png')
        meta.pop('object_ids');records.append(meta)
    sheet.save(out/'triplets.png');write(out/'preview-scenes.json',records)
    print('PREVIEW_READY',str(out/'triplets.png'),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--preview',required=True);preview(p.parse_args().preview)
