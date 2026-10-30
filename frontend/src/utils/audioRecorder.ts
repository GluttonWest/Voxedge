/**
 * audioRecorder.ts — Browser PCM Audio Recorder that produces clean 16-bit Mono WAV blobs.
 *
 * Captures raw microphone audio via Web Audio API AudioContext.
 * Ensures microphone output is muted to speakers (gain = 0) to prevent acoustic feedback
 * and echo-cancellation pumping. Encodes clean RIFF PCM 16-bit WAV with exact sample rate metadata.
 */

export class AudioRecorder {
  private mediaStream: MediaStream | null = null;
  private audioContext: AudioContext | null = null;
  private sourceNode: MediaStreamAudioSourceNode | null = null;
  private processorNode: ScriptProcessorNode | null = null;
  private muteGainNode: GainNode | null = null;
  private recordedSamples: Float32Array[] = [];
  private totalLength = 0;
  private recording = false;

  public isRecording(): boolean {
    return this.recording;
  }

  public async start(): Promise<void> {
    if (this.recording) return;

    this.recordedSamples = [];
    this.totalLength = 0;

    // Request microphone access with echo cancellation & noise suppression
    this.mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });

    const AudioContextClass =
      window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;

    // Try requesting 16,000 Hz native context first for optimal hardware resampling
    try {
      this.audioContext = new AudioContextClass({ sampleRate: 16000 });
    } catch {
      this.audioContext = new AudioContextClass();
    }

    this.sourceNode = this.audioContext.createMediaStreamSource(this.mediaStream);

    // 4096 buffer size, 1 input channel, 1 output channel
    this.processorNode = this.audioContext.createScriptProcessor(4096, 1, 1);

    this.processorNode.onaudioprocess = (e) => {
      if (!this.recording) return;
      const inputBuffer = e.inputBuffer.getChannelData(0);
      const copy = new Float32Array(inputBuffer.length);
      copy.set(inputBuffer);
      this.recordedSamples.push(copy);
      this.totalLength += copy.length;
    };

    // Mute gain node: keeps Web Audio graph active while preventing audio from playing through speakers
    this.muteGainNode = this.audioContext.createGain();
    this.muteGainNode.gain.value = 0;

    this.sourceNode.connect(this.processorNode);
    this.processorNode.connect(this.muteGainNode);
    this.muteGainNode.connect(this.audioContext.destination);

    this.recording = true;
  }

  public async stop(): Promise<Blob> {
    if (!this.recording) {
      throw new Error('Recorder is not active.');
    }

    this.recording = false;

    // Disconnect audio graph
    if (this.processorNode && this.sourceNode && this.muteGainNode) {
      this.sourceNode.disconnect();
      this.processorNode.disconnect();
      this.muteGainNode.disconnect();
    }

    // Stop all microphone tracks
    if (this.mediaStream) {
      this.mediaStream.getTracks().forEach((track) => track.stop());
      this.mediaStream = null;
    }

    const actualSampleRate = this.audioContext?.sampleRate || 16000;
    if (this.audioContext && this.audioContext.state !== 'closed') {
      await this.audioContext.close();
      this.audioContext = null;
    }

    // Merge recorded chunks into single continuous Float32Array
    const merged = new Float32Array(this.totalLength);
    let offset = 0;
    for (const chunk of this.recordedSamples) {
      merged.set(chunk, offset);
      offset += chunk.length;
    }

    // Encode directly as 16-bit PCM WAV preserving actual sample rate in header
    return this.encodeWAV(merged, actualSampleRate);
  }

  private encodeWAV(samples: Float32Array, sampleRate: number): Blob {
    const buffer = new ArrayBuffer(44 + samples.length * 2);
    const view = new DataView(buffer);

    // Write RIFF header
    this.writeString(view, 0, 'RIFF');
    view.setUint32(4, 36 + samples.length * 2, true); // file length - 8
    this.writeString(view, 8, 'WAVE');

    // fmt subchunk
    this.writeString(view, 12, 'fmt ');
    view.setUint32(16, 16, true); // Subchunk1Size (16 for PCM)
    view.setUint16(20, 1, true); // AudioFormat (1 for PCM)
    view.setUint16(22, 1, true); // NumChannels (1 = Mono)
    view.setUint32(24, sampleRate, true); // SampleRate
    view.setUint32(28, sampleRate * 2, true); // ByteRate (SampleRate * 1 * 16/8)
    view.setUint16(32, 2, true); // BlockAlign (1 * 16/8)
    view.setUint16(34, 16, true); // BitsPerSample (16 bits)

    // data subchunk
    this.writeString(view, 36, 'data');
    view.setUint32(40, samples.length * 2, true);

    // Write PCM 16-bit samples
    let index = 44;
    for (let i = 0; i < samples.length; i++) {
      const s = Math.max(-1, Math.min(1, samples[i]));
      view.setInt16(index, s < 0 ? s * 0x8000 : s * 0x7fff, true);
      index += 2;
    }

    return new Blob([view], { type: 'audio/wav' });
  }

  private writeString(view: DataView, offset: number, str: string): void {
    for (let i = 0; i < str.length; i++) {
      view.setUint8(offset + i, str.charCodeAt(i));
    }
  }
}
