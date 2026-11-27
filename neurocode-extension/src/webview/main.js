/**
 * neurocode-extension/src/webview/main.js
 *
 * Webview client script running inside the VS Code Webview iframe.
 * Handles UI events, text commands, audio recording, and relays messages
 * to/from the Extension Host via acquireVsCodeApi().
 */

(function () {
  const vscode = acquireVsCodeApi();
  const statusEl = document.getElementById('status');
  const logEl = document.getElementById('log');
  const observerStripEl = document.getElementById('observerStrip');
  const observerTextEl = document.getElementById('observerText');
  
  // UI Elements
  const micBtn = document.getElementById('micBtn');
  const textInput = document.getElementById('textInput');
  const sendBtn = document.getElementById('sendBtn');
  const confirmArea = document.getElementById('confirmArea');
  const confirmPrompt = document.getElementById('confirmPrompt');
  const yesBtn = document.getElementById('yesBtn');
  const noBtn = document.getElementById('noBtn');

  function escapeHtml(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function addFeedItem(tag, text, type = 'system') {
    if (!logEl) return;

    const item = document.createElement('article');
    item.className = 'feed-item ' + type;
    item.tabIndex = 0; // Screen-reader & keyboard focusable

    const time = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });

    let tagClass = 'tag-system';
    if (type === 'user') tagClass = 'tag-user';
    else if (type === 'assistant') tagClass = 'tag-assistant';

    const accessibleLabel = `${tag} at ${time}: ${text}`;
    item.setAttribute('aria-label', accessibleLabel);

    item.innerHTML = `
      <div class="feed-header-row">
        <span class="feed-tag ${tagClass}">${escapeHtml(tag)}</span>
        <span class="feed-time">${time}</span>
      </div>
      <div class="feed-body">${escapeHtml(text)}</div>
    `;

    logEl.appendChild(item);
    logEl.scrollTop = logEl.scrollHeight;
  }

  function log(msg) {
    if (!msg) return;
    const str = String(msg).trim();

    if (str.startsWith('Sent text:')) {
      const clean = str.replace(/^Sent text:\s*/, '');
      addFeedItem('INPUT COMMAND', clean, 'user');
    } else if (str.startsWith('Transcribed:')) {
      const clean = str.replace(/^Transcribed:\s*/, '');
      addFeedItem('VOICE COMMAND', clean, 'user');
    } else if (str.startsWith('Backend:')) {
      const clean = str.replace(/^Backend:\s*/, '');
      if (clean.startsWith('Workspace set to') || clean.startsWith('WebSocket') || clean.startsWith('Connected') || clean.startsWith('Session')) {
        addFeedItem('SYSTEM EVENT', clean, 'system');
      } else {
        addFeedItem('NEUROCODE REASONING', clean, 'assistant');
      }
    } else if (str.startsWith('Audio playback notice:') || str.startsWith('Audio narration received')) {
      return;
    } else {
      addFeedItem('SYSTEM EVENT', str, 'system');
    }
  }

  // --- Zero Dead-Air Processing Audio Ticker ---
  let pendingRequestTicker = null;

  function startProcessingAudio() {
    stopProcessingAudio();
    playEarcon('start');
    // No spoken filler here: the backend answers every command at once with a short
    // acknowledgement in the Sarvam voice ("Reading your changes."), see the 'ack' message.
    
    // Continuous tick chime sound every 1.8s while waiting for backend LLM response
    pendingRequestTicker = setInterval(() => {
      playEarcon('tick');
    }, 1800);
  }

  function stopProcessingAudio() {
    if (pendingRequestTicker) {
      clearInterval(pendingRequestTicker);
      pendingRequestTicker = null;
    }
  }

  // --- UI Event Listeners ---
  if (sendBtn && textInput) {
    sendBtn.addEventListener('click', () => {
      const text = textInput.value.trim();
      if (text) {
        log('Sent text: ' + text);
        startProcessingAudio();
        vscode.postMessage({ type: 'text_command', text });
        textInput.value = '';
      }
    });

    textInput.addEventListener('keypress', (e) => {
      if (e.key === 'Enter') {
        sendBtn.click();
      }
    });
  }


  if (micBtn) {
    micBtn.disabled = false;
    micBtn.title = 'Toggle Voice Input (Backend OS Mic)';
    micBtn.addEventListener('click', () => {
      vscode.postMessage({ type: 'toggle_backend_mic' });
    });
  }

  if (yesBtn && noBtn && confirmArea) {
    yesBtn.addEventListener('click', () => {
      addFeedItem('INPUT COMMAND', 'Confirmed action: Yes', 'user');
      vscode.postMessage({ type: 'confirm_response', confirmed: true });
      confirmArea.style.display = 'none';
    });

    noBtn.addEventListener('click', () => {
      addFeedItem('INPUT COMMAND', 'Confirmed action: Cancel', 'user');
      vscode.postMessage({ type: 'confirm_response', confirmed: false });
      confirmArea.style.display = 'none';
    });

    // Listen for Alt+Y (confirm) and Alt+N (cancel) shortcuts when focused inside the webview
    window.addEventListener('keydown', (e) => {
      const isAltY = e.altKey && (e.key === 'y' || e.key === 'Y');
      const isAltN = e.altKey && (e.key === 'n' || e.key === 'N');
      
      if (confirmArea.style.display !== 'none') {
        if (isAltY) {
          e.preventDefault();
          yesBtn.click();
        } else if (isAltN) {
          e.preventDefault();
          noBtn.click();
        }
      }
    });
  }

  // --- Audio State ---
  let isCapturing = false;

  // --- Pre-cache Female Voice (async voice load fix for Windows/Chromium) ---
  let cachedFemaleVoice = null;
  function cacheFemaleVoice() {
    const voices = window.speechSynthesis.getVoices();
    if (voices.length === 0) return;
    cachedFemaleVoice = voices.find(v =>
      /zira|female|hazel|samantha|victoria|karen|eva|catherine|anushka/i.test(v.name) &&
      !/david|mark|george|james|male|guy/i.test(v.name)
    ) || voices.find(v => !/david|mark|george|james|male/i.test(v.name) && v.lang.startsWith('en'));
    if (cachedFemaleVoice) {
      console.log('[Webview Speech] Cached female voice:', cachedFemaleVoice.name);
    }
  }
  if ('speechSynthesis' in window) {
    window.speechSynthesis.onvoiceschanged = cacheFemaleVoice;
    cacheFemaleVoice();
  }

  // --- Web Audio Earcon Synthesizer ---
  // Synthesizes 4 distinct earcon tones locally via OscillatorNode (<5ms latency).
  let audioCtxEarcon = null;
  let audioCtxPrewarmed = false;

  function getEarconContext() {
    if (!audioCtxEarcon || audioCtxEarcon.state === 'closed') {
      audioCtxEarcon = new (window.AudioContext || window.webkitAudioContext)();
    }
    if (audioCtxEarcon.state === 'suspended') {
      audioCtxEarcon.resume().catch(() => {});
    }
    return audioCtxEarcon;
  }

  // Pre-warm AudioContext on first user interaction (click/key) to guarantee earcons fire.
  // Browsers block audio until a user gesture has occurred at least once.
  function prewarmAudioContext() {
    if (audioCtxPrewarmed) return;
    try {
      const ctx = getEarconContext();
      // Play a silent node to unblock the context
      const buf = ctx.createBuffer(1, 1, 22050);
      const src = ctx.createBufferSource();
      src.buffer = buf;
      src.connect(ctx.destination);
      src.start(0);
      audioCtxPrewarmed = true;
      console.log('[Webview Audio] AudioContext pre-warmed — earcons ready');
    } catch (e) { /* silent */ }
  }
  // Attach to common user gestures
  document.addEventListener('click', prewarmAudioContext, { once: false, capture: true });
  document.addEventListener('keydown', prewarmAudioContext, { once: false, capture: true });
  // Also try immediately (may work if no autoplay block in VS Code webview)
  setTimeout(prewarmAudioContext, 500);

  function playTone(freq, duration, type = 'sine', gain = 0.18) {
    try {
      const ctx = getEarconContext();
      const osc = ctx.createOscillator();
      const gainNode = ctx.createGain();
      osc.connect(gainNode);
      gainNode.connect(ctx.destination);
      osc.frequency.setValueAtTime(freq, ctx.currentTime);
      osc.type = type;
      gainNode.gain.setValueAtTime(gain, ctx.currentTime);
      gainNode.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + duration);
      osc.start(ctx.currentTime);
      osc.stop(ctx.currentTime + duration);
    } catch (e) { /* silent fail */ }
  }

  function playEarcon(type) {
    switch (type) {
      case 'start':
        // Ascending two-tone chime: A4 then C5
        playTone(440, 0.12, 'sine', 0.15);
        setTimeout(() => playTone(523, 0.18, 'sine', 0.12), 100);
        break;
      case 'tick':
        // Crisp audible woodblock click pulse
        playTone(850, 0.06, 'sine', 0.35);
        setTimeout(() => playTone(1200, 0.04, 'triangle', 0.25), 25);
        break;
      case 'complete':
        // Satisfying rising chime: C5 -> E5
        playTone(523, 0.15, 'sine', 0.15);
        setTimeout(() => playTone(659, 0.25, 'sine', 0.12), 130);
        break;
      case 'error':
        // Low double-tone: 200Hz + 160Hz
        playTone(200, 0.2, 'sawtooth', 0.14);
        setTimeout(() => playTone(160, 0.2, 'sawtooth', 0.12), 220);
        break;
    }
  }

  // --- Observer Status Strip ---
  function updateObserverStrip(state, extra) {
    if (!observerStripEl || !observerTextEl) return;
    switch (state) {
      case 'generating':
        observerStripEl.style.display = 'flex';
        observerTextEl.textContent = `Copilot generating in ${extra || '...'}...`;
        observerStripEl.className = 'observer-strip generating';
        break;
      case 'complete':
        observerStripEl.style.display = 'flex';
        observerTextEl.textContent = `Copilot done — ${extra || 0} lines added`;
        observerStripEl.className = 'observer-strip complete';
        setTimeout(() => {
          if (observerStripEl) observerStripEl.style.display = 'none';
        }, 4000);
        break;
      case 'file_created':
        observerStripEl.style.display = 'flex';
        observerTextEl.textContent = `Copilot created file: ${extra || ''}`;
        observerStripEl.className = 'observer-strip file';
        setTimeout(() => {
          if (observerStripEl) observerStripEl.style.display = 'none';
        }, 4000);
        break;
      case 'idle':
      default:
        observerStripEl.style.display = 'none';
        break;
    }
  }

  // Browser Web Speech API — ONLY used as last-resort fallback when cloud TTS fails.
  function speakText(text) {
    if (!text || typeof text !== 'string') return;
    try {
      if ('speechSynthesis' in window) {
        window.speechSynthesis.cancel();
        const cleanText = text.replace(/[*_#`~]/g, '').trim();
        const utterance = new SpeechSynthesisUtterance(cleanText);
        utterance.rate = 1.05;
        utterance.pitch = 1.15;
        if (cachedFemaleVoice) utterance.voice = cachedFemaleVoice;
        window.speechSynthesis.speak(utterance);
        console.log('[Webview Speech] Web Speech API fallback (Female):', cleanText.substring(0, 60));
      }
    } catch (err) {
      console.warn('[Webview Speech] SpeechSynthesis error:', err);
    }
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // AudioQueueManager — Sequential, gap-free audio playback
  // Queues earcon sounds and cloud TTS narration so they play one after another
  // without overlap or stutter. Higher priority items can interrupt lower ones.
  // ═══════════════════════════════════════════════════════════════════════════
  const AudioQueue = {
    _queue: [],          // Array of { base64, fallbackText, priority }
    _player: null,       // Shared HTMLAudioElement
    _playing: false,

    /** Add audio to the queue and start playback if idle. */
    enqueue(base64Data, fallbackText = '', priority = 0) {
      // If a higher-priority item arrives (e.g. runtime error > syntax error),
      // stop current audio and jump to new content.
      if (priority > 1 && this._playing) {
        this.stop();
      }
      this._queue.push({ base64Data, fallbackText, priority });
      if (!this._playing) this._playNext();
    },

    /** Stop current playback and flush the queue. */
    stop() {
      if (this._player) {
        try { this._player.pause(); this._player.currentTime = 0; } catch(e) {}
      }
      if ('speechSynthesis' in window) window.speechSynthesis.cancel();
      this._queue = [];
      this._playing = false;
    },

    /** Internal: play the next item in the queue. */
    _playNext() {
      if (this._queue.length === 0) {
        this._playing = false;
        return;
      }
      this._playing = true;
      const { base64Data, fallbackText } = this._queue.shift();

      if (base64Data && base64Data.length > 50) {
        try {
          const mimeType = base64Data.startsWith('UklGR') ? 'audio/wav' : 'audio/mp3';
          if (!this._player) this._player = new Audio();
          this._player.src = `data:${mimeType};base64,${base64Data}`;
          this._player.onended = () => this._playNext();
          this._player.onerror = () => {
            console.warn('[AudioQueue] Audio element error, trying Web Speech fallback');
            if (fallbackText) speakText(fallbackText);
            this._playNext();
          };
          this._player.play()
            .then(() => console.log('[AudioQueue] Playing cloud TTS audio'))
            .catch(err => {
              console.warn('[AudioQueue] play() rejected:', err);
              if (fallbackText) speakText(fallbackText);
              this._playNext();
            });
          return;
        } catch (err) {
          console.warn('[AudioQueue] Exception creating audio element:', err);
        }
      }

      // Fallback: Web Speech API
      if (fallbackText) {
        speakText(fallbackText);
        // Web Speech doesn't give us an onended event reliably; wait estimated duration
        const estimatedMs = Math.max(1500, fallbackText.length * 60);
        setTimeout(() => this._playNext(), estimatedMs);
      } else {
        this._playNext();
      }
    },
  };

  /** Legacy helper — enqueue audio narration from cloud TTS or fall back to Web Speech. */
  function playAudioNarration(base64Data, fallbackText = '', priority = 0) {
    AudioQueue.enqueue(base64Data, fallbackText, priority);
  }

  // --- Listen for messages from the Extension Host ---
  window.addEventListener('message', async (event) => {
    const msg = event.data;

    if (msg.type === 'play_earcon') {
      playEarcon(msg.earconType);
    } else if (msg.type === 'speak_text') {
      speakText(msg.text);
    } else if (msg.type === 'observer_status') {
      const extra = msg.state === 'complete' ? msg.linesAdded : msg.file;
      updateObserverStrip(msg.state, extra);
    } else if (msg.type === 'start_mic') {
      vscode.postMessage({ type: 'toggle_backend_mic' });
    } else if (msg.type === 'stop_mic') {
      vscode.postMessage({ type: 'toggle_backend_mic' });
    } else if (msg.type === 'backend_message') {
      const payload = msg.payload;
      if (payload.type === 'mic_status') {
        if (payload.state === 'recording') {
          isCapturing = true;
          if (micBtn) {
            micBtn.classList.add('recording');
            micBtn.innerHTML = '🛑';
          }
          if (statusEl) {
            statusEl.textContent = 'Listening…';
            statusEl.classList.add('listening');
          }
          log('Microphone listening (OS Recording)...');
        } else if (payload.state === 'transcribing') {
          if (statusEl) {
            statusEl.textContent = 'Transcribing…';
          }
          log('Transcribing voice audio...');
        } else if (payload.state === 'idle') {
          isCapturing = false;
          if (micBtn) {
            micBtn.classList.remove('recording');
            micBtn.innerHTML = '🎙️';
          }
          if (statusEl) {
            statusEl.textContent = 'microphone off';
            statusEl.classList.remove('listening');
          }
          if (payload.transcript) {
            log('Transcribed: ' + payload.transcript);
          }
        }
      } else if (payload.type === 'action_result') {
        stopProcessingAudio();
        log('Backend: ' + payload.detail);
        // audio_base64 holds the first sentence; the rest follows as 'agent_continuation'
        playAudioNarration(payload.audio_base64, payload.spoken_text || payload.detail);
      } else if (payload.type === 'confirmation_request') {
        stopProcessingAudio();
        if (payload.prompt) {
          addFeedItem('NEUROCODE REASONING', payload.prompt, 'assistant');
        }
        if (confirmPrompt && confirmArea) {
          confirmPrompt.textContent = payload.prompt;
          confirmArea.style.display = 'block';
        }
        playAudioNarration(payload.audio_base64, payload.spoken_text || payload.prompt);
      } else if (payload.type === 'ack') {
        // Instant acknowledgement of a command, then keep ticking until the answer arrives
        playAudioNarration(payload.audio_base64, payload.text);
        if (!pendingRequestTicker) {
          pendingRequestTicker = setInterval(() => playEarcon('tick'), 1800);
        }
      } else if (payload.type === 'audio_narration' && payload.channel === 'agent_continuation') {
        // The rest of a reply whose text is already in the feed: just play it
        playAudioNarration(payload.audio_base64, payload.narration);
      } else if (payload.type === 'audio_narration') {
        stopProcessingAudio();
        const channelLabel = payload.channel === 'manual_observer' ? 'ERROR ANALYSIS' : 'OBSERVER NARRATION';
        if (payload.narration) {
          addFeedItem(channelLabel, payload.narration, 'assistant');
        }
        // Play cloud TTS audio (female Sarvam/ElevenLabs) — DO NOT also call speakText
        playAudioNarration(payload.audio_base64, payload.narration);

      } else if (payload.type === 'workspace_ack') {
        if (payload.detail) {
          addFeedItem('SYSTEM EVENT', payload.detail, 'system');
        }
      } else {
        log('Backend: ' + JSON.stringify(payload));
      }
    }
  });

  // --- AudioWorklet PCM Capture ---
  async function startMicCapture() {
    if (isCapturing) {
      log('Already capturing audio');
      return;
    }

    try {
      mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          sampleRate: 16000,
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
        }
      });

      audioContext = new AudioContext({ sampleRate: 16000 });
      
      // processorUri is injected by extension host via data attribute or global
      const processorUrl = window.processorUri || 'pcm-processor.js';
      await audioContext.audioWorklet.addModule(processorUrl);

      const source = audioContext.createMediaStreamSource(mediaStream);
      workletNode = new AudioWorkletNode(audioContext, 'pcm-processor');

      workletNode.port.onmessage = (e) => {
        const { base64 } = e.data;
        vscode.postMessage({
          type: 'audio_frame',
          data: base64
        });
      };

      source.connect(workletNode);

      isCapturing = true;
      if (micBtn) {
        micBtn.classList.add('recording');
        micBtn.innerHTML = '🛑';
      }
      if (statusEl) {
        statusEl.textContent = 'Listening…';
        statusEl.classList.add('listening');
      }
      log('Mic capture started (16kHz PCM)');
    } catch (err) {
      log('Mic capture error: ' + err.message);
      isCapturing = false;
      if (micBtn) {
        micBtn.classList.remove('recording');
        micBtn.innerHTML = '🎙️';
        micBtn.title = 'Microphone error: ' + err.message;
      }
      if (statusEl) {
        statusEl.textContent = 'Mic Error';
        statusEl.classList.remove('listening');
      }
    }
  }

  function stopMicCapture() {
    if (workletNode) {
      workletNode.disconnect();
      workletNode = null;
    }
    if (mediaStream) {
      mediaStream.getTracks().forEach(t => t.stop());
      mediaStream = null;
    }
    if (audioContext) {
      audioContext.close();
      audioContext = null;
    }
    isCapturing = false;
    if (micBtn) {
      micBtn.classList.remove('recording');
      micBtn.innerHTML = '🎙️';
    }
    if (statusEl) {
      statusEl.textContent = 'microphone off';
      statusEl.classList.remove('listening');
    }
    log('Mic capture stopped');
  }
})();
