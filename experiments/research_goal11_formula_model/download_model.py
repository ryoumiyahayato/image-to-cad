"""Download only pinned official inference files. No training data or hash list."""
import json,time,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'local-artifacts/research-goal11-formula-model-20261023'
def main():
    plan=json.loads((OUT/'pre-download-record.json').read_text('utf8'))
    folder=OUT/'model/PP-FormulaNet_plus-L';folder.mkdir(parents=True,exist_ok=True)
    rows=[]
    for item in sorted(plan['selected_files'],key=lambda x:x['bytes']):
        name=item['name'];target=folder/name
        if target.exists():raise RuntimeError('Refuse unregistered replacement: '+str(target))
        url=f"https://huggingface.co/PaddlePaddle/PP-FormulaNet_plus-L/resolve/{plan['revision']}/{name}"
        start=time.perf_counter();received=0;last=start
        print('DOWNLOAD',name,item['bytes'],flush=True)
        with urllib.request.urlopen(url,timeout=90) as response,target.open('wb') as dest:
            while chunk:=response.read(1024*1024):
                dest.write(chunk);received+=len(chunk)
                if time.perf_counter()-last>15:print('PROGRESS',name,received,flush=True);last=time.perf_counter()
        if received!=item['bytes']:raise RuntimeError('Incomplete HTTP payload length')
        rows.append({'name':name,'source_url':url,'bytes':received,'path':str(target),'seconds':time.perf_counter()-start,'revision':plan['revision'],'format':'official inference export, no parameter modification'})
        (OUT/'model-files.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),'utf8')
        print('DONE',name,received,flush=True)
if __name__=='__main__':main()
