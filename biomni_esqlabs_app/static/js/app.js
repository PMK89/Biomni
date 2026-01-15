document.addEventListener('DOMContentLoaded', () => {
    // --- Source Attribution Toggle ---
    const sourceToggle = document.getElementById('source-toggle');
    if (sourceToggle) {
        sourceToggle.addEventListener('change', () => {
            document.body.classList.toggle('show-sources', sourceToggle.checked);
        });
    }

    // --- Tab Switching ---
    const tabBtns = document.querySelectorAll('.tab-btn');
    const tabPanes = document.querySelectorAll('.tab-pane');
    const tabContent = document.getElementById('tab-content');

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

    const apiBase = (window.BIOMNI_ROOT_PATH || '').replace(/\/$/, '');
    const withRootPath = (path) => `${apiBase}${path.startsWith('/') ? path : `/${path}`}`;

    fetch(withRootPath('/api/tools'))
        .then((res) => res.json())
        .then((payload) => {
            populateTools(payload?.tools || []);
            // Backend always provides all tools now; disable UI toggles for simplicity.
            const toolsContainer = document.querySelector('.tools-container');
            if (toolsContainer) {
                toolsContainer.classList.add('hidden');
            }
        })
        .catch((err) => {
            console.error('Failed to load tools metadata:', err);
            const toolsContainer = document.querySelector('.tools-container');
            if (toolsContainer) {
                toolsContainer.classList.add('hidden');
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

    const AUTOSCROLL_THRESHOLD_PX = 120;

    function isNearBottom(container) {
        if (!container) return true;
        const distance = container.scrollHeight - container.scrollTop - container.clientHeight;
        return distance <= AUTOSCROLL_THRESHOLD_PX;
    }

    function scrollToBottom(container, behavior = 'auto') {
        if (!container) return;
        container.scrollTo({ top: container.scrollHeight, behavior });
    }

    let chatAutoScrollEnabled = true;
    let thoughtsAutoScrollEnabled = true;

    if (!messagesContainer || !thoughtsLog || !variablesView) {
        console.error('Chat containers are missing from the DOM.');
        return;
    }

    // Disable autoscroll when the user scrolls up, re-enable when back near the bottom.
    messagesContainer.addEventListener('scroll', () => {
        chatAutoScrollEnabled = isNearBottom(messagesContainer);
    });

    thoughtsLog.addEventListener('scroll', () => {
        thoughtsAutoScrollEnabled = isNearBottom(thoughtsLog);
    });

    if (tabContent) {
        tabContent.addEventListener('scroll', () => {
            const activeTabBtn = document.querySelector('.tab-btn.active');
            const active = activeTabBtn?.dataset?.tab;
            if (active === 'thoughts') {
                thoughtsAutoScrollEnabled = isNearBottom(tabContent);
            } else if (active === 'answer') {
                chatAutoScrollEnabled = isNearBottom(tabContent);
            }
        });
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

    // --- Chat Zip Export / Import ---
    const chatExportZipBtn = document.getElementById('chat-export-zip-btn');
    const chatImportZipBtn = document.getElementById('chat-import-zip-btn');
    const chatZipUpload = document.getElementById('chat-zip-upload');

    if (chatExportZipBtn) {
        chatExportZipBtn.addEventListener('click', () => {
            const chatId = ensureChatId();
            window.open(withRootPath(`/files/chat/${chatId}/export_zip`), '_blank');
        });
    }

    if (chatImportZipBtn && chatZipUpload) {
        chatImportZipBtn.addEventListener('click', () => chatZipUpload.click());
        chatZipUpload.addEventListener('change', async () => {
            const file = chatZipUpload.files?.[0];
            chatZipUpload.value = '';
            if (!file) return;
            try {
                const formData = new FormData();
                formData.append('file', file);
                const res = await fetch(withRootPath('/files/chat/import_zip'), {
                    method: 'POST',
                    body: formData
                });
                if (!res.ok) throw new Error('Import failed');
                const payload = await res.json();
                const newChatId = payload?.chat_id;
                if (!newChatId) throw new Error('Import returned no chat_id');
                loadHistoryFromStorage();
                setTimeout(() => loadChat(newChatId), 200);
            } catch (err) {
                console.error('Chat zip import error:', err);
            }
        });
    }

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

            fetch(withRootPath('/files/upload'), {
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

    // --- File Tree Logic ---
    function formatSize(bytes) {
        if (bytes === 0) return '0 B';
        const k = 1024;
        const sizes = ['B', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
    }

    function buildFileTree(files) {
        const root = {};
        files.forEach(file => {
            const parts = file.name.split('/');
            let current = root;
            parts.forEach((part, index) => {
                if (!current[part]) {
                    current[part] = (index === parts.length - 1) ? { __file__: file } : {};
                }
                current = current[part];
            });
        });
        return root;
    }

    function renderFileTree(tree, container, chatId, level = 0) {
        const sortedKeys = Object.keys(tree).sort((a, b) => {
            const aIsFile = tree[a].__file__;
            const bIsFile = tree[b].__file__;
            if (aIsFile && !bIsFile) return 1;
            if (!aIsFile && bIsFile) return -1;
            return a.localeCompare(b);
        });

        sortedKeys.forEach(key => {
            const node = tree[key];
            const itemDiv = document.createElement('div');
            itemDiv.className = 'file-tree-item';
            itemDiv.style.paddingLeft = `${level * 12}px`;
            itemDiv.style.marginBottom = '4px';

            if (node.__file__) {
                itemDiv.style.display = 'flex';
                itemDiv.style.alignItems = 'center';
                itemDiv.style.position = 'relative';
                
                const sizeStr = formatSize(node.__file__.size || 0);

                itemDiv.innerHTML = `
                    <span style="margin-right:6px">📄</span>
                    <span class="file-link" style="flex:1; cursor:pointer; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${key}">${key}</span>
                    <span style="font-size:0.75em; color:var(--muted); background:var(--bg); padding-left:4px; position:absolute; right:0; z-index:1;">${sizeStr}</span>
                `;
                itemDiv.querySelector('.file-link').onclick = () => window.open(withRootPath(`/files/download/${chatId}/${node.__file__.name}`), '_blank');
                container.appendChild(itemDiv);
            } else {
                // Folder
                const folderHeader = document.createElement('div');
                folderHeader.style.display = 'flex';
                folderHeader.style.alignItems = 'center';
                folderHeader.style.cursor = 'pointer';
                folderHeader.innerHTML = `
                    <span style="margin-right:6px">📂</span>
                    <span style="font-weight:600">${key}</span>
                `;
                itemDiv.appendChild(folderHeader);
                container.appendChild(itemDiv);

                const childrenContainer = document.createElement('div');
                childrenContainer.className = 'folder-children';
                folderHeader.onclick = () => {
                    childrenContainer.style.display = childrenContainer.style.display === 'none' ? 'block' : 'none';
                };
                renderFileTree(node, childrenContainer, chatId, level + 1);
                container.appendChild(childrenContainer);
            }
        });
    }

    function fetchFiles(chatId) {
        const fileList = document.getElementById('files-list');
        
        fetch(withRootPath(`/files/list/${chatId}`))
        .then(res => res.json())
        .then(files => {
            fileList.innerHTML = ''; 
            if (!files || files.length === 0) {
                fileList.innerHTML = '<div style="color:var(--muted); padding:8px;">No files</div>';
                return;
            }
            const tree = buildFileTree(files);
            renderFileTree(tree, fileList, chatId);
        })
        .catch(err => console.error('Error fetching files:', err));
    }

    function addFileToList(name, status, downloadUrl) {
         const fileList = document.getElementById('files-list');
         const div = document.createElement('div');
         div.className = 'file-item';
         div.style.padding = '4px 0';
         div.innerHTML = `<span>📄 ${name}</span> <span style="font-size:0.8em; margin-left:8px; color:var(--muted)">${status}</span>`;
         fileList.prepend(div);
         return div.querySelector('span:last-child');
    }
    
    function makeFileItemClickable(div, chatId, filename) {
        setTimeout(() => fetchFiles(chatId), 500);
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
        fetch(withRootPath('/files/chats'))
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
        fetch(withRootPath(`/files/chat/${chatId}`), { method: 'DELETE' })
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
        
        fetch(withRootPath(`/files/chat/${chatId}/history`))
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
            // Force reload of files list for this chat
            fetchFiles(chatId);
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
        fetch(withRootPath(`/files/chat/${chatId}/metadata`))
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
        fetch(withRootPath('/files/chat/init'), {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ chat_id: chatId, title: title })
        }).catch(e => console.error('Save chat error:', e));
    }
    
    function addMessageToStorage(chatId, role, content) {
        // Server-side append
        fetch(withRootPath('/files/chat/append'), {
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
        const tools = null;

        try {
            const response = await fetch(withRootPath('/api/chat_stream'), {
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
                        // Append to thoughts
                        const logDiv = document.createElement('div');
                        logDiv.className = 'log-entry';
                        logDiv.textContent = data.content;
                        thoughtsLog.appendChild(logDiv);
                        if (thoughtsAutoScrollEnabled) {
                            scrollToBottom(tabContent);
                        }
                    } else if (data.type === 'solution') {
                        if (!botMessageDiv) {
                            botMessageDiv = appendMessage('bot', '');
                        }
                        currentSolution += data.content;
                        botMessageDiv.innerHTML = marked.parse(currentSolution);
                        if (chatAutoScrollEnabled) {
                            scrollToBottom(messagesContainer);
                        }
                    } else if (data.type === 'tool_call') {
                        const pre = document.createElement('pre');
                        pre.textContent = JSON.stringify(data.content, null, 2);
                        variablesView.appendChild(pre);
                    } else if (data.type === 'file_created') {
                        const logDiv = document.createElement('div');
                        logDiv.className = 'log-entry';
                        logDiv.textContent = `Snapshot saved: ${data.content?.filename || 'unknown file'}`;
                        thoughtsLog.appendChild(logDiv);
                        if (thoughtsAutoScrollEnabled) {
                            scrollToBottom(tabContent || thoughtsLog);
                        }
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
        if (chatAutoScrollEnabled) {
            scrollToBottom(messagesContainer);
        }
        return div;
    }
});

// --- Source Attribution Parsing ---
// Parse source annotations in the format: [[source:type|description]]text[[/source]]
// Types: web, literature, database, tool, internal, user
function parseSourceAttributions(html) {
    // Pattern: [[source:type|description]]content[[/source]]
    const sourcePattern = /\[\[source:(web|literature|database|tool|internal|user)\|([^\]]*)\]\](.*?)\[\[\/source\]\]/gs;

    return html.replace(sourcePattern, (match, type, description, content) => {
        const escapedDesc = description.replace(/"/g, '&quot;').replace(/'/g, '&#39;');
        return `<span class="source-highlight source-${type}">` +
               `${content}` +
               `<span class="source-tooltip">${escapedDesc}</span>` +
               `</span>`;
    });
}

// Alternative pattern for inline source markers: [source:type]text[/source] with source info in data attributes
function parseInlineSourceMarkers(html) {
    // Pattern for simple source markers with type info embedded
    // Format: <source type="web" info="URL or description">text</source>
    const xmlPattern = /<source\s+type="(web|literature|database|tool|internal|user)"\s+info="([^"]*)">(.*?)<\/source>/gs;

    return html.replace(xmlPattern, (match, type, info, content) => {
        return `<span class="source-highlight source-${type}">` +
               `${content}` +
               `<span class="source-tooltip">${info}</span>` +
               `</span>`;
    });
}

// Simple Markdown parser placeholder if marked.js isn't available
const marked = {
    parse: (text) => {
        let html = text
            .replace(/\n/g, '<br>')
            .replace(/\*\*(.*?)\*\*/g, '<b>$1</b>');

        // Apply source attribution parsing
        html = parseSourceAttributions(html);
        html = parseInlineSourceMarkers(html);

        return html;
    }
};
