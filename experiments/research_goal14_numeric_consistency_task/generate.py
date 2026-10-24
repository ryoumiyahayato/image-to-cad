"""Original small paired data. No real images, OCR, weights, or training imports."""
import argparse
import copy
import json
import random
import time
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
from fontTools.ttLib import TTFont
from task import ROOT, OUT, ROLES, PAIR_SCHEMA, parts, label, read, write, reused_primitives

font, text_image = reused_primitives()
SIZE = (512, 128)

def spec(kind, whole=None, n=None, d=None, unit='inch', context=None, sign=None, glyph=None):
    return dict(kind=kind, whole=whole, numerator=n, denominator=d, unit=unit, context=context, sign=sign, glyph=glyph)

def spelling(s):
    k=s['kind']; a=s.get('sign') or ''
    if s.get('glyph'): a += (s['whole'] or '') + s['glyph']
    elif k in ('integer','decimal'): a += s['whole']
    else: a += ((s['whole']+' ') if k=='mixed' else '') + s['numerator']+'/'+s['denominator']
    a += {'inch':'"','mm':' mm',None:''}[s['unit']]
    if s['context']: a += ' '+s['context']
    return a

def families():
    f=lambda n,d,**kw: spec('fraction',n=n,d=d,**kw)
    m=lambda w,n,d,**kw: spec('mixed',whole=w,n=n,d=d,**kw)
    i=lambda w,**kw: spec('integer',whole=w,**kw)
    return [
        ('separator14',i('14'),f('1','4')),
        ('separator18',i('18'),f('1','8')),
        ('mixed_whole',m('1','1','2'),f('1','2')),
        ('mixed_boundary',m('1','1','2'),f('11','2')),
        ('denominator',m('1','3','16',context='DIA. HOLE'),m('1','3','6',context='DIA. HOLE')),
        ('unit',f('1','2'),f('1','2',unit='mm')),
        ('context',m('1','3','16',context='DIA. HOLE'),m('1','3','16')),
        ('decimal',spec('decimal',whole='1.4'),i('14')),
        ('sign',i('14',sign='-'),i('14')),
        ('numeric_equivalence',f('1','2'),spec('decimal',whole='0.5')),
        ('unicode',m('1','1','2',glyph='½'),f('11','2')),
    ]

def bbox(mask):
    yy,xx=np.where(mask>32)
    return [int(xx.min()),int(yy.min()),int(xx.max()+1),int(yy.max()+1)] if len(xx) else None

def render(s, path, layout, background=0, shift=(0,0)):
    """Shared pixel/role translation, based on P21-D's integer-transform principle."""
    paper = 255 if background==0 else 239
    bg=Image.new('L',SIZE,paper); bd=ImageDraw.Draw(bg)
    # Original leader/frame are identical across both values in a contrast family.
    bd.line((18,103,491,103),fill=170,width=1)
    bd.line((18,99,18,107),fill=170,width=1); bd.line((491,99,491,107),fill=170,width=1)
    if background: bd.line((18,20,18,90),fill=200,width=1)
    layers=[]; glyphs=[]; x=44; y=36
    def add(text, roles, xx, yy, size=36):
        ff=font(str(path),size); start=xx
        for char in text:
            if not char.isspace():
                tile=text_image(char,ff); box=ff.getbbox(char)
                mask=Image.new('L',SIZE)
                # P21-C helper tightly crops glyph; restore font baseline placement.
                mask.paste(Image.eval(tile,lambda p:255-p),(round(xx+box[0]-1+shift[0]),round(yy+box[1]-1+shift[1])))
                layers.append(np.asarray(mask).copy())
                glyphs.append(dict(char=char,roles=list(roles),bbox=bbox(layers[-1])))
            xx += ff.getlength(char)
        return xx-start
    if s.get('sign'): x+=add(s['sign'],['sign'],x,y)
    if s.get('whole'):
        for char in s['whole']:
            rr=['whole','decimal_point'] if char=='.' else ['whole']
            x+=add(char,rr,x,y)
        if s['kind']=='mixed': x+=11
    if s.get('glyph'):
        x+=add(s['glyph'],['numerator','denominator','relation'],x,y)
    elif s.get('numerator'):
        if layout=='inline':
            x+=add(s['numerator'],['numerator'],x,y)
            x+=add('/',['relation'],x,y)
            x+=add(s['denominator'],['denominator'],x,y)
        elif layout=='stacked':
            n,d=s['numerator'],s['denominator'];ff=font(str(path),23)
            w=max(ff.getlength(n),ff.getlength(d))+7
            add(n,['numerator'],x+(w-ff.getlength(n))/2,19,23)
            ma=Image.new('L',SIZE);ImageDraw.Draw(ma).line((round(x+shift[0]),54+shift[1],round(x+w+shift[0]),54+shift[1]),fill=255,width=2)
            layers.append(np.asarray(ma));glyphs.append(dict(char='FRACTION_BAR',roles=['relation'],bbox=bbox(layers[-1])))
            add(d,['denominator'],x+(w-ff.getlength(d))/2,55,23);x+=w+3
        else:
            x+=add(s['numerator'],['numerator'],x,26,24)
            x+=add('/',['relation'],x-2,34,36)-2
            x+=add(s['denominator'],['denominator'],x,51,24)
    if s.get('unit'): x+=add('"' if s['unit']=='inch' else ' mm',['unit'],x+3,y)
    if s.get('context'): x+=add(' '+s['context'],['context'],x+4,y+7,25)
    assert x<490, ('overflow',s,x)
    masks=np.stack(layers); image=np.asarray(bg).copy()
    for mask in masks: image=np.minimum(image,255-mask)
    return image,masks,glyphs,np.asarray(bg).copy()

def main(out):
    started=time.perf_counter();out=Path(out)
    if (out/'pairs.json').exists(): raise RuntimeError('Use a fresh output directory; preserve prior samples.')
    (out/'images').mkdir(parents=True,exist_ok=True);(out/'annotations').mkdir(exist_ok=True)
    ff=ROOT/'local-artifacts/product-p21c-fraction-learning-20261020/fonts'
    fonts=[('barlow',ff/'barlow/Barlow-Regular.ttf','inline'),
           ('ibmplexmono',ff/'ibmplexmono/IBMPlexMono-Regular.ttf','stacked'),
           ('sourceserif4',ff/'sourceserif4/SourceSerif4[opsz,wght].ttf','raised')]
    licenses=[]
    chars=set('0123456789/". -+mmDIAHOLE½')
    for name,p,layout in fonts:
        tt=TTFont(p);cmap=tt.getBestCmap();missing=[c for c in chars if ord(c) not in cmap];tt.close()
        assert not missing,(name,missing)
        license_path=p.parent/'OFL.txt';assert 'SIL OPEN FONT LICENSE' in license_path.read_text(encoding='utf-8')
        licenses.append(dict(family=name,font_path=str(p.relative_to(ROOT)),license_path=str(license_path.relative_to(ROOT)),
                             license='SIL OFL 1.1',font_bytes=p.stat().st_size,checked_characters=''.join(sorted(chars)),missing=missing,font_redistributed=False))
    jobs=[]
    for fi,(name,path,layout) in enumerate(fonts):
        for fam,a,b in families():
            group=f'{name}:{fam}';candidates=[spelling(a),spelling(b)]
            for variant,s in enumerate((a,b)):
                jobs.append(dict(source=s,candidates=candidates,font=path,family=name,layout=layout,group=group,
                                 origin=f'{group}:{variant}',mode='complete',shift=(0,0),background=fi%2))
        # Identical final pixels from two hidden denominators. Same group and candidates.
        for d in ('4','8'):
            jobs.append(dict(source=spec('fraction',n='1',d=d),candidates=['1/4"','1/8"','2/4"'],font=path,family=name,
                             layout='inline',group=f'{name}:hidden_twins',origin=f'{name}:hidden:{d}',mode='hidden_denominator',shift=(0,0),background=0))
        # Existing base scene augmented; it must stay in its original group.
        s=spec('mixed',whole='1',n='3',d='16',context='DIA. HOLE')
        for mode in ('shifted','unit_crop','context_occluded'):
            jobs.append(dict(source=s,candidates=[spelling(s),'1 3/6" DIA. HOLE','1 3/16 DIA. HOLE'],font=path,family=name,
                             layout=layout,group=f'{name}:denominator',origin=f'{name}:denominator:0',mode=mode,
                             shift=(7,-3) if mode=='shifted' else (0,0),background=fi%2))
    # Shuffle identifiers independent of labels, strings, source kind and split.
    random.Random(142026).shuffle(jobs)
    images=[];pairs=[]
    for j,job in enumerate(jobs):
        s=job['source'];im,masks,glyphs,bg=render(s,job['font'],job['layout'],job['background'],job['shift'])
        unknown=[];region=None;mode=job['mode']
        if mode=='hidden_denominator':
            # Fixed region independent of hidden glyph width/value; zero all denominator evidence.
            left=max(g['bbox'][2] for g in glyphs if 'relation' in g['roles'])
            region=[left,12,150,96];unknown=['denominator','relation','unit']
        elif mode=='unit_crop':
            left=min(g['bbox'][0] for g in glyphs if 'unit' in g['roles'])-2
            region=[left,0,SIZE[0],SIZE[1]];unknown=['unit','context']
        elif mode=='context_occluded':
            left=min(g['bbox'][0] for g in glyphs if 'context' in g['roles'])-2
            region=[left,0,SIZE[0],SIZE[1]];unknown=['context']
        if region:
            x0,y0,x1,y1=region
            if mode in ('unit_crop','context_occluded'):
                # An observable clipped/occluding panel, not invisible white deletion.
                # Without this, context-free complete scenes can be pixel-identical but labelled differently.
                bg[y0:y1,x0:x1]=210
                bg[y0:y1,x0:x0+1]=160
            im[y0:y1,x0:x1]=bg[y0:y1,x0:x1];masks[:,y0:y1,x0:x1]=0
        image_id=f'i{j:03d}';image_path=f'images/{image_id}.png'
        Image.fromarray(im).save(out/image_path)
        for g,mask in zip(glyphs,masks):
            g['final_bbox']=bbox(mask);g['visible_pixels']=int((mask>32).sum())
            g['visibility']='VISIBLE' if g['final_bbox'] else 'HIDDEN_NOT_SUPERVISED'
        np.savez_compressed(out/'annotations'/f'{image_id}.npz',masks=masks,background=bg)
        source_parts=parts(s)
        visible_parts={r:(None if r in unknown else source_parts[r]) for r in ROLES}
        images.append(dict(image=image_path,source_object=job['origin'],group=job['group'],font=job['family'],layout=job['layout'],
                           mode=mode,shift=list(job['shift']),size=list(SIZE),background=job['background'],
                           construction_only=dict(expression=s,raw_form=spelling(s)),visible_parts=visible_parts,unknown_roles=unknown,
                           glyphs=glyphs,damage_region=region,mask_file=f'annotations/{image_id}.npz',
                           proposed_partition={'barlow':'development','ibmplexmono':'validation','sourceserif4':'holdout'}[job['family']]))
        for candidate in job['candidates']:
            anno=label(source_parts,candidate,unknown)
            pairs.append(dict(pair_id='',image=image_path,candidate_raw=candidate,scope='NUMBER_UNIT_CONTEXT',
                              provenance=dict(source_object=job['origin'],input_role='ORIGINAL_SYNTHETIC',group=job['group'],
                                              assessment='SYNTHETIC_VISIBLE_PROVISIONAL',human_reviewed=False),annotation=anno))
    random.Random(140023).shuffle(pairs)
    for i,p in enumerate(pairs):p['pair_id']=f'p{i:04d}'
    write(out/'images.json',images);write(out/'pairs.json',pairs);write(out/'pair.schema.json',PAIR_SCHEMA)
    write(out/'font-provenance.json',licenses)
    write(out/'generation.json',dict(base_images=72,final_images=len(images),pairs=len(pairs),seconds=time.perf_counter()-started,
                                   model_calls=0,training=False,source='ORIGINAL_LAYOUT_AND_PRIMITIVES',
                                   note='66 complete bases + 6 hidden twins; 9 additional views of existing bases. No model predictions.'))
    print(json.dumps(read(out/'generation.json'),ensure_ascii=False))

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,default=OUT);main(ap.parse_args().out)
