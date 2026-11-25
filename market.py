import urllib.request, urllib.parse, urllib.error, re, time, threading
from html.parser import HTMLParser
lock=threading.Lock()
cache={}
last=0
class Catalog(HTMLParser):
 def __init__(self):
  super().__init__(); self.items={}; self.current=None
 def handle_starttag(self,tag,attrs):
  a=dict(attrs)
  if tag=='a':
   u=urllib.parse.urljoin('https://www.vinted.at',a.get('href',''))
   p=urllib.parse.urlparse(u)
   m=re.match(r'/items/(\d+)(?:-|$)',p.path)
   self.current=None
   if p.hostname=='www.vinted.at' and m:
    self.current=m.group(1)
    self.items.setdefault(self.current,{'id':self.current,'url':'https://www.vinted.at'+p.path,'title':a.get('title') or a.get('aria-label') or '', 'price':None})
  elif tag=='img' and self.current:
   d=self.items[self.current]
   if not d['title']: d['title']=a.get('alt','')
 def handle_endtag(self,tag):
  if tag=='a': self.current=None
 def handle_data(self,data):
  if self.current:
   m=re.fullmatch(r'\s*(\d+(?:[,.]\d{2})?)\s*€\s*',data)
   if m: self.items[self.current]['price']=float(m.group(1).replace(',','.'))
def search(q,lo='',hi=''):
 global last
 params={'search_text':q,'order':'price_low_to_high'}
 if lo: params['price_from']=lo
 if hi: params['price_to']=hi
 url='https://www.vinted.at/catalog?'+urllib.parse.urlencode(params)
 with lock:
  now=time.monotonic()
  if url in cache and now-cache[url][0]<300: return cache[url][1]
  if now-last<30: return {'error':'Bitte 30 Sekunden zwischen neuen Suchabfragen warten.','items':[]}
  last=now
  try:
   req=urllib.request.Request(url,headers={'User-Agent':'RESELL-RADAR/1.0 (public catalog search)'})
   with urllib.request.urlopen(req,timeout=15) as r:
    if urllib.parse.urlparse(r.geturl()).hostname!='www.vinted.at': raise ValueError('Unerwartete Weiterleitung')
    raw=r.read(3000000).decode('utf-8','replace')
   parser=Catalog();parser.feed(raw)
   items=sorted([d for d in parser.items.values() if d['title'] and d['price'] is not None],key=lambda d:d['price'])
   result={'items':items,'source':url,'coverage':'Erste HTML-Ergebnisseite; keine vollständige Marktabdeckung','error':None if items else 'Keine auswertbaren Artikel im öffentlichen HTML gefunden.'}
  except (OSError,ValueError) as e: result={'items':[],'error':'Vinted-Abruf fehlgeschlagen: '+str(e),'source':url}
  cache[url]=(now,result)
  if len(cache)>100: cache.pop(next(iter(cache)))
  return result
