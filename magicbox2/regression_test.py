import sys,csv,glob,io
import os; CODE=os.environ.get('CODE','/home/claude/mb/magicbox'); sys.path.insert(0,CODE)
from stage0_reorder import reorder_by_article
from stage1_core import Stage1Extractor
from stage2_group_v2 import run_stage2A, run_stage2C
from stage3_final import run_stage3_final
import importlib
app_src=open(CODE+'/app.py',encoding='utf-8').read()
# extract run_stage1 from app without streamlit
ns={'Stage1Extractor':Stage1Extractor}
s=app_src.index('def run_stage1'); e=app_src.index('# ---------- 로그인')
exec(app_src[s:e],ns); run_stage1=ns['run_stage1']
def run(path,name,sur):
    rows=list(csv.reader(open(path,encoding='utf-8-sig')))
    h,d=rows[0],rows[1:]
    d=reorder_by_article(d,h)
    s1,st=run_stage1(d,h,name,sur)
    a=run_stage2A(s1[1:],s1[0]); c=run_stage2C(a[1:],a[0])
    s3,rem=run_stage3_final(c[1:],c[0],threshold=0.8,min_subset_portion=0.30)
    hi=s3[0].index('인용문(발췌)')
    act=[r for r in s3[1:] if r[hi].strip()]
    csv.writer(open(f'{os.environ.get("TAG","new")}_s1_{path.split("/")[-1][:30]}.csv','w',encoding='utf-8-sig',newline='')).writerows(s1)
    return s3,len(act),sum(r[hi].count('"')//2 for r in act)
if __name__=='__main__':
    U='/mnt/user-data/uploads/'
    cases={'이해찬':('업로드용_파일_이해찬*','이해찬','이'),'이준석1':('업로드용파일_20250629*','이준석','이'),'이낙연':('업로드용파일_20251020_103221*','이낙연','이'),'이인영':('업로드용파일_20251021*','이인영','이'),'이언주':('업로드용파일_20251020_172437*','이언주','이')}
    for k,(g,n,s) in cases.items():
        p=glob.glob(U+g)[0]
        out,a,b=run(p,n,s); print(k,a,b)
        csv.writer(open(f'{os.environ.get("TAG","new")}_{k}.csv','w',encoding='utf-8-sig',newline='')).writerows(out)
