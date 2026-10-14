const fileInput = document.querySelector('#audio-file');
const transcribeButton = document.querySelector('#transcribe');
const recordButton = document.querySelector('#record');
const stopButton = document.querySelector('#stop-recording');
const sttMessage = document.querySelector('#stt-message');
const transcript = document.querySelector('#transcript');
const copyButton = document.querySelector('#copy-transcript');
const sourceAudio = document.querySelector('#source-audio');
const maxBytes = 20 * 1024 * 1024;
let source = null, sourceUrl = null, sttReady = false, transcribing = false;
let recorder = null, microphone = null, recording = false, acquiring = false;
let stopTimer = null, clockTimer = null;

function notifyStt(value, error = false) {
  sttMessage.className = `small mt-3 mb-0 ${error ? 'text-danger' : 'text-body-secondary'}`;
  sttMessage.textContent = value;
}
function updateTranscription() {
  transcribeButton.disabled = !sttReady || !source || transcribing || recording || acquiring;
  fileInput.disabled = transcribing || recording || acquiring;
  recordButton.disabled = transcribing || recording || acquiring || !navigator.mediaDevices?.getUserMedia || !window.MediaRecorder;
  copyButton.disabled = !transcript.value;
}
document.addEventListener('studio-health', event => {
  const state = event.detail?.stt?.status;
  const progress = event.detail?.stt?.progress;
  sttReady = state === 'ready';
  const statusMessage = !event.detail
    ? 'Server is offline. Start the app to reconnect.'
    : !event.detail.stt
      ? 'This server does not have speech recognition. Restart the app to load the update.'
      : sttReady
        ? 'Swahili recognition ready'
        : state === 'error'
          ? 'Recognition could not load. Restart the app to retry.'
          : progress?.phase === 'downloading'
            ? 'Downloading the recognition model…'
            : 'Loading the recognition model into memory…';
  document.querySelector('#stt-model-status').textContent = statusMessage;
  const downloading = state === 'loading' && progress?.phase === 'downloading';
  document.querySelector('#stt-download').hidden = !downloading;
  if (downloading) {
    document.querySelector('#stt-download-fill').style.width = `${progress.percent}%`;
    document.querySelector('#stt-download-bar').setAttribute('aria-valuenow', progress.percent);
    document.querySelector('#stt-download-text').textContent = `${(progress.downloaded_bytes / 1e9).toFixed(2)} GB / ${(progress.total_bytes / 1e9).toFixed(2)} GB · ${progress.percent}% · This download is needed only once.`;
  }
  updateTranscription();
});
function setSource(file) {
  if (!file || !file.size) throw new Error('Choose a non-empty audio file.');
  if (file.size > maxBytes) throw new Error('Audio files must be 20 MB or smaller.');
  sourceAudio.pause(); sourceAudio.removeAttribute('src'); sourceAudio.load();
  if (sourceUrl) URL.revokeObjectURL(sourceUrl);
  source = file; sourceUrl = URL.createObjectURL(file); sourceAudio.src = sourceUrl;
  document.querySelector('#source-name').textContent = `${file.name} · ${(file.size / 1024 / 1024).toFixed(2)} MB`;
  document.querySelector('#source-preview').hidden = false;
  transcript.value = ''; document.querySelector('#transcript-meta').textContent = '';
  copyButton.textContent = 'Copy transcript';
  notifyStt('Audio selected. Press Transcribe Swahili when the recognizer is ready.');
  updateTranscription();
}
fileInput.addEventListener('change', () => {
  if (!fileInput.files.length) return;
  try { setSource(fileInput.files[0]); }
  catch (error) {
    source = null; document.querySelector('#source-preview').hidden = true;
    sourceAudio.pause(); sourceAudio.removeAttribute('src'); sourceAudio.load();
    if (sourceUrl) URL.revokeObjectURL(sourceUrl); sourceUrl = null;
    notifyStt(error.message, true); updateTranscription();
  }
});
function releaseMicrophone() {
  clearTimeout(stopTimer); clearInterval(clockTimer);
  if (microphone) microphone.getTracks().forEach(track => track.stop());
  microphone = null;
}
function stopRecording() {
  if (recorder && recorder.state !== 'inactive') recorder.stop();
  releaseMicrophone();
}
recordButton.addEventListener('click', async () => {
  if (acquiring || recording || transcribing) return;
  acquiring = true; updateTranscription();
  try {
    microphone = await navigator.mediaDevices.getUserMedia({audio: true});
    const mime = ['audio/webm;codecs=opus', 'audio/mp4', 'audio/ogg;codecs=opus'].find(type => MediaRecorder.isTypeSupported(type));
    recorder = new MediaRecorder(microphone, mime ? {mimeType: mime} : undefined);
    const chunks = [];
    let failed = false;
    recorder.ondataavailable = event => { if (event.data.size) chunks.push(event.data); };
    recorder.onstop = () => {
      releaseMicrophone(); recording = false; stopButton.hidden = true;
      document.querySelector('#recording-time').textContent = '';
      if (!failed) {
        const type = recorder.mimeType;
        const extension = type.includes('mp4') ? 'm4a' : type.includes('ogg') ? 'ogg' : 'webm';
        fileInput.value = '';
        try { setSource(new File(chunks, `microphone.${extension}`, {type})); }
        catch (error) { notifyStt(error.message, true); }
      }
      updateTranscription();
    };
    recorder.onerror = () => { failed = true; stopRecording(); notifyStt('Recording failed. Please upload an audio file instead.', true); };
    recorder.start(); recording = true; stopButton.hidden = false;
    const started = Date.now();
    const tick = () => { document.querySelector('#recording-time').textContent = `Recording · ${Math.min(60, Math.floor((Date.now() - started) / 1000))} / 60 seconds`; };
    tick(); clockTimer = setInterval(tick, 500); stopTimer = setTimeout(stopRecording, 60000);
    notifyStt('Recording your microphone. Press Stop recording when finished.');
  } catch (error) {
    releaseMicrophone(); recording = false; stopButton.hidden = true;
    notifyStt(error.name === 'NotAllowedError' ? 'Microphone access was denied. You can upload an audio file instead.' : 'Cannot start the microphone. Try uploading an audio file.', true);
  } finally { acquiring = false; updateTranscription(); }
});
stopButton.addEventListener('click', stopRecording);
document.querySelector('#transcription-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (!source || !sttReady || transcribing || recording || acquiring) return;
  transcribing = true; updateTranscription(); transcribeButton.textContent = 'Transcribing…';
  notifyStt('Listening to your audio. Transcription may take a moment on CPU.');
  try {
    const body = new FormData(); body.append('file', source, source.name);
    const response = await fetch('/api/v1/stt', {method: 'POST', body});
    const result = await response.json();
    if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Could not transcribe this audio.');
    transcript.value = result.text;
    document.querySelector('#transcript-meta').textContent = `Kiswahili · ${result.duration_seconds} seconds · Meta MMS`;
    notifyStt(result.text ? 'Your transcript is ready. Review it before using it.' : 'No words were recognized. Try a clearer recording.');
  } catch (error) { notifyStt(error.message || 'Could not connect to the server.', true); }
  finally { transcribing = false; transcribeButton.textContent = 'Transcribe Swahili'; updateTranscription(); }
});
copyButton.addEventListener('click', async () => {
  try { await navigator.clipboard.writeText(transcript.value); copyButton.textContent = 'Copied'; }
  catch { transcript.focus(); transcript.select(); notifyStt('Select and copy the transcript manually; clipboard access is unavailable.'); }
});
window.addEventListener('beforeunload', () => { releaseMicrophone(); if (sourceUrl) URL.revokeObjectURL(sourceUrl); });
updateTranscription();
