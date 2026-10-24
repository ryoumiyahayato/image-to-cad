"""Balanced, family-disjoint synthetic data. Real drawings are never read here."""
import functools
import json
import random
import time
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from common import OUT, CFG_PATH, prepare, read_json, write_json

@functools.lru_cache(maxsize=512)
def font(path, size):
    from PIL import ImageFont
    return ImageFont.truetype(path, size)

def text_image(text, f):
    box = f.getbbox(text)
    image = Image.new('L', (max(1, box[2]-box[0])+2, max(1, box[3]-box[1])+2), 255)
    ImageDraw.Draw(image).text((1-box[0], 1-box[1]), text, font=f, fill=0)
    return image

def token_image(label, kind, path, size, rng):
    f = font(path, size)
    n, den = rng.choice([('1','4'), ('3','8'), ('5','16'), ('1','2'), ('3','4'), ('7','8')])
    if not label:
        choices = {
            'integer': ['14', '45 degrees', '20', '114', '4 IN', '16', '48', '125'],
            'decimal': ['1.5%', '0.25', '11.5%', '4.6', '0.5 MAX'],
            'feet': ["2'-0\"", "8'-8\"", "3'-8\"", '10\"'],
            'symbols': ['4×6', '#4', 'Ø16', 'R4', '6 x 6', '#14'],
            'nonfraction_slash': ['A/B', 'N/A', 'S/2', '14/NOTE', 'SEE A/4', 'W/O', 'I/O'],
            'integer_line': ['14', '45', '4', '16', '28', '4×6', '#4']}
        value = rng.choice(choices[kind])
        return text_image(value, f), value
    if kind == 'inline':
        value = f'{n}/{den}'
        return text_image(value, f), value
    if kind == 'mixed_glyph':
        value = rng.choice(['1¼', '1½', '2¾', '3½', '¼', '½'])
        return text_image(value, f), value
    small = font(path, max(10, int(size * .60)))
    a, b = text_image(n, small), text_image(den, small)
    if kind == 'stacked':
        w = max(a.width, b.width) + 4
        image = Image.new('L', (w, a.height+b.height+7), 255)
        image.paste(a, ((w-a.width)//2, 0)); image.paste(b, ((w-b.width)//2, a.height+7))
        ImageDraw.Draw(image).line((0, a.height+3, w-1, a.height+3), fill=0, width=1)
    else:
        slash = text_image('/', f)
        image = Image.new('L', (a.width+slash.width+b.width, max(size, a.height+b.height)), 255)
        image.paste(a, (0, 0)); image.paste(slash, (a.width, (image.height-slash.height)//2))
        image.paste(b, (a.width+slash.width, image.height-b.height))
    if rng.random() < .4:
        whole = text_image(str(rng.randint(1, 4)), f)
        mixed = Image.new('L', (whole.width+image.width+3, max(image.height, whole.height)), 255)
        mixed.paste(whole, (0, (mixed.height-whole.height)//2)); mixed.paste(image, (whole.width+3, 0))
        image = mixed
    return image, f'{n}/{den}'

def sample(label, family, content_rng, nuisance_seed, index):
    # Paired opposite labels use the same nuisance seed. No class-specific augmentation.
    rng = random.Random(nuisance_seed)
    nrng = np.random.default_rng(nuisance_seed)
    size = rng.randint(22, 36)
    style = rng.choice(['clean', 'blur', 'noise', 'lines', 'lowres', 'thick'])
    kind = content_rng.choice(['inline','supsub','stacked','mixed_glyph'] if label else
                              ['integer','decimal','feet','symbols','nonfraction_slash','integer_line'])
    token, value = token_image(label, kind, family['path'], size, content_rng)
    context = rng.choice([('', ''), ('', ' IN'), ('BAR ', ' TYP'), ('MAX ', ' CLEAR'),
                          ('LIMIT ', ' INCH.'), ('STEEL ', ' @ 12 IN'), ('DIM ', ''),
                          ('EXCEEDING ', ' INCH.'), ('', ' CONCRETE SLAB')])
    f = font(family['path'], size)
    left, right = text_image(context[0], f), text_image(context[1], f)
    h = max(token.height, left.height, right.height) + rng.randint(8, 20)
    gap = rng.randint(2, 7)
    w = left.width+right.width+token.width+gap*4
    image = Image.new('L', (w, h), 255)
    x = gap
    for part in [left, token, right]:
        image.paste(part, (x, (h-part.height)//2)); x += part.width+gap
    draw = ImageDraw.Draw(image)
    if style == 'lines':
        for _ in range(rng.randint(1, 2)):
            if rng.random() < .5:
                yy = rng.randrange(h); draw.line((0, yy, w-1, yy), fill=rng.randint(20,140), width=1)
            else:
                xx = rng.randrange(w); draw.line((xx, 0, min(w-1,xx+rng.randint(-20,20)), h-1), fill=60, width=1)
    if style == 'thick': image = image.filter(ImageFilter.MinFilter(3))
    if style == 'blur': image = image.filter(ImageFilter.GaussianBlur(rng.uniform(.3, .9)))
    if style == 'lowres':
        s = rng.uniform(.45,.75)
        image = image.resize((max(1,int(w*s)),max(1,int(h*s))), Image.Resampling.BILINEAR).resize((w,h),Image.Resampling.BILINEAR)
    image = image.rotate(rng.uniform(-3,3), resample=Image.Resampling.BILINEAR, expand=True, fillcolor=255)
    arr = np.asarray(image).astype(np.float32)
    background, ink = rng.uniform(220,255), rng.uniform(0,55)
    arr = ink + arr/255*(background-ink)
    if style == 'noise':
        arr += nrng.normal(0,rng.uniform(4,15),arr.shape)
        arr[nrng.random(arr.shape)<.004] = 80
    image = Image.fromarray(np.clip(arr,0,255).astype(np.uint8))
    return prepare(image), dict(id=index, label=int(label), family=family['family'], kind=kind,
                               degradation=style, visible_text=context[0]+value+context[1])

def main():
    cfg, fonts = read_json(CFG_PATH), read_json(OUT/'font-sources.json')
    start = time.perf_counter()
    for j, split in enumerate(['train','validation','test']):
        count = cfg[f'{split}_samples']
        eligible = [f for f in fonts if f['split']==split]
        rng = random.Random(cfg['seed']+j*100000)
        images = np.empty((count,cfg['height'],cfg['width']), dtype=np.uint8)
        labels = np.empty(count, dtype=np.int64)
        records = []
        for i in range(count):
            label = i % 2
            family = eligible[(i//2) % len(eligible)]
            arr, row = sample(label, family, rng, cfg['seed']+j*100000+i//2, i)
            images[i], labels[i] = arr, label
            records.append(row)
        np.save(OUT/f'{split}-images.npy', images, allow_pickle=False)
        np.save(OUT/f'{split}-labels.npy', labels, allow_pickle=False)
        (OUT/f'{split}-metadata.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in records),encoding='utf-8')
        sheet=Image.new('RGB',(768,60*12),'#dddddd'); d=ImageDraw.Draw(sheet)
        for k in range(24):
            xx,yy=(k%2)*384,(k//2)*60
            sheet.paste(Image.fromarray(images[k]),(xx,yy+12));d.text((xx,yy),f'{split} {records[k]["family"]} y={labels[k]} {records[k]["kind"]}',fill='black')
        sheet.save(OUT/f'{split}-preview.png')
        print(split,count,'positives',int(labels.sum()),flush=True)
    write_json(OUT/'generation.json',dict(seconds=time.perf_counter()-start,config=cfg,
               real_images_read=0,split_unit='font_family',nuisance_pairing='same nuisance seed for adjacent opposite labels'))

if __name__ == '__main__': main()
