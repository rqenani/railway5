
let TOKEN = null;
let ME = null;
let CURRENT_PEER = { id: "global", name: "Global (Anonim)", global: true };
let MODE = "global"; // 'global' or 'direct'
let USERS_CACHE = [];
let POLL_HANDLE = null;

const qs = (s)=>document.querySelector(s);
const qsa = (s)=>Array.from(document.querySelectorAll(s));
const auth = qs("#auth");
const app  = qs("#app");
const statusEl = qs("#status");
const usersList = qs("#usersList");
const searchUsers = qs("#searchUsers");
const meName = qs("#meName");
const messagesEl = qs("#messages");
const msgInput = qs("#msgInput");

function setStatus(t){ if(statusEl) statusEl.textContent = t; }
function showAuth(){ if(auth) auth.style.display="block"; if(app) app.style.display="none"; }
function showApp(){ if(auth) auth.style.display="none"; if(app) app.style.display="flex"; }

async function fetchJSON(url, opts = {}){
  const headers = opts.headers ? {...opts.headers} : {};
  if (TOKEN) headers["Authorization"] = "Bearer " + TOKEN;
  if (opts.body && !(opts.body instanceof FormData)) headers["Content-Type"]="application/json";
  const res = await fetch(url, {...opts, headers});
  if (!res.ok){
    let msg = await res.text();
    try { const j = JSON.parse(msg); msg = j.detail || j.message || msg; } catch {}
    throw new Error(msg || (res.status + " " + res.statusText));
  }
  const ct = res.headers.get("content-type") || "";
  if (!ct.includes("application/json")) return {};
  return await res.json();
}

// Token storage
function saveToken(t){ TOKEN = t; try{ localStorage.setItem("qenani_token", t||""); }catch{} }
function loadToken(){ try{ const t = localStorage.getItem("qenani_token"); if (t) TOKEN = t; }catch{} }

// Theme toggle (blue/green)
const themeBtn = qs("#themeBtn");
if (themeBtn){
  themeBtn.onclick = () => {
    document.documentElement.classList.toggle("green");
    try{ localStorage.setItem("qenani_theme_green", document.documentElement.classList.contains("green") ? "1":"0"); }catch{}
  };
  // load pref
  try{ if (localStorage.getItem("qenani_theme_green")==="1") document.documentElement.classList.add("green"); }catch{}
}

// ---- Auth ----
async function loginFlow(u, p){
  try {
    const r = await fetchJSON("/api/login", { method:"POST", body: JSON.stringify({ username:u, password:p }) });
    saveToken(r.token); ME = r.username || u;
    await afterLogin();
  } catch(e1){
    try {
      const r2 = await fetchJSON("/api/signin", { method:"POST", body: JSON.stringify({ username:u, password:p }) });
      saveToken(r2.token); ME = r2.username || u;
      await afterLogin();
    } catch(e2){
      qs("#authMsg").textContent = "Login dështoi: " + (e2.message || e2);
    }
  }
}
async function signupFlow(u, p){
  try {
    const r = await fetchJSON("/api/signup", { method:"POST", body: JSON.stringify({ username:u, password:p, display_name:u }) });
    saveToken(r.token); ME = r.username || u;
    await afterLogin();
  } catch(e1){
    try {
      const r2 = await fetchJSON("/api/register", { method:"POST", body: JSON.stringify({ username:u, password:p, display_name:u }) });
      saveToken(r2.token); ME = r2.username || u;
      await afterLogin();
    } catch(e2){
      qs("#authMsg").textContent = "Signup dështoi: " + (e2.message || e2);
    }
  }
}
async function afterLogin(){
  setStatus("Identifikuar si " + (ME || "—"));
  showApp();
  meName.textContent = ME || "—";
  await bootstrapData();
  switchTab("global");
  startPolling();
}

// ---- Bootstrap ----
async function bootstrapData(){
  try {
    try{
      const me = await fetchJSON("/api/me");
      ME = me.username || me.name || me.email || ME;
      meName.textContent = ME || "—";
    }catch(_){}

    await refreshUsers();
  } catch(err){
    setStatus("Gabim gjatë nisjes: " + (err.message || err));
  }
}

async function refreshUsers(){
  let users = [];
  const eps = ["/api/users", "/api/list-users", "/users"];
  for (const ep of eps){
    try { const r = await fetchJSON(ep); if (Array.isArray(r)) { users = r; break; } if (Array.isArray(r.users)) { users = r.users; break; } } catch {}
  }
  USERS_CACHE = users;
  renderUsers(users);
  return users;
}

function avatarLetters(name){
  const n = (name||"").trim();
  const parts = n.split(/\s+/);
  let letters = parts[0]?.[0] || "?";
  if (parts.length>1) letters += parts[1][0];
  return letters.toUpperCase();
}

function renderUsers(users){
  usersList.innerHTML = "";
  if (MODE==="global"){
    const li = document.createElement("li");
    li.classList.add("active");
    li.dataset.uid = "global";
    li.dataset.uname = "Global (Anonim)";
    li.innerHTML = `<div class="user-avatar">🌍</div><div><div style="font-weight:600">Global (Anonim)</div><div style="font-size:12px;color:var(--muted)">Chat i përbashkët</div></div>`;
    li.onclick = ()=> selectPeer("global","Global (Anonim)", true);
    usersList.appendChild(li);
  }
  users.forEach(u => {
    const uname = u.username || u.name || u.email || "—";
    const uid = u.id || uname;
    const li = document.createElement("li");
    li.dataset.uid = uid;
    li.dataset.uname = uname;
    li.innerHTML = `
      <div class="user-avatar">${avatarLetters(uname)}</div>
      <div style="display:flex;flex-direction:column">
        <div style="font-weight:600">${uname}</div>
        <div style="font-size:12px;color:var(--muted)">${u.display_name || u.email || ""}</div>
      </div>`;
    li.onclick = ()=> selectPeer(uid, uname, false);
    usersList.appendChild(li);
  });
}

// Tabs
qsa(".tab").forEach(t => t.addEventListener("click", () => {
  qsa(".tab").forEach(x => x.classList.remove("active"));
  t.classList.add("active");
  switchTab(t.dataset.tab);
}));
function switchTab(name){
  MODE = name;
  if (MODE==="global"){
    CURRENT_PEER = { id: "global", name: "Global (Anonim)", global: true };
    qs("#chatHeader").textContent = CURRENT_PEER.name;
  } else {
    CURRENT_PEER = null;
    qs("#chatHeader").textContent = "Zgjidh një kontakt";
  }
  renderUsers(USERS_CACHE);
  messagesEl.innerHTML = "";
  if (MODE==="global") loadMessages();
}

// Select peer
async function selectPeer(uid, uname, isGlobal){
  CURRENT_PEER = { id: uid, name: uname, global: !!isGlobal };
  qsa(".users li").forEach(li => li.classList.toggle("active", li.dataset.uid===uid));
  qs("#chatHeader").textContent = uname;
  messagesEl.innerHTML = "";
  await loadMessages();
}

// Anonymize name for global
function anonLabel(from){
  // consistent anon label based on name hash
  const base = String(from||"");
  let h = 0; for (let i=0;i<base.length;i++){ h = (h*31 + base.charCodeAt(i))|0; }
  const n = Math.abs(h % 9000) + 1000;
  return "User#" + n;
}

// Load messages
async function loadMessages(){
  let msgs = [];
  try{
    if (CURRENT_PEER?.global){
      // Global endpoints
      const urls = ["/api/messages/global", "/api/global/messages", "/messages/global"];
      for (const url of urls){
        try { const r = await fetchJSON(url); if (Array.isArray(r)) { msgs = r; break; } if (Array.isArray(r.messages)) { msgs = r.messages; break; } } catch {}
      }
    } else if (CURRENT_PEER){
      const urls = [
        `/api/messages?peer=${encodeURIComponent(CURRENT_PEER.id)}`,
        `/api/chat?peer=${encodeURIComponent(CURRENT_PEER.id)}`,
        `/messages?peer=${encodeURIComponent(CURRENT_PEER.id)}`,
      ];
      for (const url of urls){
        try { const r = await fetchJSON(url); if (Array.isArray(r)) { msgs = r; break; } if (Array.isArray(r.messages)) { msgs = r.messages; break; } } catch {}
      }
    }
  }catch{}
  renderMessages(msgs);
}

function renderMessages(msgs){
  messagesEl.innerHTML = "";
  msgs.forEach(m => messagesEl.appendChild(bubbleFromMsg(m)));
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function bubbleFromMsg(m){
  const mine = (m.from === ME) || (m.sender === ME) || m.mine === true;
  const text = m.text || m.body || m.message || JSON.stringify(m);
  const time = m.time || m.timestamp || "";
  const id = m.id || m._id || m.mid || null;
  const who = CURRENT_PEER?.global ? anonLabel(m.from || m.sender || "anon") : (mine ? "Ju" : (m.from || m.sender || "Ata"));
  const div = document.createElement("div");
  div.className = "bubble" + (mine ? " me" : "");
  div.dataset.mid = id || "";
  div.innerHTML = `<div><strong>${escapeHtml(who)}:</strong> ${escapeHtml(text)}</div><div class="meta">${time}</div>`;
  if (mine && id){
    const del = document.createElement("span");
    del.className = "del"; del.textContent = "🗑";
    del.title = "Fshij mesazhin";
    del.onclick = () => deleteMessage(id, div);
    div.appendChild(del);
  }
  return div;
}

function escapeHtml(s){ return String(s).replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m])); }

// Send message
async function sendMessage(){
  const txt = (msgInput.value || "").trim();
  if (!txt) return;
  if (!CURRENT_PEER){
    setStatus("Zgjidh një kontakt ose Global.");
    return;
  }
  let payload, urls;
  if (CURRENT_PEER.global){
    payload = { text: txt };
    urls = ["/api/messages/global", "/api/global/messages", "/messages/global"];
  } else {
    payload = { to: CURRENT_PEER.id, text: txt };
    urls = ["/api/messages", "/api/chat", "/messages"];
  }
  let ok = false, errLast = null;
  for (const url of urls){
    try{
      await fetchJSON(url, { method:"POST", body: JSON.stringify(payload) });
      ok = true; break;
    }catch(e){ errLast = e; }
  }
  if (!ok){
    setStatus("S'munda të dërgoj: " + (errLast?.message || errLast));
    return;
  }
  // optimistic
  const now = new Date();
  const m = { id: null, from: ME, text: txt, timestamp: now.toLocaleString() };
  messagesEl.appendChild(bubbleFromMsg(m));
  messagesEl.scrollTop = messagesEl.scrollHeight;
  msgInput.value = "";
}

// Delete message
async function deleteMessage(mid, node){
  const urls = [
    `/api/messages/${encodeURIComponent(mid)}`,
    `/messages/${encodeURIComponent(mid)}`
  ];
  let ok = false;
  for (const url of urls){
    try{ await fetchJSON(url, { method:"DELETE" }); ok = true; break; }catch{}
  }
  if (!ok){
    // fallbacks that some backends use
    const alt = ["/api/messages/delete", "/api/delete-message"];
    for (const url of alt){
      try{ await fetchJSON(url, { method:"POST", body: JSON.stringify({ id: mid }) }); ok = true; break; }catch{}
    }
  }
  if (ok && node){ node.remove(); }
}

// Search users
if (searchUsers){
  searchUsers.addEventListener("input", () => {
    const q = (searchUsers.value || "").toLowerCase();
    qsa("#usersList li").forEach(li => {
      if (li.dataset.uid==="global" && MODE==="global"){ li.style.display = ""; return; }
      li.style.display = li.dataset.uname?.toLowerCase().includes(q) ? "" : "none";
    });
  });
}

// Add user (admin quick add)
const addUserBtn = qs("#addUserBtn");
if (addUserBtn){
  addUserBtn.onclick = async () => {
    const u = (qs("#newUserName")?.value || "").trim();
    const p = (qs("#newUserPass")?.value || "").trim();
    const msg = qs("#addUserMsg");
    if (!u || !p){ msg.textContent = "Plotëso përdoruesin dhe fjalëkalimin."; return; }
    msg.textContent = "";
    // Common endpoints for creating user
    const tryEndpoints = [
      { url: "/api/users", method:"POST", body:{ username:u, password:p, display_name:u } },
      { url: "/api/signup-admin", method:"POST", body:{ username:u, password:p, display_name:u } },
      { url: "/api/register", method:"POST", body:{ username:u, password:p, display_name:u } },
      { url: "/api/signup", method:"POST", body:{ username:u, password:p, display_name:u } },
    ];
    let ok = false, errLast = null;
    for (const ep of tryEndpoints){
      try{
        await fetchJSON(ep.url, { method:ep.method, body: JSON.stringify(ep.body) });
        ok = true; break;
      }catch(e){ errLast = e; }
    }
    if (!ok){ msg.textContent = "S’krijova dot: " + (errLast?.message || errLast); return; }
    msg.textContent = "U shtua!";
    qs("#newUserName").value = ""; qs("#newUserPass").value = "";
    await refreshUsers();
  };
}

// Buttons
const loginBtn  = qs("#loginBtn");
const signupBtn = qs("#signupBtn");
if (loginBtn) loginBtn.onclick = () => {
  const u = (qs("#username")?.value || "").trim();
  const p = (qs("#password")?.value || "").trim();
  if (!u || !p){ qs("#authMsg").textContent = "Shkruaj username dhe fjalëkalim."; return; }
  loginFlow(u,p);
};
if (signupBtn) signupBtn.onclick = () => {
  const u = (qs("#username")?.value || "").trim();
  const p = (qs("#password")?.value || "").trim();
  if (!u || !p){ qs("#authMsg").textContent = "Shkruaj username dhe fjalëkalim."; return; }
  signupFlow(u,p);
};

// Signout
const signoutBtn = qs("#signoutBtn");
if (signoutBtn) signoutBtn.onclick = async () => {
  try{ await fetchJSON("/api/logout", { method:"POST" }); }catch{}
  saveToken(""); ME=null; CURRENT_PEER=null;
  showAuth();
  setStatus("Dole nga llogaria.");
};

// Send message
const sendBtn = qs("#sendBtn");
if (sendBtn) sendBtn.onclick = sendMessage;
msgInput?.addEventListener("keydown", (e)=>{
  if (e.key === "Enter" && !e.shiftKey){ e.preventDefault(); sendMessage(); }
});

// Polling
function startPolling(){
  stopPolling();
  POLL_HANDLE = setInterval(async () => {
    if (MODE==="global" || CURRENT_PEER){ await loadMessages(); }
    await refreshUsers();
  }, 3000);
}
function stopPolling(){ if (POLL_HANDLE) { clearInterval(POLL_HANDLE); POLL_HANDLE = null; } }

// Init
(async function init(){
  loadToken();
  if (TOKEN){
    try{
      const me = await fetchJSON("/api/me");
      ME = me.username || me.name || me.email || null;
      await afterLogin();
    }catch(e){
      saveToken(""); showAuth();
    }
  } else {
    showAuth();
  }
})();
