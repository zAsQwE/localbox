(function(){
if(window.__lbxAdmin)return;window.__lbxAdmin=1;
var ws=null,code=null,ents=Object.create(null),players=[],me=null,appTag='',open=false,authed=false,nick='',poll=null;
var hints={answers:[],prices:[],contentCount:0},rooms=[],startAuth=null,retry=null;
var SHOWANS=!(window.__lbxCfg&&window.__lbxCfg.showAnswer===false);   // показывать «правильный ответ» (настройка)
var SHOWPRICE=!(window.__lbxCfg&&window.__lbxCfg.showPrice===false);  // показывать цену картины (Дуракцион)
var HILITE=!(window.__lbxCfg&&window.__lbxCfg.highlight===false);     // подсвечивать правильную кнопку в игре
var OWS=window.WebSocket;
function identify(n,c){if(!n||!c)return;if(n!==nick||c!==code){nick=n;code=c;ents=Object.create(null);hints={answers:[],prices:[],contentCount:0};if(startAuth)startAuth();}}
// Ecast controllers pass their identity in the URL; Blobcast sends JoinRoom after opening the socket.
function Patched(url,protocols){
 var socket=protocols!==undefined?new OWS(url,protocols):new OWS(url);
 try{var parsed=new URL(String(url),location.href);var match=parsed.pathname.match(/[/]api[/]v2[/]rooms[/]([^/]+)[/]play$/);
  if(match&&parsed.searchParams.get('role')!=='host')identify(parsed.searchParams.get('name'),decodeURIComponent(match[1]));
  if(/[/]socket[.]io[/]/.test(parsed.pathname)){var originalSend=socket.send;
   socket.send=function(data){try{if(typeof data==='string'&&data.slice(0,4)==='5:::'){
    var packet=JSON.parse(data.slice(4));var args=Array.isArray(packet.args)?packet.args:[packet.args];
    args.forEach(function(arg){if(arg&&arg.action==='JoinRoom')identify(arg.name,arg.roomId);});}}catch(_){}
    return originalSend.call(socket,data);};}
  socket.addEventListener('message',function(event){try{var msg=JSON.parse(event.data);
   if(match&&msg.opcode==='client/welcome'&&msg.result&&msg.result.name)identify(msg.result.name,decodeURIComponent(match[1]));}catch(_){}});
 }catch(_){}
 return socket;
}
Patched.prototype=OWS.prototype;Object.setPrototypeOf(Patched,OWS);
try{Object.defineProperty(window,'WebSocket',{value:Patched,writable:true,configurable:true});}catch(_){}
function boot(){
var css=[
'#lbxa,#lbxa *{box-sizing:border-box;font-family:system-ui,sans-serif}',
'#lbxa{position:fixed;top:0;right:0;height:100%;z-index:2147483647;pointer-events:none}',
'#lbxaTab{position:fixed;top:36%;right:0;background:#7c5cff;color:#fff;padding:9px 6px 8px;border-radius:10px 0 0 10px;cursor:pointer;font-size:12px;writing-mode:vertical-rl;text-align:center;pointer-events:auto;box-shadow:-2px 0 8px rgba(0,0,0,.4)}',
'#lbxaX{writing-mode:horizontal-tb;font-size:10px;opacity:.75;margin-bottom:5px;cursor:pointer}',
'#lbxaP{position:fixed;top:0;right:-390px;width:380px;max-width:92vw;height:100%;background:#141024;color:#e7e2f5;overflow:auto;transition:right .2s;pointer-events:auto;padding:12px;font-size:13px;box-shadow:-4px 0 16px rgba(0,0,0,.5)}',
'#lbxaP.on{right:0}',
'#lbxa input,#lbxa textarea,#lbxa button{font:inherit;background:#221c38;color:#e7e2f5;border:1px solid #372f57;border-radius:7px;padding:6px 8px}',
'#lbxa button{background:#7c5cff;border:0;color:#fff;cursor:pointer;padding:5px 9px;margin:2px 2px 2px 0}',
'#lbxa button.g{background:#2a2440}#lbxa button.bad{background:#e23b6d}#lbxa button.ok{background:#1fae8c}',
'#lbxa h3{margin:12px 0 4px;font-size:13px;color:#b7a6ff}',
'#lbxa .row{display:flex;gap:5px;align-items:center;flex-wrap:wrap;margin:3px 0}',
'#lbxa .ans{background:#1c2b1c;border:1px solid #2f5c2f;border-radius:8px;padding:6px 8px;margin:4px 0}',
'#lbxa .ans b{color:#7fe08a}',
'#lbxa textarea{width:100%;min-height:34px;font-family:monospace;font-size:12px}',
'#lbxa .k{font-family:monospace;color:#b7a6ff;font-size:11px;word-break:break-all}',
'#lbxa .mut{color:#8f88a8;font-size:11px}',
'#lbxa .card{background:#1b1630;border-radius:9px;padding:8px;margin:6px 0}',
// Пульсирующий ценник у картины (Дуракцион). Немного пульсирует, не перехватывает клики.
'#lbxPrice{position:fixed;z-index:2147483646;background:#ffd23f;color:#241a00;font:800 15px/1 system-ui,sans-serif;padding:4px 9px;border-radius:10px;pointer-events:none;box-shadow:0 2px 10px rgba(0,0,0,.55);white-space:nowrap;animation:lbxPulse 1.5s ease-in-out infinite;transform-origin:center}',
'@keyframes lbxPulse{0%,100%{transform:scale(1)}50%{transform:scale(1.08)}}',
// Подсветка кнопки правильного ответа прямо в игре (зелёное свечение + лёгкая пульсация).
'.lbxCorrect{outline:3px solid #24e07a !important;outline-offset:-2px !important;border-radius:10px !important;animation:lbxGlow 1.25s ease-in-out infinite !important}',
'@keyframes lbxGlow{0%,100%{box-shadow:0 0 0 2px rgba(36,224,122,.5),0 0 10px 2px rgba(36,224,122,.55)}50%{box-shadow:0 0 0 4px rgba(36,224,122,.85),0 0 24px 5px rgba(36,224,122,.9)}}'
].join('');
var st=document.createElement('style');st.textContent=css;(document.head||document.documentElement).appendChild(st);
var root=document.createElement('div');root.id='lbxa';root.style.display='none';
root.innerHTML='<div id="lbxaTab"><div id="lbxaX">✕</div>🎛 читы</div><div id="lbxaP"></div>';
(document.body||document.documentElement).appendChild(root);
var tab=root.querySelector('#lbxaTab'),panel=root.querySelector('#lbxaP'),hideBtn=root.querySelector('#lbxaX');
tab.onclick=function(e){if(e.target===hideBtn)return;open=!open;panel.classList.toggle('on',open);if(open)render();};
hideBtn.onclick=function(e){e.stopPropagation();open=false;panel.classList.remove('on');root.style.display='none';};
function esc(s){return String(s==null?'':s).replace(/[&<>]/g,function(x){return{'&':'&amp;','<':'&lt;','>':'&gt;'}[x];});}
function fmt(v){try{return typeof v==='string'?v:JSON.stringify(v,null,1);}catch(_){return String(v);}}
function tryAuth(){if(!nick)return;clearTimeout(retry);if(poll){clearInterval(poll);poll=null;}
 var old=ws;ws=null;try{old&&old.close();}catch(_){}authed=false;
 var url=(location.protocol==='https:'?'wss':'ws')+'://'+location.host+'/admin/ws?nick='+encodeURIComponent(nick);
 var current;try{current=ws=new OWS(url);}catch(_){return;}
 current.onmessage=function(e){if(ws!==current)return;try{handle(JSON.parse(e.data));}catch(_){}};
 current.onclose=function(){if(ws!==current)return;var connected=authed;authed=false;hints={answers:[],prices:[],contentCount:0};
  highlightAnswer();pinPrice();if(poll){clearInterval(poll);poll=null;}if(connected)retry=setTimeout(tryAuth,1500);};
}
startAuth=tryAuth;
function sendc(o){if(!ws||ws.readyState!==1)return;if(!o.code)o.code=code;ws.send(JSON.stringify(o));}
function watch(c){code=c;ents=Object.create(null);hints={answers:[],prices:[],contentCount:0};sendc({cmd:'watch',code:c});}
function handle(m){
 if(m.t==='ok'){authed=true;rooms=m.rooms||[];root.style.display='';
   if(code&&rooms.some(function(r){return r.code===code;}))watch(code);else if(rooms.length===1)watch(rooms[0].code);else code=null;
   render();if(!poll)poll=setInterval(function(){sendc({cmd:'rooms'});if(code)sendc({cmd:'players'});},3000);}
 else if(m.t==='rooms'){rooms=m.rooms||[];if(!code&&rooms.length===1)watch(rooms[0].code);
   if(code&&!rooms.some(function(r){return r.code===code;})){code=null;ents=Object.create(null);hints={answers:[],prices:[],contentCount:0};}scheduleRender();}
 else if(m.t==='err'){window.__lbxErr=m.msg;if(!authed){if(window.__lbxManual)render();else root.style.display='none';}}
 else if(m.t==='snapshot'){code=m.code;ents=Object.assign(Object.create(null),m.entities||{});players=m.players;appTag=m.appTag||'';hints=m.hints||{answers:[],prices:[],contentCount:0};
  var now=Date.now();Object.keys(ents).forEach(function(k){ents[k]._t=now;});setMe();render();highlightAnswer();pinPrice();}
 else if(m.t==='hints'){hints=m.hints;highlightAnswer();pinPrice();scheduleRender();}
 else if(m.t==='players'){players=m.players;setMe();scheduleRender();}
 else if(m.t==='entity'){ents[m.key]={type:m.type,body:m.body,_t:Date.now()};scheduleRender();}
 else if(m.t==='drop'){delete ents[m.key];scheduleRender();}
}
function setMe(){me=players.filter(function(p){return (p.name||'').toLowerCase()===nick.toLowerCase();})[0]||null;}
function mine(){return Object.keys(ents).filter(function(k){var lk=k.toLowerCase();
 var isAns=/(answer|response|submission|recording|lie|text|entry|guess)/.test(lk);
 var mineId=me&&(k.indexOf(':'+me.id)>=0||new RegExp('[^0-9]'+me.id+'$').test(k));
 return isAns&&(mineId|| /:my|self/.test(lk));});}
function setBtn(key){var e=ents[key];var v=e&&e.body&&e.body.val;var ta=document.createElement('textarea');ta.value=fmt(v);
 var b=document.createElement('button');b.className='ok';b.textContent='сменить';
 b.onclick=function(){var val;try{val=JSON.parse(ta.value);}catch(_){val=ta.value;}sendc({cmd:'set',key:key,val:val,type:e.type,from:e.body&&e.body.from});};
 var wrap=document.createElement('div');wrap.appendChild(ta);wrap.appendChild(b);return wrap;}
// Prices are tied to the painting title, never to an arbitrary numeric field or largest canvas.
function prices(){return hints.prices||[];}
function pinPrice(){var tag=document.getElementById('lbxPrice');
 if(!SHOWPRICE||!authed||!/auction|bidiots/i.test(appTag)){if(tag)tag.style.display='none';return;}
 var ps=prices(),best=null,price=null;
 var nodes=document.querySelectorAll('#page-auction h1,#page-auction h2,#page-auction h3,#page-auction .title,#page-auction #title,[data-artwork-title]');
 for(var i=0;i<nodes.length;i++){var el=nodes[i],r=el.getBoundingClientRect();if(!r.width||!r.height)continue;
  var title=normT(el.getAttribute('data-artwork-title')||el.textContent);
  for(var j=0;j<ps.length;j++)if(title===normT(ps[j].title)){best=el;price=ps[j];break;}
  if(price)break;
 }
 if(!price){if(tag)tag.style.display='none';return;}
 if(!tag){tag=document.createElement('div');tag.id='lbxPrice';document.body.appendChild(tag);}
 tag.style.display='';tag.textContent='💰 '+price.value;
 var rect=best.getBoundingClientRect();tag.style.left=Math.max(2,Math.min(window.innerWidth-(tag.offsetWidth||64)-2,rect.right-(tag.offsetWidth||64)))+'px';tag.style.top=Math.max(2,rect.bottom+4)+'px';
}
function normT(s){var node=document.createElement('div');node.innerHTML=String(s==null?'':s).replace(/<blank\s*\/?\s*>|\[blank\]|_{2,}/gi,' BLANK ').replace(/\[\/?(?:i|b|u|s|br|color|size)(?:=[^\]]*)?\]/gi,'');
 return (node.textContent||'').replace(/[‘’]/g,"'").replace(/[“”]/g,'"').replace(/\s+/g,' ').trim().normalize('NFKC').toUpperCase();}
function relevantAnswers(){var all=hints.answers||[];if(!me)return all.filter(function(a){return a.entity==='bc:room'||!/^(bc:customer:|player[:\d])/.test(a.entity);});
 return all.filter(function(a){var k=a.entity;return k==='bc:room'||k==='bc:customer:'+me.userId||k==='player:'+me.id||k==='player'+me.id||k==='player:'+me.userId||!/^(bc:customer:|player[:\d])/.test(k);});}
function correctTexts(){var out=[];relevantAnswers().forEach(function(a){a.texts.forEach(function(t){var n=normT(t);if(n&&out.indexOf(n)<0)out.push(n);});});return out;}
// Подсветить прямо в игре кнопку/элемент, чей текст совпадает с правильным ответом.
function highlightAnswer(){
 document.querySelectorAll('.lbxCorrect').forEach(function(el){el.classList.remove('lbxCorrect');});
 if(!HILITE||!authed)return;var texts=correctTexts();if(!texts.length)return;
 document.querySelectorAll('button,[role=button],.choice-button,.make-many-choices-button,input[type=checkbox]+label').forEach(function(el){
  if(el.closest('#lbxa'))return;var rect=el.getBoundingClientRect();if(!rect.width||!rect.height)return;
  var t=normT(el.textContent);if(t&&texts.indexOf(t)>=0)el.classList.add('lbxCorrect');
 });
}
function render(){
 if(!open)return;
 if(authed&&panel.contains(document.activeElement)&&document.activeElement.matches('textarea,input:not(#lbxaF)'))return;
 if(!authed){ // форма входа (по секретной комбинации Ctrl+Shift+K, если авто-детект не сработал)
   var hl=document.createElement('div');hl.innerHTML='<b>🎛 вход в читы</b>';
   var rl=document.createElement('div');rl.className='row';
   var inp=document.createElement('input');inp.placeholder='твой ник (админа)';inp.value=nick||'';inp.style.flex='1';
   inp.oninput=function(){nick=inp.value.trim();};inp.onkeydown=function(e){if(e.key==='Enter')tryAuth();};
   var b=document.createElement('button');b.textContent='войти';b.onclick=tryAuth;
   rl.appendChild(inp);rl.appendChild(b);hl.appendChild(rl);
   if(window.__lbxErr){var er=document.createElement('div');er.className='mut';er.textContent=window.__lbxErr;hl.appendChild(er);}
   panel.innerHTML='';panel.appendChild(hl);setTimeout(function(){try{inp.focus();}catch(_){}}, 0);return;
 }
 var h=document.createElement('div');
 var top=document.createElement('div');top.className='row';
 top.innerHTML='<b>🎛 читы</b> <span class="mut">'+esc(appTag||'')+(code?' · '+code:'')+'</span>';
 var cx=mkb('✕','g',function(){open=false;panel.classList.remove('on');});cx.style.marginLeft='auto';top.appendChild(cx);
 h.appendChild(top);
 var choose=document.createElement('select');choose.style.width='100%';
 var empty=document.createElement('option');empty.value='';empty.textContent='Выбрать комнату';choose.appendChild(empty);
 rooms.forEach(function(r){var option=document.createElement('option');option.value=r.code;option.textContent=r.code+' · '+r.appTag;choose.appendChild(option);});choose.value=code||'';
 choose.onchange=function(){if(choose.value)watch(choose.value);};h.appendChild(choose);
 if(!code){var wait=document.createElement('p');wait.textContent='Создай комнату в игре или выбери её из списка.';h.appendChild(wait);panel.innerHTML='';panel.appendChild(h);return;}
 // Blobcast (Бредовуха/Смертельная Вечеринка/Голову ты не забыл и др.): что ввёл/выбрал КАЖДЫЙ.
 // Блобы игроков (bc:customer:*) видны админу целиком (в обход ACL) — видно чужое враньё/выборы.
 var bcKeys=Object.keys(ents).filter(function(k){return k.indexOf('bc:customer:')===0;});
 var room=(ents['bc:room']&&ents['bc:room'].body&&ents['bc:room'].body.val)||{};
 if(bcKeys.length||room.question){
   var hb=document.createElement('h3');hb.textContent='👥 Ответы игроков';h.appendChild(hb);
   if(room.question){var q=document.createElement('div');q.className='card';q.innerHTML='<b>Вопрос:</b> '+esc(room.question);h.appendChild(q);}
   var roomCh=Array.isArray(room.choices)?room.choices:null;
   if(roomCh&&roomCh.length){var rc=document.createElement('div');rc.className='mut';
     rc.textContent='Варианты: '+roomCh.map(function(x){return typeof x==='string'?x:(x.text||x.html||JSON.stringify(x));}).join(' · ');h.appendChild(rc);}
   var entered=[];
   bcKeys.forEach(function(k){var v=ents[k].body.val||{};
     var nm=v.playerName||v.displayName||(v.playerInfo&&v.playerInfo.username)||k.slice(12,20);
     var said=v.entry||v.lieEntered||v.chosen||(v.choice&&(v.choice.text||v.choice))||'';
     if(said&&typeof said==='string')entered.push(said.toUpperCase());
     var extra=v.state?(' <span class="mut">'+esc(v.state)+'</span>'):'';
     var d=document.createElement('div');d.className='ans';
     d.innerHTML=esc(nm)+': '+(said?('<b>'+esc(typeof said==='string'?said:JSON.stringify(said))+'</b>'):'<span class="mut">—</span>')+extra;
     h.appendChild(d);});
 }
 if(SHOWANS){var ans=relevantAnswers();
 var ha=document.createElement('h3');ha.textContent='✔ Правильные ответы';h.appendChild(ha);
 if(!ans.length){var mm=document.createElement('div');mm.className='mut';
  mm.textContent='Ответ для текущего вопроса не найден. '+(hints.contentCount?'Проверь, что выбрана папка с той же версией и переводом игры.':'Укажи папку установленной игры в настройках LocalBox, чтобы читать ответы из её файлов.');h.appendChild(mm);}
 ans.forEach(function(o){var d=document.createElement('div');d.className='ans';
  var question=document.createElement('div');question.className='mut';question.textContent=normT(o.question);d.appendChild(question);
  var answer=document.createElement('b');answer.textContent=o.texts.map(function(t){return normT(t);}).join(' / ');d.appendChild(answer);
  var source=document.createElement('div');source.className='mut';source.textContent=o.method==='content'?'Из файлов установленной игры':'Передано игрой';d.appendChild(source);h.appendChild(d);});}
 if(SHOWPRICE){var pr=prices();if(!pr.length&&/auction|bidiots/i.test(appTag)){var noPrice=document.createElement('p');noPrice.className='mut';noPrice.textContent='Игра ещё не передала оценки картин.';h.appendChild(noPrice);}if(pr.length){var hpp=document.createElement('h3');hpp.textContent='💰 Цены картин ('+pr.length+')';h.appendChild(hpp);
   pr.forEach(function(o){var d=document.createElement('div');d.className='ans';d.style.borderColor='#ffd23f';
     d.innerHTML='<b>'+esc(String(o.value))+'</b> <span class="mut">'+esc(o.title)+'</span>';h.appendChild(d);});}}
 var mk=mine();if(mk.length){var hm=document.createElement('h3');hm.textContent='✏️ Мой ответ (сменить)';h.appendChild(hm);
   mk.forEach(function(k){var c=document.createElement('div');c.className='card';c.innerHTML='<div class="k">'+esc(k)+'</div>';c.appendChild(setBtn(k));h.appendChild(c);});}
 var hp=document.createElement('h3');hp.textContent='🔨 Игроки ('+players.filter(function(p){return p.role!=='host';}).length+')';h.appendChild(hp);
 players.forEach(function(p){if(p.role==='host')return;var r=document.createElement('div');r.className='row';
   r.innerHTML='<span>'+esc(p.name)+' <span class="mut">#'+p.id+(p.muted?' 🔇':'')+'</span></span>';
   r.appendChild(mkb('кик','bad',function(){sendc({cmd:'kick',id:p.id});}));
   r.appendChild(mkb('бан','bad',function(){sendc({cmd:'kick',id:p.id,ban:true});}));
   r.appendChild(mkb(p.muted?'размьют':'мьют','g',function(){sendc({cmd:'mute',id:p.id,on:!p.muted});}));
   h.appendChild(r);});
 var hg=document.createElement('h3');hg.textContent='👁 Все сущности';h.appendChild(hg);
 var f=document.createElement('input');f.id='lbxaF';f.placeholder='фильтр…';f.style.width='100%';f.value=window.__lbxF||'';
 f.oninput=function(){window.__lbxF=f.value;window.__lbxFocus=true;scheduleRender();};
 f.onblur=function(){window.__lbxFocus=false;};h.appendChild(f);
 var flt=(window.__lbxF||'').toLowerCase();
 Object.keys(ents).filter(function(k){return k.toLowerCase().indexOf(flt)>=0;}).sort(function(a,b){return (ents[b]._t||0)-(ents[a]._t||0)||(a<b?-1:1);}).slice(0,60).forEach(function(k){
   var c=document.createElement('div');c.className='card';c.innerHTML='<div class="k">'+esc(k)+' <span class="mut">'+esc(ents[k].type)+'</span></div>';
   c.appendChild(setBtn(k));h.appendChild(c);});
 panel.innerHTML='';panel.appendChild(h);
 if(window.__lbxFocus){var nf=panel.querySelector('#lbxaF');if(nf){nf.focus();try{nf.setSelectionRange(nf.value.length,nf.value.length);}catch(_){}}}
}
function mkb(t,c,fn){var b=document.createElement('button');b.textContent=t;b.className=c;b.onclick=fn;return b;}
var _rt;function scheduleRender(){clearTimeout(_rt);_rt=setTimeout(render,450);}
// Секретный вход, если авто-детект ника не сработал (напр. Бредовуха XL): Ctrl+Shift+K.
document.addEventListener('keydown',function(e){
 if(e.ctrlKey&&e.shiftKey&&(e.key==='K'||e.key==='k'||e.code==='KeyK')){
   window.__lbxManual=true;root.style.display='';open=true;panel.classList.add('on');render();}
},true);
setInterval(function(){pinPrice();highlightAnswer();},600);   // ценник у картины + подсветка правильной кнопки
try{console.log('[LocalBox] оверлей читов загружен. Если панель не появилась сама — Ctrl+Shift+K и введи админ-ник.');}catch(_){}
if(nick)tryAuth();
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();
