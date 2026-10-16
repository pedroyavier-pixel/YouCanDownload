'use strict';
const $ = id => document.getElementById(id);
const form = $('download-form'), input = $('url'), submit = $('submit');
let busy = false, available = false, jobId = null, pollTimer = null, debounce = null, failures = 0;
const ACTIVE = new Set(['recognizing', 'downloading', 'merging']);
const bytes = n => n ? (n >= 1024 ** 3 ? (n / 1024 ** 3).toFixed(2) + ' GB' : (n / 1024 ** 2).toFixed(1) + ' MB') : '';
const duration = n => n ? Math.floor(n / 60) + ':' + String(Math.floor(n % 60)).padStart(2, '0') : '';

function validURL(value) {
  try {
    const u = new URL(/^https?:\/\//i.test(value.trim()) ? value.trim() : 'https://' + value.trim());
    if (!['youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com', 'youtu.be', 'www.youtube-nocookie.com'].includes(u.hostname) || u.username || u.password || (u.port && !['80', '443'].includes(u.port))) return false;
    const parts = u.pathname.replace(/^\/|\/$/g, '').split('/');
    const id = u.hostname === 'youtu.be' && parts.length === 1 ? parts[0] : u.pathname === '/watch' ? u.searchParams.get('v') : parts.length === 2 && ['shorts', 'embed', 'live'].includes(parts[0]) ? parts[1] : '';
    return /^[\w-]{11}$/.test(id || '');
  } catch { return false; }
}

async function api(path, options = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15000);
  try {
    const response = await fetch('./api/' + path, {...options, signal: controller.signal, headers: {'Content-Type': 'application/json', ...options.headers}});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = new Error(typeof data.detail === 'string' ? data.detail : 'No se pudo conectar con el servidor de descargas.');
      error.status = response.status;
      throw error;
    }
    return data;
  } finally { clearTimeout(timeout); }
}

function setBusy(value) {
  busy = value;
  input.disabled = value;
  submit.disabled = value;
  $('paste').disabled = value;
  submit.querySelector('span').textContent = value ? 'Preparando tu video…' : 'Descargar video';
}

async function start() {
  if (busy) return;
  clearTimeout(debounce);
  $('message').textContent = '';
  if (!validURL(input.value)) { $('message').textContent = 'Pega el enlace de un video o Short de YouTube.'; input.focus(); return; }
  if (!available) { $('message').textContent = 'El servidor de descargas todavía no está conectado. Esta página aún no puede descargar videos.'; return; }
  setBusy(true);
  $('job-card').hidden = false;
  $('job-label').textContent = 'RECONOCIENDO ENLACE';
  $('video-title').textContent = 'Buscando tu video…';
  $('video-meta').textContent = 'Un momento, por favor.';
  $('thumbnail').hidden = true;
  $('download-link').hidden = true;
  $('another').hidden = true;
  $('cancel').hidden = false;
  $('cancel').disabled = true;
  $('progress').removeAttribute('value');
  $('stage').textContent = 'Reconociendo video';
  $('percent').textContent = '';
  $('progress-detail').textContent = 'Buscando la mejor resolución disponible.';
  try {
    const result = await api('jobs', {method: 'POST', body: JSON.stringify({url: input.value.trim()})});
    jobId = result.id;
    sessionStorage.setItem('ycd-job', jobId);
    $('cancel').disabled = false;
    failures = 0;
    await poll();
  } catch (error) { finishError(error.message); }
}

function finishError(message) {
  clearTimeout(pollTimer);
  $('message').textContent = message;
  $('job-label').textContent = 'NO SE PUDO COMPLETAR';
  $('stage').textContent = 'Descarga detenida';
  $('progress').value = 0;
  $('percent').textContent = '';
  $('progress-detail').textContent = '';
  $('cancel').hidden = true;
  $('another').hidden = false;
  sessionStorage.removeItem('ycd-job');
  jobId = null;
  setBusy(false);
}

async function poll() {
  try {
    const data = await api('jobs/' + jobId);
    failures = 0;
    const m = data.metadata, p = data.progress;
    if (m.title) {
      $('video-title').textContent = m.title;
      $('video-meta').textContent = [m.channel, duration(m.duration), m.height ? m.height + 'p' : '', m.size_bytes ? bytes(m.size_bytes) : ''].filter(Boolean).join(' · ');
      if (m.thumbnail && /^https:\/\/i\.ytimg\.com\/vi\/[\w-]{11}\/hqdefault\.jpg$/.test(m.thumbnail)) {
        $('thumbnail').src = m.thumbnail;
        $('thumbnail').hidden = false;
      }
    }
    $('stage').textContent = {recognizing:'Reconociendo video',downloading:'Descargando · pista ' + (p.track || 1),merging:'Uniendo video y audio',ready:'Tu video está listo',cancelled:'Descarga cancelada',error:'No se pudo completar'}[data.status] || 'Procesando';
    if (data.status === 'downloading') {
      $('job-label').textContent = 'DESCARGANDO EN LA MEJOR CALIDAD';
      if (p.percent != null) { $('progress').value = p.percent; $('percent').textContent = Math.round(p.percent) + '%'; }
      else { $('progress').removeAttribute('value'); $('percent').textContent = ''; }
      $('progress-detail').textContent = [bytes(p.downloaded_bytes), p.total_bytes ? 'de ' + bytes(p.total_bytes) : '', p.speed ? bytes(p.speed) + '/s' : ''].filter(Boolean).join(' ');
    } else if (data.status === 'merging') {
      $('job-label').textContent = 'UN ÚLTIMO PASO';
      $('progress').removeAttribute('value');
      $('percent').textContent = '';
      $('progress-detail').textContent = 'Preparando un solo archivo con video y audio.';
    } else if (data.status === 'ready') {
      $('job-label').textContent = 'LISTO. DALE PLAY.';
      $('progress').value = 100;
      $('percent').textContent = '100%';
      $('progress-detail').textContent = 'Intentamos iniciar la descarga. Si no aparece, toca «Guardar video».';
      const link = $('download-link');
      link.href = './' + data.download_url.replace(/^\//, '');
      link.download = '';
      link.hidden = false;
      $('cancel').hidden = true;
      $('another').hidden = false;
      setBusy(false);
      sessionStorage.removeItem('ycd-job');
      link.click();
      return;
    } else if (data.status === 'error' || data.status === 'cancelled') {
      finishError(data.error || 'La descarga se canceló.');
      return;
    }
    if (ACTIVE.has(data.status)) pollTimer = setTimeout(poll, 1200);
  } catch (error) {
    if (error.status === 404 || error.status === 401) { finishError(error.message); return; }
    failures++;
    if (failures < 4) { $('progress-detail').textContent = 'Reconectando con el servidor…'; pollTimer = setTimeout(poll, 2500); }
    else {
      // Preserve the job ID: refresh can resume a download after a brief outage.
      clearTimeout(pollTimer);
      $('message').textContent = 'Se perdió la conexión. Recarga esta página para recuperar la descarga.';
      $('cancel').hidden = true;
      submit.disabled = true;
    }
  }
}

form.addEventListener('submit', event => { event.preventDefault(); start(); });
input.addEventListener('input', () => { clearTimeout(debounce); if (validURL(input.value)) debounce = setTimeout(start, 850); });
$('paste').addEventListener('click', async () => {
  try { input.value = await navigator.clipboard.readText(); start(); }
  catch { $('message').textContent = 'Mantén presionado el campo o usa Ctrl/⌘ + V para pegar el enlace.'; input.focus(); }
});
$('cancel').addEventListener('click', async () => {
  if (!jobId) return;
  $('cancel').disabled = true;
  clearTimeout(pollTimer);
  try { await api('jobs/' + jobId, {method:'DELETE'}); finishError('La descarga se canceló.'); }
  catch (error) { $('message').textContent = error.message; $('cancel').disabled = false; pollTimer = setTimeout(poll, 1200); }
});
$('another').addEventListener('click', () => { $('job-card').hidden = true; $('message').textContent = ''; input.value = ''; jobId = null; input.focus(); });
$('unlock-form').addEventListener('submit', async event => {
  event.preventDefault();
  try { await api('unlock', {method:'POST',body:JSON.stringify({code:$('access-code').value})}); $('unlock-dialog').close(); await initialize(); }
  catch (error) { $('unlock-message').textContent = error.message; }
});

async function initialize() {
  if (window.YCD_ENGINE_URL) {
    try {
      const destination = new URL(window.YCD_ENGINE_URL);
      if (destination.protocol === 'https:' && destination.origin !== location.origin) {
        destination.search = location.search;
        location.replace(destination.href);
        return;
      }
    } catch { /* Invalid deployment configuration is reported below. */ }
  }
  try {
    const health = await api('health');
    if (health.locked) { if (!$('unlock-dialog').open) $('unlock-dialog').showModal(); return; }
    if (!health.ready) throw new Error('El servidor no está listo.');
    available = true;
    $('service-notice').hidden = true;
    const saved = sessionStorage.getItem('ycd-job');
    if (saved && /^[a-f0-9]{48}$/.test(saved)) {
      jobId = saved; setBusy(true); $('job-card').hidden = false; await poll();
    } else {
      const passed = new URLSearchParams(location.search).get('url');
      if (passed && validURL(passed)) { input.value = passed; start(); }
    }
  } catch {
    available = false;
    $('service-notice').textContent = 'Servidor de descargas pendiente de conectar. La interfaz está disponible, pero las descargas todavía no están activas.';
    $('service-notice').hidden = false;
  }
}
initialize();
