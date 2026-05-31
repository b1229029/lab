/**
 * record.js
 *
 * 會議錄製頁面的主控制器。這個檔案負責串接：
 * - UIManager：畫面狀態與渲染。
 * - AudioManager：瀏覽器錄音與音訊切片。
 * - WebSocket listener.py：即時轉錄、圖片分析、摘要與行事曆事件。
 * - FastAPI REST API：儲存會議結果與完整音訊。
 */
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
    // 建立與 listener.py 的 WebSocket 連線，後續所有即時轉錄與摘要都走這條通道。
    let host = window.location.hostname; if (!host || host === "") host = "192.168.150.5";
    ws = new WebSocket(`ws://${host}:8765`);

    window.ws = ws;

    ws.onopen = () => { 
        UIManager.els.statusText.textContent = '狀態：已連線'; 
        UIManager.els.actionButton.disabled = false; 
        UIManager.toggleMode(); 
    };

    ws.onmessage = (event) => {
        // 後端所有控制訊息都是 JSON；音訊二進位只由前端送出，不會在這裡處理。
        try {
            const data = JSON.parse(event.data);

            if (data.type === 'agenda_ready') { 
                UIManager.els.statusText.textContent = '狀態：會議中 / 分析中...'; 
                if (UIManager.currentMode === 'mic') startActualRecording(); 
                else startFileUpload(); 
                UIManager.renderAgendaList(); 
            }
            if (data.type === 'transcript') UIManager.updateTranscript(data);
            if (data.type === 'image_analysis_result') {
                UIManager.updateImageAnalysis(data);
                if (ws && ws.readyState === WebSocket.OPEN) {
                    ws.send(JSON.stringify({
                        type: "append_image_result",
                        filename: data.filename || "圖片",
                        description: data.description || ""
                    }));
                }
            }
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
    // actionButton 在不同階段有不同語意：開始會議、停止錄音、查看摘要。
    if(UIManager.els.actionButton.classList.contains('btn-success')) { UIManager.switchPage('summary'); return; }
    
    if (!UIManager.isAgendaLocked) {
        if (UIManager.myTopics.length === 0) { alert("請至少輸入一個議程！"); return; }
        if (UIManager.currentMode === 'file' && !UIManager.els.audioFileInput.files[0]) { alert("請選擇檔案！"); return; }
        

        // 新增：抓取與會人員名單
        const participantsInput = document.getElementById('participants-input');
        const participantsList = participantsInput ? participantsInput.value.trim() : "";

        UIManager.resetMeetingUI();
        
        // 修改：將 participants 一併透過 WebSocket 送給後端
        ws.send(JSON.stringify({ 
            type: "setup_agenda", 
            topics: UIManager.myTopics,
            participants: participantsList // 將人名傳送給後端
        }));

    } else { 
        if (AudioManager.isRecording) stopRecording(); 
    }
};

// 圖片分析上傳按鈕綁定
UIManager.els.btnUploadImage.onclick = () => {
    // 使用 FileReader 先讓前端立即預覽圖片，再把 base64 送到 WebSocket 分析。
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
    // 將下次會議時間、email 與 AI 建議議程送到後端建立 Google Calendar 事件。
    const datetime = UIManager.els.nextMeetingTime.value; 
    if (!datetime) { alert("請選擇時間！"); return; }
    const emails = UIManager.els.nextEmails.value.split(',').map(e => e.trim()).filter(e => e);
    UIManager.els.btnScheduleNext.disabled = true; UIManager.els.btnScheduleNext.textContent = "發送中...";
    ws.send(JSON.stringify({ type: "schedule_next", topic: "專題跟進會議 (AI 自動預約)", description: "【待解決議題】\n" + UIManager.els.nextAgendaPreview.value, datetime: datetime, emails: emails }));
};

// 4. 錄音與上傳邏輯
async function startActualRecording() {
    // 啟動麥克風模式：錄音切片送 WebSocket，完整音訊留待會議結束上傳。
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
    // 停止麥克風模式，並在 AudioManager 完成最後片段後要求總摘要。
    UIManager.els.actionButton.innerHTML = '分析中...'; UIManager.els.actionButton.disabled = true; UIManager.els.statusText.textContent = '狀態：正在呼叫 AI 進行分析...';
    if (interimSummaryTimer) { clearInterval(interimSummaryTimer); interimSummaryTimer = null; }
    AudioManager.stop();
}

function startFileUpload() {
    // 啟動檔案模式：將大檔切成 1MB ArrayBuffer 分批送到 WebSocket。
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

function extractImageAnalysisFromTranscript(transcriptText) {
    // 從舊版逐字稿標籤回收圖片分析文字，保留向後相容。
    return transcriptText
        .split('\n')
        .map(line => line.trim())
        .filter(line => line.includes('圖片分析'))
        .filter((line, index, arr) => arr.indexOf(line) === index)
        .join('\n');
}

function getImageAnalysisTextForSave() {
    // 取得本次會議要寫進資料庫的圖片分析文字。
    if (typeof UIManager.getImageAnalysisText === 'function') {
        return UIManager.getImageAnalysisText();
    }

    const fromLog = (UIManager.imageAnalysisLog || []).join('\n\n').trim();
    const finalTranscript = UIManager.fullTranscriptLog.join('\n');
    const fromTranscript = extractImageAnalysisFromTranscript(finalTranscript).trim();
    return fromLog || fromTranscript;
}

function requestSummary() {
    // 要求後端把目前累積的逐字稿、圖片分析與議程狀態整理成總摘要。
    setTimeout(() => {
        ws.send(JSON.stringify({
            type: "request_summary",
            template: UIManager.els.templateSelect.value,
            image_analysis_text: getImageAnalysisTextForSave()
        }));
    }, 500);
}

// 5. 資料庫儲存
async function saveMeetingDataToDB(summary, mindmap) {
    // 將摘要、心智圖、逐字稿、圖片分析與完整音訊保存到後端資料庫。
    if (!currentMeetingId) return;

    UIManager.els.actionButton.textContent = "資料庫存檔中，請勿關閉網頁...";
    UIManager.els.actionButton.disabled = true;
    
    const backBtn = document.getElementById('welcome-msg');
    if (backBtn) backBtn.style.pointerEvents = 'none';
    if (backBtn) backBtn.style.opacity = '0.5';

    try {
        const finalTranscript = UIManager.fullTranscriptLog.join('\n');
        const imageAnalysisText = getImageAnalysisTextForSave();
        
        await fetch(`${API_BASE_URL}/meetings/${currentMeetingId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                summary_text: summary, 
                mindmap_data: mindmap, 
                transcript_text: finalTranscript,
                image_analysis_text: imageAnalysisText
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
// ==========================================
// 🚀 會議問答機器人前端邏輯
// ==========================================
const sendChatBtn = document.getElementById('send-chat-btn');
const chatInput = document.getElementById('chat-input');

if (sendChatBtn && chatInput) {
    const handleSendChat = async () => {
        // RAG 問答只在有 meeting_id 的會議中啟用，問題會送到 /meetings/{id}/chat。
        const historyEl = document.getElementById('chat-history');
        const question = chatInput.value.trim();

        if (!question) return;
        if (!currentMeetingId) {
            alert("⚠️ 找不到會議 ID！\n請問答功能必須在「已儲存的會議」中才能使用。");
            return;
        }

        historyEl.innerHTML += `<div style="text-align: right; margin-bottom: 8px;"><span style="background: #007bff; color: white; padding: 5px 10px; border-radius: 15px; display: inline-block;">${question}</span></div>`;
        chatInput.value = '';

        const loadingId = 'loading-' + Date.now();
        historyEl.innerHTML += `<div id="${loadingId}" style="color: #888; font-size: 0.9em; margin-bottom: 8px;">🤖 助手思考中...</div>`;
        historyEl.scrollTop = historyEl.scrollHeight;

        try {
            const response = await fetch(`${API_BASE_URL}/meetings/${currentMeetingId}/chat`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ question: question })
            });
            const data = await response.json();

            const loadingEl = document.getElementById(loadingId);
            if(loadingEl) loadingEl.remove();

            historyEl.innerHTML += `<div style="margin-bottom: 8px;"><span style="background: #e9ecef; color: #333; padding: 8px 12px; border-radius: 15px; display: inline-block; max-width: 80%; line-height: 1.5; text-align: left;">🤖 ${data.answer.replace(/\n/g, '<br>')}</span></div>`;
            historyEl.scrollTop = historyEl.scrollHeight;
        } catch (err) {
            const loadingEl = document.getElementById(loadingId);
            if(loadingEl) loadingEl.innerText = "❌ 發生錯誤，無法連接後端。";
        }
    };

    sendChatBtn.onclick = handleSendChat;
    chatInput.addEventListener('keypress', function (e) {
        if (e.key === 'Enter') handleSendChat();
    });
}
