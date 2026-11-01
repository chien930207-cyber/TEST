import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from bs4 import BeautifulSoup
from PIL import Image

MODULE=Path(__file__).resolve().parents[1]/'scripts/collect_assets.py'
spec=importlib.util.spec_from_file_location('collector',MODULE);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
TEAM={'id':'MLB-NYY','league':'MLB','en':'New York Yankees','zh':'Yankees','logos':['https://example.com/logo.png'],'jerseyDirect':'https://example.com/jersey.jpg','jerseyLabel':'Home front','jerseyPage':'https://example.com/product/home','jerseyTeamExclusive':True}

def img_bytes(w=1200,h=1500):
    buf=io.BytesIO();Image.new('RGB',(w,h),'white').save(buf,format='PNG');return buf.getvalue()

class CollectorTests(unittest.TestCase):
    def test_original_dimensions_untouched(self):
        data=img_bytes(3200,4000);info=m.image_info(data)
        self.assertEqual((info['width'],info['height']),(3200,4000));self.assertEqual(info['bytes'],len(data))
    def test_original_url_not_upscale(self):
        urls=m.originals('https://fanatics.frgimages.com/team/x_full.jpg?w=1018&h=800&_hv=2')
        self.assertNotIn('w=',urls[0]);self.assertNotIn('h=',urls[0]);self.assertIn('_hv=2',urls[0]);self.assertNotIn('4096',' '.join(urls))
    def test_shopify_original(self):
        self.assertEqual(m.originals('https://store.example.com/cdn/shop/files/x_800x.jpg?width=800')[0],'https://store.example.com/cdn/shop/files/x.jpg')
    def test_reject_error_page(self):
        with self.assertRaises(Exception):m.image_info(b'<html>Access denied</html>','image/png')
    def test_vector_and_unsafe_svg(self):
        self.assertTrue(m.image_info(b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 300"><path d="M0 0h20v20z"/></svg>')['vector'])
        for s in [b'<svg><script>alert(1)</script></svg>',b'<svg onload="alert(1)"/>',b'<svg><image href="https://x/a.png"/></svg>']:
            with self.assertRaises(ValueError):m.image_info(s)
    def test_ssrf_scheme(self):
        for url in ['http://x.com/a','file:///etc/passwd','https://user:pass@example.com/a','https://example.com:81/a']:
            with self.assertRaises(ValueError):m.public_url(url,resolve=False)
    def test_ssrf_private_dns(self):
        with patch.object(m.socket,'getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',443))]):
            with self.assertRaises(ValueError):m.public_url('https://example.com/a')
    def test_jersey_not_shirt_or_wrong_team(self):
        self.assertGreater(m.product_score('New York Yankees Nike Home Replica Jersey',TEAM),0)
        self.assertLess(m.product_score('Boston Red Sox Home Jersey',TEAM),0)
        self.assertLess(m.product_score('New York Yankees home t-shirt',TEAM),0)
        self.assertGreater(m.product_score('New York Yankees Home Jersey',TEAM),m.product_score('New York Yankees City Connect Jersey',TEAM))
    def test_front_not_back_or_composite(self):
        s=BeautifulSoup('<h1>New York Yankees Home Replica Jersey</h1><div>Product ID: 1234</div><img alt="front" src="https://fanatics.frgimages.com/a/1234_front.jpg"><img alt="back" src="https://fanatics.frgimages.com/a/1234_back.jpg"><img src="https://fanatics.frgimages.com/a/1234+pv-1.jpg">','html.parser')
        cs=m.jersey_candidates(s,'https://www.mlbshop.com/product/a',TEAM)
        self.assertEqual(len(cs),1);self.assertIn('front',cs[0]['url']);self.assertFalse(cs[0]['visualVerified'])
    def test_same_pixel_bytes_preserved_and_cached(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);data=img_bytes(1600,1800)
            with patch.object(m.Collector,'best_image',return_value=(data,m.image_info(data),'https://example.com/source.png')):
                r=m.collect({'teams':[TEAM]},root/'site',root/'cache',workers=1,seconds=2)
            self.assertEqual(r['summary']['logos'],1);self.assertEqual(r['summary']['jerseys'],1)
            for a in r['assets'].values():self.assertEqual((root/'site'/a['path']).read_bytes(),data)
            with patch.object(m.Collector,'best_image',side_effect=AssertionError('cache should prevent download')):
                r2=m.collect({'teams':[TEAM]},root/'site2',root/'cache',workers=1,seconds=2)
            self.assertEqual(len(r2['assets']),2)
    def test_partial_success_is_retained(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);data=img_bytes()
            with patch.object(m.Collector,'logo',return_value=(data,m.image_info(data),{'source':'https://example.com/a.png'})),patch.object(m.Collector,'jersey',side_effect=ValueError('blocked')):
                r=m.collect({'teams':[TEAM]},root/'site',root/'cache',workers=1,seconds=2)
            self.assertEqual(r['summary']['logos'],1);self.assertEqual(r['summary']['jerseys'],0);self.assertEqual(len(r['errors']),1)
    def test_source_roster_consistency(self):
        p=Path(__file__).resolve().parents[1]/'data/sources.json';d=json.loads(p.read_text())
        self.assertEqual(len(d['teams']),136);self.assertEqual(len({t['id'] for t in d['teams']}),136)
        self.assertEqual(len({t['league'] for t in d['teams']}),9)

if __name__=='__main__':unittest.main()
