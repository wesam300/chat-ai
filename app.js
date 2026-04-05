// =============== Initialization & Auth ===============
import { initializeApp } from "https://www.gstatic.com/firebasejs/11.0.0/firebase-app.js";
import { getAuth, signInWithPopup, GoogleAuthProvider } from "https://www.gstatic.com/firebasejs/11.0.0/firebase-auth.js";

const firebaseConfig = {
  apiKey: "AIzaSyCY3zFRaaTKKYfpo1BrQXPZxacmDdT-j-4",
  authDomain: "we-ai-21415.firebaseapp.com",
  projectId: "we-ai-21415",
  storageBucket: "we-ai-21415.firebasestorage.app",
  messagingSenderId: "983774256661",
  appId: "1:983774256661:web:18fa6ca1619f3d4d77781c"
};

const app = initializeApp(firebaseConfig);
const auth = getAuth(app);
const googleProvider = new GoogleAuthProvider();

// =============== DOM Elements ===============
const authOverlay = document.getElementById('authOverlay');
const tabLogin = document.getElementById('tabLogin');
const tabRegister = document.getElementById('tabRegister');
const loginForm = document.getElementById('loginForm');
const registerForm = document.getElementById('registerForm');
const btnGoogleSignIn = document.getElementById('btnGoogleSignIn');

const userProfileSection = document.getElementById('userProfileSection');
const userNameDisplay = document.getElementById('userNameDisplay');
const logoutBtn = document.getElementById('logoutBtn');

const chatMessages = document.getElementById('chatMessages');
const messageInput = document.getElementById('messageInput');
const sendBtn = document.getElementById('sendBtn');
const clearChatBtn = document.getElementById('clearChatBtn');
const attachMediaBtn = document.getElementById('attachMediaBtn');

const sidebar = document.getElementById('sidebar');
const openSidebar = document.getElementById('openSidebar');
const closeSidebar = document.getElementById('closeSidebar');

// Constants & State
let isGenerating = false;
let currentConversationId = null;

// =============== Initialization & Helpers ===============
async function checkAuth() {
    try {
        const res = await fetch('/api/auth/me');
        const data = await res.json();
        if (data.user) {
            setLoggedInState(data.user);
            loadConversations();
        } else {
            setLoggedOutState();
        }
    } catch (e) {
        setLoggedOutState();
    }
}

function setLoggedInState(user) {
    if (authOverlay) authOverlay.classList.add('hidden');
    if (userProfileSection) userProfileSection.style.display = 'block';
    if (userNameDisplay) userNameDisplay.textContent = user.username;
    
    // Check if admin
    let adminBtn = document.getElementById('linkAdminPanel');
    if (user.email === "wemu20@gmail.com") {
        if(!adminBtn) {
            adminBtn = document.createElement('a');
            adminBtn.id = 'linkAdminPanel';
            adminBtn.href = '/admin';
            adminBtn.className = 'history-item';
            adminBtn.innerHTML = '<i class="fa-solid fa-user-shield"></i> <span>لوحة الإدارة</span>';
            const hist = document.querySelector('.sidebar-history');
            if (hist) hist.prepend(adminBtn);
        }
    } else if (adminBtn) adminBtn.remove();
}

function setLoggedOutState() {
    if (authOverlay) authOverlay.classList.remove('hidden');
    if (userProfileSection) userProfileSection.style.display = 'none';
}

// Google Sign-In
btnGoogleSignIn.addEventListener('click', async () => {
    try {
        const result = await signInWithPopup(auth, googleProvider);
        const user = result.user;
        const res = await fetch('/api/auth/google', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                idToken: await user.getIdToken(),
                email: user.email,
                username: user.displayName
            })
        });
        if (res.ok) checkAuth();
    } catch (error) {
        alert('فشل تسجيل الدخول عبر جوجل');
    }
});

tabLogin.addEventListener('click', () => {
    tabLogin.classList.add('active'); tabRegister.classList.remove('active');
    loginForm.classList.add('active'); registerForm.classList.remove('hidden');
    registerForm.classList.add('hidden'); loginForm.classList.remove('hidden');
});

tabRegister.addEventListener('click', () => {
    tabRegister.classList.add('active'); tabLogin.classList.remove('active');
    registerForm.classList.add('active'); loginForm.classList.remove('active');
    registerForm.classList.remove('hidden'); loginForm.classList.add('hidden');
});

loginForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const username = document.getElementById('loginEmail').value;
    const password = document.getElementById('loginPassword').value;
    const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password })
    });
    if (res.ok) checkAuth();
    else alert('خطأ في البيانات');
});

registerForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const username = document.getElementById('registerEmail').value;
    const password = document.getElementById('registerPassword').value;
    const res = await fetch('/api/auth/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password })
    });
    if (res.ok) checkAuth();
    else alert('فشل إنشاء الحساب');
});

logoutBtn.addEventListener('click', async () => {
    await fetch('/api/auth/logout', { method: 'POST' });
    location.reload();
});

// =============== Chat Logic ===============

async function loadConversations() {
    const res = await fetch('/api/conversations');
    const data = await res.json();
    const container = document.querySelector('.sidebar-history');
    const historyTitle = container.querySelector('.section-title');
    // Clear old items except title and admin btn
    const items = container.querySelectorAll('.history-item:not(#linkAdminPanel)');
    items.forEach(i => i.remove());

    data.forEach(c => {
        const div = document.createElement('div');
        div.className = `history-item ${c.id === currentConversationId ? 'active' : ''}`;
        div.innerHTML = `<i class="fa-regular fa-message"></i> <span>${c.title}</span>`;
        div.onclick = () => loadChat(c.id);
        container.appendChild(div);
    });
}

async function loadChat(id) {
    currentConversationId = id;
    const res = await fetch(`/api/conversations/${id}`);
    const data = await res.json();
    chatMessages.innerHTML = '';
    data.messages.forEach(m => addMessageToUI(m.content, m.role));
    if(window.innerWidth <= 850) sidebar.classList.remove('open');
    loadConversations();
}

// Expose copy function globally for inline onclick handlers
window.copyCodeClick = function(button, encodedCode) {
    navigator.clipboard.writeText(decodeURIComponent(encodedCode)).then(() => {
        const originalText = button.innerHTML;
        button.innerHTML = '<i class="fa-solid fa-check"></i> تم';
        setTimeout(() => button.innerHTML = originalText, 2000);
    }).catch(err => {
        console.error('Failed to copy: ', err);
    });
};

function addMessageToUI(text, sender) {
    const isUser = sender === 'user';
    const msgDiv = document.createElement('div');
    msgDiv.className = `message ${isUser ? 'user-message' : 'bot-message'} fade-in`;
    
    let contentHTML = '';
    if (isUser) {
        contentHTML = `<p>${text.replace(/\n/g, '<br>')}</p>`;
    } else {
        try {
            // Parse and Sanitize
            let parsed = marked.parse(text);
            let safeHTML = DOMPurify.sanitize(parsed);
            
            // Highlight and add Copy Buttons
            const tempDiv = document.createElement('div');
            tempDiv.innerHTML = safeHTML;
            
            tempDiv.querySelectorAll('pre code').forEach((block) => {
                hljs.highlightElement(block);
                const pre = block.parentNode;
                
                const header = document.createElement('div');
                header.className = 'code-header';
                
                const langClass = Array.from(block.classList).find(c => c.startsWith('language-')) || 'Code';
                const langSpan = document.createElement('span');
                langSpan.textContent = langClass.replace('language-', '').trim().toUpperCase() || 'CODE';
                header.appendChild(langSpan);
                
                const copyBtn = document.createElement('button');
                copyBtn.className = 'btn-copy-code';
                copyBtn.innerHTML = '<i class="fa-regular fa-copy"></i> نسخ';
                
                const encodedCode = encodeURIComponent(block.innerText || block.textContent);
                copyBtn.setAttribute('onclick', `window.copyCodeClick(this, '${encodedCode}')`);
                header.appendChild(copyBtn);
                
                pre.parentNode.insertBefore(header, pre);
            });
            contentHTML = `<div class="markdown-body" dir="auto">${tempDiv.innerHTML}</div>`;
        } catch (e) {
            console.error("Markdown Error:", e);
            contentHTML = `<p>${text.replace(/\n/g, '<br>')}</p>`;
        }
    }

    msgDiv.innerHTML = `
        <div class="avatar"><i class="fa-solid ${isUser ? 'fa-user' : 'fa-robot'}"></i></div>
        <div class="message-bubble">${contentHTML}</div>
    `;
    
    chatMessages.appendChild(msgDiv);
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

async function handleSend() {
    if (isGenerating) return;
    const text = messageInput.value.trim();
    if (!text) return;

    addMessageToUI(text, 'user');
    messageInput.value = '';
    isGenerating = true;
    
    // لقطة رقم المحادثة قبل بدء الطلب (منع التداخل)
    const requestConvId = currentConversationId;
    
    // Add typing indicator
    const tid = 'typing-' + Date.now();
    const tdiv = document.createElement('div');
    tdiv.id = tid;
    tdiv.className = 'message bot-message fade-in';
    tdiv.innerHTML = '<div class="avatar"><i class="fa-solid fa-robot"></i></div><div class="message-bubble">... جاري التفكير ...</div>';
    chatMessages.appendChild(tdiv);
    chatMessages.scrollTop = chatMessages.scrollHeight;

    try {
        const res = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: text, conversation_id: currentConversationId })
        });
        
        const loader = document.getElementById(tid);
        if (loader) loader.remove();
        
        // ---- الحماية من تداخل الجلسات ----
        if (currentConversationId !== requestConvId && requestConvId !== null) {
            return;
        }

        // إنشاء مكان للرسالة المباشرة
        const msgDiv = document.createElement('div');
        msgDiv.className = `message bot-message fade-in`;
        msgDiv.innerHTML = `
            <div class="avatar"><i class="fa-solid fa-robot"></i></div>
            <div class="message-bubble"><div class="markdown-body" dir="auto"></div></div>
        `;
        chatMessages.appendChild(msgDiv);
        const mdBody = msgDiv.querySelector('.markdown-body');

        const reader = res.body.getReader();
        const decoder = new TextDecoder('utf-8');
        let accumulatedText = "";
        
        while(true) {
            const {done, value} = await reader.read();
            if(done) break;
            const chunk = decoder.decode(value, {stream: true});
            const lines = chunk.split('\n\n');
            for(const line of lines) {
                if(line.startsWith('data: ')) {
                    try {
                        const j = JSON.parse(line.substring(6));
                        if(j.event === 'init') {
                            if (!currentConversationId || currentConversationId === requestConvId) {
                                currentConversationId = j.conversation_id;
                            }
                        } else if (j.event === 'chunk' || j.event === 'error') {
                            accumulatedText += j.content;
                            if (currentConversationId === requestConvId || requestConvId === null) {
                                mdBody.innerHTML = DOMPurify.sanitize(marked.parse(accumulatedText));
                                chatMessages.scrollTop = chatMessages.scrollHeight;
                            }
                        } else if (j.event === 'done') {
                            if (currentConversationId === requestConvId || requestConvId === null) {
                                mdBody.innerHTML = DOMPurify.sanitize(marked.parse(accumulatedText));
                                // Highlighting at the end
                                mdBody.querySelectorAll('pre code').forEach((block) => {
                                    hljs.highlightElement(block);
                                    const pre = block.parentNode;
                                    const header = document.createElement('div');
                                    header.className = 'code-header';
                                    const langClass = Array.from(block.classList).find(c => c.startsWith('language-')) || 'Code';
                                    const langSpan = document.createElement('span');
                                    langSpan.textContent = langClass.replace('language-', '').trim().toUpperCase() || 'CODE';
                                    header.appendChild(langSpan);
                                    
                                    const copyBtn = document.createElement('button');
                                    copyBtn.className = 'btn-copy-code';
                                    copyBtn.innerHTML = '<i class="fa-regular fa-copy"></i> نسخ';
                                    const encodedCode = encodeURIComponent(block.innerText || block.textContent);
                                    copyBtn.setAttribute('onclick', `window.copyCodeClick(this, '${encodedCode}')`);
                                    header.appendChild(copyBtn);
                                    pre.parentNode.insertBefore(header, pre);
                                });
                                loadConversations();
                            }
                        }
                    } catch(e) {}
                }
            }
        }
    } catch (e) {
        const loader = document.getElementById(tid);
        if (loader) loader.innerHTML = '<div class="avatar"><i class="fa-solid fa-robot"></i></div><div class="message-bubble" style="color:#ef4444;">خطأ في الاتصال بالسيرفر</div>';
    } finally {
        isGenerating = false;
    }
}

sendBtn.addEventListener('click', handleSend);
messageInput.addEventListener('keydown', (e) => { if(e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); } });

clearChatBtn.addEventListener('click', () => {
    currentConversationId = null;
    chatMessages.innerHTML = `
        <div class="welcome-screen">
            <div class="welcome-icon"><i class="fa-solid fa-robot"></i></div>
            <h2>كيف يمكنني مساعدتك؟</h2>
            <p>اطرح سؤالك، اطلب كوداً، أو قم بأي مهمة تخطر ببالك</p>
        </div>
    `;
    loadConversations();
});

// Sidebar
if(openSidebar) openSidebar.addEventListener('click', () => sidebar.classList.add('open'));
if(closeSidebar) closeSidebar.addEventListener('click', () => sidebar.classList.remove('open'));

checkAuth();
