document.addEventListener('DOMContentLoaded', () => {
    // --- Tab Switching ---
    const tabBtns = document.querySelectorAll('.tab-btn');
    const tabPanes = document.querySelectorAll('.tab-pane');

    function switchTab(tabId) {
        tabBtns.forEach(btn => {
            btn.classList.toggle('active', btn.dataset.tab === tabId);
        });
        tabPanes.forEach(pane => {
            pane.classList.toggle('active', pane.id === `${tabId}-tab`);
        });
    }

    tabBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            switchTab(btn.dataset.tab);
        });
    });

    // --- Tool Management ---
    const primaryToolsContainer = document.getElementById('primary-tools');
    const secondaryToolsContainer = document.getElementById('secondary-tools');
    const secondaryToggleBtn = document.getElementById('secondary-tools-toggle');
    let secondaryVisible = false;

    const toggleSecondaryTools = () => {
        if (!secondaryToolsContainer || !secondaryToggleBtn) return;
        secondaryVisible = !secondaryVisible;
        secondaryToolsContainer.classList.toggle('collapsed', !secondaryVisible);
        secondaryToggleBtn.textContent = secondaryVisible ? 'Hide more tools' : 'Show more tools';
    };

    if (secondaryToggleBtn) {
        secondaryToggleBtn.addEventListener('click', toggleSecondaryTools);
    }

    const describeTool = (tool) => {
        if (tool?.description) return tool.description;
        return 'Runs the Biomni tool "' + (tool?.label || tool?.name || 'Custom tool') + '".';
    };

    const renderToolOption = (tool) => {
        const wrapper = document.createElement('label');
        wrapper.className = 'tool-option';

        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.className = 'tool-checkbox';
        checkbox.dataset.toolName = tool.name;
        checkbox.checked = Boolean(tool.default_enabled);

        const textWrap = document.createElement('div');
        textWrap.className = 'tool-option-text';

        const nameEl = document.createElement('div');
        nameEl.className = 'tool-name';
        nameEl.textContent = tool.label || tool.name;

        const descEl = document.createElement('div');
        descEl.className = 'tool-description';
        descEl.textContent = describeTool(tool);

        textWrap.appendChild(nameEl);
        textWrap.appendChild(descEl);
        wrapper.appendChild(checkbox);
        wrapper.appendChild(textWrap);
        return wrapper;
    };

    const populateTools = (tools = []) => {
        if (!primaryToolsContainer || !secondaryToolsContainer) return;
        primaryToolsContainer.innerHTML = '';
        secondaryToolsContainer.innerHTML = '';

        const primaries = [];
        const secondaries = [];
        tools.forEach((tool) => {
            if ((tool.importance || 'secondary').toLowerCase() === 'primary') {
                primaries.push(tool);
            } else {
                secondaries.push(tool);
            }
        });

        const renderList = (target, list) => {
            if (!list.length) {
                const placeholder = document.createElement('div');
                placeholder.className = 'tool-placeholder';
                placeholder.textContent = 'No tools available';
                target.appendChild(placeholder);
                return;
            }
            list.forEach((tool) => {
                target.appendChild(renderToolOption(tool));
            });
        };

        renderList(primaryToolsContainer, primaries);
        renderList(secondaryToolsContainer, secondaries);

        if (secondaries.length === 0 && secondaryToggleBtn) {
            secondaryToggleBtn.classList.add('hidden');
        } else if (secondaryToggleBtn) {
            secondaryToggleBtn.classList.remove('hidden');
        }
    };

    fetch('/api/tools')
        .then((res) => res.json())
        .then((payload) => {
            populateTools(payload?.tools || []);
        })
        .catch((err) => {
            console.error('Failed to load tools metadata:', err);
            if (primaryToolsContainer) {
                primaryToolsContainer.innerHTML = '<div class="tool-placeholder">Unable to load tools</div>';
            }
        });

    const gatherSelectedTools = () => {
        const payload = {};
        const inputs = document.querySelectorAll('.tool-checkbox');
        inputs.forEach((input) => {
            const name = input.dataset.toolName;
            if (!name) return;
            payload[name] = input.checked;
        });
        return payload;
    };

    // --- Main View Switching (Chat vs Docs) ---
    const navLinks = document.querySelectorAll('.nav-link[data-target]');
    const views = document.querySelectorAll('.main-view');

    navLinks.forEach(link => {
        link.addEventListener('click', (e) => {
            const target = link.dataset.target;
            if (!target) return; // e.g. external link
            
            e.preventDefault();
            
            // Update nav state
            navLinks.forEach(l => l.classList.remove('active'));
            link.classList.add('active');

            // Update view state
            views.forEach(view => {
                if (view.id === `view-${target}`) {
                    view.style.display = 'flex';
                    // Restore flex layout for chat, block for docs if needed, 
                    // but CSS has #main-center as flex col.
                    // The views are children.
                    // Chat view needs flex to stretch input/tabs.
                    // Docs view can be block.
                    if (target === 'chat') {
                        view.style.display = 'flex';
                        view.style.flexDirection = 'column';
                        view.style.height = '100%';
                    } else {
                        view.style.display = 'block';
                    }
                } else {
                    view.style.display = 'none';
                }
            });
        });
    });

    // --- Input Auto-resize ---
    const chatInput = document.getElementById('chat-input');
    const messagesContainer = document.getElementById('chat-messages');
    const thoughtsLog = document.getElementById('thoughts-log');
    const variablesView = document.getElementById('variables-view');

    if (!messagesContainer || !thoughtsLog || !variablesView) {
        console.error('Chat containers are missing from the DOM.');
        return;
    }
    chatInput.addEventListener('input', function() {
        this.style.height = 'auto';
        this.style.height = (this.scrollHeight) + 'px';
        if (this.value === '') {
            this.style.height = '24px';
        }
    });

    chatInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    document.getElementById('send-btn').addEventListener('click', sendMessage);

    // --- File Upload ---
    const dropZone = document.getElementById('drop-zone');
    const fileInput = document.getElementById('file-upload');

    dropZone.addEventListener('click', () => fileInput.click());

    dropZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        dropZone.classList.add('dragover');
    });

    dropZone.addEventListener('dragleave', () => {
        dropZone.classList.remove('dragover');
    });

    dropZone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropZone.classList.remove('dragover');
        const files = e.dataTransfer.files;
        handleFiles(files);
    });

    fileInput.addEventListener('change', () => {
        handleFiles(fileInput.files);
    });

    function setActiveChatItem(chatId) {
        document.querySelectorAll('.chat-item').forEach(item => {
            if (item.id === 'new-chat-btn') {
                item.classList.toggle('active', !chatId);
            } else {
                item.classList.toggle('active', item.dataset.chatId === chatId);
            }
        });
    }

    function createHistoryItemElement(chatId, title) {
        const div = document.createElement('div');
        div.className = 'chat-item';
        div.dataset.chatId = chatId;

        const titleSpan = document.createElement('span');
        titleSpan.className = 'chat-title-text';
        titleSpan.textContent = title;

        const deleteBtn = document.createElement('button');
        deleteBtn.type = 'button';
        deleteBtn.className = 'chat-delete-btn';
        deleteBtn.title = 'Delete chat';
        deleteBtn.setAttribute('aria-label', 'Delete chat');
        deleteBtn.textContent = '🗑️';

        div.appendChild(titleSpan);
        div.appendChild(deleteBtn);
        return div;
    }

    function ensureChatId() {
        if (currentChatId) return currentChatId;
        
        currentChatId = 'chat_' + Date.now();
        const title = 'New Chat'; // Placeholder until first message
        
        // Create UI item
        const newItem = createHistoryItemElement(currentChatId, title);
        newItem.classList.add('active');
        
        // Deactivate "New Chat"
        setActiveChatItem(currentChatId);

        // Insert after New Chat button
        if (historyList.children.length > 1) {
            historyList.insertBefore(newItem, historyList.children[1]);
        } else {
            historyList.appendChild(newItem);
        }
        
        // Initial save
        saveChatToStorage(currentChatId, title, []);
        return currentChatId;
    }

    function handleFiles(files) {
        if (!files.length) return;
        
        const chatId = ensureChatId();

        Array.from(files).forEach(file => {
            const formData = new FormData();
            formData.append('file', file); 
            formData.append('chat_id', chatId); // Pass chat ID

            // Optimistic UI update & get status element
            const statusSpan = addFileToList(file.name, 'uploading...', null);

            fetch('/files/upload', {
                method: 'POST',
                body: formData
            })
            .then(response => {
                if (!response.ok) throw new Error(response.statusText);
                return response.json();
            })
            .then(data => {
                console.log('Upload success:', data);
                if (statusSpan) {
                    statusSpan.textContent = 'Done';
                    statusSpan.style.color = 'var(--accent)';
                    // Update parent to be clickable
                    const item = statusSpan.closest('.file-item');
                    makeFileItemClickable(item, chatId, data.filename);
                }
            })
            .catch(error => {
                console.error('Upload error:', error);
                if (statusSpan) {
                    statusSpan.textContent = 'Error';
                    statusSpan.style.color = '#ef4444';
                }
            });
        });
    }

    function addFileToList(name, status, downloadUrl) {
        const fileList = document.getElementById('files-list');
        const div = document.createElement('div');
        div.className = 'file-item';
        if (downloadUrl) {
            div.style.cursor = 'pointer';
            div.onclick = () => window.open(downloadUrl, '_blank');
        }
        
        div.innerHTML = `
            <span>📄</span>
            <span style="flex:1; overflow:hidden; text-overflow:ellipsis;">${name}</span>
            <span class="file-status" style="font-size:0.8em; color:var(--muted);">${status || ''}</span>
        `;
        fileList.appendChild(div);
        return div.querySelector('.file-status');
    }
    
    function makeFileItemClickable(div, chatId, filename) {
         div.style.cursor = 'pointer';
         div.onclick = () => window.open(`/files/download/${chatId}/${filename}`, '_blank');
    }

    function fetchFiles(chatId) {
        const fileList = document.getElementById('files-list');
        fileList.innerHTML = ''; // Clear list
        
        fetch(`/files/list/${chatId}`)
        .then(res => res.json())
        .then(files => {
            files.forEach(f => {
                const url = `/files/download/${chatId}/${f.name}`;
                addFileToList(f.name, '', url);
            });
        })
        .catch(err => console.error('Error fetching files:', err));
    }

    // --- Chat History Logic ---
    const historyList = document.getElementById('history-list');
    const newChatBtn = document.getElementById('new-chat-btn');
    let currentChatId = null; // null means "New Chat" mode

    // Load history on startup
    loadHistoryFromStorage();

    // Delegate click for dynamic history items
    historyList.addEventListener('click', (e) => {
        const deleteBtn = e.target.closest('.chat-delete-btn');
        if (deleteBtn) {
            e.stopPropagation();
            const parent = deleteBtn.closest('.chat-item');
            const chatId = parent?.dataset.chatId;
            if (chatId) {
                deleteChatHistory(chatId, parent);
            }
            return;
        }

        const item = e.target.closest('.chat-item');
        if (!item) return;

        if (item.id === 'new-chat-btn') {
            startNewChat();
        } else {
            // Load chat history
            const chatId = item.dataset.chatId;
            if (chatId) {
                setActiveChatItem(chatId);
                loadChat(chatId);
            }
        }
    });

    function startNewChat() {
        currentChatId = null;
        messagesContainer.innerHTML = `
            <div class="message bot-message">
                Hello! I am Biomni, your biomedical AI assistant. How can I help you today?
            </div>
        `;
        thoughtsLog.innerHTML = '';
        variablesView.innerHTML = '';
        chatInput.value = '';
        document.getElementById('files-list').innerHTML = ''; // Clear files
        switchTab('answer');
        
        // Ensure New Chat is active if called programmatically
        setActiveChatItem(null);
    }
    
    function loadHistoryFromStorage() {
        // Load from server instead of localStorage
        fetch('/files/chats')
        .then(res => res.json())
        .then(chats => {
            // Clear existing items except "New Chat"
            Array.from(historyList.children).forEach(child => {
                if (child.id !== 'new-chat-btn') child.remove();
            });
            
            // Append saved chats
            chats.forEach(chat => {
                const div = createHistoryItemElement(chat.id, chat.title);
                historyList.appendChild(div);
            });
            if (!currentChatId && chats.length) {
                setActiveChatItem(chats[0].id);
            }
        })
        .catch(err => console.error('Failed to load chats:', err));
    }

    function deleteChatHistory(chatId, itemElement) {
        fetch(`/files/chat/${chatId}`, { method: 'DELETE' })
        .then(res => {
            if (!res.ok) throw new Error('Failed to delete chat');
            itemElement?.remove();
            if (currentChatId === chatId) {
                startNewChat();
            }
        })
        .catch(err => console.error('Delete chat error:', err));
    }

    function loadChat(chatId) {
        currentChatId = chatId;
        setActiveChatItem(chatId);
        
        fetch(`/files/chat/${chatId}/history`)
        .then(res => res.json())
        .then(messages => {
            messagesContainer.innerHTML = '';
            if (!messages || messages.length === 0) {
                 messagesContainer.innerHTML = `
                    <div class="message bot-message">
                        Hello! I am Biomni, your biomedical AI assistant. How can I help you today?
                    </div>
                `;
            } else {
                messages.forEach(msg => {
                    const div = appendMessage(msg.role, '');
                    div.innerHTML = msg.role === 'bot' ? marked.parse(msg.content) : msg.content;
                });
            }
            
            thoughtsLog.innerHTML = ''; 
            renderVariablesPanel(chatId, messages);
            fetchFiles(chatId); // Load files for this chat
            switchTab('answer');
        })
        .catch(err => console.error('Failed to load chat history:', err));
    }

    function renderVariablesPanel(chatId, messages) {
        variablesView.innerHTML = '';

        const sections = [];

        const addSection = (title, contentElement) => {
            const section = document.createElement('div');
            section.className = 'variables-section';

            const header = document.createElement('button');
            header.type = 'button';
            header.className = 'variables-section-header';
            header.textContent = title;

            const body = document.createElement('div');
            body.className = 'variables-section-body collapsed';
            body.appendChild(contentElement);

            header.addEventListener('click', () => {
                body.classList.toggle('collapsed');
            });

            section.appendChild(header);
            section.appendChild(body);
            variablesView.appendChild(section);
        };

        // Metadata section
        fetch(`/files/chat/${chatId}/metadata`)
            .then(res => res.json())
            .then(meta => {
                const metaList = document.createElement('dl');
                metaList.className = 'variables-list';

                const entries = {
                    'Chat ID': chatId,
                    'Title': meta?.title || '(untitled)',
                    'Created': meta?.created ? new Date(meta.created * 1000).toLocaleString() : 'n/a',
                    'Updated': meta?.updated ? new Date(meta.updated * 1000).toLocaleString() : 'n/a',
                    'Message count': Array.isArray(messages) ? messages.length : 'n/a'
                };

                Object.entries(entries).forEach(([label, value]) => {
                    const dt = document.createElement('dt');
                    dt.textContent = label;
                    const dd = document.createElement('dd');
                    dd.textContent = value;
                    metaList.append(dt, dd);
                });

                addSection('Chat Metadata', metaList);
            })
            .catch(err => console.error('Failed to load chat metadata:', err));

        // History summary section
        const historyContainer = document.createElement('div');
        if (messages && messages.length) {
            messages.slice(-5).forEach((msg, idx) => {
                const item = document.createElement('div');
                item.className = 'variables-message-snippet';
                item.innerHTML = `<strong>${msg.role}</strong>: ${msg.content.substring(0, 120)}${msg.content.length > 120 ? '…' : ''}`;
                historyContainer.appendChild(item);
            });
        } else {
            historyContainer.textContent = 'No messages stored.';
        }
        addSection('Recent Messages', historyContainer);
    }

    function saveChatToStorage(chatId, title, messages) {
        // Server-side init
        fetch('/files/chat/init', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ chat_id: chatId, title: title })
        }).catch(e => console.error('Save chat error:', e));
    }
    
    function addMessageToStorage(chatId, role, content) {
        // Server-side append
        fetch('/files/chat/append', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ chat_id: chatId, role: role, content: content })
        }).catch(e => console.error('Append message error:', e));
    }
    
    function updateChatTitle(chatId, newTitle) {
        // For server-side, just re-init with new title
        saveChatToStorage(chatId, newTitle, []);
        // Update UI
        const item = document.querySelector(`.chat-item[data-chat-id="${chatId}"] .chat-title-text`);
        if (item) item.textContent = newTitle;
    }

    async function sendMessage() {
        const text = chatInput.value.trim();
        if (!text) return;

        // Ensure chat ID exists
        let isNew = !currentChatId;
        const chatId = ensureChatId();
        
        if (isNew) {
            const title = text.substring(0, 25) + (text.length > 25 ? '...' : '');
            updateChatTitle(chatId, title);
        }

        // 1. Add User Message
        appendMessage('user', text);
        addMessageToStorage(chatId, 'user', text);
        
        chatInput.value = '';
        chatInput.style.height = '24px';

        // 2. Switch to Thoughts tab
        switchTab('thoughts');
        thoughtsLog.innerHTML = ''; 
        const turnMarker = document.createElement('div');
        turnMarker.className = 'log-entry';
        turnMarker.textContent = `--- Request: ${text.substring(0, 20)}... ---`;
        thoughtsLog.appendChild(turnMarker);

        // 3. Call API
        const tools = gatherSelectedTools();

        try {
            const response = await fetch('/api/chat_stream', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ 
                    prompt: text,
                    tools: tools,
                    chat_id: chatId
                })
            });

            if (!response.ok) throw new Error('Network response was not ok');

            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let botMessageDiv = null;
            let currentSolution = "";
            let buffer = "";

            const processEvent = (eventChunk) => {
                if (!eventChunk.trim()) return;
                const dataLine = eventChunk.split('\n').find(line => line.startsWith('data: '));
                if (!dataLine) return;
                try {
                    const data = JSON.parse(dataLine.slice(6));
                    if (data.type === 'log') {
                        const logDiv = document.createElement('div');
                        logDiv.className = 'log-entry';
                        logDiv.textContent = data.content;
                        thoughtsLog.appendChild(logDiv);
                        thoughtsLog.scrollTop = thoughtsLog.scrollHeight;
                    } else if (data.type === 'solution') {
                        if (!botMessageDiv) {
                            botMessageDiv = appendMessage('bot', '');
                        }
                        currentSolution += data.content;
                        botMessageDiv.innerHTML = marked.parse(currentSolution);
                        messagesContainer.scrollTop = messagesContainer.scrollHeight;
                    } else if (data.type === 'tool_call') {
                        const pre = document.createElement('pre');
                        pre.textContent = JSON.stringify(data.content, null, 2);
                        variablesView.appendChild(pre);
                    } else if (data.type === 'file_created') {
                        const logDiv = document.createElement('div');
                        logDiv.className = 'log-entry';
                        logDiv.textContent = `Snapshot saved: ${data.content?.filename || 'unknown file'}`;
                        thoughtsLog.appendChild(logDiv);
                        thoughtsLog.scrollTop = thoughtsLog.scrollHeight;
                        if (chatId) {
                            fetchFiles(chatId);
                        }
                    } else if (data.type === 'done') {
                        switchTab('answer');
                        if (currentSolution) {
                            addMessageToStorage(chatId, 'bot', currentSolution);
                        }
                        if (chatId) {
                             fetchFiles(chatId);
                        }
                    }
                } catch (e) {
                    console.error('Error parsing SSE event:', e, eventChunk);
                }
            };

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                const decoded = decoder.decode(value, { stream: true });
                buffer += decoded.replace(/\r/g, '');
                let boundaryIndex = buffer.indexOf('\n\n');
                while (boundaryIndex !== -1) {
                    const eventChunk = buffer.slice(0, boundaryIndex);
                    processEvent(eventChunk);
                    buffer = buffer.slice(boundaryIndex + 2);
                    boundaryIndex = buffer.indexOf('\n\n');
                }
            }

            if (buffer.trim()) {
                processEvent(buffer);
            }

        } catch (error) {
            console.error('Chat error:', error);
            appendMessage('bot', 'Error: ' + error.message);
        }
    }

    function appendMessage(role, text) {
        const div = document.createElement('div');
        div.className = `message ${role === 'user' ? 'user-message' : 'bot-message'}`;
        div.textContent = text; // Initial text, for bot will be updated with HTML
        messagesContainer.appendChild(div);
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
        return div;
    }
});

// Simple Markdown parser placeholder if marked.js isn't available
const marked = {
    parse: (text) => {
        return text
            .replace(/\n/g, '<br>')
            .replace(/\*\*(.*?)\*\*/g, '<b>$1</b>');
    }
};
