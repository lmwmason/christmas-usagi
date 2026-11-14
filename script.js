'use strict';

const $ = (id) => document.getElementById(id);
const scene = $('stageScene');
const progress = $('progress');
let performanceData = window.USAGI_PERFORMANCE || { duration: 8, notes: [] };
let bgmEnabled = Boolean(performanceData.backing?.enabled);
let pendingSeek = null;
const audio = new Audio(bgmEnabled ? performanceData.backing.mixFile : 'assets/usagi-vocals.mp3');
audio.preload = 'metadata';
const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
const soundBank = window.USAGI_SOUNDBANK || [];
const bankList = $('soundbankList');
for (const sound of soundBank) {
  const row = document.createElement('div');
  row.className = 'sample-row bank-row';
  row.dataset.group = sound.group;
  const label = document.createElement('span');
  const name = document.createElement('strong');
  name.textContent = sound.name;
  const source = document.createElement('a');
  source.href = sound.page;
  source.target = '_blank';
  source.rel = 'noopener noreferrer';
  source.textContent = `원본 출처 ↗ · ${sound.duration.toFixed(1)}초`;
  label.append(name, source);
  const player = document.createElement('audio');
  player.className = 'reference-audio';
  player.controls = true;
  player.preload = 'none';
  player.src = sound.file;
  player.setAttribute('aria-label', `${sound.name} 원본 효과음`);
  row.append(label, player);
  bankList.appendChild(row);
}
$('bankCount').textContent = String(soundBank.length);
if (!soundBank.length) bankList.textContent = '소리 모음 파일을 불러오지 못했어요. assets/soundbank.js를 확인해 주세요.';
const referencePlayers = [...document.querySelectorAll('.reference-audio')];
document.querySelectorAll('.bank-filter').forEach((button) => {
  button.addEventListener('click', () => {
    document.querySelectorAll('.bank-filter').forEach((other) => other.setAttribute('aria-pressed', String(other === button)));
    document.querySelectorAll('.bank-row').forEach((row) => {
      row.hidden = button.dataset.group !== 'all' && row.dataset.group !== button.dataset.group;
      if (row.hidden) row.querySelector('audio').pause();
    });
  });
});
let playing = false;
let repeat = false;
let volume = 0.65;
let muted = false;
let duration = performanceData.duration;
let timer;
let toastTimer;
let hopTimer;
let cheers = 0;
let playRequest = 0;

function toast(message) {
  $('toast').textContent = message;
  $('toast').classList.add('visible');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => $('toast').classList.remove('visible'), 3500);
}
function formatTime(value) {
  const seconds = Math.max(0, Math.floor(Number.isFinite(value) ? value : 0));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
}
function paintRange(input) {
  const width = Number(input.max) - Number(input.min);
  input.style.setProperty('--fill', `${width > 0 ? (Number(input.value) - Number(input.min)) / width * 100 : 0}%`);
}
function renderProgress() {
  const position = Math.min(audio.currentTime || 0, duration);
  progress.max = duration;
  progress.value = position;
  paintRange(progress);
  $('currentTime').textContent = formatTime(position);
  $('duration').textContent = formatTime(duration);
  progress.setAttribute('aria-valuetext', `${formatTime(position)} / ${formatTime(duration)}`);
  scene.classList.toggle('is-singing', playing && performanceData.notes.some((note) => position >= note.time && position < note.time + note.duration));
  syncDance(position);
  if (playing && performanceData.phrases) {
    const phrase = performanceData.phrases.find((item) => position >= item.time && position < item.time + item.duration);
    const names = {'Wula!':'우라!', 'Bryy':'브르르!', 'Haaaa?!':'하아?!', 'Haiyaha!':'하이야하!', 'Puriyaha Yiha':'프리야하! 이햐!', 'Wulalawulala':'우라라 우라라♪', 'Wula wula wula':'우라! 우라! 우라!', 'Wuyayiha':'우야이햐!', 'Uriri':'우 리 리!', 'Yahayaha Yahayaha':'야하야하 야하야하!', 'Una yaha - curry':'우나! 야하!', 'Wulayaha yahawula fast':'우라야하! 야하우라!', 'Wulayaha yahawula slow':'우라야하~ 야하우라~', 'Bryyyyyyyyy':'브르르르르!', 'u-una-na-ya-ha':'우! 우나나! 야하!', 'usagi yahaaaaaa':'야하아아!', 'Yaaaahaaaaa':'야하아아!'};
    $('speechBubble').textContent = phrase ? (names[phrase.name] || phrase.name) : '♬ … ♬';
  }
}
function renderPlaying() {
  scene.classList.toggle('is-playing', playing);
  if (!playing) scene.classList.remove('is-singing');
  if (!playing) $('usagiButton').style.transform = '';
  $('playButton').setAttribute('aria-label', playing ? '일시 정지' : '재생');
  $('playIcon').innerHTML = playing
    ? '<path d="M7 5h4v14H7zm7 0h4v14h-4z" fill="currentColor"/>'
    : '<path d="m9 5 11 7-11 7Z" fill="currentColor"/>';
  $('liveBadge').innerHTML = `<i></i> ${playing ? 'LIVE · YAHAAA!' : audio.currentTime > 0 ? 'TAKE A LITTLE BREAK' : 'READY TO SING'}`;
  $('speechBubble').textContent = playing ? '야하! 우라! 야하~♪' : '우라! 크리스마스다!';
}
function syncDance(position) {
  const beats = performanceData.rhythm?.beats;
  const rapid = performanceData.arrangement?.style === 'energetic-rap';
  scene.classList.toggle('rap-energy',rapid);
  scene.style.setProperty('--rap-beat',`${60/(performanceData.arrangement?.quarterBpm || 150)}s`);
  const synced = Array.isArray(beats) && beats.length > 1;
  scene.classList.toggle('beat-synced', synced);
  if (!playing || !synced || reducedMotion.matches) {
    $('usagiButton').style.transform = '';
    return;
  }
  let low = 0;
  let high = beats.length;
  while (low < high) {
    const middle = (low + high) >> 1;
    if (beats[middle] <= position) low = middle + 1;
    else high = middle;
  }
  const index = Math.max(0, low - 1);
  const left = beats[index];
  const right = beats[index + 1] ?? left + 60 / (performanceData.rhythm.bpm || 120);
  const phase = Math.max(0, Math.min(1, (position - left) / Math.max(.1, right - left)));
  const subdivision = rapid && (performanceData.rhythm.bpm || 120) < 105 ? 2 : 1;
  const bouncePhase = (phase*subdivision)%1;
  const lift = -Math.sin(bouncePhase * Math.PI) * (rapid ? 15 : 10);
  const lean = Math.sin((index*subdivision + phase*subdivision) * Math.PI) * (rapid ? 7 : 4.5);
  $('usagiButton').style.transform = `translateY(${lift.toFixed(2)}px) rotate(${lean.toFixed(2)}deg)`;
}
function pauseReferences() { referencePlayers.forEach((player) => player.pause()); }
async function play() {
  const request = ++playRequest;
  pauseReferences();
  try {
    if (audio.ended) audio.currentTime = 0;
    await audio.play();
    if (request !== playRequest) return;
  } catch (error) {
    if (request !== playRequest || error.name === 'AbortError') return;
    toast('샘플을 재생하지 못했어요. assets 폴더도 index.html 옆에 있는지 확인해 주세요.');
    pause();
  }
}
function pause() {
  playRequest += 1;
  audio.pause();
  playing = false;
  clearInterval(timer);
  renderPlaying();
}
audio.addEventListener('playing', () => {
  playing = true;
  clearInterval(timer);
  timer = setInterval(renderProgress, 40);
  renderPlaying();
  renderProgress();
});
audio.addEventListener('pause', () => {
  playing = false;
  clearInterval(timer);
  renderPlaying();
  renderProgress();
});
audio.addEventListener('waiting', () => {
  playing = false;
  clearInterval(timer);
  renderPlaying();
  $('liveBadge').innerHTML = '<i></i> LOADING VOICE…';
});
audio.addEventListener('loadedmetadata', () => {
  if (Number.isFinite(audio.duration) && audio.duration > 0) duration = audio.duration;
  if (pendingSeek !== null) {
    audio.currentTime = Math.min(pendingSeek, Math.max(0, duration - .01));
    pendingSeek = null;
  }
  renderProgress();
});
audio.addEventListener('ended', () => {
  pause();
  audio.currentTime = 0;
  renderProgress();
  renderPlaying();
  $('speechBubble').textContent = '앵콜? 야하!';
});
audio.addEventListener('error', () => {
  pause();
  toast('공연 파일을 읽을 수 없어요. assets/usagi-christmas-preview.mp3를 확인해 주세요.');
});
$('playButton').addEventListener('click', () => audio.paused ? play() : pause());
$('replayButton').addEventListener('click', () => {
  audio.currentTime = 0;
  renderProgress();
  renderPlaying();
  if (audio.paused) play();
});
$('loopButton').addEventListener('click', () => {
  repeat = !repeat;
  audio.loop = repeat;
  $('loopButton').setAttribute('aria-pressed', String(repeat));
  $('loopButton').setAttribute('aria-label', `반복 재생 ${repeat ? '끄기' : '켜기'}`);
  toast(repeat ? '우사기의 앙코르! 반복 재생을 켰어요.' : '반복 재생을 껐어요.');
});
progress.addEventListener('input', () => {
  if (Number.isFinite(audio.duration)) audio.currentTime = Number(progress.value);
  renderProgress();
});
function renderVolume() {
  audio.volume = volume;
  audio.muted = muted;
  referencePlayers.forEach((player) => { player.volume = volume; player.muted = muted; });
  $('volume').value = muted ? 0 : volume * 100;
  paintRange($('volume'));
  $('volumeValue').textContent = muted ? '0%' : `${Math.round(volume * 100)}%`;
  $('muteButton').setAttribute('aria-label', muted ? '음소거 해제' : '음소거');
  $('muteButton').style.opacity = muted ? '0.4' : '1';
}
$('volume').addEventListener('input', (event) => {
  volume = Number(event.target.value) / 100;
  muted = volume === 0;
  renderVolume();
});
function toggleMute() {
  muted = !muted;
  renderVolume();
  toast(muted ? '쉿, 잠깐 조용한 크리스마스.' : '다시 신나게! 음소거를 해제했어요.');
}
$('muteButton').addEventListener('click', toggleMute);

function renderBacking() {
  const button = $('bgmButton');
  button.disabled = !performanceData.backing?.enabled;
  button.classList.toggle('is-active', bgmEnabled);
  button.setAttribute('aria-pressed', String(bgmEnabled));
  button.setAttribute('aria-label', bgmEnabled ? '반주 끄고 우사기 목소리만 듣기' : '원곡 반주 켜기');
  $('bgmLabel').textContent = button.disabled ? '반주 준비 중' : bgmEnabled ? '반주 켜짐' : '목소리만';
  $('trackArtist').textContent = bgmEnabled ? `${performanceData.backing.artist || performanceData.artist || '원곡'} 원곡 · 우사기 버전` : '우사기 목소리만 · 반주 없이 듣는 중';
}
$('bgmButton').addEventListener('click', () => {
  if (!performanceData.backing?.enabled) return;
  const resume = !audio.paused;
  const position = audio.ended ? 0 : audio.currentTime;
  pause();
  bgmEnabled = !bgmEnabled;
  audio.src = bgmEnabled ? performanceData.backing.mixFile : performanceData.backing.voiceFile;
  pendingSeek = position;
  audio.load();
  renderBacking();
  if (resume) play();
});

// Snow and confetti never intercept clicks; reduced-motion users get a still stage.
let snowEnabled = !reducedMotion.matches;
function renderSnow() {
  $('snowfall').replaceChildren();
  $('snowButton').classList.toggle('is-active', snowEnabled);
  $('snowButton').setAttribute('aria-pressed', String(snowEnabled));
  if (!snowEnabled || reducedMotion.matches) return;
  const fragment = document.createDocumentFragment();
  for (let index = 0; index < 35; index++) {
    const flake = document.createElement('i');
    flake.className = 'snowflake';
    const size = 2 + Math.random() * 4;
    Object.assign(flake.style, {left: `${Math.random() * 100}%`, width: `${size}px`, height: `${size}px`, animationDuration: `${9 + Math.random() * 14}s`, animationDelay: `${-Math.random() * 25}s`, opacity: String(0.3 + Math.random() * 0.6)});
    flake.style.setProperty('--drift', `${Math.random() * 100 - 50}px`);
    fragment.appendChild(flake);
  }
  $('snowfall').appendChild(fragment);
}
$('snowButton').addEventListener('click', () => {
  snowEnabled = !snowEnabled;
  renderSnow();
  if (snowEnabled && reducedMotion.matches) toast('기기의 동작 줄이기 설정에 맞춰 눈 애니메이션은 쉬어가요.');
});
reducedMotion.addEventListener('change', () => {
  snowEnabled = !reducedMotion.matches;
  renderSnow();
  if (reducedMotion.matches) $('usagiButton').classList.remove('hop');
  syncDance(audio.currentTime);
});
$('lightButton').addEventListener('click', () => {
  const off = scene.classList.toggle('lights-off');
  $('lightButton').setAttribute('aria-pressed', String(!off));
  $('lightButton').setAttribute('aria-label', `무대 조명 ${off ? '켜기' : '끄기'}`);
  $('lightButton').textContent = off ? '☾' : '☀';
});

function cheer() {
  cheers += 1;
  $('cheerCount').textContent = String(cheers);
  const sayings = ['야하! 선물은 나야!', '우라라라~! ♡', '더 크게! 야하!', '메리 우사기마스!'];
  $('speechBubble').textContent = sayings[(cheers - 1) % sayings.length];
  $('usagiButton').classList.remove('hop');
  if (!reducedMotion.matches) {
    void $('usagiButton').offsetWidth;
    $('usagiButton').classList.add('hop');
  }
  clearTimeout(hopTimer);
  hopTimer = setTimeout(() => $('usagiButton').classList.remove('hop'), 600);
  if (reducedMotion.matches) return;
  // Bound active particles even if the visitor cheers very enthusiastically.
  if ($('confetti').childElementCount > 60) return;
  const fragment = document.createDocumentFragment();
  for (let index = 0; index < 15; index++) {
    const piece = document.createElement('span');
    piece.className = 'confetti-piece';
    piece.textContent = ['♡', '✦', '♪', '✧'][index % 4];
    piece.style.color = ['#b64b42', '#d3ab55', '#7a9670', '#cf967b'][index % 4];
    piece.style.setProperty('--x', `${Math.random() * 480 - 240}px`);
    piece.style.setProperty('--y', `${-60 - Math.random() * 270}px`);
    piece.style.setProperty('--r', `${Math.random() * 250 - 125}deg`);
    piece.addEventListener('animationend', () => piece.remove(), {once:true});
    fragment.appendChild(piece);
  }
  $('confetti').appendChild(fragment);
}
$('cheerButton').addEventListener('click', cheer);
$('usagiButton').addEventListener('click', cheer);

const musicDialog = $('musicDialog');
$('musicButton').addEventListener('click', () => musicDialog.showModal());
$('helpButton').addEventListener('click', () => $('helpDialog').showModal());
document.querySelectorAll('[data-close]').forEach((button) => button.addEventListener('click', () => button.closest('dialog').close()));
document.querySelectorAll('dialog').forEach((dialog) => {
  dialog.addEventListener('close', pauseReferences);
  dialog.addEventListener('click', (event) => {
    const bounds = dialog.getBoundingClientRect();
    if (event.target === dialog && (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom)) dialog.close();
  });
});
referencePlayers.forEach((player) => {
  player.addEventListener('play', () => {
    pause();
    referencePlayers.filter((other) => other !== player).forEach((other) => other.pause());
  });
});
$('previewButton').addEventListener('click', () => {
  musicDialog.close();
  audio.currentTime = 0;
  play();
});
document.addEventListener('keydown', (event) => {
  const target = event.target;
  if (target instanceof HTMLElement && (target.matches('input,textarea,select,button,a,audio') || target.isContentEditable)) return;
  if (document.querySelector('dialog[open]') || event.ctrlKey || event.metaKey || event.altKey) return;
  if (event.code === 'Space') {
    event.preventDefault();
    audio.paused ? play() : pause();
  } else if (event.key.toLowerCase() === 'm') toggleMute();
});
window.addEventListener('pagehide', () => { pause(); pauseReferences(); });
renderSnow();
renderVolume();
renderProgress();
$('trackKicker').textContent = `USAGI CHRISTMAS LIVE · ${formatTime(duration)}`;
renderBacking();
if (performanceData.songStart !== undefined) $('originalSongLink').href = `https://www.youtube.com/watch?v=yXQViqx6GMY&t=${Math.floor(performanceData.songStart)}s`;

// Conversion uses the separate Python service; static-file preview stays usable.
const apiBase = (window.USAGI_CONFIG?.apiBaseUrl || '').replace(/\/$/, '');
let serverReady = false;
let pendingJob = null;
let pollTimer;
let pollingGeneration = 0;
let lastRequestKey = '';
let requestToken = '';
let currentShare = null;
const apiUrl = (path) => `${apiBase}${path}`;

async function apiRequest(path, options = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 12000);
  try {
    const response = await fetch(apiUrl(path), {...options, signal: controller.signal});
    let body;
    try { body = await response.json(); }
    catch { throw new Error('공연 준비실에서 응답을 읽지 못했어요. 잠시 뒤 다시 시도해 주세요.'); }
    if (!response.ok) {
      const message = typeof body.detail === 'string' ? body.detail : response.status === 422 ? 'YouTube 링크와 시작 시각을 다시 확인해 주세요.' : '지금 요청을 처리하지 못했어요. 잠시 뒤 다시 시도해 주세요.';
      throw new Error(message);
    }
    return body;
  } catch (error) {
    if (error.name === 'AbortError') throw new Error('응답이 늦어지고 있어요. 잠시 뒤 다시 눌러주세요.');
    throw error;
  } finally { clearTimeout(timeout); }
}
function rememberJob(id) {
  try {
    if (id) localStorage.setItem('usagi-active-job-v4', JSON.stringify({id, apiBase}));
    else localStorage.removeItem('usagi-active-job-v4');
  } catch { /* Private browsing may disable storage. */ }
}
function setRequestBusy(busy) {
  for (const id of ['youtubeUrl', 'songLength', 'songStart']) $(id).disabled = busy;
  $('convertButton').disabled = busy || !serverReady;
  $('convertButton').textContent = busy ? '우사기가 준비 중…' : '우사기, 불러줘! ↗';
}
function loadPerformance(result, shared = null) {
  pause();
  currentShare = shared;
  if (!shared && new URL(location.href).searchParams.has('share')) history.replaceState(null, '', shareUrl());
  performanceData = {...result, backing: {...result.backing}};
  for (const field of ['file', 'mixFile', 'voiceFile']) performanceData.backing[field] = apiUrl(result.backing[field]);
  duration = result.duration;
  bgmEnabled = true;
  pendingSeek = 0;
  audio.src = performanceData.backing.mixFile;
  audio.load();
  $('trackTitle').textContent = result.title;
  document.title = `${result.title} · 우사기의 작은 무대`;
  $('trackKicker').textContent = `우사기의 새 공연 · ${formatTime(duration)}`;
  $('originalSongName').textContent = result.title;
  $('originalArtist').textContent = ` · ${result.artist}`;
  const source = new URL(result.songSource);
  source.searchParams.set('t', `${Math.floor(result.songStart)}s`);
  $('originalSongLink').href = source.href;
  renderBacking();
  renderProgress();
  renderPlaying();
}
async function pollJob(identifier, generation) {
  if (generation !== pollingGeneration) return;
  try {
    const job = await apiRequest(`/api/jobs/${identifier}`);
    if (generation !== pollingGeneration) return;
    $('conversionStatus').hidden = false;
    $('jobTitle').textContent = job.title || '우사기가 무대에 오를 준비 중!';
    $('jobMessage').textContent = job.message;
    const value = Math.round(job.progress * 100);
    $('jobProgress').setAttribute('aria-valuenow', value);
    $('jobProgress').style.setProperty('--progress', `${value}%`);
    if (job.status === 'completed') {
      loadPerformance(job.result);
      pendingJob = null;
      setRequestBusy(false);
      $('cancelJobButton').hidden = true;
      $('jobResult').hidden = false;
      $('downloadResult').href = `${performanceData.backing.mixFile}?download=true`;
      toast('우사기 공연 준비 끝! 재생 버튼을 눌러줘.');
      return;
    }
    if (job.status === 'failed' || job.status === 'cancelled') {
      pendingJob = null;
      requestToken = '';
      rememberJob(null);
      setRequestBusy(false);
      $('cancelJobButton').hidden = true;
      return;
    }
    pollTimer = setTimeout(() => pollJob(identifier, generation), 2000);
  } catch (error) {
    if (generation !== pollingGeneration) return;
    $('jobMessage').textContent = error.message.includes('만료') ? error.message : '잠시 연결이 끊겼어요. 진행 중인 공연을 다시 확인하고 있어요.';
    if (error.message.includes('만료')) {
      pendingJob = null;
      rememberJob(null);
      setRequestBusy(false);
      $('cancelJobButton').hidden = true;
    } else pollTimer = setTimeout(() => pollJob(identifier, generation), 5000);
  }
}
$('conversionForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  if (!serverReady || pendingJob) return;
  setRequestBusy(true);
  $('jobResult').hidden = true;
  $('conversionStatus').hidden = false;
  $('cancelJobButton').hidden = true;
  $('jobProgress').style.setProperty('--progress', '0%');
  $('jobProgress').setAttribute('aria-valuenow', '0');
  $('jobMessage').textContent = '공연을 부탁하고 있어요…';
  try {
    const payload = {youtube_url: $('youtubeUrl').value.trim(), start: Number($('songStart').value), duration: $('songLength').value ? Number($('songLength').value) : null};
    const key = JSON.stringify(payload);
    if (key !== lastRequestKey || !requestToken) {
      lastRequestKey = key;
      const bytes = new Uint8Array(16);
      crypto.getRandomValues(bytes);
      requestToken = [...bytes].map((byte) => byte.toString(16).padStart(2, '0')).join('');
    }
    const job = await apiRequest('/api/jobs', {method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({...payload, client_token: requestToken})});
    pendingJob = job.id;
    rememberJob(job.id);
    $('cancelJobButton').hidden = false;
    clearTimeout(pollTimer);
    pollJob(job.id, ++pollingGeneration);
  } catch (error) {
    $('jobMessage').textContent = error.message === 'Failed to fetch' ? '공연 준비실에 연결하지 못했어요. 잠시 뒤 다시 눌러주세요.' : error.message;
    setRequestBusy(false);
  }
});
$('cancelJobButton').addEventListener('click', async () => {
  if (!pendingJob) return;
  $('cancelJobButton').disabled = true;
  try {
    await apiRequest(`/api/jobs/${pendingJob}`, {method: 'DELETE'});
    $('jobMessage').textContent = '취소를 요청했어요. 현재 작업이 멈추면 알려줄게요.';
  } catch { $('jobMessage').textContent = '취소 요청을 전달하지 못했어요. 다시 눌러주세요.'; }
  finally { $('cancelJobButton').disabled = false; }
});
$('playResultButton').addEventListener('click', () => {
  $('stage').scrollIntoView({behavior: reducedMotion.matches ? 'instant' : 'smooth', block: 'center'});
  play();
});

function shareUrl(identifier) {
  const url = new URL(location.href);
  url.search = '';
  url.hash = '';
  if (identifier) url.searchParams.set('share', identifier);
  return url.href;
}

$('shareButton').addEventListener('click', async () => {
  $('shareDialog').showModal();
  $('shareSongTitle').textContent = performanceData.title || $('trackTitle').textContent;
  $('shareControls').hidden = true;
  $('shareMessage').textContent = '공유 링크를 준비하고 있어요…';
  if (!['http:', 'https:'].includes(location.protocol)) {
    $('shareMessage').textContent = '사이트 주소로 접속하면 공연 링크를 공유할 수 있어요.';
    return;
  }
  // Keep the selected performance even if another conversion finishes meanwhile.
  const selected = performanceData;
  const selectedShare = currentShare;
  try {
    let shared = selectedShare;
    if (shared && shared.expires_at * 1000 <= Date.now() && !selected.jobId) throw new Error('이 공연의 공유 기간이 끝났어요. 새 공연을 만들어 주세요.');
    if (selected.jobId && (!shared || shared.expires_at * 1000 <= Date.now())) {
      shared = await apiRequest(`/api/jobs/${selected.jobId}/share`, {method: 'POST'});
      if (performanceData === selected) currentShare = shared;
    }
    $('shareLink').value = shareUrl(shared?.id);
    $('shareControls').hidden = false;
    $('nativeShareButton').hidden = typeof navigator.share !== 'function';
    $('shareMessage').textContent = shared ? `이 공연은 ${new Date(shared.expires_at * 1000).toLocaleDateString('ko-KR')}까지 공유돼요. 받은 사람은 재생 버튼만 누르면 돼요.` : '크리스마스 우사기 공연을 친구에게 보내줘!';
    $('shareFootnote').textContent = ['localhost', '127.0.0.1', '[::1]'].includes(location.hostname) ? '현재 주소는 이 기기에서만 열려요. 배포된 사이트에서는 친구에게 보낼 수 있어요.' : '링크를 아는 사람은 누구나 이 공연을 들을 수 있어요.';
  } catch (error) { $('shareMessage').textContent = error.message; }
});
$('shareLink').addEventListener('click', () => $('shareLink').select());
$('copyShareButton').addEventListener('click', async () => {
  try {
    await navigator.clipboard.writeText($('shareLink').value);
    toast('공연 링크를 복사했어! 친구에게 보내줘.');
  } catch {
    $('shareLink').focus();
    $('shareLink').select();
    $('shareMessage').textContent = '주소를 선택했어요. 길게 누르거나 Ctrl+C로 복사해 주세요.';
  }
});
$('nativeShareButton').addEventListener('click', async () => {
  try {
    await navigator.share({title: `${$('shareSongTitle').textContent} · 우사기 공연`, text: '우사기가 부르는 이 노래, 같이 듣자! 야하!', url: $('shareLink').value});
  } catch (error) {
    if (error.name !== 'AbortError') $('shareMessage').textContent = '앱 공유를 열지 못했어요. 링크 복사를 이용해 주세요.';
  }
});

async function openSharedPerformance(identifier) {
  $('conversionStatus').hidden = false;
  $('cancelJobButton').hidden = true;
  $('jobResult').hidden = true;
  $('jobTitle').textContent = '친구가 보낸 우사기 공연';
  $('jobMessage').textContent = '공유받은 공연을 불러오고 있어요…';
  setRequestBusy(true);
  try {
    if (!/^[a-f0-9]{32}$/.test(identifier)) throw new Error('공유 링크가 올바르지 않아요. 주소를 다시 확인해 주세요.');
    const shared = await apiRequest(`/api/shares/${identifier}`);
    loadPerformance(shared.result, shared);
    $('jobTitle').textContent = shared.result.title;
    $('jobMessage').textContent = `공유받은 우사기 공연이에요. ${new Date(shared.expires_at * 1000).toLocaleDateString('ko-KR')}까지 들을 수 있어요.`;
    $('jobProgress').style.setProperty('--progress', '100%');
    $('jobProgress').setAttribute('aria-valuenow', '100');
    $('jobResult').hidden = false;
    $('downloadResult').href = `${performanceData.backing.mixFile}?download=true`;
  } catch (error) {
    $('jobMessage').textContent = `${error.message} 아래 기본 공연을 듣거나 새 공연을 만들어 주세요.`;
  } finally { setRequestBusy(false); }
}
async function connectService() {
  try {
    if (location.protocol === 'file:' && !apiBase) throw new Error('static-preview');
    const health = await apiRequest('/api/health');
    if (health.status !== 'ok') throw new Error('unavailable');
    serverReady = true;
    $('connectionStatus').textContent = '● 노래할 준비 완료';
    $('connectionStatus').classList.add('connected');
    $('connectionNote').textContent = '노래의 반주는 그대로, 다양한 우사기 발성과 추임새로 공연을 만들어요.';
    setRequestBusy(false);
    const sharedId = new URL(location.href).searchParams.get('share');
    if (sharedId !== null) {
      await openSharedPerformance(sharedId);
      return;
    }
    let saved;
    try { saved = JSON.parse(localStorage.getItem('usagi-active-job-v4')); } catch { /* Nothing to restore. */ }
    if (saved?.id && saved.apiBase === apiBase && /^[a-f0-9]{32}$/.test(saved.id)) {
      pendingJob = saved.id;
      $('conversionStatus').hidden = false;
      $('cancelJobButton').hidden = false;
      setRequestBusy(true);
      pollJob(saved.id, ++pollingGeneration);
    }
  } catch {
    $('connectionStatus').textContent = '샘플 공연 모드';
    $('connectionNote').textContent = '지금은 노래 변환에 연결할 수 없어요. 아래 크리스마스 샘플 공연은 바로 들을 수 있어요.';
    setRequestBusy(false);
    if (new URL(location.href).searchParams.has('share')) {
      $('conversionStatus').hidden = false;
      $('cancelJobButton').hidden = true;
      $('jobMessage').textContent = '공유 공연에 연결하지 못했어요. 잠시 뒤 새로고침해 주세요. 현재는 기본 공연을 듣고 있어요.';
    }
  }
}
window.addEventListener('pagehide', () => { clearTimeout(pollTimer); pollingGeneration += 1; });
window.addEventListener('pageshow', (event) => {
  if (event.persisted && pendingJob) pollJob(pendingJob, ++pollingGeneration);
});
connectService();
