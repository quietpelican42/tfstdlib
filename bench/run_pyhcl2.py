import json,sys,signal
from pyhcl2.parse import parse_expr
from pyhcl2.eval import Evaluator
ex=open('exprs.txt').read().split('\n')
out={}
class TO(Exception):pass
def h(*a): raise TO()
signal.signal(signal.SIGALRM,h)
def raw(v):
    r=v.raw()
    if isinstance(r,dict): return {str(k):raw2(x) for k,x in r.items()}
    return raw2(r)
def raw2(r):
    if hasattr(r,'raw'): return raw(r)
    if isinstance(r,(list,tuple)): return [raw2(x) for x in r]
    if isinstance(r,dict): return {str(k):raw2(x) for k,x in r.items()}
    return r
for i,e in enumerate(ex,1):
    if not e: continue
    signal.alarm(5)
    try: out[i]=raw(Evaluator().eval(parse_expr(e)))
    except BaseException as x: out[i]={'__error__':type(x).__name__+': '+str(x)[:80]}
    signal.alarm(0)
json.dump(out,sys.stdout,default=str)
