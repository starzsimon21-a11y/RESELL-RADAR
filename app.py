import os, json, sqlite3, secrets, hmac, time, hashlib, csv, io
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse
from threading import Lock
P=os.environ['RADAR_PASSWORD']; K=os.environ['SESSION_SECRET'].encode()
DB=os.getenv('DB_PATH','radar.db')
lock=Lock(); attempts={}
def db():
 c=sqlite3.connect(DB); c.execute('CREATE TABLE IF NOT EXISTS records(id INTEGER PRIMARY KEY, kind TEXT, data TEXT)'); return c
def rows(k):
 with db() as c: return [dict(json.loads(d),id=i) for i,d in c.execute('SELECT id,data FROM records WHERE kind=?',(k,))]
def num(x):
 if x in (None,''): return None
 n=float(x)
 if not 0<=n<=1e9: raise ValueError()
 return n
def calc(d):
 a=[num(d.get(k)) for k in ('price','shipping','fee','extra')]; cost=sum(a) if None not in a else None
 def profit(k):
  v=num(d.get(k)); s=num(d.get('selling')); return round(v-cost-s,2) if None not in (v,cost,s) else None
 p=profit('target')
 return dict(cost=cost,potential=p,realized=profit('sale') if d.get('status')=='Verkauft' else None,roi=round(p/cost*100,2) if p is not None and cost else None)
def sig(t): return hmac.new(K,t.encode(),hashlib.sha256).hexdigest()
class H(BaseHTTPRequestHandler):
 def send(self,d,status=200,typ='application/json',headers=None):
  b=json.dumps(d,ensure_ascii=False).encode() if typ=='application/json' else d if isinstance(d,bytes) else d.encode()
  self.send_response(status)
  for k,v in {'Content-Type':typ,'Content-Length':str(len(b)),'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Content-Security-Policy':"default-src 'self'; frame-ancestors 'none'; base-uri 'none'",**(headers or {})}.items(): self.send_header(k,v)
  self.end_headers(); self.wfile.write(b)
 def auth(self):
  try:
   t,s=next(x.strip()[6:] for x in self.headers.get('Cookie','').split(';') if x.strip().startswith('radar=')).split('.')
   return int(t)>time.time() and hmac.compare_digest(s,sig(t))
  except (ValueError,StopIteration): return False
 def do_GET(self):
  p=urlparse(self.path).path
  if p in ('/','/ui.js','/style.css','/manifest.json','/sw.js','/icon.svg'):
   f='index.html' if p=='/' else p[1:]; typ={'html':'text/html','js':'text/javascript','css':'text/css','json':'application/manifest+json','svg':'image/svg+xml'}[f.split('.')[-1]]
   return self.send(Path(__file__).with_name(f).read_bytes(),typ=typ)
  if p=='/health':
   with db() as c: c.execute('SELECT 1')
   return self.send({'ok':True})
  if not self.auth(): return self.send({'error':'Anmeldung erforderlich'},401)
  if p=='/api/status': return self.send({'database':'online','provider':'nicht verbunden','scanner':'nicht aktiv','storage':'SQLite; Render Free nicht dauerhaft'})
  if p=='/api/export':
   a=rows('inventory'); out=io.StringIO(); keys=['title','brand','size','category','price','shipping','fee','extra','target','sale','selling','status','cost','potential','realized','roi']; w=csv.DictWriter(out,fieldnames=keys,extrasaction='ignore'); w.writeheader()
   for d in a: w.writerow({k:("'"+v if isinstance(v,str) and v.startswith(('=','+','-','@','\t','\r')) else v) for k,v in dict(d,**calc(d)).items()})
   return self.send(out.getvalue(),typ='text/csv',headers={'Content-Disposition':'attachment; filename=inventory.csv'})
  k=p.removeprefix('/api/')
  if k in ('profiles','deals','inventory'): return self.send([dict(d,**calc(d)) if k!='profiles' else d for d in rows(k)])
  return self.send({'error':'Nicht gefunden'},404)
 def do_POST(self):
  try:
   if self.headers.get('Content-Type')!='application/json' or self.headers.get('Sec-Fetch-Site')=='cross-site': return self.send({'error':'Ungültige Anfrage'},403)
   n=int(self.headers.get('Content-Length','0'))
   if not 0<n<100000: raise ValueError()
   d=json.loads(self.rfile.read(n)); p=self.path
   if p=='/api/login':
    with lock:
     now=time.time(); recent=[x for x in attempts.get('global',[]) if now-x<60]
     if len(recent)>=10: return self.send({'error':'Bitte eine Minute warten'},429)
     attempts['global']=recent+[now]
    if not hmac.compare_digest(str(d.get('password','')).encode(),P.encode()): return self.send({'error':'Falsches Passwort'},403)
    t=str(int(time.time()+86400)); return self.send({'ok':True},headers={'Set-Cookie':f'radar={t}.{sig(t)}; Path=/; HttpOnly; SameSite=Strict; Secure; Max-Age=86400'})
   if not self.auth(): return self.send({'error':'Anmeldung erforderlich'},401)
   if p=='/api/logout': return self.send({'ok':True},headers={'Set-Cookie':'radar=; Path=/; Max-Age=0; Secure; HttpOnly; SameSite=Strict'})
   k=p.removeprefix('/api/')
   if k not in ('profiles','deals','inventory'): raise ValueError()
   i=d.pop('id',None)
   with db() as c:
    if d.get('delete'): c.execute('DELETE FROM records WHERE id=? AND kind=?',(int(i),k))
    else:
     if not str(d.get('name' if k=='profiles' else 'title','')).strip(): raise ValueError()
     if k!='profiles': calc(d)
     if d.get('url'):
      u=urlparse(d['url'])
      if u.scheme!='https' or u.hostname not in ('www.vinted.at','www.vinted.de','www.vinted.fr','www.vinted.it','vinted.at') or not u.path.startswith('/items/'): raise ValueError()
     if i: c.execute('UPDATE records SET data=? WHERE id=? AND kind=?',(json.dumps(d),int(i),k))
     else: c.execute('INSERT INTO records(kind,data) VALUES(?,?)',(k,json.dumps(d)))
   return self.send({'ok':True})
  except (ValueError,TypeError,KeyError,AttributeError): return self.send({'error':'Ungültige Eingabe'},400)
if __name__=='__main__': ThreadingHTTPServer(('0.0.0.0',int(os.getenv('PORT','8000'))),H).serve_forever()
