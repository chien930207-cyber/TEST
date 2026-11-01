#!/usr/bin/env python3
"""Copy public files only. Never publish scripts, caches, or repository metadata."""
from pathlib import Path
import shutil
ROOT=Path(__file__).resolve().parents[1]
SITE=ROOT/'_site'
if SITE.exists():shutil.rmtree(SITE)
SITE.mkdir()
for name in ['index.html','help.html','legal.html','favicon.svg','site.webmanifest','sw.js']:
    shutil.copy2(ROOT/name,SITE/name)
for name in ['assets','data']:
    shutil.copytree(ROOT/name,SITE/name,dirs_exist_ok=True)
(SITE/'.nojekyll').write_text('')
print('Prepared _site. Build scripts and caches are excluded.')
