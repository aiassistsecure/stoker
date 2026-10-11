/* Shared Stoker frontend helpers. Cookie sessions — no tokens in JS. */
async function api(path, opts={}){
  const r=await fetch(path,{credentials:'same-origin',
    headers:{'Content-Type':'application/json',...(opts.headers||{})},
    ...opts});
  if(r.status===401){document.getElementById('login').classList.remove('hidden');throw new Error('unauthorized');}
  if(!r.ok){const e=await r.json().catch(()=>({}));throw new Error(e.error?.message||r.statusText);}
  return r.json();
}
async function doLogin(){
  const token=document.getElementById('token').value;
  const r=await fetch('/api/v1/auth/login',{method:'POST',credentials:'same-origin',
    headers:{'Content-Type':'application/json'},body:JSON.stringify({token})});
  if(r.ok){document.getElementById('login').classList.add('hidden');tick&&tick();}
  else alert('Invalid token');
}
function setText(id,v){const el=document.getElementById(id);if(el)el.textContent=v;}
function fmtGB(b){return (b/1073741824).toFixed(1)+' GB';}
// Track foreground/background for reconnect (Oracle P2-9)
let lastVisible=Date.now();
document.addEventListener('visibilitychange',()=>{
  if(!document.hidden){lastVisible=Date.now();tick&&tick();}
});
