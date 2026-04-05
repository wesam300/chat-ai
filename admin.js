// =============== Admin Authentication & Control ===============
const adminOverlay = document.getElementById('adminOverlay');
const navDashboard = document.getElementById('navDashboard');
const navSettings = document.getElementById('navSettings');
const navUsers = document.getElementById('navUsers');

const sectionDashboard = document.getElementById('sectionDashboard');
const sectionSettings = document.getElementById('sectionSettings');
const sectionUsers = document.getElementById('sectionUsers');

const statUsers = document.getElementById('statUsers');
const statSuccess = document.getElementById('statSuccess');
const statFailed = document.getElementById('statFailed');
const usersTableBody = document.getElementById('usersTableBody');

const ADMIN_EMAIL_REQUIRED = "wemu20@gmail.com";

// حاجز الأمان والتحقق
async function checkAdminAuth() {
    try {
        const res = await fetch('/api/auth/me');
        const data = await res.json();
        if (!data.user || data.user.email !== ADMIN_EMAIL_REQUIRED) {
            alert("ليس لديك صلاحية.");
            window.location.href = "/";
            return;
        }
        adminOverlay.style.display = 'none';
        loadDashboardStats();
    } catch (e) {
        window.location.href = "/";
    }
}

// 2. Navigation
function activateSection(navElem, sectionElem) {
    [navDashboard, navSettings, navUsers].forEach(el => el.classList.remove('active'));
    [sectionDashboard, sectionSettings, sectionUsers].forEach(el => {
        el.classList.add('hidden');
        el.classList.remove('active');
    });
    navElem.classList.add('active');
    sectionElem.classList.remove('hidden');
    sectionElem.classList.add('active');
}

navDashboard.addEventListener('click', () => { activateSection(navDashboard, sectionDashboard); loadDashboardStats(); });
navSettings.addEventListener('click', () => activateSection(navSettings, sectionSettings));
navUsers.addEventListener('click', () => { activateSection(navUsers, sectionUsers); loadUsers(); });

// 3. Statistics Logic
async function loadDashboardStats() {
    try {
        const res = await fetch('/api/admin/stats');
        const data = await res.json();
        statUsers.innerText = data.total_users;
        statSuccess.innerText = data.total_messages;
        statFailed.innerText = data.failed_chats || 0;
    } catch (error) {
        console.error("Error loading stats.", error);
    }
}

// 4. Users List Logic
async function loadUsers() {
    try {
        usersTableBody.innerHTML = '<tr><td colspan="4" style="text-align: center;">جاري التحميل...</td></tr>';
        const res = await fetch('/api/admin/users');
        const users = await res.json();
        
        if (users.length === 0) {
            usersTableBody.innerHTML = '<tr><td colspan="4" style="text-align: center;">لا يوجد مستخدمين بعد.</td></tr>';
            return;
        }

        let html = '';
        users.forEach(u => {
            const date = u.date ? new Date(u.date).toLocaleDateString('ar-EG') : 'غير محدد';
            html += `
                <tr>
                    <td>${u.username || 'مستخدم'}</td>
                    <td>${u.email || '--'}</td>
                    <td dir="ltr" style="text-align:right;">${date}</td>
                </tr>
            `;
        });
        usersTableBody.innerHTML = html;
    } catch (error) {
        usersTableBody.innerHTML = '<tr><td colspan="4" style="text-align: center; color: red;">فشل في جلب البيانات.</td></tr>';
    }
}

checkAdminAuth();
