const text = document.querySelector('#text');
const button = document.querySelector('#generate');
const message = document.querySelector('#message');
const audio = document.querySelector('#audio');
let ready = false, busy = false, audioUrl = null;
const examples = {
  greeting: 'Habari za asubuhi! Karibu katika studio yetu ya sauti. Tunafurahi kuwa nawe leo.',
  story: 'Jua lilipochomoza, Amina alifungua dirisha na kusikiliza ndege wakiimba. Ilikuwa siku mpya, yenye matumaini mapya.',
  announcement: 'Tangazo kwa wanafunzi wote. Mkutano wetu utafanyika kesho saa nne asubuhi katika ukumbi wa shule. Karibuni nyote.'
};
function update() {
  document.querySelector('#count').textContent = `${text.value.length.toLocaleString()} / 1,000`;
  button.disabled = !ready || busy || !text.value.trim();
}
text.addEventListener('input', update);
document.querySelectorAll('[data-example]').forEach(el => el.addEventListener('click', () => {
  text.value = examples[el.dataset.example]; update(); text.focus();
}));
async function checkHealth() {
  try {
    const response = await fetch('/api/v1/health');
    if (!response.ok) throw new Error();
    const data = await response.json();
    document.dispatchEvent(new CustomEvent('studio-health', {detail: data}));
    ready = data.status === 'ready';
    document.querySelector('#model-status').textContent = ready ? 'Voice ready to create' : data.status === 'error' ? 'Voice unavailable · restart to retry' : 'Loading the voice…';
    document.querySelector('#status-dot').className = `me-2 ${ready ? 'text-success' : data.status === 'error' ? 'text-danger' : 'text-warning'}`;
  } catch {
    document.dispatchEvent(new CustomEvent('studio-health', {detail: null}));
    ready = false;
    document.querySelector('#model-status').textContent = 'Cannot connect to the server';
    document.querySelector('#status-dot').className = 'text-danger me-2';
  }
  update();
}
document.querySelector('#speech-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (!ready || busy || !text.value.trim()) return;
  const submittedText = text.value;
  busy = true; update();
  button.firstElementChild.textContent = 'Creating your speech…';
  message.className = 'small mt-3 mb-0 text-body-secondary';
  message.textContent = 'Turning your words into speech. Longer passages take a little more time.';
  try {
    const response = await fetch('/api/v1/tts', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({text: submittedText})});
    if (!response.ok) {
      const error = await response.json();
      throw new Error(typeof error.detail === 'string' ? error.detail : 'Please enter between 1 and 1,000 characters of Kiswahili text.');
    }
    const blob = await response.blob();
    audio.pause(); audio.removeAttribute('src'); audio.load();
    if (audioUrl) URL.revokeObjectURL(audioUrl);
    audioUrl = URL.createObjectURL(blob);
    audio.src = audioUrl;
    document.querySelector('#download').href = audioUrl;
    document.querySelector('#empty-output').hidden = true;
    document.querySelector('#audio-output').hidden = false;
    document.querySelector('#audio-meta').textContent = `${submittedText.length} characters · WAV · 16 kHz · ${Math.round(blob.size / 1024)} KB`;
    message.textContent = 'Your speech is ready. Press play to listen.';
  } catch (error) {
    message.className = 'small mt-3 mb-0 text-danger'; message.textContent = error.message || 'Could not generate speech. Please try again.';
  } finally {
    busy = false; button.firstElementChild.textContent = 'Generate speech'; update(); checkHealth();
  }
});
text.addEventListener('keydown', event => {
  if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
    event.preventDefault(); document.querySelector('#speech-form').requestSubmit();
  }
});
update(); checkHealth(); setInterval(checkHealth, 5000);
window.addEventListener('beforeunload', () => {if (audioUrl) URL.revokeObjectURL(audioUrl);});
