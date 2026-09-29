import json,sys,math
gold=json.load(open('gold_min.json'))
def norm(x):
    if isinstance(x,dict):
        if set(x)=={'__set__'}: return sorted(x['__set__'])
        return {k:norm(v) for k,v in x.items()}
    if isinstance(x,list): return [norm(v) for v in x]
    if isinstance(x,float) and math.isfinite(x) and x==int(x): return int(x)
    return x
def score(fn):
    P=json.load(open(fn)); ok=0; n=0
    for i,(expr,gok,gj) in enumerate(gold,1):
        n+=1
        p=P.get(str(i),{'__error__':'missing'})
        perr=isinstance(p,dict) and '__error__' in p
        if not gok:
            ok+= perr
        elif gj is not None and not perr:
            try: gv=json.loads(gj)
            except Exception: continue
            ok+= norm(p)==norm(gv)
    return ok,n
for fn in sys.argv[1:]:
    ok,n=score(fn); print(fn, ok, n, '%.1f%%'%(100*ok/n))
