// audio_manager.js
const AudioManager = {
    mediaRecorder: null, fullMediaRecorder: null,
    recordedChunks: [], allRecordedChunks: [],
    isRecording: false, intervalId: null,
    onChunkReady: null, onStopCallback: null,

    async start(onChunkReady, onStopCallback) {
        this.reset();
        this.onChunkReady = onChunkReady;
        this.onStopCallback = onStopCallback;

        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });

            this.mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm;codecs=opus' });
            this.mediaRecorder.ondataavailable = e => { if (e.data.size > 0) this.recordedChunks.push(e.data); };
            this.mediaRecorder.onstop = () => {
                const blob = new Blob(this.recordedChunks, { type: 'audio/webm;codecs=opus' });
                if (this.onChunkReady && blob.size > 0) this.onChunkReady(blob);
                this.recordedChunks = [];
                if (this.isRecording) { this.mediaRecorder.start(); } 
                else { if (this.onStopCallback) this.onStopCallback(); }
            };

            this.fullMediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm;codecs=opus' });
            this.fullMediaRecorder.ondataavailable = e => { if (e.data.size > 0) this.allRecordedChunks.push(e.data); };

            this.isRecording = true;
            this.mediaRecorder.start();
            this.fullMediaRecorder.start(); 

            this.intervalId = setInterval(() => { if (this.isRecording) this.mediaRecorder.stop(); }, 30000); 
        } catch (err) {
            console.error("麥克風權限錯誤", err);
            throw err;
        }
    },

    stop() {
        this.isRecording = false;
        if (this.intervalId) { clearInterval(this.intervalId); this.intervalId = null; }
        if (this.mediaRecorder && this.mediaRecorder.state === "recording") this.mediaRecorder.stop();
        if (this.fullMediaRecorder && this.fullMediaRecorder.state === "recording") this.fullMediaRecorder.stop();
    },

    getFullAudioBlob() { return new Blob(this.allRecordedChunks, { type: 'audio/webm' }); },
    reset() { this.recordedChunks = []; this.allRecordedChunks = []; this.isRecording = false; }
};