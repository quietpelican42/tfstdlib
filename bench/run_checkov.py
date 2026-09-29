import json,re,sys,signal
from checkov.terraform.graph_builder.variable_rendering.evaluate_terraform import evaluate_terraform
ex=open('exprs.txt').read().split('\n')
out={}
class TO(Exception):pass
def h(*a): raise TO()
signal.signal(signal.SIGALRM,h)
for i,e in enumerate(ex,1):
    if not e: continue
    signal.alarm(5)
    try: r=evaluate_terraform('${%s}'%e)
    except BaseException as x: r={'__error__':type(x).__name__+': '+str(x)[:80]}
    signal.alarm(0)
    out[i]=r
json.dump(out,sys.stdout,default=lambda o: {'__set__':sorted(map(str,o))} if isinstance(o,set) else str(o))
