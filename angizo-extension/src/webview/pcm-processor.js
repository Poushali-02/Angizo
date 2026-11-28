/**
 * angizo-extension/src/webview/pcm-processor.js
 *
 * AudioWorkletProcessor that captures raw PCM audio from the microphone,
 * converts Float32 samples to Int16, and posts base64-encoded chunks
 * to the main webview thread.
 *
 * WHY AudioWorklet and not MediaRecorder (ROADMAP.md):
 *   "MediaRecorder's default webm/opus output is incompatible with
 *    Sarvam's WAV/PCM-only streaming endpoint — must use
 *    AudioWorkletNode for raw PCM capture, not MediaRecorder."
 *
 * Output: ~100ms chunks of 16kHz mono Int16 PCM, base64-encoded.
 * At 16kHz, 100ms = 1600 samples = 3200 bytes (Int16).
 */

class PCMProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    // Buffer to accumulate samples before sending a chunk
    this._buffer = new Float32Array(0);
    // Chunk size: 1600 samples = 100ms at 16kHz
    this._chunkSize = 1600;
  }

  /**
   * Called by the audio rendering thread for each 128-sample block.
   * Accumulates samples and posts Int16 PCM chunks when enough have
   * been collected.
   */
  process(inputs, outputs, parameters) {
    const input = inputs[0];
    if (!input || !input[0]) {
      return true; // keep processor alive
    }

    const channelData = input[0]; // mono channel

    // Append new samples to the buffer
    const newBuffer = new Float32Array(
      this._buffer.length + channelData.length
    );
    newBuffer.set(this._buffer);
    newBuffer.set(channelData, this._buffer.length);
    this._buffer = newBuffer;

    // Send complete chunks
    while (this._buffer.length >= this._chunkSize) {
      const chunk = this._buffer.slice(0, this._chunkSize);
      this._buffer = this._buffer.slice(this._chunkSize);

      // Convert Float32 [-1, 1] to Int16 [-32768, 32767]
      const int16 = new Int16Array(chunk.length);
      for (let i = 0; i < chunk.length; i++) {
        const s = Math.max(-1, Math.min(1, chunk[i]));
        int16[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
      }

      // Convert to base64
      const bytes = new Uint8Array(int16.buffer);
      let binary = "";
      for (let i = 0; i < bytes.length; i++) {
        binary += String.fromCharCode(bytes[i]);
      }
      const base64 = btoa(binary);

      // Post to main thread
      this.port.postMessage({ base64 });
    }

    return true; // keep processor alive
  }
}

registerProcessor("pcm-processor", PCMProcessor);
