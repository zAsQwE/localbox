"use strict";
//
// LocalBox — читы для приватной игры в LAN (оверлей прямо в игре, без отдельной веб-страницы).
//
// Доступ по нику из LOCALBOX_ADMINS (список ников через запятую). Читы встраиваются в игровой
// клиент оверлеем (вкладка справа). Возможности:
//   • God view — видеть ВСЕ сущности комнаты в реальном времени (секретные ответы/голоса/рисунки);
//   • правильный ответ — подсветка (для викторин/Бредовухи); включается LOCALBOX_CHEAT_ANSWER;
//   • подмена — менять значение любой сущности (напр. изменить ответ игрока в Бредовухе);
//   • модерация — кик/бан/мьют/переименование игроков.
//
// Правила игр считает Steam-хост, так что «форснуть победу/очки» нельзя — но текст ответов и
// прочие сущности хост просто хранит, поэтому подмена «прилипает». Только для игры с друзьями.
//

const mgr = require("./room.js");

const ADMINS = new Set((process.env.LOCALBOX_ADMINS || "").split(",").map((s) => s.trim().toLowerCase()).filter(Boolean));
// Показывать в оверлее «правильный ответ» (подсветка для викторин/Бредовухи). Выкл: LOCALBOX_CHEAT_ANSWER=0.
const SHOW_ANSWER = process.env.LOCALBOX_CHEAT_ANSWER !== "0";
// Показывать цену картины (Дуракцион/Bidiots) пульсирующим ценником у картины. Выкл: LOCALBOX_CHEAT_PRICE=0.
const SHOW_PRICE = process.env.LOCALBOX_CHEAT_PRICE !== "0";
// Подсвечивать правильный вариант ПРЯМО НА КНОПКЕ в игре (все викторины). Выкл: LOCALBOX_CHEAT_HIGHLIGHT=0.
const SHOW_HIGHLIGHT = process.env.LOCALBOX_CHEAT_HIGHLIGHT !== "0";
function isAdmin(nick) { return ADMINS.has(String(nick || "").trim().toLowerCase()); }
function enabled() { return ADMINS.size > 0; }
function adminList() { return [...ADMINS]; }

// Подписчики панели: ws -> код комнаты (или null, пока не выбрана).
const subs = new Map();

function playersOf(r) {
    const out = [];
    if (r.host && r.host.profileId != null) out.push({ id: r.host.profileId, name: r.host.name || "(хост)", role: "host" });
    Object.values(r.players).forEach((p) => out.push({
        id: p.profileId, name: p.name, role: p.role,
        muted: !!(r.muted && r.muted.has(p.profileId)), banned: !!p.banned,
    }));
    return out;
}
function entitiesOf(r) {
    const out = {};
    for (const k of Object.keys(r.entities)) {
        try { out[k] = { type: r.entities[k].type, body: r.getBody(k) }; } catch { /* skip */ }
    }
    return out;
}
function roomsSummary() {
    return mgr.list().map((r) => ({ code: r.code, appTag: r.appTag, players: Object.keys(r.players).length }));
}
function send(ws, obj) { try { ws.send(JSON.stringify(obj)); } catch { /* закрыт */ } }

function snapshot(ws, code) {
    const r = mgr.get(code);
    if (!r) return send(ws, { t: "err", msg: "нет комнаты " + code });
    send(ws, { t: "snapshot", code, appTag: r.appTag, players: playersOf(r), entities: entitiesOf(r) });
}

// Хук из room.js — событие по комнате (рассылаем подписчикам этой комнаты).
function onRoomEvent(code, ev) {
    for (const [ws, c] of subs) {
        if (c !== code) continue;
        if (ev.t === "entity") send(ws, { t: "entity", key: ev.body.key, type: ev.type, body: ev.body });
        else if (ev.t === "drop") send(ws, { t: "drop", key: ev.key });
        else if (ev.t === "players") { const r = mgr.get(code); if (r) send(ws, { t: "players", players: playersOf(r) }); }
    }
}

function handleWs(ws, query) {
    if (!isAdmin(query.nick)) { send(ws, { t: "err", msg: "ник «" + (query.nick || "") + "» не в списке админов" }); try { ws.close(); } catch { /* ignore */ } return; }
    subs.set(ws, null);
    send(ws, { t: "ok", nick: query.nick, rooms: roomsSummary() });
    ws.on("message", (data) => {
        let m; try { m = JSON.parse(data.toString()); } catch { return; }
        if (m.cmd === "rooms") return send(ws, { t: "rooms", rooms: roomsSummary() });
        if (m.cmd === "watch") { subs.set(ws, m.code); return snapshot(ws, m.code); }
        const code = m.code || subs.get(ws);
        const r = code && mgr.get(code);
        if (!r) return send(ws, { t: "err", msg: "комната не выбрана/не найдена" });
        try { doCmd(r, m, ws); } catch (e) { send(ws, { t: "err", msg: String((e && e.message) || e) }); }
    });
    ws.on("close", () => subs.delete(ws));
    ws.on("error", () => subs.delete(ws));
}

function doCmd(r, m, ws) {
    switch (m.cmd) {
        case "set": {
            const e = r.entities[m.key];
            if (e) {
                r.updateEntity(m.key, { val: m.val }, m.from != null ? Number(m.from) : e.from);
            } else {
                r.setEntity(m.type || "object", m.key, m.acl || ["rw *"], { val: m.val });
            }
            r.notify(m.key, true, null);
            send(ws, { t: "info", msg: "✔ сущность " + m.key + " обновлена" });
            break;
        }
        case "players": send(ws, { t: "players", players: playersOf(r) }); break;   // авто-обновление ростера
        case "kick": r.kick(Number(m.id), !!m.ban); send(ws, { t: "info", msg: "игрок #" + m.id + (m.ban ? " забанен" : " кикнут") }); break;
        case "mute": r.setMute(Number(m.id), !!m.on); onRoomEvent(r.code, { t: "players" }); send(ws, { t: "info", msg: "мьют #" + m.id + ": " + (m.on ? "вкл" : "выкл") }); break;
        case "rename": r.renamePlayer(Number(m.id), String(m.name || "")); onRoomEvent(r.code, { t: "players" }); send(ws, { t: "info", msg: "переименован #" + m.id }); break;
        default: send(ws, { t: "err", msg: "неизвестная команда " + m.cmd });
    }
}

function mountHttp(app) {
    // Отдельной веб-страницы /admin больше нет — только оверлей, встраиваемый в игровой клиент.
    // В начало оверлея подставляем конфиг (показывать ли «правильный ответ»).
    app.get("/admin/overlay.js", (_req, res) =>
        res.type("application/javascript").send("window.__lbxCfg={showAnswer:" + SHOW_ANSWER + ",showPrice:" + SHOW_PRICE + ",highlight:" + SHOW_HIGHLIGHT + "};\n" + OVERLAY_JS));
}

// Оверлей-панелька, встраиваемая в игровой клиент (client.js вставляет <script src="/admin/overlay.js">).
// Появляется вкладка справа; вводишь ник → если админ, открывается панель с читами прямо в игре.
const OVERLAY_JS = String.raw`(function(){
if(window.__lbxAdmin)return;window.__lbxAdmin=1;
var ws=null,code=null,ents={},players=[],me=null,appTag='',open=false,authed=false,nick='',poll=null;
var SHOWANS=!(window.__lbxCfg&&window.__lbxCfg.showAnswer===false);   // показывать «правильный ответ» (настройка)
var SHOWPRICE=!(window.__lbxCfg&&window.__lbxCfg.showPrice===false);  // показывать цену картины (Дуракцион)
var HILITE=!(window.__lbxCfg&&window.__lbxCfg.highlight===false);     // подсвечивать правильную кнопку в игре
var STRONG=/^(correct|truth|iscorrect|istrue|rightanswer|correctanswer|solution|winner|answertext|secret|realprice|actualprice)$/i;
var WEAK=/(answer|price|cost|value|target|reward|payout|worth)/i;
var OWS=window.WebSocket;
// Перехват WS игры: при входе в игру берём НИК игрока и КОД комнаты из URL play-сокета.
function Patched(url,protocols){try{var u=String(url);var m=u.match(/[/]api[/]v2[/]rooms[/]([^/]+?)[/]play[?](.*)$/);
 if(m){var nm=(m[2].match(/[?&]name=([^&]*)/)||[])[1];
   if(nm){var n=decodeURIComponent(nm.replace(/[+]/g,' '));var c=decodeURIComponent(m[1]);
     if(n&&(n!==nick||c!==code)){nick=n;code=c;tryAuth();}}}}catch(_){}
 return protocols!==undefined?new OWS(url,protocols):new OWS(url);}
Patched.prototype=OWS.prototype;['CONNECTING','OPEN','CLOSING','CLOSED'].forEach(function(k){try{Patched[k]=OWS[k];}catch(_){}});
try{Object.defineProperty(window,'WebSocket',{value:Patched,writable:true,configurable:true});}catch(_){try{window.WebSocket=Patched;}catch(__){}}
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
function tryAuth(){if(!nick)return;try{ws&&ws.close();}catch(_){}authed=false;
 var url=(location.protocol==='https:'?'wss':'ws')+'://'+location.host+'/admin/ws?nick='+encodeURIComponent(nick);
 try{ws=new OWS(url);}catch(_){return;}
 ws.onmessage=function(e){handle(JSON.parse(e.data));};
 ws.onclose=function(){authed=false;if(poll){clearInterval(poll);poll=null;}};}
function sendc(o){if(!ws||ws.readyState!==1)return;o.code=code;ws.send(JSON.stringify(o));}
function handle(m){
 if(m.t==='ok'){authed=true;root.style.display='';if(code)sendc({cmd:'watch',code:code});
   if(!poll)poll=setInterval(function(){if(ws&&ws.readyState===1)sendc({cmd:'players'});},3000);}
 else if(m.t==='err'){window.__lbxErr=m.msg;if(!authed){if(window.__lbxManual)render();else root.style.display='none';}}
 else if(m.t==='snapshot'){code=m.code;ents=m.entities;players=m.players;appTag=m.appTag||appTag;var _n=Date.now();Object.keys(ents).forEach(function(k){ents[k]._t=_n;});setMe();render();}
 else if(m.t==='players'){players=m.players;setMe();scheduleRender();}
 else if(m.t==='entity'){ents[m.key]={type:m.type,body:m.body,_t:Date.now()};scheduleRender();}
 else if(m.t==='drop'){delete ents[m.key];scheduleRender();}
}
function setMe(){me=players.filter(function(p){return (p.name||'').toLowerCase()===nick.toLowerCase();})[0]||null;}
function walk(o,path,out){if(o==null||typeof o!=='object')return;
 if(Array.isArray(o)){o.forEach(function(it,i){
   if(it&&typeof it==='object'&&(it.correct===true||it.isCorrect===true||it.isTrue===true||it.right===true))
     out.push({p:path,h:'✔ правильный',v:it.text||it.label||it.title||it.name||it.answer||JSON.stringify(it)});
   walk(it,path+'['+i+']',out);});return;}
 Object.keys(o).forEach(function(k){var v=o[k];var lk=k.toLowerCase();
   if((lk==='correct'||lk==='iscorrect'||lk==='istrue')&&v===true)
     out.push({p:path,h:'✔ правильный',v:o.text||o.label||o.title||o.answer||JSON.stringify(o)});
   if(typeof v!=='object'){ if(STRONG.test(lk))out.push({p:path+'.'+k,h:'⭐ '+k,v:v}); else if(WEAK.test(lk))out.push({p:path+'.'+k,h:k,v:v}); }
   walk(v,path+'.'+k,out);});}
function sniff(){var out=[];Object.keys(ents).forEach(function(key){try{var pre=out.length;walk(ents[key].body.val,key,out);for(var i=pre;i<out.length;i++)out[i].t=ents[key]._t||0;}catch(_){}});
 out.sort(function(a,b){return (b.t||0)-(a.t||0);});
 var seen={},res=[];out.forEach(function(o){var id=o.p+'='+o.v;if(!seen[id]&&String(o.v).length){seen[id]=1;res.push(o);}});return res;}
function mine(){return Object.keys(ents).filter(function(k){var lk=k.toLowerCase();
 var isAns=/(answer|response|submission|recording|lie|text|entry|guess)/.test(lk);
 var mineId=me&&(k.indexOf(':'+me.id)>=0||new RegExp('[^0-9]'+me.id+'$').test(k));
 return isAns&&(mineId|| /:my|self/.test(lk));});}
function setBtn(key){var e=ents[key];var v=e&&e.body&&e.body.val;var ta=document.createElement('textarea');ta.value=fmt(v);
 var b=document.createElement('button');b.className='ok';b.textContent='сменить';
 b.onclick=function(){var val;try{val=JSON.parse(ta.value);}catch(_){val=ta.value;}sendc({cmd:'set',key:key,val:val,type:e.type,from:e.body&&e.body.from});};
 var wrap=document.createElement('div');wrap.appendChild(ta);wrap.appendChild(b);return wrap;}
// Цены картин (Дуракцион): числовые поля вроде price/value/worth/target из God-view сущностей.
function prices(){var out=[];Object.keys(ents).forEach(function(key){try{(function w(o,p){if(o==null||typeof o!=='object')return;
   Object.keys(o).forEach(function(k){var v=o[k],lk=k.toLowerCase();
     if(typeof v==='number'&&v>0&&/price|value|worth|target/.test(lk)&&!/index|count|round|time|version|max|min|current|^id$|width|height/.test(lk))
       out.push({p:key+' · '+k,v:v,t:ents[key]._t||0});
     w(v,p+'.'+k);});})(ents[key].body&&ents[key].body.val,key);}catch(_){}});
 out.sort(function(a,b){return (b.t||0)-(a.t||0);});
 var seen={},res=[];out.forEach(function(o){if(!seen[o.p]){seen[o.p]=1;res.push(o);}});return res;}
// Пульсирующий ценник рядом с картиной = самый крупный canvas/img/svg на экране (текущая картина).
function pinPrice(){var tag=document.getElementById('lbxPrice');
 if(!SHOWPRICE||!authed){if(tag)tag.style.display='none';return;}
 var ps=prices();if(!ps.length){if(tag)tag.style.display='none';return;}
 var best=null,area=0;
 document.querySelectorAll('canvas,img,svg').forEach(function(el){try{if(el.closest&&el.closest('#lbxa'))return;var r=el.getBoundingClientRect();var a=r.width*r.height;if(r.width>=70&&r.height>=70&&a>area){area=a;best=el;}}catch(_){}});
 if(!tag){tag=document.createElement('div');tag.id='lbxPrice';(document.body||document.documentElement).appendChild(tag);}
 tag.style.display='';tag.textContent='💰 '+ps[0].v;
 if(best){var r=best.getBoundingClientRect();var tw=tag.offsetWidth||64;
   tag.style.left=Math.max(2,Math.min(window.innerWidth-tw-2,r.right-tw-6))+'px';tag.style.top=Math.max(2,r.top+6)+'px';tag.style.right='';}
 else{tag.style.left='';tag.style.right='12px';tag.style.top='12px';}}
function normT(s){return String(s==null?'':s).replace(/<[^>]+>/g,' ').replace(/[\s ]+/g,' ').trim().toUpperCase();}
// Тексты правильных ответов: явные метки correct/isCorrect/*Text/truth + правда-по-исключению (Бредовуха).
function correctTexts(){var out=[];
 Object.keys(ents).forEach(function(k){try{(function w(o){if(o==null||typeof o!=='object')return;
   if(Array.isArray(o)){o.forEach(function(it){if(it&&typeof it==='object'&&(it.correct===true||it.isCorrect===true||it.isTrue===true||it.right===true)){var t=it.text||it.label||it.title||it.name||it.answer;if(t)out.push(t);}w(it);});return;}
   Object.keys(o).forEach(function(kk){var v=o[kk],lk=kk.toLowerCase();
     if((lk==='correcttext'||lk==='answertext'||lk==='truth'||lk==='solution'||lk==='rightanswer'||lk==='correctanswer'||lk==='realanswer')&&(typeof v==='string'||typeof v==='number'))out.push(v);
     w(v);});})(ents[k].body&&ents[k].body.val);}catch(_){}});
 try{var room=(ents['bc:room']&&ents['bc:room'].body&&ents['bc:room'].body.val)||{};var ch=Array.isArray(room.choices)?room.choices:null;
   if(ch){var entered=[];Object.keys(ents).forEach(function(k){if(k.indexOf('bc:customer:')!==0)return;var v=ents[k].body.val||{};var said=v.entry||v.lieEntered||v.chosen;if(said&&typeof said==='string')entered.push(normT(said));});
     if(entered.length)ch.forEach(function(x){var t=typeof x==='string'?x:(x.text||x.html||'');if(t&&entered.indexOf(normT(t))<0)out.push(t);});}}catch(_){}
 var seen={},res=[];out.forEach(function(t){var n=normT(t);if(n.length>=2&&!seen[n]){seen[n]=1;res.push(n);}});return res;}
// Подсветить прямо в игре кнопку/элемент, чей текст совпадает с правильным ответом.
function highlightAnswer(){
 var prev=document.querySelectorAll('.lbxCorrect');for(var j=0;j<prev.length;j++)prev[j].classList.remove('lbxCorrect');
 if(!HILITE||!authed)return;
 var cts=correctTexts();if(!cts.length)return;
 var nodes=document.querySelectorAll('button,[role=button],a,li,label,div,span,p');
 for(var i=0;i<nodes.length;i++){var el=nodes[i];try{
   if(el.closest&&(el.closest('#lbxa')||el.closest('.lbxCorrect')))continue;
   if(el.children&&el.children.length>4)continue;
   var t=normT(el.textContent);if(t.length<2||t.length>90)continue;
   for(var c=0;c<cts.length;c++){if(t===cts[c]||(cts[c].length>=5&&t.length<=cts[c].length+6&&t.indexOf(cts[c])>=0)){el.classList.add('lbxCorrect');break;}}
 }catch(_){}}}
function render(){
 if(!open)return;
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
   // В Бредовухе правда = вариант из списка, который никто не вводил.
   if(SHOWANS&&roomCh&&entered.length){var truth=roomCh.map(function(x){return typeof x==='string'?x:(x.text||x.html||'');}).filter(function(t){return t&&entered.indexOf(String(t).toUpperCase())<0;});
     if(truth.length){var tr=document.createElement('div');tr.className='ans';tr.style.borderColor='#7fe08a';
       tr.innerHTML='✔ <b>Возможно правда:</b> '+truth.map(esc).join(' / ')+' <span class="mut">(нет в чужом вранье)</span>';h.appendChild(tr);}}
   var hint=document.createElement('div');hint.className='mut';
   hint.textContent='Правда = вариант, который никто из игроков не вводил (остальное — их враньё + вброс игры).';
   h.appendChild(hint);
 }
 if(SHOWANS){var ans=sniff();
 var ha=document.createElement('h3');ha.textContent='🔎 Похоже на правильный ответ ('+ans.length+')';h.appendChild(ha);
 if(!ans.length){var mm=document.createElement('div');mm.className='mut';mm.textContent='пока не видно — игра могла не прислать ответ на сервер (появится, если пришлёт).';h.appendChild(mm);}
 ans.slice(0,25).forEach(function(o){var d=document.createElement('div');d.className='ans';
   d.innerHTML='<b>'+esc(String(o.v))+'</b> <span class="mut">'+esc(o.h)+'</span><div class="k">'+esc(o.p)+'</div>';h.appendChild(d);});}
 if(SHOWPRICE){var pr=prices();if(pr.length){var hpp=document.createElement('h3');hpp.textContent='💰 Цены картин ('+pr.length+')';h.appendChild(hpp);
   pr.slice(0,12).forEach(function(o){var d=document.createElement('div');d.className='ans';d.style.borderColor='#ffd23f';
     d.innerHTML='<b>'+esc(String(o.v))+'</b> <span class="mut">'+esc(o.p)+'</span>';h.appendChild(d);});}}
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
})();`;

module.exports = { isAdmin, enabled, adminList, handleWs, mountHttp, onRoomEvent };
