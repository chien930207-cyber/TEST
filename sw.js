/* Immutable image filenames; network-first HTML and manifests avoid stale builds. */
const CACHE='team-id-v6.0.0';
self.addEventListener('install',()=>self.skipWaiting());
self.addEventListener('activate',e=>e.waitUntil((async()=>{for(const key of await caches.keys())if(key.startsWith('team-id-')&&key!==CACHE)await caches.delete(key);await self.clients.claim();})()));
self.addEventListener('fetch',event=>{
 const u=new URL(event.request.url);if(event.request.method!=='GET'||u.origin!==self.location.origin)return;
 const immutable=u.pathname.includes('/assets/images/');
 event.respondWith((async()=>{const cache=await caches.open(CACHE);if(immutable){const hit=await cache.match(event.request);if(hit)return hit;}
 try{const r=await fetch(event.request);if(r.ok&&r.type==='basic')await cache.put(event.request,r.clone());return r;}
 catch(e){const hit=await cache.match(event.request);if(hit)return hit;throw e;}})());
});
