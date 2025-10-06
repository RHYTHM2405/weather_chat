/* ---------------- utilities ---------------- */
const toastRoot = document.getElementById('toast');

function createPlaceImage(imgMeta) {
  const wrap = document.createElement('div');
  wrap.style.display = 'flex';
  wrap.style.flexDirection = 'column';
  wrap.style.gap = '6px';
  wrap.style.marginTop = '6px';
  const placeholder = document.createElement('div');
  placeholder.style.width = '200px';
  placeholder.style.height = '120px';
  placeholder.style.borderRadius = '8px';
  placeholder.style.background = 'linear-gradient(90deg, #f0f0f0, #e8e8e8)';
  placeholder.style.display = 'flex';
  placeholder.style.alignItems = 'center';
  placeholder.style.justifyContent = 'center';
  placeholder.textContent = 'Loading...';
  wrap.appendChild(placeholder);
  const img = document.createElement('img');
  img.src = imgMeta.thumbnail || imgMeta.url;
  img.alt = imgMeta.title || 'Image';
  img.loading = 'lazy';
  img.style.width = '200px';
  img.style.maxWidth = '100%';
  img.style.height = 'auto';
  img.style.borderRadius = '8px';
  img.style.objectFit = 'cover';
  img.style.display = 'none';
  img.addEventListener('load', () => {
    try { placeholder.replaceWith(img); } catch(e){ /* ignore */ }
    img.style.display = 'block';
  });
  img.addEventListener('error', () => {
    console.warn('Image load failed for', img.src);
    if (!img.dataset.triedProxy && imgMeta.url) {
      img.dataset.triedProxy = "1";
      img.src = '/api/image_proxy?url=' + encodeURIComponent(imgMeta.url);
      return;
    }
    placeholder.textContent = 'Image not available';
  });
  if (imgMeta.source_page) {
    img.style.cursor = 'pointer';
    img.addEventListener('click', () => { window.open(imgMeta.source_page, '_blank'); });
  }
  const credit = document.createElement('div');
  credit.className = 'small';
  credit.style.fontSize = '11px';
  credit.style.color = '#666';
  credit.textContent = imgMeta.attribution || '';
  wrap.appendChild(credit);
  return wrap;
}

function showToast(msg, dur=3000){
  const el = document.createElement('div');
  el.className = 'toast';
  el.textContent = msg;
  el.style.background='#111'; el.style.color='#fff'; el.style.padding='8px 12px'; el.style.borderRadius='8px';
  toastRoot.appendChild(el);
  setTimeout(()=>{ el.style.opacity='0'; setTimeout(()=>el.remove(),300); }, dur);
}
function normalizeMarkdown(s) {
  if (!s && s !== "") return s;
  s = String(s || "");
  s = s.replace(/\r\n/g, "\n");
  s = s.split("\n").map(line => line.replace(/[ \t]+$/g, "")).join("\n");
  s = s.replace(/\n{3,}/g, "\n\n");
  s = s.replace(/([a-z0-9\u00C0-\u017F])\n([a-z0-9\u00C0-\u017F])/g, "$1 $2");
  s = s.replace(/^\s+/, "").replace(/\s+$/, "");
  return s;
}

/* ---------------- state & elements ---------------- */
const conversationEl = document.getElementById('conversation');
const userInput = document.getElementById('userInput');
const enterBtn = document.getElementById('enterBtn');
const micBtn = document.getElementById('micBtn');
const clearBtn = document.getElementById('clearBtn');
const locBtn = document.getElementById('locBtn');
const sttLang = document.getElementById('sttLang');
const statusSmall = document.getElementById('statusSmall');

let mediaRecorder = null;
let recordedChunks = [];
let isRecording = false;

/* ---------------- localStorage chat persistence ---------------- */
const STORAGE_KEY = "weatherchat_history_v1";

function loadHistory(){
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const arr = JSON.parse(raw);
    return Array.isArray(arr) ? arr : [];
  } catch(e){
    console.error("loadHistory err", e);
    return [];
  }
}
function saveHistory(messages){
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(messages));
  } catch(e){ console.error("saveHistory err", e); }
}
function appendToHistory(msg){
  const h = loadHistory();
  h.push(msg); saveHistory(h);
}
function clearHistory(){
  localStorage.removeItem(STORAGE_KEY);
}

/* ---------------- helper: render conversation ---------------- */
function clearConversationDOM(){
  conversationEl.innerHTML = "";
}
function renderHistory(){
  clearConversationDOM();
  const h = loadHistory();
  h.forEach(m => renderMessage(m, false));
  conversationEl.scrollTop = conversationEl.scrollHeight;
}

function renderMessage(msg, animate = true) {
  const el = document.createElement('div');
  el.className = 'msg ' + (msg.role === 'user' ? 'user' : 'assistant');
  if (msg.role === 'assistant') el.classList.add('assistant');
  if (msg.role === 'assistant' && animate) el.classList.add('fade-in');

  if (msg.role === 'assistant') {
    const container = document.createElement('div');
    container.style.display = 'flex';
    container.style.flexDirection = 'column';
    container.style.gap = '6px';
    const topRow = document.createElement('div');
    topRow.style.display = 'flex';
    topRow.style.gap = '8px';
    topRow.style.alignItems = 'flex-start';
    const icon = document.createElement('div');
    icon.className = 'weather-icon';
    icon.innerHTML = getWeatherIcon(msg.weather && msg.weather.condition);
    topRow.appendChild(icon);
    const inner = document.createElement('div');
    inner.className = 'bubble-text';
    try {
      const sourceMarkdown = (typeof normalizeMarkdown === 'function') ? normalizeMarkdown(msg.content || '') : (msg.content || '');
      const rawHtml = (typeof marked !== 'undefined') ? marked.parse(sourceMarkdown) : (sourceMarkdown.replace(/\n/g, '<br/>'));
      const safeHtml = (typeof DOMPurify !== 'undefined') ? DOMPurify.sanitize(rawHtml) : rawHtml;
      inner.innerHTML = safeHtml;
    } catch (e) {
      inner.textContent = msg.content || '';
    }
    topRow.appendChild(inner);
    container.appendChild(topRow);
    if (msg.image && (msg.image.thumbnail || msg.image.url)) {
      const imgNode = createPlaceImage(msg.image);
      container.appendChild(imgNode);
    }
    el.appendChild(container);
  } else {
    const inner = document.createElement('div');
    inner.className = 'bubble-text';
    inner.textContent = msg.content;
    el.appendChild(inner);
  }

  conversationEl.appendChild(el);
  conversationEl.scrollTop = conversationEl.scrollHeight;
}

/* ---------------- weather icons mapping ---------------- */
function getWeatherIcon(cond){
  const c = (cond||'other').toString().toLowerCase();
  switch(c){
    case 'sunny': return '☀️';
    case 'rainy': return '🌧️';
    case 'cloudy': return '☁️';
    case 'windy': return '🌬️';
    case 'fog': return '🌫️';
    case 'snowy': return '❄️';
    case 'drizzle': return '🌦️';
    case 'thunderstorm': return '⛈️';
    default: return '🌤️';
  }
}

/* ---------------- append helpers (history + DOM) ---------------- */
function pushUserMessage(text){
  const msg = { role:'user', content: text };
  appendToHistory(msg);
  renderMessage(msg);
}
function pushAssistantMessagePartial(textPart, meta){
  let last = conversationEl.lastElementChild;
  if (!last || !last.classList.contains('assistant') || last.dataset.streamFinal === "true") {
    const msgObj = { role:'assistant', content: textPart || '', weather: meta && meta.weather ? meta.weather : null };
    appendToHistory(msgObj);
    renderMessage(msgObj);
    last = conversationEl.lastElementChild;
    last.dataset.streaming = "true";
    last.dataset.historyIndex = loadHistory().length - 1;
    return;
  } else {
    const idx = Number(last.dataset.historyIndex);
    const h = loadHistory();
    const appended = textPart || '';
    if (h[idx]) {
      h[idx].content = (h[idx].content || '') + appended;
      saveHistory(h);
    }
    const inner = last.querySelector('.bubble-text');
    try {
      const fullRaw = h[idx] ? h[idx].content : (inner.textContent || '');
      const cleaned = normalizeMarkdown(fullRaw);
      const rawHtml = marked.parse(cleaned);
      const safeHtml = DOMPurify.sanitize(rawHtml);
      inner.innerHTML = safeHtml;
    } catch (e) {
      inner.textContent = inner.textContent + appended;
    }
    conversationEl.scrollTop = conversationEl.scrollHeight;
  }
}
function finalizeAssistantStream(){
  const last = conversationEl.lastElementChild;
  if (!last || !last.classList.contains('assistant')) return;
  last.dataset.streamFinal = "true";
}

/* ---------------- clear chat button ---------------- */
clearBtn.addEventListener('click', ()=>{ clearHistory(); clearConversationDOM(); showToast('Chat cleared'); statusSmall.textContent = 'Ready'; });

/* ---------------- detect location (reverse geocode via Nominatim) ---------------- */
locBtn.addEventListener('click', async ()=>{ if (!navigator.geolocation){ showToast('Geolocation not available in this browser',4000); return; } statusSmall.textContent = 'Detecting location...'; showToast('Detecting location...'); navigator.geolocation.getCurrentPosition(async (pos)=>{ const lat = pos.coords.latitude; const lon = pos.coords.longitude; try { const resp = await fetch(`https://nominatim.openstreetmap.org/reverse?format=json&lat=${lat}&lon=${lon}`); const j = await resp.json(); const city = j.address.city || j.address.town || j.address.village || j.address.county || j.display_name; if (city) { userInput.value = city; showToast('Detected: ' + city, 3000); statusSmall.textContent = `Detected: ${city}`; } else { showToast('Could not determine city name',4000); statusSmall.textContent = 'Ready'; } } catch (e){ console.error(e); showToast('Reverse geocoding failed',4000); statusSmall.textContent='Ready'; } }, (err)=>{ console.error(err); showToast('Location permission denied or failed',4000); statusSmall.textContent='Ready'; }, {timeout:10000}); });

/* ---------------- STT mic logic (records, uploads to /api/transcribe) ---------------- */
micBtn.addEventListener('click', async ()=>{ if (!isRecording){ try { statusSmall.textContent = 'Requesting mic permission...'; const stream = await navigator.mediaDevices.getUserMedia({ audio:true }); recordedChunks = []; mediaRecorder = new MediaRecorder(stream); mediaRecorder.ondataavailable = e => { if (e.data && e.data.size>0) recordedChunks.push(e.data); }; mediaRecorder.onstop = async ()=>{ statusSmall.textContent = 'Uploading audio...'; showToast('Uploading audio for transcription...'); const blob = new Blob(recordedChunks, { type: recordedChunks[0]?.type || 'audio/webm' }); const form = new FormData(); form.append('file', blob, 'rec.webm'); form.append('language', sttLang.value || 'auto'); try { const resp = await fetch('/api/transcribe', { method:'POST', body: form }); const j = await resp.json(); if (!resp.ok) { showToast('Transcription failed',4000); console.error(j); statusSmall.textContent = 'Ready'; return; } const text = j.text || j.transcript || ''; userInput.value = text; showToast('Transcription complete'); statusSmall.textContent = 'Transcribed'; } catch(e){ console.error(e); showToast('Upload failed',4000); statusSmall.textContent = 'Ready'; } }; mediaRecorder.start(); isRecording = true; micBtn.classList.add('recording'); statusSmall.textContent = 'Recording... Click mic again to stop'; showToast('Recording started'); } catch(e){ console.error(e); showToast('Mic permission denied',4000); statusSmall.textContent='Ready'; } } else { if (mediaRecorder && mediaRecorder.state === 'recording'){ mediaRecorder.stop(); isRecording = false; micBtn.classList.remove('recording'); statusSmall.textContent = 'Processing transcription...'; showToast('Stopped recording'); try { mediaRecorder.stream.getTracks().forEach(t=>t.stop()); } catch(e){} } } });

/* ---------------- streaming call to /api/stream_process ---------------- */
async function sendAndStream(text){
  pushUserMessage(text);
  userInput.value = '';
  userInput.focus();
  statusSmall.textContent = 'Processing...';
  showToast('Extracting city & fetching weather...');
  try {
    const resp = await fetch('/api/stream_process', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ userText: text })
    });
    if (!resp.ok){
      const err = await resp.json().catch(()=>({error:'unknown'}));
      showToast('Server error — see console',4000); console.error(err);
      statusSmall.textContent = 'Error';
      appendAssistantMessage('Server error. See console.');
      applyBackgroundForCondition('other');
      return;
    }
    const rl = resp.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buffer = '';
    while (true){
      const { done, value } = await rl.read();
      if (done) break;
      buffer += decoder.decode(value, {stream:true});
      let idx;
      while ((idx = buffer.indexOf('\n\n')) !== -1){
        const rawEvent = buffer.slice(0, idx).trim();
        buffer = buffer.slice(idx + 2);
        const lines = rawEvent.split('\n').map(s=>s.trim()).filter(Boolean);
        for (const line of lines){
          if (!line.startsWith('data:')) continue;
          const payloadText = line.slice(5).trim();
          if (!payloadText) continue;
          let payload;
          try { payload = JSON.parse(payloadText); } catch(e){ console.error('bad payload', e, payloadText); continue; }
          if (payload.error){
            showToast('Server error during stream',4000);
            console.error(payload);
            appendAssistantMessage('Error: ' + JSON.stringify(payload));
            statusSmall.textContent = 'Error';
            applyBackgroundForCondition('other');
            return;
          }
          if (payload.type === 'meta'){
            applyBackgroundForCondition(payload.weather && payload.weather.condition);
            pushAssistantMessagePartial('', {city: payload.city, weather: payload.weather});
            continue;
          }
          if (payload.type === 'chunk'){
            pushAssistantMessagePartial(payload.text, { });
            continue;
          }
          if (payload.type === 'done'){
            finalizeAssistantStream();
            statusSmall.textContent = 'Done';
            showToast('Answer ready');
            return;
          }
        }
      }
    }
    finalizeAssistantStream();
    statusSmall.textContent = 'Done';
  } catch(e){
    console.error(e); showToast('Stream failed: ' + (e.message||e),4000); statusSmall.textContent = 'Error';
    appendAssistantMessage('Stream failed: ' + (e.message||e));
    applyBackgroundForCondition('other');
  }
}

/* ---------------- helper: non-stream send for fallback (calls /api/process) ---------------- */
async function sendOnce(text){
  pushUserMessage(text);
  userInput.value = '';
  userInput.focus();
  statusSmall.textContent = 'Processing...';
  showToast('Processing...');
  try {
    const resp = await fetch('/api/process', {
      method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ userText: text })
    });
    const j = await resp.json();
    if (!resp.ok){
      showToast('Server error — see console',4000);
      console.error(j);
      appendAssistantMessage('Server error. See console.');
      applyBackgroundForCondition('other');
      statusSmall.textContent = 'Error';
      return;
    }
    if (j.error){
      if (j.answer){
        const msg = { role:'assistant', content: j.answer, weather: j.weather || null };
        appendToHistory(msg); renderMessage(msg);
        applyBackgroundForCondition(j.weather && j.weather.condition);
        statusSmall.textContent = 'Done';
        return;
      }
      appendAssistantMessage(j.message || j.error);
      applyBackgroundForCondition('other');
      statusSmall.textContent = 'Done';
      return;
    }
    const msg = { role:'assistant', content: j.answer, weather: j.weather || null };
    appendToHistory(msg); renderMessage(msg);
    applyBackgroundForCondition(j.weather && j.weather.condition);
    statusSmall.textContent = 'Done';
    showToast('Done');
  } catch(e){
    console.error(e); showToast('Request failed',4000); statusSmall.textContent='Error';
    appendAssistantMessage('Request failed: ' + (e.message||e));
    applyBackgroundForCondition('other');
  }
}

/* ---------------- events ---------------- */
enterBtn.addEventListener('click', ()=> {
  const text = userInput.value.trim();
  if (!text) { showToast('Please enter text or use mic'); return; }
  sendAndStream(text);
});
userInput.addEventListener('keydown', (ev)=> {
  if (ev.key === 'Enter'){
    ev.preventDefault();
    enterBtn.click();
  }
});

/* on load: render history (we render but keep UI hidden until intro finishes) */
renderHistory();

/* ---------------- apply dynamic background (smooth via class swap) ---------------- */
function applyBackgroundForCondition(cond){
  const all = ['bg-sunny','bg-rainy','bg-cloudy','bg-windy','bg-fog','bg-snowy','bg-drizzle','bg-thunderstorm','bg-other'];
  document.body.classList.remove(...all);
  const mapping = { sunny:'bg-sunny', rainy:'bg-rainy', cloudy:'bg-cloudy', windy:'bg-windy', fog:'bg-fog', snowy:'bg-snowy', drizzle:'bg-drizzle', thunderstorm:'bg-thunderstorm', other:'bg-other' };
  const cls = mapping[(cond||'other').toString().toLowerCase()] || 'bg-other';
  document.body.classList.add(cls);
}

/* Sidebar controls + persistence */
const sidebar = document.getElementById('sidebar');
const sidebarOverlay = document.getElementById('sidebarOverlay');
const sidebarOpenBtn = document.getElementById('sidebarOpenBtn');
const sidebarClose = document.getElementById('sidebarClose');
const workflowBtn = document.getElementById('workflowBtn');
const workflowModal = document.getElementById('workflowModal');
const workflowClose = document.getElementById('workflowClose');

const SIDEBAR_KEY = 'weatherchat_sidebar_open';
function isSidebarOpen() { return localStorage.getItem(SIDEBAR_KEY) === '1'; }
function setSidebarOpen(open) {
  if (open) {
    sidebar.classList.add('open');
    sidebarOverlay.classList.add('show');
    sidebar.setAttribute('aria-hidden','false');
    sidebarOverlay.setAttribute('aria-hidden','false');
  } else {
    sidebar.classList.remove('open');
    sidebarOverlay.classList.remove('show');
    sidebar.setAttribute('aria-hidden','true');
    sidebarOverlay.setAttribute('aria-hidden','true');
  }
  localStorage.setItem(SIDEBAR_KEY, open ? '1' : '0');
}
setSidebarOpen(isSidebarOpen());
sidebarOpenBtn.addEventListener('click', ()=> setSidebarOpen(true));
sidebarClose.addEventListener('click', ()=> setSidebarOpen(false));
sidebarOverlay.addEventListener('click', ()=> setSidebarOpen(false));
function updateFloatingBtnVisibility(){
  const show = (window.innerWidth <= 880) || !sidebar.classList.contains('open');
  sidebarOpenBtn.style.display = show ? 'inline-flex' : 'none';
}
window.addEventListener('resize', updateFloatingBtnVisibility);
updateFloatingBtnVisibility();
workflowBtn.addEventListener('click', ()=> {
  workflowModal.classList.add('show');
  workflowModal.setAttribute('aria-hidden','false');
});
workflowClose.addEventListener('click', ()=> {
  workflowModal.classList.remove('show');
  workflowModal.setAttribute('aria-hidden','true');
});
workflowModal.addEventListener('click', (e)=>{
  if (e.target === workflowModal) {
    workflowModal.classList.remove('show');
    workflowModal.setAttribute('aria-hidden','true');
  }
});

/* ---------------- initial background ---------------- */
applyBackgroundForCondition('other');

/* ------------------ INTRO SEQUENCE (slide → typing → reveal) ------------------ */
(function runIntroSequence(){
  const intro = document.getElementById('intro');
  const slide = document.getElementById('introSlide');
  const content = document.getElementById('introContent');
  const titleEl = document.getElementById('introTitle');
  const mainWrap = document.getElementById('mainWrap');

  // configuration
  const appName = 'WeatherChat';
  const slideDuration = parseInt(getComputedStyle(document.documentElement).getPropertyValue('--intro-slide-duration')) || 2000;
  const cps = Number(getComputedStyle(document.documentElement).getPropertyValue('--intro-typing-cps')) || 80;
  const typingDelayPerChar = 1000 / (cps || 80);

  // Ensure main UI hidden to start
  mainWrap.classList.add('hidden-onload');
  mainWrap.setAttribute('aria-hidden','true');

  // helper: promise that resolves on transitionend/animationend (safeguarded with timeout)
  function waitForTransition(el, propName, timeout = 1500){
    return new Promise(resolve => {
      let done = false;
      function handler(e){
        if (propName && e.propertyName && e.propertyName !== propName) return;
        if (done) return;
        done = true;
        el.removeEventListener('transitionend', handler);
        el.removeEventListener('animationend', handler);
        clearTimeout(timer);
        resolve();
      }
      el.addEventListener('transitionend', handler);
      el.addEventListener('animationend', handler);
      const timer = setTimeout(()=> {
        if (!done) { done = true; try { el.removeEventListener('transitionend', handler); el.removeEventListener('animationend', handler); } catch(e){} resolve(); }
      }, timeout);
    });
  }

  // step 1: animate slide from right -> left (by toggling class)
  // show content area (text) slightly delayed so it's not visible until the slide begins
  setTimeout(()=> content.classList.add('show'), 80);

  // start slide
  requestAnimationFrame(()=>{
    slide.classList.add('animate');
  });

  // after slide finishes, play typing
  waitForTransition(slide, 'transform', slideDuration + 200).then(async ()=>{
    // small pause so user sees colored bar fully in place
    await new Promise(r => setTimeout(r, 160));

    // start typing into titleEl
    titleEl.textContent = '';
    titleEl.classList.add('caret');
    // progressively type characters
    for (let i=0;i<appName.length;i++){
      titleEl.textContent += appName[i];
      // small pause per char
      await new Promise(r => setTimeout(r, typingDelayPerChar));
    }

    // small pause after typing then reveal main UI
    await new Promise(r => setTimeout(r, 380));

    // mark intro fadeout and reveal main
    intro.classList.add('fadeout');

    // reveal main
    mainWrap.classList.remove('hidden-onload');
    mainWrap.classList.add('revealed');
    mainWrap.setAttribute('aria-hidden','false');

    // after fadeout remove intro from DOM (cleanup)
    waitForTransition(intro, 'opacity', 420).then(()=> {
      try { intro.remove(); } catch(e){}
    });
  });
})();

/* ----------------- utility stubs used earlier but not defined in snippet ----------------- */
/* appendAssistantMessage used in error paths earlier */
function appendAssistantMessage(text){
  const msg = { role:'assistant', content: String(text || ''), weather: null };
  appendToHistory(msg); renderMessage(msg);
}

/* ----------------- RIGHT SIDEBAR LOGIC (login panel) ----------------- */
const rightSidebar = document.getElementById('rightSidebar');
const rightSidebarOverlay = document.getElementById('rightSidebarOverlay');
const loginOpenBtn = document.getElementById('loginOpenBtn');
const rightSidebarClose = document.getElementById('rightSidebarClose');

function setRightSidebarOpen(open) {
  if (open) {
    rightSidebar.classList.add('open');
    rightSidebarOverlay.classList.add('show');
    rightSidebar.setAttribute('aria-hidden','false');
    rightSidebarOverlay.setAttribute('aria-hidden','false');
  } else {
    rightSidebar.classList.remove('open');
    rightSidebarOverlay.classList.remove('show');
    rightSidebar.setAttribute('aria-hidden','true');
    rightSidebarOverlay.setAttribute('aria-hidden','true');
  }
}

if (loginOpenBtn) loginOpenBtn.addEventListener('click', ()=> setRightSidebarOpen(true));
if (rightSidebarClose) rightSidebarClose.addEventListener('click', ()=> setRightSidebarOpen(false));
if (rightSidebarOverlay) rightSidebarOverlay.addEventListener('click', ()=> setRightSidebarOpen(false));

/* optional small handlers for register / google buttons (non-destructive - you can wire them up) */
const registerBtn = document.getElementById('registerBtn');
if (registerBtn) registerBtn.addEventListener('click', ()=> { showToast('Register flow not implemented'); });

const googleLoginBtn = document.getElementById('googleLoginBtn');
if (googleLoginBtn) googleLoginBtn.addEventListener('click', ()=> { showToast('Google sign-in flow not implemented'); });

