"""Reproducible one-source entry; always writes a fresh isolated directory."""
import argparse
from pathlib import Path
from experiment2 import run_source
def main():
    p=argparse.ArgumentParser(description='EXPERIMENTAL_ONLY native-dash study; no production conversion')
    p.add_argument('--source',required=True);p.add_argument('--page',type=int,default=1);p.add_argument('--out',required=True);p.add_argument('--limit',type=int,default=6)
    a=p.parse_args()
    if a.page<1 or not 1<=a.limit<=12:raise SystemExit('page>=1 and limit in 1..12 required')
    run_source(Path(a.source),a.page-1,Path(a.out),select_limit=a.limit,role='REPRODUCTION_EXPERIMENT; not new blind evidence')
if __name__=='__main__':main()
