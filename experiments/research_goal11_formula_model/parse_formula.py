"""Format parser only. No source labels, coordinates or engineering corrections."""
import json,re
VULGAR={'¼':('1','4'),'½':('1','2'),'¾':('3','4')}
WRAPPERS={'text','textrm','mathrm','mathit','mathbf','operatorname','mathsf','mathtt','mbox','emph'}
IGNORE={'left','right','displaystyle','textstyle','scriptstyle','scriptscriptstyle','quad','qquad','small','large','Large','limits','nolimits'}

def group(s,i):
    while i<len(s) and s[i].isspace():i+=1
    if i>=len(s):return '',i,False
    if s[i]!='{':return s[i],i+1,True
    depth=1;j=i+1
    while j<len(s) and depth:
        depth+=(s[j]=='{')-(s[j]=='}');j+=1
    return s[i+1:j-1] if depth==0 else s[i+1:],j,depth==0

def parse(raw):
    s=re.sub(r'([+-])\s+(?=\d)',r'\1',str(raw));nodes=[];unknown=[];ignored=[];i=0
    def add(kind,**values):nodes.append(dict(kind=kind,**values))
    while i<len(s):
        c=s[i]
        if c.isspace() or c in '{}$':i+=1;continue
        if c=='\\':
            match=re.match(r'\\([A-Za-z]+|.)',s[i:])
            if not match:unknown.append(s[i:]);break
            cmd=match.group(1);i+=len(match.group(0))
            if cmd in ['frac','dfrac','tfrac']:
                a,i,ok1=group(s,i);b,i,ok2=group(s,i)
                if ok1 and ok2 and re.fullmatch(r'[+-]?\d+',a.strip()) and re.fullmatch(r'\d+',b.strip()):add('fraction',numerator=a.strip(),denominator=b.strip())
                elif ok1 and ok2 and re.fullmatch(r'[A-Za-z]',a.strip()) and re.fullmatch(r'\d+',b.strip()):add('symbolic_fraction',numerator=a.strip(),denominator=b.strip())
                else:unknown.append({'command':cmd,'numerator':a,'denominator':b});add('unknown_fraction',numerator=a,denominator=b)
            elif cmd in WRAPPERS:
                body,i,ok=group(s,i);child=parse(body);nodes.extend(child['nodes']);unknown.extend(child['unknown']);ignored.extend(child['ignored_formatting'])
                if not ok:unknown.append('unclosed '+cmd)
            elif cmd in IGNORE or cmd in [',',';','!',':',' ','/']:
                ignored.append(cmd)
            elif cmd in ['prime','doubleprime']:
                if cmd=='prime' and nodes and nodes[-1]=={'kind':'unit','value':'foot'}:nodes[-1]={'kind':'unit','value':'inch'}
                else:add('unit',value='inch' if cmd=='doubleprime' else 'foot')
            elif cmd in ['%','circ']:add('unit',value='percent' if cmd=='%' else 'degree')
            elif cmd in ['times','cdot']:add('operator',value='multiply')
            elif cmd in ['le','leq','ge','geq','pm']:add('operator',value=cmd)
            elif cmd=='"':unknown.append('accent_doublequote');add('unknown',value='\\"')
            else:unknown.append('\\'+cmd);add('unknown',value='\\'+cmd)
            continue
        if c in '^_':
            body,end,ok=group(s,i+1)
            if c=='^' and re.fullmatch(r'\s*\\(?:prime|doubleprime)(?:\s*\\prime)?\s*',body):
                n=2 if 'doubleprime' in body else body.count('prime');add('unit',value='inch' if n==2 else 'foot')
            elif c=='^' and body.strip()=='\\circ':add('unit',value='degree')
            else:unknown.append({'position':c,'body':body});add('script',position=c,body=body)
            i=end;continue
        m=re.match(r'[+-]?\d+(?:\.\d+)?',s[i:])
        if m:
            value=m.group();i+=len(value)
            if i<len(s) and s[i] in VULGAR and '.' not in value:
                a,b=VULGAR[s[i]];add('mixed_literal',whole=value,numerator=a,denominator=b);i+=1;continue
            match=re.match(r'\s*/\s*(\d+)',s[i:])
            if match and '.' not in value:add('fraction',numerator=value,denominator=match.group(1));i+=len(match.group())
            else:add('decimal' if '.' in value else 'integer',value=value)
            continue
        if c in VULGAR:
            a,b=VULGAR[c];add('fraction',numerator=a,denominator=b);i+=1;continue
        if c in ['"','″','”','“']:add('unit',value='inch');i+=1;continue
        if c in ["'",'′','’','‘']:
            if i+1<len(s) and s[i+1] in ["'",'′']:add('unit',value='inch');i+=2
            else:add('unit',value='foot');i+=1
            continue
        if c=='%':add('unit',value='percent');i+=1;continue
        if c=='°':add('unit',value='degree');i+=1;continue
        m=re.match(r'[A-Za-z]+',s[i:])
        if m:
            word=m.group() if len(m.group())==1 else m.group().casefold();i+=len(m.group());units={'inch':'inch','inches':'inch','degrees':'degree','degree':'degree','mm':'mm','cm':'cm','ft':'foot'}
            ratio=re.match(r'\s*/\s*(\d+)',s[i:])
            if len(word)==1 and ratio:add('symbolic_fraction',numerator=word,denominator=ratio.group(1));i+=len(ratio.group());continue
            add('unit' if word in units else 'word',value=units.get(word,word));continue
        if c=='.' and i>0 and s[i-1].isalpha():ignored.append('letter_period');i+=1;continue
        if c in ['-','+','×','*','=','(',')','[',']',':','/','#']:
            add('operator',value='multiply' if c in ['×','*'] else c);i+=1;continue
        unknown.append(c);add('unknown',value=c);i+=1
    for j in range(1,len(nodes)-1):
        if nodes[j]=={'kind':'word','value':'x'} and nodes[j-1]['kind'] in ['integer','decimal','fraction','symbolic_fraction','unit','mixed_literal'] and nodes[j+1]['kind'] in ['integer','decimal','fraction','mixed_literal']:nodes[j]={'kind':'operator','value':'multiply'}
    uncertain=[]
    for j in range(len(nodes)-1):
        if nodes[j]['kind']=='integer' and nodes[j+1]['kind']=='fraction':uncertain.append({'relation':'MIXED_OR_JUXTAPOSITION_UNCERTAIN','node_indices':[j,j+1]})
    return {'raw':raw,'nodes':nodes,'unknown':unknown,'uncertain_relations':uncertain,'ignored_formatting':ignored,'complete_parse':not unknown and not uncertain}

if __name__=='__main__':
    cases=[('\\frac{11}{2}"','fraction'),('1\\frac{1}{2}"','uncertain'),('\\frac{13}{6}"','fraction'),('1½"','mixed_literal'),('-1.4\\%','decimal'),('3^{n}','script'),('3^{\\prime\\prime}','integer'),('45^{\\circ}','integer'),('\\mathrm{DIA.HOLE}','word'),('\\text{1 3/16"}','uncertain'),('\\frac{3}{16}','fraction'),('\\bad{14}','unknown'),('T/3 x 1½"','symbolic_fraction'),('\\frac{T}{3}\\times1½"','symbolic_fraction')]
    rows=[]
    for text,expected in cases:
        result=parse(text);actual='uncertain' if result['uncertain_relations'] else 'script' if any(n['kind']=='script' for n in result['nodes']) else result['nodes'][0]['kind'];rows.append({'input':text,'expected':expected,'actual':actual,'as_expected':actual==expected,'parsed':result})
    if not all(r['as_expected'] for r in rows):raise RuntimeError('Original format rule mismatch')
    print(json.dumps({'scope':'14 original format examples, not model inference or real transfer','rows':rows},ensure_ascii=False,indent=2))
