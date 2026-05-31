/**
 * audio_manager.js
 *
 * 瀏覽器端錄音管理器。這個物件封裝 MediaRecorder 的生命週期，並同時維護：
 * 1. 每 30 秒送到 WebSocket 的即時辨識片段。
 * 2. 會議結束後要上傳後端保存的完整音訊。
 *
 * record.js 只需要呼叫 start/stop/getFullAudioBlob，不必直接處理 MediaRecorder
 * 事件、Blob 組裝或定時切片。
 */
const AudioManager = {
    // mediaRecorder 負責短片段；fullMediaRecorder 負責完整錄音。
    mediaRecorder: null, fullMediaRecorder: null,
    // recordedChunks 每次切片後清空；allRecordedChunks 會保留到整場會議結束。
    recordedChunks: [], allRecordedChunks: [],
    isRecording: false, intervalId: null,
    onChunkReady: null, onStopCallback: null,

    async start(onChunkReady, onStopCallback) {
        // 每次開始錄音都重置舊狀態，避免上一場會議的音訊混入新會議。
        this.reset();
        this.onChunkReady = onChunkReady;
        this.onStopCallback = onStopCallback;

        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });

            // 短片段錄音器：每次 stop 都把當前片段送給 WebSocket，再立即重新 start。
            this.mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm;codecs=opus' });
            this.mediaRecorder.ondataavailable = e => { if (e.data.size > 0) this.recordedChunks.push(e.data); };
            this.mediaRecorder.onstop = () => {
                const blob = new Blob(this.recordedChunks, { type: 'audio/webm;codecs=opus' });
                if (this.onChunkReady && blob.size > 0) this.onChunkReady(blob);
                this.recordedChunks = [];
                if (this.isRecording) { this.mediaRecorder.start(); } 
                else { if (this.onStopCallback) this.onStopCallback(); }
            };

            // 完整錄音器：不中斷錄製，供會議結束後上傳與心智圖時間軸播放。
            this.fullMediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm;codecs=opus' });
            this.fullMediaRecorder.ondataavailable = e => { if (e.data.size > 0) this.allRecordedChunks.push(e.data); };

            this.isRecording = true;
            this.mediaRecorder.start();
            this.fullMediaRecorder.start(); 

            // 固定 30 秒切一段，讓後端可以邊錄邊轉錄，不用等整場會議結束。
            this.intervalId = setInterval(() => { if (this.isRecording) this.mediaRecorder.stop(); }, 30000); 
        } catch (err) {
            console.error("麥克風權限錯誤", err);
            throw err;
        }
    },

    stop() {
        // 停止錄音後，下一次 mediaRecorder.onstop 會走到 onStopCallback 觸發摘要流程。
        this.isRecording = false;
        if (this.intervalId) { clearInterval(this.intervalId); this.intervalId = null; }
        if (this.mediaRecorder && this.mediaRecorder.state === "recording") this.mediaRecorder.stop();
        if (this.fullMediaRecorder && this.fullMediaRecorder.state === "recording") this.fullMediaRecorder.stop();
    },

    // 回傳整場錄音 Blob，讓 record.js 上傳後端或建立本機播放 URL。
    getFullAudioBlob() { return new Blob(this.allRecordedChunks, { type: 'audio/webm' }); },
    // 清空狀態但不主動停止硬體 stream；停止流程由 stop() 控制。
    reset() { this.recordedChunks = []; this.allRecordedChunks = []; this.isRecording = false; }
};
