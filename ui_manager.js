// ui_manager.js
const UIManager = {
    myTopics: [], topicToTranscriptId: {},
    fullTranscriptLog: [], chunkCounter: 0,
    mindmapTimestamps: [], targetEndTime: null,
    pendingMindmapRoot: null, currentMode: 'mic',
    isAgendaLocked: false, meetingStartTime: null,
    currentSummaryData: "", els: {},

    init(initialTopic) {
        if (initialTopic) this.myTopics.push(initialTopic);

        const ids = ['actionButton', 'statusText', 'live-transcript', 'full-transcript', 'agenda-list', 'warning-msg', 
                     'new-topic-input', 'add-topic-btn', 'input-area', 'file-upload-area', 'audio-file-input', 
                     'ai-summary-box', 'template-select', 'markmap-svg', 'downloadBtn', 'copyBtn', 
                     'next-agenda-preview', 'next-meeting-time', 'next-emails', 'btn-schedule-next', 
                     'cal-status', 'btn-upload-image', 'image-input', 'img-status', 'interim-summary-box', 'mindmap-audio-player'];
                     
        ids.forEach(id => {
            let key = id.replace(/-([a-z])/g, g => g[1].toUpperCase()); 
            this.els[key] = document.getElementById(id);
        });

        this.bindEvents();
        this.renderAgendaList();
        this.toggleMode(); 
    },

    bindEvents() {
        if (this.els.imageInput) {
            this.els.imageInput.onchange = () => {
                if (this.els.imageInput.files.length > 0) {
                    this.els.btnUploadImage.style.display = 'inline-block';
                    this.els.imgStatus.textContent = `已選取: ${this.els.imageInput.files[0].name}`;
                }
            };
        }

        this.els.addTopicBtn.onclick = () => {
            const val = this.els.newTopicInput.value.trim();
            if (val) { this.myTopics.push(val); this.els.newTopicInput.value = ''; this.renderAgendaList(); }
        };
        this.els.newTopicInput.addEventListener("keypress", (e) => { if (e.key === "Enter") this.els.addTopicBtn.click(); });
        
        if (this.els.markmapSvg) this.els.markmapSvg.addEventListener('click', (e) => this.handleMindmapClick(e));

        if (this.els.downloadBtn) {
            this.els.downloadBtn.onclick = () => {
                const a = document.createElement('a');
                a.href = URL.createObjectURL(new Blob([this.currentSummaryData], { type: 'text/markdown' }));
                a.download = 'meeting_notes.md'; a.click();
            };
        }
        if (this.els.copyBtn) this.els.copyBtn.onclick = () => navigator.clipboard.writeText(this.currentSummaryData).then(() => alert("已複製！"));

        window.switchPage = (pageName) => this.switchPage(pageName);
        window.toggleMode = () => this.toggleMode();
        window.removeTopic = (index) => { this.myTopics.splice(index, 1); this.renderAgendaList(); };
    },

    switchPage(pageName) {
        document.querySelectorAll('.page-section').forEach(el => el.classList.remove('active'));
        document.querySelectorAll('.nav-btn').forEach(el => el.classList.remove('active'));
        const targetPage = document.getElementById(`page-${pageName}`);
        if(targetPage) targetPage.classList.add('active');
        
        const btnIndex = pageName === 'home' ? 0 : pageName === 'summary' ? 1 : 2;
        const navBtns = document.querySelectorAll('.nav-btn');
        if(navBtns[btnIndex]) navBtns[btnIndex].classList.add('active');

        if(pageName === 'mindmap' && this.pendingMindmapRoot) {
            setTimeout(() => {
                try {
                    if (!window.mm) {
                        this.els.markmapSvg.innerHTML = '';
                        window.mm = window.markmap.Markmap.create(this.els.markmapSvg, null, this.pendingMindmapRoot);
                    } else { window.mm.setData(this.pendingMindmapRoot); window.mm.fit(); }
                } catch (err) { console.warn("D3 動畫警告:", err); }
            }, 150); 
        }
    },

    toggleMode() {
        const radios = document.getElementsByName('mode');
        for (let r of radios) if (r.checked) this.currentMode = r.value;
        if (this.currentMode === 'mic') { 
            this.els.fileUploadArea.style.display = 'none'; 
            if(!this.isAgendaLocked) this.els.actionButton.textContent = '鎖定議程並開始會議'; 
        } else { 
            this.els.fileUploadArea.style.display = 'block'; 
            if(!this.isAgendaLocked) this.els.actionButton.textContent = '上傳檔案並開始分析'; 
        }
    },

    renderAgendaList() {
        this.els.agendaList.innerHTML = '';
        if (this.myTopics.length === 0) { this.els.agendaList.innerHTML = '<p style="text-align:center; color:#ccc; font-size:0.9em;">無議程</p>'; return; }
        this.myTopics.forEach((topic, index) => {
            const div = document.createElement('div'); div.className = 'topic-item'; div.id = `topic-${topic}`;
            const deleteBtn = this.isAgendaLocked ? '' : `<button onclick="removeTopic(${index})" style="background:none; color:red; padding:0; font-weight:bold;">✕</button>`;
            div.innerHTML = `<span>${topic}</span> ${deleteBtn}`;
            
            if (this.topicToTranscriptId[topic]) {
                div.classList.add('done'); div.style.cursor = 'pointer'; 
                div.onclick = () => {
                    const targetEl = document.getElementById(this.topicToTranscriptId[topic]);
                    if (targetEl) { targetEl.scrollIntoView({ behavior: 'smooth', block: 'center' }); targetEl.style.backgroundColor = '#ffff99'; setTimeout(() => targetEl.style.backgroundColor = 'transparent', 2000); }
                };
            }
            this.els.agendaList.appendChild(div);
        });
    },

    updateTranscript(data) {
        // 🚀 接收後端算好的時間戳，若無則預設為片段
        const ts = data.ts ? data.ts.trim() : `[片段]`;
        const p = document.createElement('p'); p.id = `transcript-${this.chunkCounter}`; 
        
        let tag = ''; 
        if (data.status === 'CONSENSUS') tag = '<span class="tag tag-consensus">共識</span>'; 
        else if (data.status === 'DISPUTE') { tag = '<span class="tag tag-dispute">爭議</span>'; p.style.color = '#c0392b'; }
        
        p.innerHTML = `${tag} <strong>${ts}</strong> ${data.text}`; p.style.padding = '5px'; 
        this.els.liveTranscript.appendChild(p); this.els.liveTranscript.scrollTop = this.els.liveTranscript.scrollHeight;
        
        // 推入紀錄陣列，確保儲存帶有時間戳
        this.fullTranscriptLog.push(`${ts} ${data.text}`);
        
        if (data.hit_topics && data.hit_topics.length > 0) {
            let shouldRenderAgenda = false;
            data.hit_topics.forEach(t => { if (!this.topicToTranscriptId[t]) { this.topicToTranscriptId[t] = p.id; shouldRenderAgenda = true; } });
            if (shouldRenderAgenda) this.renderAgendaList();
        }
        this.chunkCounter++; 
        
        this.els.fullTranscript.innerHTML = this.fullTranscriptLog.map(t => `<p>${t}</p>`).join(''); 
        this.els.fullTranscript.scrollTop = this.els.fullTranscript.scrollHeight;
        this.els.warningMsg.style.display = data.warning ? 'block' : 'none'; this.els.warningMsg.textContent = data.warning || '';
    },

    updateImageAnalysis(data) {
        const p = document.createElement('p'); p.style.background = "#e3f2fd"; p.style.borderLeft = "4px solid #17a2b8";
        p.innerHTML = `<strong>[圖片分析]</strong> ${data.description}`;
        this.els.liveTranscript.appendChild(p); this.els.liveTranscript.scrollTop = this.els.liveTranscript.scrollHeight;
        this.els.btnUploadImage.disabled = false; this.els.btnUploadImage.textContent = "分析圖片"; 
        this.els.imgStatus.textContent = "✅ 分析完成"; this.els.imageInput.value = "";
    },

    updateInterimSummary(data) {
        if(!this.els.interimSummaryBox) return;
        const now = new Date(); const timeStr = now.getHours().toString().padStart(2, '0') + ':' + now.getMinutes().toString().padStart(2, '0');
        const newEntry = `<div style="margin-bottom: 10px; border-bottom: 1px dashed #ccc; padding-bottom: 5px;"><strong>[${timeStr} 更新]</strong><br>${data.replace(/\n/g, '<br>')}</div>`;
        if(this.els.interimSummaryBox.innerHTML.includes("會議開始後")) this.els.interimSummaryBox.innerHTML = '';
        this.els.interimSummaryBox.innerHTML = newEntry + this.els.interimSummaryBox.innerHTML;
    },

    renderSummaryAndMindmap(res, audioSourceUrl) {
        if (res && res.summary) {
            this.els.aiSummaryBox.innerHTML = res.summary; this.currentSummaryData = res.summary;
            const clean = res.summary.replace(/<[^>]+>/g, '');
            if (clean.includes("二、尚未解決議題")) {
                const parts = clean.split("二、尚未解決議題");
                if (parts.length > 1) this.els.nextAgendaPreview.value = parts[1].split("三、")[0].trim();
            }
        } else { this.els.aiSummaryBox.innerHTML = "<p style='color:red;'>⚠️ AI 未回傳有效摘要內容。</p>"; }

        if (this.els.mindmapAudioPlayer && audioSourceUrl) {
            this.els.mindmapAudioPlayer.src = audioSourceUrl; this.els.mindmapAudioPlayer.style.display = 'block'; 
            this.els.mindmapAudioPlayer.ontimeupdate = () => {
                if (this.targetEndTime !== null && this.els.mindmapAudioPlayer.currentTime >= this.targetEndTime) {
                    this.els.mindmapAudioPlayer.pause(); this.targetEndTime = null;
                }
            };
        }

        if (res && res.mindmap && window.markmap) {
            let rawMindmap = res.mindmap.replace(/```markdown/g, '').replace(/```/g, '').trim();
            rawMindmap = rawMindmap.replace(/\[\s*\]/g, "[00:00]"); 
            
            rawMindmap = rawMindmap.replace(/【第二部分：結構化心智圖】/g, '').trim();
            if (!rawMindmap.startsWith('#')) rawMindmap = '# 會議心智圖\n' + rawMindmap; 

            try {
                const transformer = new window.markmap.Transformer();
                const { root } = transformer.transform(rawMindmap);
                this.pendingMindmapRoot = root;
                this.mindmapTimestamps = [];
                const extractTimes = (node) => {
                    if(!node) return;
                    if(node.content) {
                        const m = node.content.match(/\[(\d+):(\d+)\]/);
                        if(m) {
                            const sec = parseInt(m[1], 10) * 60 + parseInt(m[2], 10);
                            if(!this.mindmapTimestamps.includes(sec)) this.mindmapTimestamps.push(sec);
                        }
                    }
                    if(node.children) node.children.forEach(extractTimes);
                };
                extractTimes(root);
                this.mindmapTimestamps.sort((a, b) => a - b);
                
                if (document.getElementById('page-mindmap').classList.contains('active')) {
                    if (!window.mm) { this.els.markmapSvg.innerHTML = ''; window.mm = window.markmap.Markmap.create(this.els.markmapSvg, null, this.pendingMindmapRoot); 
                    } else { window.mm.setData(this.pendingMindmapRoot); window.mm.fit(); }
                }
            } catch (err) { console.error("心智圖渲染失敗", err); }
        } else if (res && res.mindmap) { this.els.markmapSvg.innerHTML = '<text x="20" y="40" fill="red">⚠️ 心智圖套件載入失敗</text>'; }

        this.els.downloadBtn.disabled = false; this.els.copyBtn.disabled = false;
        this.els.statusText.textContent = '狀態：報告已生成！請切換分頁查看。'; 
        this.els.actionButton.textContent = '會議已結束 (點擊切換查看結果)';
        this.els.actionButton.className = 'btn-success'; 
        this.els.actionButton.onclick = () => this.switchPage('summary'); 
        this.els.actionButton.disabled = false;
    },

    handleMindmapClick(e) {
        const nodeGroup = e.target.closest('.markmap-node');
        if (nodeGroup && window.d3) {
            const datum = window.d3.select(nodeGroup).datum();
            if (datum && datum.data && datum.data.content) {
                const timeMatch = datum.data.content.match(/\[(\d+):(\d+)\]/);
                if (timeMatch && this.els.mindmapAudioPlayer) {
                    const totalSeconds = (parseInt(timeMatch[1], 10) * 60) + parseInt(timeMatch[2], 10);
                    const currentIndex = this.mindmapTimestamps.indexOf(totalSeconds);
                    this.targetEndTime = (currentIndex !== -1 && currentIndex < this.mindmapTimestamps.length - 1) ? this.mindmapTimestamps[currentIndex + 1] : null;
                    let jumpTime = totalSeconds - 2; 
                    this.els.mindmapAudioPlayer.currentTime = jumpTime < 0 ? 0 : jumpTime;
                    this.els.mindmapAudioPlayer.play();
                }
            }
        }
    },

    resetMeetingUI() {
        this.els.inputArea.style.display = 'none';
        this.els.aiSummaryBox.innerHTML = '<div style="text-align:center; margin-top:50px; color:#888;">生成中...</div>';
        this.els.markmapSvg.innerHTML = ''; this.els.nextAgendaPreview.value = ''; this.pendingMindmapRoot = null;
        this.els.liveTranscript.innerHTML = ""; this.els.fullTranscript.innerHTML = ""; 
        this.chunkCounter = 0; this.fullTranscriptLog = []; this.topicToTranscriptId = {}; 
        this.meetingStartTime = Date.now(); this.isAgendaLocked = true;
        this.els.actionButton.disabled = true; this.els.statusText.textContent = '狀態：初始化中...';
    }
};