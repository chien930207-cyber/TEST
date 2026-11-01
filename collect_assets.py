#!/usr/bin/env python3
"""Build-time image collector. No browser proxies, credentials or image upscaling.
Runs on GitHub-hosted runners. It preserves original bytes and records provenance.
Failure of a team is non-fatal; a deployment requires at least one valid logo.
"""
from __future__ import annotations
import argparse
import concurrent.futures as futures
import csv
import hashlib
import html
import io
import ipaddress
import json
import logging
import re
import shutil
import socket
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit, parse_qsl, urlencode, unquote
from urllib.robotparser import RobotFileParser
import requests
from bs4 import BeautifulSoup
from PIL import Image
from defusedxml import ElementTree as ET

LOG = logging.getLogger('team-id')
MAX_BYTES = 40 * 1024 * 1024
AGENT = 'TeamID-AssetCollector/6.0 (personal sports quiz; static-site build)'
TIMEOUT = (5, 14)
PRODUCT_WORD = re.compile(r'jersey|uniform|\u7403\u8863|\u30e6\u30cb\u30d5\u30a9\u30fc\u30e0|\uc720\ub2c8\ud3fc', re.I)
REJECT_WORD = re.compile(r't-?shirt|hoodie|shorts|hat|cap\b|autograph|signed|size.?chart|\u77ed\u8932|\u5e3d|\u5916\u5957|\u80cc\u5305|\u53e4\u8457|\u30bf\u30aa\u30eb|\ud0a4\ub9c1|\ubaa8\uc790', re.I)
FRONT_WORD = re.compile(r'\bfront\b|\u6b63\u9762|\u524d\u9762|\u8868\u9762|\u30d5\u30ed\u30f3\u30c8|\uc55e\uba74|\uc804\uba74', re.I)
BACK_WORD = re.compile(r'\bback\b|\brear\b|\u80cc\u9762|\u88cf\u9762|\u30d0\u30c3\u30af|\ub4b7\uba74|\ub4a4\ud310', re.I)
HOME_WORD = re.compile(r'\bhome\b|\bicon\b|\u4e3b\u5834|\u4e3b\u6230|\u30db\u30fc\u30e0|\ud648', re.I)
SPECIAL_WORD = re.compile(r'city.connect|city.edition|throwback|cooperstown|all.star|anniversary|commemorat|world.series|champion|\u806f\u540d|\u7d00\u5ff5|\u4e3b\u984c|\u5fa9\u53e4|\u30b3\u30e9\u30dc', re.I)
PRODUCT_URL = re.compile(r'/products?/|/goods/|goods_view|goodsNo=|product_no=|/items?/|/detail/|itemCode=|/g/|\+p-|%2Bp-|/p-\d|/pd/|/i/|jersey-\d+/?$', re.I)
SAFE_IMAGE_TYPES = {'PNG': ('png', 'image/png'), 'JPEG': ('jpg','image/jpeg'), 'WEBP': ('webp','image/webp')}


def uniq(values):
    return list(dict.fromkeys(x for x in values if x))


def public_url(url: str, resolve: bool = True) -> str:
    p = urlsplit(url)
    if p.scheme != 'https' or not p.hostname or p.username or p.password or p.port not in (None, 443):
        raise ValueError('Only public HTTPS source URLs are accepted')
    if resolve:
        addresses = socket.getaddrinfo(p.hostname, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
            raise ValueError('Source must resolve to a public address')
    return url


def originals(url: str) -> list[str]:
    """Strip known thumbnail transforms, never request synthetic raster upscales."""
    p = urlsplit(html.unescape(url))
    q, path, host = dict(parse_qsl(p.query, keep_blank_values=True)), p.path, p.hostname or ''
    out = []
    if 'frgimages.com' in host or 'shopify' in host or '/cdn/shop/' in path or 'shoplineimg.com' in host:
        for k in ['w','h','width','height','quality','q','imwidth','imheight','crop']:
            q.pop(k, None)
        path = re.sub(r'_thumb(?=\.)', '_full', path)
        path = re.sub(r'_\d+x\d*(?=\.[^.]+$)', '', path)
        if 'shoplineimg.com' in host:
            path = re.sub(r'/(?:\d+x|large|medium|small|master)(?:\.[a-z]+)?$', '/original.jpeg', path)
        out.append(urlunsplit((p.scheme,p.netloc,path,urlencode(q),'')))
    if '/web/product/medium/' in path:
        out.append(urlunsplit((p.scheme,p.netloc,path.replace('/web/product/medium/','/web/product/big/'),p.query,'')))
    if re.search(r'-\d{2,5}x\d{2,5}\.(png|jpe?g|webp)$',path,re.I):
        out.append(urlunsplit((p.scheme,p.netloc,re.sub(r'-\d{2,5}x\d{2,5}(?=\.[^.]+$)','',path),p.query,'')))
    if host.endswith('nfl.com') and '/image/' in path:
        out.append(urlunsplit((p.scheme,p.netloc,re.sub(r'/(?:f_auto|[^/]*w_\d+[^/]*|[^/]*h_\d+[^/]*)/', '/f_png,q_100/',path),p.query,'')))
    out.append(url)
    return uniq(out)


def image_info(data: bytes, mime: str = '') -> dict:
    """Accept actual images, not HTML error responses; keep original dimensions."""
    if len(data) > MAX_BYTES:
        raise ValueError('Image exceeds 40 MB safety limit; not compressed or resized')
    if b'<svg' in data[:4096].lower():
        root = ET.fromstring(data)
        if root.tag.split('}')[-1] != 'svg':
            raise ValueError('Invalid SVG root')
        for node in root.iter():
            if node.tag.split('}')[-1].lower() in {'script','foreignobject','iframe','object','embed','image','audio','video'}:
                raise ValueError('Unsafe or externally dependent SVG')
            for k,v in node.attrib.items():
                if k.split('}')[-1].lower().startswith('on'):
                    raise ValueError('SVG event handlers are not permitted')
                if k.split('}')[-1].lower() == 'href' and not v.startswith('#'):
                    raise ValueError('External SVG references are not permitted')
                if re.search(r'url\s*\(\s*[\'"]?(?!#)[\w:/]', v, re.I):
                    raise ValueError('External SVG CSS is not permitted')
            if node.tag.split('}')[-1] == 'style' and re.search(r'@import|https?://',node.text or '',re.I):
                raise ValueError('External SVG style is not permitted')
        vb = re.split(r'[,\s]+',root.attrib.get('viewBox','').strip())
        try:
            w,h = (float(vb[2]),float(vb[3])) if len(vb)==4 else (float(re.sub(r'[^\d.]','',root.attrib.get('width','1000'))),float(re.sub(r'[^\d.]','',root.attrib.get('height','1000'))))
        except (ValueError, IndexError): w,h = 1000,1000
        if w <= 0 or h <= 0: raise ValueError('Empty SVG canvas')
        return {'ext':'svg','mime':'image/svg+xml','width':w,'height':h,'vector':True,'bytes':len(data)}
    with Image.open(io.BytesIO(data)) as im:
        if im.format not in SAFE_IMAGE_TYPES: raise ValueError('Unsupported raster format')
        w,h = im.size
        if min(w,h)<24 or w*h>80_000_000: raise ValueError('Invalid image dimensions')
        ext,mt = SAFE_IMAGE_TYPES[im.format]
        im.verify()
    return {'ext':ext,'mime':mt,'width':w,'height':h,'vector':False,'bytes':len(data)}


def team_match(text: str, team: dict, exclusive: bool = False) -> bool:
    if exclusive: return True
    normalize=lambda x: re.sub(r'[\s_\-]+','',unquote(str(x)).lower())
    txt=normalize(text)
    names=[team.get(k,'') for k in ['zh','en','local']] + team.get('aliases',[])
    return any(len(normalize(n))>=3 and normalize(n) in txt for n in names if n)


def product_score(text: str, team: dict, exclusive: bool = False) -> int:
    if not PRODUCT_WORD.search(text) or REJECT_WORD.search(text) or not team_match(text,team,exclusive): return -1000
    if re.search(r'women|youth|kids|toddler|infant|\u5152\u7ae5|\u5973\u6b3e',text,re.I): return -1000
    score=20 + (100 if HOME_WORD.search(text) else 0)
    score+=30 if re.search(r'2026|26.?27',text) else 15 if re.search(r'2025|25.?26',text) else 0
    score+=15 if re.search(r'replica|swingman|\u30ec\u30d7\u30ea\u30ab|\ub808\ud50c\ub9ac\uce74',text,re.I) else 0
    if SPECIAL_WORD.search(text): score-=130
    return score


def image_urls(img, base: str) -> list[str]:
    out=[]
    for attr in ['srcset','data-srcset']:
        candidates=[]
        for item in (img.get(attr) or '').split(','):
            parts=item.strip().split()
            if parts:
                try: n=float(re.sub(r'[^\d.]','',parts[-1])) if len(parts)>1 else 0
                except ValueError: n=0
                candidates.append((n,urljoin(base,parts[0])))
        out += [u for _,u in sorted(candidates,reverse=True)]
    for attr in ['data-original','data-full','data-zoom-image','data-large-image','data-src','data-lazy-src','src']:
        if img.get(attr): out.append(urljoin(base,img[attr]))
    return uniq(u for u in out if u.startswith('https://'))


def json_products(soup):
    out=[]
    def walk(v):
        if isinstance(v,list):
            for item in v: walk(item)
        elif isinstance(v,dict):
            kinds=v.get('@type',[]); kinds=kinds if isinstance(kinds,list) else [kinds]
            if 'Product' in kinds: out.append(v)
            else:
                for value in v.values(): walk(value)
    for s in soup.select('script[type="application/ld+json"]'):
        try: walk(json.loads(s.string or s.get_text()))
        except (ValueError,TypeError): pass
    return out


def jersey_candidates(soup, base: str, team: dict, exclusive: bool = False) -> list[dict]:
    h1=soup.find('h1'); og=soup.find('meta',property='og:title')
    title=(h1.get_text(' ',strip=True) if h1 else og.get('content','') if og else soup.title.get_text(' ',strip=True) if soup.title else '')
    if product_score(title+' '+unquote(base).replace('-',' '),team,exclusive)<0: return []
    candidates=[]
    fanatics=any(s in urlsplit(base).hostname for s in ['mlbshop.com','nflshop.com','nba.com','nbastore.com','fanatics.com'])
    pid_match=re.search(r'Product ID\s*:\s*(\d+)',soup.get_text(' ',strip=True),re.I)
    pid=pid_match.group(1) if pid_match else None
    def add(raw,alt='',rank=0,semantic=False):
        if not isinstance(raw,str): return
        u=urljoin(base,html.unescape(raw)); text=unquote(u)+' '+alt
        if not u.startswith('https://') or re.search(r'logo|banner|size.?chart|shipping|placeholder|swatch|zoom-detail',text,re.I) or BACK_WORD.search(text): return
        if fanatics and pid and pid not in u: return
        explicit=bool(FRONT_WORD.search(text))
        # The old alt2 naming convention is a candidate, NOT a visual verification.
        conventional=bool(re.search(r'_altimages_.*alt2_(?:full|thumb)',u,re.I))
        primary=bool(re.search(r'\bpv-1\b',unquote(u),re.I))
        if team['league']=='MLB' and not(explicit or conventional): return
        if fanatics and not(explicit or conventional or primary or semantic): return
        score=(250 if explicit else 120 if conventional else 50 if primary else 20 if semantic else 0)-rank
        candidates.append({'url':u,'page':base,'label':title[:150], 'frontStatus':'front-labelled' if explicit else 'catalogue-primary-needs-review','visualVerified':False,'score':score})
    for p in json_products(soup):
        if product_score(str(p.get('name',''))+' '+base,team,exclusive)<0: continue
        images=p.get('image',[]); images=images if isinstance(images,list) else [images]
        for i,im in enumerate(images):
            add(im if isinstance(im,str) else im.get('url') or im.get('contentUrl'),str(p.get('name','')),i,True)
    for i,im in enumerate(soup.select('img')):
        for u in image_urls(im,base):
            desc=' '.join(str(im.get(x,'')) for x in ['alt','title'])
            # Galleries, team/product-labelled images, and Fanatics IDs only.
            gallery=im.find_parent(class_=re.compile(r'product|gallery|imgArea|image-container',re.I)) is not None
            if gallery or FRONT_WORD.search(desc+' '+u) or fanatics:
                add(u,desc,i,False)
    ogim=soup.find('meta',property='og:image')
    if ogim: add(ogim.get('content',''),title,5,True)
    seen=set();out=[]
    for c in sorted(candidates,key=lambda x:x['score'],reverse=True):
        if c['url'] not in seen: seen.add(c['url']);out.append(c)
    return out


class Collector:
    def __init__(self, output: Path, cache: Path, deadline: float, refresh=False, max_pages=10):
        self.output,self.cache,self.deadline,self.refresh,self.max_pages=output,cache,deadline,refresh,max_pages
        self.local=threading.local();self.lock=threading.RLock();self.robots={};self.pages={};self.visited={}
        self.old={}
        try:self.old=json.loads((cache/'manifest.json').read_text())['assets']
        except (FileNotFoundError,ValueError,KeyError):pass
        (output/'assets/images').mkdir(parents=True,exist_ok=True); (output/'data').mkdir(parents=True,exist_ok=True);cache.mkdir(parents=True,exist_ok=True)

    def session(self):
        if not hasattr(self.local,'session'):
            s=requests.Session();s.headers.update({'User-Agent':AGENT,'Accept':'image/png,image/jpeg,image/svg+xml,image/webp,text/html,application/json;q=0.9,*/*;q=0.5'})
            self.local.session=s
        return self.local.session

    def check_time(self):
        if time.monotonic()>=self.deadline: raise TimeoutError('Build download time budget reached')

    def get(self,url,robots=True):
        self.check_time();public_url(url)
        if robots and not self.robot_allowed(url): raise ValueError('Source robots.txt disallows this URL')
        current=url
        for _ in range(5):
            public_url(current);self.check_time()
            r=self.session().get(current,timeout=TIMEOUT,stream=True,allow_redirects=False)
            if r.is_redirect:
                nxt=urljoin(current,r.headers.get('Location',''));r.close()
                public_url(nxt)
                if robots and not self.robot_allowed(nxt): raise ValueError('Redirect disallowed by robots.txt')
                current=nxt;continue
            try:
                r.raise_for_status()
                if int(r.headers.get('Content-Length','0'))>MAX_BYTES:raise ValueError('Source file is too large')
                chunks=[];n=0
                for block in r.iter_content(65536):
                    self.check_time();n+=len(block)
                    if n>MAX_BYTES:raise ValueError('Source file is too large')
                    chunks.append(block)
                return b''.join(chunks),r.headers.get('Content-Type',''),current
            finally:r.close()
        raise ValueError('Too many redirects')

    def robot_allowed(self,url):
        p=urlsplit(url);origin=f'{p.scheme}://{p.netloc}'
        with self.lock:
            if origin in self.robots:
                rule=self.robots[origin];return rule.can_fetch(AGENT,url) if rule else True
        rule=None
        try:
            data,_,_=self.get(origin+'/robots.txt',robots=False)
            rule=RobotFileParser();rule.parse(data.decode('utf-8','replace').splitlines())
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code in (401,403):
                rule=RobotFileParser();rule.parse(['User-agent: *','Disallow: /'])
        except Exception:pass
        with self.lock:self.robots[origin]=rule
        return rule.can_fetch(AGENT,url) if rule else True

    def page(self,url):
        self.check_time()
        with self.lock:
            if url in self.pages:return self.pages[url]
        raw,mime,actual=self.get(url)
        if 'image/' in mime:raise ValueError('Expected a page, got an image')
        soup=BeautifulSoup(raw,'html.parser')
        # Record cache only in memory; no source page text is republished.
        with self.lock:self.pages[url]=(soup,actual)
        return soup,actual

    def best_image(self,url):
        best=None;last=None
        for u in originals(url):
            try:
                raw,mime,actual=self.get(u);info=image_info(raw,mime)
                if best is None or info['vector'] or info['width']*info['height']>best[1]['width']*best[1]['height']: best=(raw,info,actual)
                if info['vector']:break
            except Exception as e:last=e
        if best:return best
        raise ValueError(str(last or 'No valid image'))

    def logo(self,team):
        best=None;errors=[]
        def accept(url,page):
            nonlocal best
            try:
                raw,info,actual=self.best_image(url)
                if best is None or info['vector'] or info['width']*info['height']>best[1]['width']*best[1]['height']:
                    best=(raw,info,{'source':actual,'page':page,'label':'Official representative team mark','visualVerified':False})
            except Exception as e:errors.append(str(e))
        for u in team.get('logos',[]):
            accept(u,team.get('logoSourcePage') or team.get('official',''))
            if best and best[1]['vector']:return best
        # A small roster icon is a fallback, not advertised as high resolution.
        for rule in team.get('logoDiscovery',[]):
            if best and (best[1]['vector'] or max(best[1]['width'],best[1]['height'])>=1200):break
            try:
                soup,base=self.page(rule['page']);out=[]
                for im in soup.select('img'):
                    for u in image_urls(im,base):
                        desc=' '.join([str(im.get('alt','')),str(im.get('title','')),unquote(u)]).lower()
                        if not any(tok.lower() in desc for tok in rule.get('tokens',[])):continue
                        if re.search(r'favicon|sponsor|anniversary|spinner|placeholder|\b(?:30|50|100)th',desc):continue
                        if rule.get('requireLogo') and not re.search(r'logo|emblem|crest|team|\u968a\u5fbd',desc,re.I):continue
                        if rule.get('headerOnly') and not im.find_parent('header') and not re.search(r'logo|brand',desc):continue
                        out.append(u)
                for u in uniq(out)[:3]:accept(u,base)
            except Exception as e:errors.append(str(e))
        if best:return best
        raise ValueError('; '.join(errors[-2:]) or 'No verified official logo URL found')

    def jersey(self,team):
        errors=[]
        if team.get('jerseyDirect'):
            try:
                raw,info,url=self.best_image(team['jerseyDirect'])
                if not info['vector'] and min(info['width'],info['height'])<160:raise ValueError('Jersey image too small')
                return raw,info,{'source':url,'page':team.get('jerseyPage',''),'label':team.get('jerseyLabel') or 'Representative jersey','frontStatus':'previously-reviewed' if team.get('jerseyFrontVerified') else 'direct-source-needs-review','visualVerified':bool(team.get('jerseyFrontVerified'))}
            except Exception as e:errors.append(str(e))
        bases=uniq(team.get('jerseyPages',[])+[team.get('jerseyPage','')]);products=[];seen=set();count=0
        exclusive=bool(team.get('jerseyTeamExclusive'))
        def scan(url,depth=0):
            nonlocal count
            if url in seen or count>=self.max_pages:return
            seen.add(url);count+=1
            try:
                soup,base=self.page(url)
            except Exception as e:errors.append(str(e));return
            if PRODUCT_URL.search(base):products.append((500,base,soup))
            follows=[]
            for a in soup.select('a[href]'):
                link=urljoin(base,a['href']);im=a.find('img')
                if not link.startswith('https://'):continue
                text=' '.join([a.get_text(' ',strip=True),str(a.get('title','')),str(im.get('alt','')) if im else '',unquote(link).replace('-',' ')])
                score=product_score(text,team,exclusive)
                if PRODUCT_URL.search(link) and score>=0:products.append((score,link,None))
                elif depth<1 and (PRODUCT_WORD.search(text) or re.search(r'official.?shop|\u516c\u5f0f\u30b7\u30e7\u30c3\u30d7|\u5546\u57ce|\u5546\u54c1|\u7dda\u4e0a\u8cfc\u7269|\uad7f\uc988|\uc628\ub77c\uc778\s*\uc1fc\ud551',text,re.I)):
                    follows.append((score,link))
            if depth<1 and not products:
                for _,u in sorted(follows,reverse=True)[:3]:scan(u,depth+1)
        for u in bases[:4]:
            scan(u)
            if products:break
        # NBA catalogue pages have team-labelled Icon / Association links.
        products=sorted(products,key=lambda x:x[0],reverse=True)
        tried=set()
        for _,url,doc in products:
            if url in tried:continue
            tried.add(url)
            if len(tried)>5:break
            try:
                soup,base=(doc,url) if doc is not None else self.page(url)
                cs=jersey_candidates(soup,base,team,exclusive)
                if not cs and 'basketballjerseyarchive.com' in base:
                    # Image archive is used only for an identified team jersey page.
                    h=soup.find('h1');title=h.get_text(' ',strip=True) if h else ''
                    if team_match(title+' '+unquote(base).replace('-',' '),team) and PRODUCT_WORD.search(title+' '+base):
                        for a in soup.select('a[href]'):
                            u=urljoin(base,a['href'])
                            if '/image/' in u and re.search(r'\.(png|jpe?g|webp)(?:\?|$)',u,re.I) and not BACK_WORD.search(u):
                                cs.append({'url':u,'page':base,'label':title,'frontStatus':'catalogue-primary-needs-review','visualVerified':False})
                        og=soup.find('meta',property='og:image')
                        if og:cs.append({'url':urljoin(base,og.get('content','')),'page':base,'label':title,'frontStatus':'catalogue-primary-needs-review','visualVerified':False})
                for c in cs[:3]:
                    try:
                        raw,info,actual=self.best_image(c['url'])
                        if info['vector'] or min(info['width'],info['height'])<160:continue
                        return raw,info,dict(c,source=actual)
                    except Exception as e:errors.append(str(e))
            except Exception as e:errors.append(str(e))
        raise ValueError('; '.join(errors[-2:]) or 'No matching front/primary jersey product found; no arbitrary page image substituted')

    def one(self,team,kind):
        key=f'{team["id"]}:{kind}';old=self.old.get(key)
        signature=hashlib.sha256(json.dumps({k:v for k,v in team.items() if k not in ['index','qualityPolicy']},sort_keys=True).encode()).hexdigest()
        if old and not self.refresh and old.get('inputHash')==signature:
            cached=self.cache/old['path']
            if cached.is_file() and hashlib.sha256(cached.read_bytes()).hexdigest()==old.get('sha256'):
                target=self.output/old['path'];target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(cached,target)
                return key,dict(old,cached=True),None
        try:
            raw,info,meta=self.logo(team) if kind=='logo' else self.jersey(team)
            digest=hashlib.sha256(raw).hexdigest();rel=f'assets/images/{team["id"]}-{kind}-{digest[:14]}.{info["ext"]}'
            for root in [self.output,self.cache]:
                p=root/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
            result={k:v for k,v in meta.items() if k not in ['score','url']}
            result.update(info,path=rel,sha256=digest,inputHash=signature,teamId=team['id'],kind=kind,downloadedAt=datetime.now(timezone.utc).isoformat(),upscaled=False)
            result['lowResolution']=not info['vector'] and max(info['width'],info['height'])<(1000 if kind=='logo' else 2000)
            LOG.info('%s %s %sx%s %s',team['id'],kind,info['width'],info['height'],info['ext'])
            return key,result,None
        except Exception as e:
            error={'teamId':team['id'],'kind':kind,'reason':str(e)[:450]}
            # Keep an actual previously downloaded original, never delete it on a transient failure.
            if old and (self.cache/old['path']).is_file():
                p=self.output/old['path'];p.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(self.cache/old['path'],p)
                return key,dict(old,cached=True,refreshFailed=True),error
            LOG.warning('%s %s unavailable: %s',team['id'],kind,error['reason'])
            return key,None,error


def collect(manifest,output,cache,workers=6,seconds=720,refresh=False,leagues=None):
    teams=[t for t in manifest['teams'] if not leagues or t['league'] in leagues]
    c=Collector(output,cache,time.monotonic()+seconds,refresh)
    assets={};errors=[]
    # Logos first: even if jersey searches are blocked, usable questions survive.
    for kind in ['logo','jersey']:
        with futures.ThreadPoolExecutor(max_workers=workers) as pool:
            jobs=[pool.submit(c.one,t,kind) for t in teams]
            for job in futures.as_completed(jobs):
                key,asset,err=job.result()
                if asset:assets[key]=asset
                if err:errors.append(err)
    result={'version':6,'builtAt':datetime.now(timezone.utc).isoformat(),'rosterAsOf':manifest.get('rosterAsOf'),'assets':assets,'errors':errors,'summary':{'teams':len(teams),'logos':sum(k.endswith(':logo') for k in assets),'jerseys':sum(k.endswith(':jersey') for k in assets),'complete':sum(f'{t["id"]}:logo' in assets and f'{t["id"]}:jersey' in assets for t in teams),'lowResolution':sum(a['lowResolution'] for a in assets.values())}}
    (output/'data/assets.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    merged=dict(c.old);merged.update(assets)
    (cache/'manifest.json').write_text(json.dumps(dict(result,assets=merged),ensure_ascii=False),encoding='utf-8')
    with (output/'data/image-report.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f);w.writerow(['team','name','kind','downloaded','width','height','vector','low_resolution','front_status','source','error'])
        for t in teams:
            for kind in ['logo','jersey']:
                a=assets.get(f'{t["id"]}:{kind}',{});e=next((x['reason'] for x in errors if x['teamId']==t['id'] and x['kind']==kind),'')
                w.writerow([t['id'],t['zh'],kind,bool(a),a.get('width',''),a.get('height',''),a.get('vector',''),a.get('lowResolution',''),a.get('frontStatus',''),a.get('source',''),e])
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--sources',type=Path,default=Path('data/sources.json'));p.add_argument('--output',type=Path,default=Path('_site'));p.add_argument('--cache',type=Path,default=Path('.image-cache'))
    p.add_argument('--workers',type=int,default=6);p.add_argument('--seconds',type=int,default=720);p.add_argument('--refresh',action='store_true');p.add_argument('--leagues',nargs='+');p.add_argument('--allow-empty',action='store_true')
    args=p.parse_args();logging.basicConfig(level=logging.INFO,format='%(levelname)s %(message)s')
    manifest=json.loads(args.sources.read_text(encoding='utf-8'))
    result=collect(manifest,args.output,args.cache,max(1,min(args.workers,12)),args.seconds,args.refresh,args.leagues)
    print(json.dumps(result['summary'],indent=2))
    summary_path=__import__('os').environ.get('GITHUB_STEP_SUMMARY')
    if summary_path:
        s=result['summary']
        with open(summary_path,'a',encoding='utf-8') as f:
            f.write(f'## TEAM / ID image build\n\nDownloaded logos: **{s["logos"]}/{s["teams"]}**  \nJerseys: **{s["jerseys"]}/{s["teams"]}**  \nComplete pairs: **{s["complete"]}**  \nLow-resolution sources: **{s["lowResolution"]}**\n\nMissing assets and provenance are in `data/image-report.csv`. No originals are upscaled. Automatically selected catalogue views require visual review.\n')
    if result['summary']['logos']==0 and not args.allow_empty:
        raise SystemExit('No logos downloaded. Deployment stopped to avoid publishing an empty quiz. Download the image-report artifact and inspect the errors.')

if __name__=='__main__':main()
