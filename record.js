// record.js
const API_BASE_URL = "http://127.0.0.1:8000"; 
const urlParams = new URLSearchParams(window.location.search);
const currentMeetingId = urlParams.get('meeting_id');
const currentMeetingTopic = urlParams.get('topic');

let ws;
let interimSummaryTimer = null;

// 1. 初始化 UI 管理器
UIManager.init(currentMeetingTopic);

// 2. 建立 WebSocket 連線與訊息處理
function setupWebSocket() {
    let host = window.location.hostname; if (!host || host === "") host = "192.168.150.5";
    ws = new WebSocket(`ws://${host}:8765`); 

    ws.onopen = () => { 
        UIManager.els.statusText.textContent = '狀態：已連線'; 
        UIManager.els.actionButton.disabled = false; 
        UIManager.toggleMode(); 
    };

    ws.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);

            if (data.type === 'agenda_ready') { 
                UIManager.els.statusText.textContent = '狀態：會議中 / 分析中...'; 
                if (UIManager.currentMode === 'mic') startActualRecording(); 
                else startFileUpload(); 
                UIManager.renderAgendaList(); 
            }
            if (data.type === 'transcript') UIManager.updateTranscript(data);
            if (data.type === 'image_analysis_result') UIManager.updateImageAnalysis(data);
            if (data.type === 'interim_summary_result') UIManager.updateInterimSummary(data.data);
            
            if (data.type === 'summary_result') {
                const res = JSON.parse(data.data);
                let audioUrl = null;
                if (UIManager.currentMode === 'mic') {
                    const finalAudioBlob = AudioManager.getFullAudioBlob();
                    if (finalAudioBlob.size > 0) audioUrl = URL.createObjectURL(finalAudioBlob);
                } else if (UIManager.currentMode === 'file' && UIManager.els.audioFileInput.files.length > 0) {
                    audioUrl = URL.createObjectURL(UIManager.els.audioFileInput.files[0]);
                }
                
                UIManager.renderSummaryAndMindmap(res, audioUrl);
                saveMeetingDataToDB(res.summary, res.mindmap);
            }
            
            if (data.type === 'schedule_success') { 
                UIManager.els.calStatus.innerHTML = `✅ <a href="${data.link}" target="_blank">活動已建立</a>`; 
                UIManager.els.btnScheduleNext.textContent = "預約成功"; 
                UIManager.els.btnScheduleNext.disabled = false; 
            }
            if (data.type === 'upload_progress') UIManager.els.statusText.textContent = `狀態：${data.message}`;
            if (data.type === 'error') { alert("❌ 錯誤：" + data.message); UIManager.els.btnScheduleNext.disabled = false; }
        } catch (e) { console.error(e); }
    };

    ws.onclose = () => { UIManager.els.statusText.textContent = '狀態：連線中斷'; UIManager.els.actionButton.disabled = true; };
}

// 3. 綁定按鈕事件
UIManager.els.actionButton.onclick = async () => {
    if(UIManager.els.actionButton.classList.contains('btn-success')) { UIManager.switchPage('summary'); return; }
    
    if (!UIManager.isAgendaLocked) {
        if (UIManager.myTopics.length === 0) { alert("請至少輸入一個議程！"); return; }
        if (UIManager.currentMode === 'file' && !UIManager.els.audioFileInput.files[0]) { alert("請選擇檔案！"); return; }
        UIManager.resetMeetingUI();
        ws.send(JSON.stringify({ type: "setup_agenda", topics: UIManager.myTopics }));
    } else { 
        if (AudioManager.isRecording) stopRecording(); 
    }
};

// 圖片分析上傳按鈕綁定
UIManager.els.btnUploadImage.onclick = () => {
    const file = UIManager.els.imageInput.files[0];
    if (!file) return;
    UIManager.els.btnUploadImage.disabled = true; UIManager.els.btnUploadImage.textContent = "分析中..."; UIManager.els.imgStatus.textContent = "正在傳送...";
    
    const reader = new FileReader();
    reader.onload = function(e) {
        const base64Data = e.target.result;
        const imgContainer = document.createElement('div');
        imgContainer.style.margin = "10px 0"; imgContainer.style.textAlign = "center";
        imgContainer.innerHTML = `<img src="${base64Data}" style="max-width: 60%; border-radius: 8px; border: 2px solid #17a2b8;"><p style="font-size:0.8em; color:#666; margin:5px 0;">[已上傳圖片] ${file.name}</p>`;
        UIManager.els.liveTranscript.appendChild(imgContainer); UIManager.els.liveTranscript.scrollTop = UIManager.els.liveTranscript.scrollHeight;
        if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "analyze_image", image_data: base64Data, filename: file.name }));
    };
    reader.readAsDataURL(file);
};

UIManager.els.btnScheduleNext.onclick = () => {
    const datetime = UIManager.els.nextMeetingTime.value; 
    if (!datetime) { alert("請選擇時間！"); return; }
    const emails = UIManager.els.nextEmails.value.split(',').map(e => e.trim()).filter(e => e);
    UIManager.els.btnScheduleNext.disabled = true; UIManager.els.btnScheduleNext.textContent = "發送中...";
    ws.send(JSON.stringify({ type: "schedule_next", topic: "專題跟進會議 (AI 自動預約)", description: "【待解決議題】\n" + UIManager.els.nextAgendaPreview.value, datetime: datetime, emails: emails }));
};

// 4. 錄音與上傳邏輯
async function startActualRecording() {
    try {
        await AudioManager.start(
            (chunkBlob) => { if (ws && ws.readyState === WebSocket.OPEN && chunkBlob.size > 0) ws.send(chunkBlob); },
            () => requestSummary()
        );
        UIManager.els.actionButton.textContent = '停止會議並生成總結'; UIManager.els.actionButton.className = 'btn-danger'; UIManager.els.actionButton.disabled = false;
        
        interimSummaryTimer = setInterval(() => { 
            if (AudioManager.isRecording && ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "request_interim_summary" })); 
        }, 60000); 
    } catch (err) { alert("麥克風權限錯誤，無法啟動會議。"); UIManager.els.actionButton.disabled = false; }
}

function stopRecording() {
    UIManager.els.actionButton.innerHTML = '分析中...'; UIManager.els.actionButton.disabled = true; UIManager.els.statusText.textContent = '狀態：正在呼叫 AI 進行分析...';
    if (interimSummaryTimer) { clearInterval(interimSummaryTimer); interimSummaryTimer = null; }
    AudioManager.stop();
}

function startFileUpload() {
    const file = UIManager.els.audioFileInput.files[0]; if (!file) return;
    UIManager.els.statusText.textContent = '狀態：上傳檔案中...'; UIManager.els.actionButton.textContent = '上傳分析中...'; UIManager.els.actionButton.disabled = true;
    ws.send(JSON.stringify({ type: "start_file_upload", filename: file.name }));
    
    const chunkSize = 1024 * 1024; let offset = 0;
    const reader = new FileReader();
    reader.onload = (e) => {
        if (ws.readyState === WebSocket.OPEN) {
            ws.send(e.target.result); offset += chunkSize;
            if (offset < file.size) reader.readAsArrayBuffer(file.slice(offset, offset + chunkSize));
            else ws.send(JSON.stringify({ type: "end_file_upload" }));
        }
    };
    reader.readAsArrayBuffer(file.slice(0, chunkSize));
}

function requestSummary() { setTimeout(() => { ws.send(JSON.stringify({ type: "request_summary", template: UIManager.els.templateSelect.value })); }, 500); }

// 5. 資料庫儲存
async function saveMeetingDataToDB(summary, mindmap) {
    if (!currentMeetingId) return;

    UIManager.els.actionButton.textContent = "資料庫存檔中，請勿關閉網頁...";
    UIManager.els.actionButton.disabled = true;
    
    const backBtn = document.getElementById('welcome-msg');
    if (backBtn) backBtn.style.pointerEvents = 'none';
    if (backBtn) backBtn.style.opacity = '0.5';

    try {
        const finalTranscript = UIManager.fullTranscriptLog.join('\n');
        
        await fetch(`${API_BASE_URL}/meetings/${currentMeetingId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                summary_text: summary, 
                mindmap_data: mindmap, 
                transcript_text: finalTranscript 
            })
        });

        const formData = new FormData();
        if (UIManager.currentMode === 'mic' && AudioManager.allRecordedChunks.length > 0) {
            const finalAudioBlob = AudioManager.getFullAudioBlob();
            formData.append('file', finalAudioBlob, 'recording.webm');
        } else if (UIManager.currentMode === 'file' && UIManager.els.audioFileInput.files.length > 0) {
            formData.append('file', UIManager.els.audioFileInput.files[0]);
        }

        if (formData.has('file')) {
            await fetch(`${API_BASE_URL}/meetings/${currentMeetingId}/upload_audio`, { 
                method: 'POST', 
                body: formData 
            });
        }

        alert("✅ 會議總結與音檔已完整儲存至歷史紀錄！");
        UIManager.els.actionButton.textContent = '會議已結束 (點擊切換查看結果)';
        UIManager.els.actionButton.disabled = false;

    } catch (err) {
        console.error(err);
        alert(`⚠️ 存檔失敗：${err.message}`);
        UIManager.els.actionButton.textContent = '存檔失敗';
    } finally {
        if (backBtn) backBtn.style.pointerEvents = 'auto';
        if (backBtn) backBtn.style.opacity = '1';
    }
}

// 啟動系統
setupWebSocket();