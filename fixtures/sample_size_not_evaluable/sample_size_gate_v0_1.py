"""SAMPLE_SIZE_NOT_EVALUABLE v0.1 (analyze_only; no orders, no keys).
Rule source: 郑珺的hermes (EigenFlux PM): BTC/USDT spot weekly, long on MA_fast crossing above MA_slow,
flat on cross below, 2019-01-01..2024-12-31, min_n=30. A strategy with n<min_n MUST be NOT_EVALUABLE,
never folded into PASS, regardless of return. Neighbour-flip arm: a flipped arm whose entry no longer
lands in the original trigger window / condition is ARM_INVALID, not GATE_FAIL.
Usage: python3 sample_size_gate_v0_1.py [--selftest]"""
import csv, json, sys, hashlib
WIN=(1546300800000, 1735689599999)
def load(p="btcusdt_1w.csv"):
    with open(p) as f: return [(int(r["open_time_ms"]), float(r["close"])) for r in csv.DictReader(f)]
def ma(xs,n,i): return sum(xs[i-n+1:i+1])/n if i>=n-1 else None
def trades(bars,fast,slow):
    c=[x[1] for x in bars]; out=[]; pos=None
    for i in range(1,len(bars)):
        f0,s0,f1,s1=ma(c,fast,i-1),ma(c,slow,i-1),ma(c,fast,i),ma(c,slow,i)
        if None in (f0,s0,f1,s1) or not (WIN[0]<=bars[i][0]<=WIN[1]): continue
        if pos is None and f0<=s0 and f1>s1: pos=(bars[i][0],c[i])
        elif pos and f0>=s0 and f1<s1: out.append({"entry_ms":pos[0],"exit_ms":bars[i][0],"ret":c[i]/pos[1]-1}); pos=None
    if pos: out.append({"entry_ms":pos[0],"exit_ms":None,"ret":c[-1]/pos[1]-1,"open":True})
    return out
def verdict(n_closed,ret_sum,min_n=30,performed=True,n_field_present=True):
    if not performed: return "NOT_PERFORMED"
    if not n_field_present: return "N_ABSENT"
    if n_closed<min_n: return "NOT_EVALUABLE"
    return "PASS" if ret_sum>0 else "FAIL"
def naive(ret_sum): return "PASS" if ret_sum>0 else "FAIL"   # the false-green baseline
def arm_check(orig_entry_ms,flip_entry_ms,trigger_window_ms,cond_holds):
    if flip_entry_ms is None or abs(flip_entry_ms-orig_entry_ms)>trigger_window_ms or not cond_holds: return "ARM_INVALID"
    return "ARM_VALID"
def run():
    bars=load(); res={}
    for fast,slow in [(20,60),(50,200)]:
        t=trades(bars,fast,slow); closed=[x for x in t if not x.get("open")]; rs=sum(x["ret"] for x in closed)
        res[f"MA{fast}/MA{slow}"]={"n_closed":len(closed),"n_open":len(t)-len(closed),"ret_sum":round(rs,4),
            "naive":naive(rs),"gate":verdict(len(closed),rs),"trades":t}
    return res
def selftest():
    cases=[  # (args, expected)
     ((9,1.2),"NOT_EVALUABLE"),((29,5.0),"NOT_EVALUABLE"),((30,0.1),"PASS"),((30,-0.1),"FAIL"),
     ((0,0.0),"NOT_EVALUABLE"),((40,1.0,30,False),"NOT_PERFORMED"),((40,1.0,30,True,False),"N_ABSENT")]
    ok=0
    for a,e in cases:
        g=verdict(*a); ok+=g==e; print(("ok  " if g==e else "BAD ")+f"verdict{a} -> {g} (want {e})")
    for a,e in [((0,0,7*86400000,True),"ARM_VALID"),((0,14*86400000,7*86400000,True),"ARM_INVALID"),
                ((0,0,7*86400000,False),"ARM_INVALID"),((0,None,7*86400000,True),"ARM_INVALID")]:
        g=arm_check(*a); ok+=g==e; print(("ok  " if g==e else "BAD ")+f"arm{a} -> {g} (want {e})")
    # must-fail: naive baseline gives PASS where gate must give NOT_EVALUABLE
    g=naive(1.2); ok+=g=="PASS"; print(("ok  " if g=="PASS" else "BAD ")+"naive(9 trades, +120%) -> PASS (documented false-green)")
    r=run()["MA20/MA60"]; e=r["gate"]=="NOT_EVALUABLE"; ok+=e; print(("ok  " if e else "BAD ")+f"real BTCUSDT 1w MA20/MA60 n_closed={r['n_closed']} gate={r['gate']}")
    tot=13; print(f"selftest {ok}/{tot}"); return ok==tot
if __name__=="__main__":
    if "--selftest" in sys.argv: sys.exit(0 if selftest() else 1)
    r=run(); print(json.dumps({k:{kk:vv for kk,vv in v.items() if kk!="trades"} for k,v in r.items()},indent=1))
    json.dump(r,open("run_out_v0_1.json","w"),indent=1)
