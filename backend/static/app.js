const API_BASE = '/api';
let currentUser = null;
let currentPage = 1;
const pageSize = 20;
let filterParams = {
    production: '',
    venue_id: '',
    status: ''
};
let venues = [];
let currentBookingId = null;
let currentWaitlistId = null;
let wlPage = 1;
let wlFilter = { production: '', venue_id: '', status: '' };

function getToken() {
    return localStorage.getItem('token');
}

function setToken(token) {
    localStorage.setItem('token', token);
}

function clearToken() {
    localStorage.removeItem('token');
}

async function apiRequest(endpoint, options = {}) {
    const headers = {
        'Content-Type': 'application/json',
        ...options.headers
    };

    const token = getToken();
    if (token) {
        headers['Authorization'] = `Bearer ${token}`;
    }

    const response = await fetch(`${API_BASE}${endpoint}`, {
        ...options,
        headers
    });

    if (response.status === 401) {
        clearToken();
        showLoginPage();
        throw new Error('未登录');
    }

    if (!response.ok) {
        let errorData;
        try {
            errorData = await response.json();
        } catch (e) {
            errorData = { detail: '请求失败' };
        }
        throw errorData;
    }

    if (response.status === 204) {
        return null;
    }

    return response.json();
}

function showToast(message, type = 'success') {
    const toast = document.getElementById('toast');
    toast.textContent = message;
    toast.className = `toast ${type}`;
    toast.style.display = 'block';

    setTimeout(() => {
        toast.style.display = 'none';
    }, 3000);
}

function formatDateTime(dt) {
    if (!dt) return '';
    const d = new Date(dt);
    return d.toLocaleString('zh-CN', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit'
    });
}

function formatDate(d) {
    if (!d) return '';
    return new Date(d).toLocaleDateString('zh-CN');
}

function getStatusText(status) {
    const map = {
        draft: '草稿',
        pending: '待审',
        confirmed: '已确认',
        rescheduling: '改期中',
        cancelled: '已取消'
    };
    return map[status] || status;
}

function getStatusClass(status) {
    return `status-${status}`;
}

function getWaitlistStatusText(status) {
    const map = {
        waiting: '排队中',
        filled: '已补位',
        cancelled: '已取消',
        expired: '已过期'
    };
    return map[status] || status;
}

function getWaitlistStatusClass(status) {
    return `wl-status-${status}`;
}

function getBlockedTypeText(t) {
    const m = { booking: '被预约挡住', closed_window: '被封场挡住', both: '预约+封场' };
    return m[t] || (t || '-');
}

function getFillMethodText(m) {
    return m === 'auto' ? '自动补位' : (m === 'manual' ? '手动补位' : (m || '-'));
}

function showLoginPage() {
    document.getElementById('login-page').style.display = 'flex';
    document.getElementById('main-app').style.display = 'none';
}

function showMainApp() {
    document.getElementById('login-page').style.display = 'none';
    document.getElementById('main-app').style.display = 'block';

    document.getElementById('user-info').innerHTML = `
        ${currentUser.full_name}
        <span class="role-badge ${currentUser.role}">${currentUser.role === 'admin' ? '管理员' : '成员'}</span>
    `;

    if (currentUser.role === 'admin') {
        document.querySelectorAll('.admin-only').forEach(el => {
            el.style.display = 'block';
        });
    } else {
        document.querySelectorAll('.admin-only').forEach(el => {
            el.style.display = 'none';
        });
    }
}

async function login(username, password) {
    const formData = new FormData();
    formData.append('username', username);
    formData.append('password', password);

    const response = await fetch(`${API_BASE}/auth/login`, {
        method: 'POST',
        body: formData
    });

    if (!response.ok) {
        throw new Error('登录失败');
    }

    const data = await response.json();
    setToken(data.access_token);
    currentUser = data.user;
    return data;
}

async function loadUserInfo() {
    try {
        const user = await apiRequest('/auth/me');
        currentUser = user;
        return user;
    } catch (e) {
        return null;
    }
}

async function loadVenues() {
    try {
        const data = await apiRequest('/venues');
        venues = data;
        renderVenueOptions();
        renderConfigVenues();
    } catch (e) {
        console.error('加载场地失败', e);
    }
}

function renderVenueOptions() {
    const filterSelect = document.getElementById('filter-venue');
    const bookingSelect = document.getElementById('booking-venue');
    const closedVenueSelect = document.getElementById('new-closed-venue');
    const windowVenueSelect = document.getElementById('new-window-venue');
    const wlFilterSelect = document.getElementById('wl-filter-venue');
    const wlVenueSelect = document.getElementById('wl-venue');

    const optionsHtml = venues.map(v => `<option value="${v.id}">${v.name}</option>`).join('');

    filterSelect.innerHTML = '<option value="">全部场地</option>' + optionsHtml;
    bookingSelect.innerHTML = '<option value="">请选择场地</option>' + optionsHtml;
    closedVenueSelect.innerHTML = '<option value="">全部场地</option>' + optionsHtml;
    if (windowVenueSelect) {
        windowVenueSelect.innerHTML = '<option value="">全部场地</option>' + optionsHtml;
    }
    if (wlFilterSelect) {
        wlFilterSelect.innerHTML = '<option value="">全部场地</option>' + optionsHtml;
    }
    if (wlVenueSelect) {
        wlVenueSelect.innerHTML = '<option value="">请选择场地</option>' + optionsHtml;
    }
}

async function loadBookings(page = 1) {
    currentPage = page;
    const params = new URLSearchParams();
    params.append('page', page);
    params.append('page_size', pageSize);

    if (filterParams.production) params.append('production', filterParams.production);
    if (filterParams.venue_id) params.append('venue_id', filterParams.venue_id);
    if (filterParams.status) params.append('status', filterParams.status);

    try {
        const data = await apiRequest(`/bookings?${params.toString()}`);
        renderBookings(data);
        renderPagination(data);
    } catch (e) {
        showToast('加载预约列表失败', 'error');
    }
}

function renderBookings(data) {
    const listEl = document.getElementById('booking-list');
    const countEl = document.getElementById('booking-count');

    countEl.textContent = `共 ${data.total} 条`;

    if (data.items.length === 0) {
        listEl.innerHTML = '<div style="text-align:center;padding:40px;color:#999;">暂无预约记录</div>';
        return;
    }

    listEl.innerHTML = data.items.map(booking => {
        let closedWindowBadge = '';
        if (booking.closed_windows && booking.closed_windows.length > 0) {
            closedWindowBadge = '<span class="status-badge status-closed-window">🚫 撞封场</span>';
        }
        return `
        <div class="booking-card" onclick="showBookingDetail(${booking.id})">
            <div class="booking-card-header">
                <span class="booking-card-title">${escapeHtml(booking.title)}</span>
                <span class="status-badge ${getStatusClass(booking.status)}">${getStatusText(booking.status)}</span>
                ${closedWindowBadge}
            </div>
            <div class="booking-card-meta">
                <span>🎬 ${escapeHtml(booking.production)}</span>
                <span>🏢 ${escapeHtml(booking.venue_name || '')}</span>
                <span>👤 ${escapeHtml(booking.user_name || '')}</span>
                <span>⏰ ${formatDateTime(booking.start_time)} ~ ${formatDateTime(booking.end_time)}</span>
                <span>⭐ 优先级: ${booking.priority}</span>
            </div>
            <div class="booking-card-actions" onclick="event.stopPropagation()">
                ${booking.status === 'draft' ? `<button class="btn btn-primary" onclick="submitBooking(${booking.id})">提交审批</button>` : ''}
                ${booking.status === 'pending' && currentUser.role === 'admin' ? `
                    <button class="btn btn-success" onclick="approveBooking(${booking.id})">通过</button>
                    <button class="btn btn-danger" onclick="rejectBooking(${booking.id})">拒绝</button>
                ` : ''}
                ${booking.status !== 'cancelled' ? `<button class="btn btn-warning" onclick="showRescheduleModal(${booking.id})">改期</button>` : ''}
                ${booking.status !== 'cancelled' && booking.status !== 'confirmed' ? `<button class="btn btn-secondary" onclick="editBooking(${booking.id})">编辑</button>` : ''}
                ${booking.status !== 'cancelled' ? `<button class="btn btn-danger" onclick="cancelBooking(${booking.id})">取消</button>` : ''}
            </div>
        </div>
    `}).join('');
}

function renderPagination(data) {
    const pagination = document.getElementById('pagination');
    const totalPages = Math.ceil(data.total / pageSize);

    if (totalPages <= 1) {
        pagination.innerHTML = '';
        return;
    }

    let html = `<button onclick="loadBookings(${currentPage - 1})" ${currentPage === 1 ? 'disabled' : ''}>上一页</button>`;

    for (let i = 1; i <= totalPages; i++) {
        if (i === 1 || i === totalPages || (i >= currentPage - 2 && i <= currentPage + 2)) {
            html += `<button class="${i === currentPage ? 'active' : ''}" onclick="loadBookings(${i})">${i}</button>`;
        } else if (i === currentPage - 3 || i === currentPage + 3) {
            html += '<span>...</span>';
        }
    }

    html += `<button onclick="loadBookings(${currentPage + 1})" ${currentPage === totalPages ? 'disabled' : ''}>下一页</button>`;

    pagination.innerHTML = html;
}

async function loadWaitlist(page = 1) {
    wlPage = page;
    const params = new URLSearchParams();
    params.append('page', page);
    params.append('page_size', pageSize);
    if (wlFilter.production) params.append('production', wlFilter.production);
    if (wlFilter.venue_id) params.append('venue_id', wlFilter.venue_id);
    if (wlFilter.status) params.append('status', wlFilter.status);

    try {
        const data = await apiRequest(`/waitlist?${params.toString()}`);
        renderWaitlist(data);
        renderWlPagination(data);
    } catch (e) {
        showToast('加载候补列表失败', 'error');
    }
}

function renderWaitlist(data) {
    const listEl = document.getElementById('waitlist-list');
    const countEl = document.getElementById('wl-count');
    countEl.textContent = `共 ${data.total} 条`;

    if (data.items.length === 0) {
        listEl.innerHTML = '<div style="text-align:center;padding:40px;color:#999;">暂无候补记录</div>';
        return;
    }

    listEl.innerHTML = data.items.map(w => {
        const queueBadge = w.status === 'waiting' && w.queue_position > 0
            ? `<span class="queue-badge">#${w.queue_position}</span>` : '';
        const floatBadge = (w.float_before_minutes || w.float_after_minutes)
            ? `<span class="status-badge wl-status-float">±${w.float_before_minutes}/${w.float_after_minutes}分钟</span>` : '';
        const blockBadge = w.blocked_by_type
            ? `<span class="status-badge wl-blocked">${getBlockedTypeText(w.blocked_by_type)}</span>` : '';

        return `
        <div class="booking-card" onclick="showWaitlistDetail(${w.id})">
            <div class="booking-card-header">
                <span class="booking-card-title">
                    ${escapeHtml(w.production)} · ${escapeHtml(w.venue_name || '')}
                    ${queueBadge}
                </span>
                <span>
                    <span class="status-badge ${getWaitlistStatusClass(w.status)}">${getWaitlistStatusText(w.status)}</span>
                    ${blockBadge}
                    ${floatBadge}
                </span>
            </div>
            <div class="booking-card-meta">
                ${w.user_name ? `<span>👤 ${escapeHtml(w.user_name)}</span>` : ''}
                <span>⏰ ${formatDateTime(w.target_start_time)} ~ ${formatDateTime(w.target_end_time)}</span>
                <span>⭐ 优先级: ${w.priority}</span>
                ${w.filled_at ? `<span>✅ ${getFillMethodText(w.filled_method)}: ${formatDateTime(w.filled_at)}</span>` : ''}
                ${w.cancelled_at ? `<span>❌ 取消: ${formatDateTime(w.cancelled_at)}</span>` : ''}
            </div>
            ${w.notes ? `<div class="booking-card-meta"><span style="color:#999;">📝 ${escapeHtml(w.notes)}</span></div>` : ''}
            <div class="booking-card-actions" onclick="event.stopPropagation()">
                ${w.status === 'waiting' ? `
                    ${currentUser.role === 'admin' ? `<button class="btn btn-success" onclick="manualFillWaitlist(${w.id})">手动补位</button>` : ''}
                    <button class="btn btn-danger" onclick="cancelWaitlist(${w.id})">取消候补</button>
                ` : ''}
                ${w.filled_booking_id ? `<button class="btn btn-outline" onclick="showBookingDetail(${w.filled_booking_id})">查看补位预约</button>` : ''}
            </div>
        </div>
    `}).join('');
}

function renderWlPagination(data) {
    const pagination = document.getElementById('wl-pagination');
    const totalPages = Math.ceil(data.total / pageSize);
    if (totalPages <= 1) { pagination.innerHTML = ''; return; }

    let html = `<button onclick="loadWaitlist(${wlPage - 1})" ${wlPage === 1 ? 'disabled' : ''}>上一页</button>`;
    for (let i = 1; i <= totalPages; i++) {
        if (i === 1 || i === totalPages || (i >= wlPage - 2 && i <= wlPage + 2)) {
            html += `<button class="${i === wlPage ? 'active' : ''}" onclick="loadWaitlist(${i})">${i}</button>`;
        } else if (i === wlPage - 3 || i === wlPage + 3) {
            html += '<span>...</span>';
        }
    }
    html += `<button onclick="loadWaitlist(${wlPage + 1})" ${wlPage === totalPages ? 'disabled' : ''}>下一页</button>`;
    pagination.innerHTML = html;
}

async function showWaitlistDetail(id) {
    try {
        const wl = await apiRequest(`/waitlist/${id}`);
        currentWaitlistId = id;
        let logsHtml = '';
        try {
            const logs = await apiRequest(`/waitlist/${id}/logs`);
            if (logs && logs.length > 0) {
                logsHtml = `
                <div class="detail-section">
                    <h3>📜 操作日志 (${logs.length})</h3>
                    <div style="font-size:13px;">
                        ${logs.map(log => `
                            <div class="conflict-item" style="margin-bottom:6px;background:#fafafa;">
                                <div class="conflict-item-title" style="color:#333;">
                                    [${formatDateTime(log.created_at)}] ${escapeHtml(log.action || '')}
                                    ${log.trigger_reason ? `<span style="color:#888;font-size:12px;">触发: ${escapeHtml(log.trigger_reason)}</span>` : ''}
                                </div>
                                <div class="conflict-item-meta">
                                    ${log.operator_name ? `操作人: ${escapeHtml(log.operator_name)}` : ''}
                                    ${log.result_booking_id ? ` · 生成预约ID: ${log.result_booking_id}` : ''}
                                    <br>
                                    ${log.blocked_by_snapshot ? `原被挡: ${escapeHtml(log.blocked_by_snapshot)}<br>` : ''}
                                    ${log.notes ? `说明: ${escapeHtml(log.notes)}` : ''}
                                </div>
                            </div>
                        `).join('')}
                    </div>
                </div>`;
            }
        } catch (e) { /* noop */ }

        let blockHtml = '';
        if (wl.blocked_by_type || wl.blocked_by_details) {
            blockHtml = `
            <div class="detail-section">
                <h3>🚫 被挡详情</h3>
                <div class="detail-row">
                    <span class="detail-label">被挡类型</span>
                    <span class="detail-value">${getBlockedTypeText(wl.blocked_by_type)}</span>
                </div>
                ${wl.blocked_by_details ? `
                <div class="detail-row">
                    <span class="detail-label">详细快照</span>
                    <span class="detail-value" style="word-break:break-all;font-size:12px;color:#555;">
                        <pre style="white-space:pre-wrap;background:#f7f7f7;padding:8px;border-radius:4px;">${escapeHtml(wl.blocked_by_details)}</pre>
                    </span>
                </div>` : ''}
            </div>`;
        }

        let fillHtml = '';
        if (wl.status === 'filled') {
            fillHtml = `
            <div class="detail-section">
                <h3>✅ 补位结果</h3>
                <div class="detail-row">
                    <span class="detail-label">补位方式</span>
                    <span class="detail-value">${getFillMethodText(wl.filled_method)}</span>
                </div>
                <div class="detail-row">
                    <span class="detail-label">补位时间</span>
                    <span class="detail-value">${formatDateTime(wl.filled_at)}</span>
                </div>
                ${wl.filled_booking_id ? `
                <div class="detail-row">
                    <span class="detail-label">关联预约</span>
                    <span class="detail-value"><a style="color:#667eea;cursor:pointer;" onclick="showBookingDetail(${wl.filled_booking_id});closeModal('waitlist-detail-modal');">#${wl.filled_booking_id} 查看详情</a></span>
                </div>` : ''}
            </div>`;
        }

        let cancelHtml = '';
        if (wl.status === 'cancelled') {
            cancelHtml = `
            <div class="detail-section">
                <h3>❌ 取消信息</h3>
                <div class="detail-row"><span class="detail-label">操作人</span><span class="detail-value">${escapeHtml(wl.cancelled_by_name || '-')}</span></div>
                <div class="detail-row"><span class="detail-label">取消时间</span><span class="detail-value">${formatDateTime(wl.cancelled_at)}</span></div>
                ${wl.cancel_reason ? `<div class="detail-row"><span class="detail-label">原因</span><span class="detail-value">${escapeHtml(wl.cancel_reason)}</span></div>` : ''}
            </div>`;
        }

        document.getElementById('wl-detail-title').textContent = `${wl.production} · ${wl.venue_name || ''} 候补详情`;
        document.getElementById('wl-detail-body').innerHTML = `
            <div class="detail-section">
                <h3>基本信息</h3>
                <div class="detail-row">
                    <span class="detail-label">状态</span>
                    <span class="detail-value"><span class="status-badge ${getWaitlistStatusClass(wl.status)}">${getWaitlistStatusText(wl.status)}</span></span>
                </div>
                ${wl.queue_position ? `<div class="detail-row"><span class="detail-label">排队号</span><span class="detail-value">#${wl.queue_position}</span></div>` : ''}
                <div class="detail-row"><span class="detail-label">剧目</span><span class="detail-value">${escapeHtml(wl.production)}</span></div>
                <div class="detail-row"><span class="detail-label">场地</span><span class="detail-value">${escapeHtml(wl.venue_name || '')}</span></div>
                ${wl.user_name ? `<div class="detail-row"><span class="detail-label">申请人</span><span class="detail-value">${escapeHtml(wl.user_name)}</span></div>` : ''}
                <div class="detail-row"><span class="detail-label">目标时段</span><span class="detail-value">${formatDateTime(wl.target_start_time)} ~ ${formatDateTime(wl.target_end_time)}</span></div>
                <div class="detail-row"><span class="detail-label">浮动范围</span><span class="detail-value">前 ${wl.float_before_minutes} 分钟 / 后 ${wl.float_after_minutes} 分钟</span></div>
                <div class="detail-row"><span class="detail-label">优先级</span><span class="detail-value">${wl.priority}</span></div>
                <div class="detail-row"><span class="detail-label">过期时间</span><span class="detail-value">${formatDateTime(wl.expires_at)}</span></div>
                ${wl.notes ? `<div class="detail-row"><span class="detail-label">备注</span><span class="detail-value">${escapeHtml(wl.notes)}</span></div>` : ''}
            </div>
            ${blockHtml}
            ${fillHtml}
            ${cancelHtml}
            ${logsHtml}
            <div class="detail-section">
                <h3>版本信息</h3>
                <div class="detail-row"><span class="detail-label">创建时间</span><span class="detail-value">${formatDateTime(wl.created_at)}</span></div>
                <div class="detail-row"><span class="detail-label">更新时间</span><span class="detail-value">${formatDateTime(wl.updated_at)}</span></div>
            </div>
        `;

        let footer = '';
        if (wl.status === 'waiting') {
            if (currentUser.role === 'admin') {
                footer += `<button class="btn btn-success" onclick="manualFillWaitlist(${wl.id});closeModal('waitlist-detail-modal');">手动补位</button>`;
            }
            footer += `<button class="btn btn-danger" onclick="cancelWaitlist(${wl.id});closeModal('waitlist-detail-modal');">取消候补</button>`;
        }
        if (wl.filled_booking_id) {
            footer += `<button class="btn btn-outline" onclick="showBookingDetail(${wl.filled_booking_id});closeModal('waitlist-detail-modal');">查看补位预约</button>`;
        }
        footer += '<button class="btn btn-outline modal-close-btn">关闭</button>';
        document.getElementById('wl-detail-footer').innerHTML = footer;
        document.getElementById('waitlist-detail-modal').style.display = 'flex';
    } catch (e) {
        handleApiError(e);
    }
}

function openWaitlistCreateModal() {
    document.getElementById('wl-production').value = '';
    const venSel = document.getElementById('wl-venue');
    if (venSel) venSel.value = venues[0] ? venues[0].id : '';
    document.getElementById('wl-start').value = '';
    document.getElementById('wl-end').value = '';
    document.getElementById('wl-before').value = '60';
    document.getElementById('wl-after').value = '60';
    document.getElementById('wl-priority').value = '10';
    document.getElementById('wl-notes').value = '';
    document.getElementById('wl-create-warn').style.display = 'none';
    document.getElementById('waitlist-create-modal').style.display = 'flex';
}

async function submitWaitlistCreate() {
    const production = document.getElementById('wl-production').value.trim();
    const venue_id = document.getElementById('wl-venue').value;
    const start = document.getElementById('wl-start').value;
    const end = document.getElementById('wl-end').value;
    const before = parseInt(document.getElementById('wl-before').value) || 0;
    const after = parseInt(document.getElementById('wl-after').value) || 0;
    const priority = parseInt(document.getElementById('wl-priority').value) || 10;
    const notes = document.getElementById('wl-notes').value.trim();

    if (!production || !venue_id || !start || !end) {
        showToast('请填写必填项', 'warning');
        return;
    }
    if (new Date(start) >= new Date(end)) {
        showToast('结束时间必须晚于开始时间', 'warning');
        return;
    }

    try {
        await apiRequest('/waitlist', {
            method: 'POST',
            body: JSON.stringify({
                title: production,
                production,
                venue_id: parseInt(venue_id),
                target_start_time: start + ':00',
                target_end_time: end + ':00',
                float_before_minutes: before,
                float_after_minutes: after,
                priority,
                notes
            })
        });
        showToast('候补登记成功');
        closeModal('waitlist-create-modal');
        loadWaitlist(1);
    } catch (e) {
        const warnEl = document.getElementById('wl-create-warn');
        let msg = '操作失败';
        if (typeof e.detail === 'string') {
            msg = e.detail;
        } else if (Array.isArray(e.detail)) {
            msg = e.detail.map(d => d.msg || d.message || JSON.stringify(d)).join('; ');
        } else if (e.detail && e.detail.message) {
            msg = e.detail.message;
        }
        warnEl.innerHTML = `<h3>⚠️ ${escapeHtml(msg)}</h3><div style="font-size:12px;color:#666;">请调整时段或联系管理员</div>`;
        warnEl.style.display = 'block';
    }
}

async function cancelWaitlist(id) {
    if (!confirm('确定取消此候补？')) return;
    try {
        await apiRequest(`/waitlist/${id}`, { method: 'DELETE' });
        showToast('已取消候补');
        loadWaitlist(wlPage);
    } catch (e) { handleApiError(e); }
}

async function manualFillWaitlist(id) {
    if (!confirm('确定手动补位此候补？系统会创建草稿预约并校验冲突。')) return;
    try {
        const r = await apiRequest(`/waitlist/${id}/fill`, { method: 'POST' });
        if (r && r.success) {
            showToast('手动补位成功，已生成草稿预约');
        } else {
            showToast('补位失败：' + ((r && r.message) || '时段仍冲突'), 'error');
        }
        loadWaitlist(wlPage);
    } catch (e) { handleApiError(e); }
}

function exportWaitlistCSV() {
    const token = getToken();
    fetch(`${API_BASE}/exports/waitlist.csv`, {
        headers: { 'Authorization': `Bearer ${token}` }
    })
    .then(async response => {
        if (!response.ok) {
            const txt = await response.text().catch(() => '');
            throw new Error('导出失败 ' + response.status + ' ' + txt.slice(0, 100));
        }
        return response.blob();
    })
    .then(blob => {
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `waitlist_${Date.now()}.csv`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);
        showToast('导出成功');
    })
    .catch(err => {
        showToast(err.message || '导出失败', 'error');
    });
}

async function showBookingDetail(id) {
    try {
        const booking = await apiRequest(`/bookings/${id}`);
        const history = await apiRequest(`/bookings/${id}/reschedule-history`);

        currentBookingId = id;

        let conflictsHtml = '';
        if (booking.conflicts && booking.conflicts.length > 0) {
            conflictsHtml = `
                <div class="detail-section">
                    <h3>⚠️ 冲突预约</h3>
                    ${booking.conflicts.map(c => `
                        <div class="conflict-item">
                            <div class="conflict-item-title">${escapeHtml(c.title)}</div>
                            <div class="conflict-item-meta">
                                🎬 ${escapeHtml(c.production)} | 👤 ${escapeHtml(c.user_name)}<br>
                                ⏰ ${formatDateTime(c.start_time)} ~ ${formatDateTime(c.end_time)}
                            </div>
                        </div>
                    `).join('')}
                </div>
            `;
        }

        let closedWindowsHtml = '';
        if (booking.closed_windows && booking.closed_windows.length > 0) {
            closedWindowsHtml = `
                <div class="detail-section">
                    <h3>🚫 命中封场窗口</h3>
                    ${booking.closed_windows.map(w => `
                        <div class="conflict-item">
                            <div class="conflict-item-title">${escapeHtml(w.venue_name || '全部场地')}</div>
                            <div class="conflict-item-meta">
                                ⏰ ${formatDateTime(w.start_time)} ~ ${formatDateTime(w.end_time)}<br>
                                📝 原因: ${escapeHtml(w.reason || '封场')}
                            </div>
                        </div>
                    `).join('')}
                </div>
            `;
        }

        let historyHtml = '';
        if (history && history.length > 0) {
            historyHtml = `
                <div class="detail-section">
                    <h3>📝 改期记录</h3>
                    <ul class="reschedule-list">
                        ${history.map(h => `
                            <li>
                                <div class="reschedule-time">
                                    原时段: ${formatDateTime(h.original_start_time)} ~ ${formatDateTime(h.original_end_time)}
                                </div>
                                <div class="reschedule-time">
                                    新时段: ${formatDateTime(h.new_start_time)} ~ ${formatDateTime(h.new_end_time)}
                                </div>
                                <div class="reschedule-reason">原因: ${escapeHtml(h.reason)}</div>
                                <div class="reschedule-operator">操作人: ${escapeHtml(h.operator_name || '')} | ${formatDateTime(h.created_at)}</div>
                            </li>
                        `).join('')}
                    </ul>
                </div>
            `;
        }

        document.getElementById('detail-title').textContent = booking.title;
        document.getElementById('detail-body').innerHTML = `
            <div class="detail-section">
                <h3>基本信息</h3>
                <div class="detail-row">
                    <span class="detail-label">状态</span>
                    <span class="detail-value"><span class="status-badge ${getStatusClass(booking.status)}">${getStatusText(booking.status)}</span></span>
                </div>
                <div class="detail-row">
                    <span class="detail-label">剧目</span>
                    <span class="detail-value">${escapeHtml(booking.production)}</span>
                </div>
                <div class="detail-row">
                    <span class="detail-label">场地</span>
                    <span class="detail-value">${escapeHtml(booking.venue_name || '')}</span>
                </div>
                <div class="detail-row">
                    <span class="detail-label">申请人</span>
                    <span class="detail-value">${escapeHtml(booking.user_name || '')}</span>
                </div>
                <div class="detail-row">
                    <span class="detail-label">开始时间</span>
                    <span class="detail-value">${formatDateTime(booking.start_time)}</span>
                </div>
                <div class="detail-row">
                    <span class="detail-label">结束时间</span>
                    <span class="detail-value">${formatDateTime(booking.end_time)}</span>
                </div>
                <div class="detail-row">
                    <span class="detail-label">优先级</span>
                    <span class="detail-value">${booking.priority}</span>
                </div>
            </div>

            ${booking.notes ? `
            <div class="detail-section">
                <h3>备注</h3>
                <p>${escapeHtml(booking.notes)}</p>
            </div>
            ` : ''}

            ${booking.rejection_reason ? `
            <div class="detail-section">
                <h3>拒绝/取消原因</h3>
                <p>${escapeHtml(booking.rejection_reason)}</p>
            </div>
            ` : ''}

            ${booking.approver_name ? `
            <div class="detail-section">
                <h3>审批信息</h3>
                <div class="detail-row">
                    <span class="detail-label">审批人</span>
                    <span class="detail-value">${escapeHtml(booking.approver_name)}</span>
                </div>
                <div class="detail-row">
                    <span class="detail-label">审批时间</span>
                    <span class="detail-value">${formatDateTime(booking.approved_at)}</span>
                </div>
            </div>
            ` : ''}

            ${conflictsHtml}
            ${closedWindowsHtml}
            ${historyHtml}

            <div class="detail-section">
                <h3>版本信息</h3>
                <div class="detail-row">
                    <span class="detail-label">当前版本</span>
                    <span class="detail-value">${booking.version}</span>
                </div>
                <div class="detail-row">
                    <span class="detail-label">创建时间</span>
                    <span class="detail-value">${formatDateTime(booking.created_at)}</span>
                </div>
                <div class="detail-row">
                    <span class="detail-label">更新时间</span>
                    <span class="detail-value">${formatDateTime(booking.updated_at)}</span>
                </div>
            </div>
        `;

        let footerHtml = '';
        if (booking.status === 'draft') {
            footerHtml += '<button class="btn btn-primary" onclick="submitBooking(' + booking.id + ')">提交审批</button>';
        }
        if (booking.status === 'pending' && currentUser.role === 'admin') {
            footerHtml += '<button class="btn btn-success" onclick="approveBooking(' + booking.id + ')">通过</button>';
            footerHtml += '<button class="btn btn-danger" onclick="rejectBooking(' + booking.id + ')">拒绝</button>';
        }
        if (booking.status !== 'cancelled') {
            footerHtml += '<button class="btn btn-warning" onclick="showRescheduleModal(' + booking.id + ')">改期</button>';
        }
        if (booking.status !== 'cancelled' && booking.status !== 'confirmed') {
            footerHtml += '<button class="btn btn-secondary" onclick="editBooking(' + booking.id + ')">编辑</button>';
        }
        if (booking.status !== 'cancelled') {
            footerHtml += '<button class="btn btn-danger" onclick="cancelBooking(' + booking.id + ')">取消</button>';
        }
        footerHtml += '<button class="btn btn-outline modal-close-btn">关闭</button>';

        document.getElementById('detail-footer').innerHTML = footerHtml;
        document.getElementById('booking-detail-modal').style.display = 'flex';
    } catch (e) {
        showToast('加载详情失败', 'error');
    }
}

function editBooking(id) {
    apiRequest(`/bookings/${id}`).then(booking => {
        document.getElementById('booking-id').value = booking.id;
        document.getElementById('booking-version').value = booking.version;
        document.getElementById('booking-title').value = booking.title;
        document.getElementById('booking-production').value = booking.production;
        document.getElementById('booking-venue').value = booking.venue_id;
        document.getElementById('booking-priority').value = booking.priority;
        document.getElementById('booking-start').value = formatDateTimeLocal(booking.start_time);
        document.getElementById('booking-end').value = formatDateTimeLocal(booking.end_time);
        document.getElementById('booking-notes').value = booking.notes || '';
        document.getElementById('form-title').textContent = '编辑预约';

        switchTab('new-booking');
        closeModal('booking-detail-modal');
    }).catch(() => {
        showToast('加载预约失败', 'error');
    });
}

function formatDateTimeLocal(dt) {
    if (!dt) return '';
    const d = new Date(dt);
    const year = d.getFullYear();
    const month = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    const hours = String(d.getHours()).padStart(2, '0');
    const minutes = String(d.getMinutes()).padStart(2, '0');
    return `${year}-${month}-${day}T${hours}:${minutes}`;
}

async function submitBooking(id) {
    if (!confirm('确定要提交审批吗？')) return;

    try {
        const booking = await apiRequest(`/bookings/${id}`);
        const result = await apiRequest(`/bookings/${id}/status`, {
            method: 'PATCH',
            body: JSON.stringify({
                status: 'pending',
                version: booking.version
            })
        });
        showToast('提交成功，等待审批');
        loadBookings(currentPage);
        closeModal('booking-detail-modal');
    } catch (e) {
        handleApiError(e);
    }
}

async function approveBooking(id) {
    if (!confirm('确定要通过此预约吗？')) return;

    try {
        const booking = await apiRequest(`/bookings/${id}`);
        const result = await apiRequest(`/bookings/${id}/status`, {
            method: 'PATCH',
            body: JSON.stringify({
                status: 'confirmed',
                version: booking.version
            })
        });
        showToast('审批通过');
        loadBookings(currentPage);
        closeModal('booking-detail-modal');
    } catch (e) {
        handleApiError(e);
    }
}

async function rejectBooking(id) {
    const reason = prompt('请输入拒绝原因：');
    if (reason === null) return;

    try {
        const booking = await apiRequest(`/bookings/${id}`);
        const result = await apiRequest(`/bookings/${id}/status`, {
            method: 'PATCH',
            body: JSON.stringify({
                status: 'cancelled',
                rejection_reason: reason,
                version: booking.version
            })
        });
        showToast('已拒绝');
        loadBookings(currentPage);
        closeModal('booking-detail-modal');
    } catch (e) {
        handleApiError(e);
    }
}

async function cancelBooking(id) {
    const reason = prompt('请输入取消原因（可选）：') || '';
    if (reason === null) return;

    try {
        const booking = await apiRequest(`/bookings/${id}`);
        const result = await apiRequest(`/bookings/${id}/status`, {
            method: 'PATCH',
            body: JSON.stringify({
                status: 'cancelled',
                rejection_reason: reason,
                version: booking.version
            })
        });
        showToast('已取消');
        loadBookings(currentPage);
        closeModal('booking-detail-modal');
    } catch (e) {
        handleApiError(e);
    }
}

function showRescheduleModal(id) {
    currentBookingId = id;
    apiRequest(`/bookings/${id}`).then(booking => {
        document.getElementById('reschedule-original').value =
            `${formatDateTime(booking.start_time)} ~ ${formatDateTime(booking.end_time)}`;
        document.getElementById('reschedule-start').value = '';
        document.getElementById('reschedule-end').value = '';
        document.getElementById('reschedule-reason').value = '';
        document.getElementById('reschedule-conflict').style.display = 'none';
        document.getElementById('reschedule-modal').style.display = 'flex';
        closeModal('booking-detail-modal');
    }).catch(() => {
        showToast('加载预约失败', 'error');
    });
}

async function submitReschedule() {
    const startTime = document.getElementById('reschedule-start').value;
    const endTime = document.getElementById('reschedule-end').value;
    const reason = document.getElementById('reschedule-reason').value;

    if (!startTime || !endTime || !reason) {
        showToast('请填写完整信息', 'warning');
        return;
    }

    try {
        const booking = await apiRequest(`/bookings/${currentBookingId}`);
        const result = await apiRequest(`/bookings/${currentBookingId}/reschedule`, {
            method: 'POST',
            body: JSON.stringify({
                new_start_time: new Date(startTime).toISOString(),
                new_end_time: new Date(endTime).toISOString(),
                reason: reason,
                version: booking.version
            })
        });
        showToast('改期申请已提交，需重新审批');
        loadBookings(currentPage);
        closeModal('reschedule-modal');
    } catch (e) {
        handleApiError(e);
    }
}

function handleApiError(error) {
    let message = '操作失败';
    if (typeof error.detail === 'string') {
        message = error.detail;
    } else if (error.detail && error.detail.message) {
        message = error.detail.message;
        if (error.detail.conflicts && error.detail.conflicts.length > 0) {
            message += '：存在时间冲突';
        }
        if (error.detail.closed_dates && error.detail.closed_dates.length > 0) {
            message += '：包含封场日期';
        }
        if (error.detail.closed_windows && error.detail.closed_windows.length > 0) {
            message += '（撞上封场窗口）';
        }
    }
    showToast(message, 'error');
}

async function checkBookingConflicts() {
    const venueId = document.getElementById('booking-venue').value;
    const startTime = document.getElementById('booking-start').value;
    const endTime = document.getElementById('booking-end').value;
    const bookingId = document.getElementById('booking-id').value;

    if (!venueId || !startTime || !endTime) {
        showToast('请先选择场地和时间', 'warning');
        return;
    }

    const params = new URLSearchParams();
    params.append('venue_id', venueId);
    params.append('start_time', new Date(startTime).toISOString());
    params.append('end_time', new Date(endTime).toISOString());
    if (bookingId) params.append('exclude_booking_id', bookingId);

    try {
        const result = await apiRequest(`/bookings/check-conflicts?${params.toString()}`);
        const warningEl = document.getElementById('conflict-warning');
        const detailsEl = document.getElementById('conflict-details');

        if (!result.valid) {
            let html = '';
            if (result.conflicts && result.conflicts.length > 0) {
                html += '<h4>以下预约与你的时段冲突：</h4>';
                html += result.conflicts.map(c => `
                    <div class="conflict-item">
                        <div class="conflict-item-title">${escapeHtml(c.title)}</div>
                        <div class="conflict-item-meta">
                            🎬 ${escapeHtml(c.production)} | 👤 ${escapeHtml(c.user_name)}<br>
                            ⏰ ${formatDateTime(c.start_time)} ~ ${formatDateTime(c.end_time)}
                        </div>
                    </div>
                `).join('');
            }
            if (result.closed_dates && result.closed_dates.length > 0) {
                html += '<h4>包含以下封场日期：</h4>';
                html += '<ul style="margin-left:20px;">' + result.closed_dates.map(d => `<li>${d}</li>`).join('') + '</ul>';
            }
            if (result.closed_windows && result.closed_windows.length > 0) {
                html += '<h4>🚫 撞上以下封场窗口：</h4>';
                html += result.closed_windows.map(w => `
                    <div class="conflict-item">
                        <div class="conflict-item-title">${escapeHtml(w.venue_name || '全部场地')}</div>
                        <div class="conflict-item-meta">
                            ⏰ ${formatDateTime(w.start_time)} ~ ${formatDateTime(w.end_time)}<br>
                            📝 原因: ${escapeHtml(w.reason || '封场')}
                        </div>
                    </div>
                `).join('');
            }
            detailsEl.innerHTML = html;
            warningEl.style.display = 'block';
        } else {
            warningEl.style.display = 'none';
            showToast('暂无冲突，可以预约', 'success');
        }
    } catch (e) {
        showToast('检测失败', 'error');
    }
}

async function loadProductions() {
    try {
        const data = await apiRequest('/bookings/productions/list');
        const datalist = document.getElementById('production-list');
        datalist.innerHTML = data.map(p => `<option value="${escapeHtml(p)}">`).join('');
    } catch (e) {
        console.error('加载剧目列表失败', e);
    }
}

async function saveBooking(asDraft = false) {
    const id = document.getElementById('booking-id').value;
    const title = document.getElementById('booking-title').value;
    const production = document.getElementById('booking-production').value;
    const venueId = document.getElementById('booking-venue').value;
    const priority = document.getElementById('booking-priority').value;
    const startTime = document.getElementById('booking-start').value;
    const endTime = document.getElementById('booking-end').value;
    const notes = document.getElementById('booking-notes').value;
    const version = document.getElementById('booking-version').value;

    if (!title || !production || !venueId || !startTime || !endTime) {
        showToast('请填写必填项', 'warning');
        return false;
    }

    const bookingData = {
        title,
        production,
        venue_id: parseInt(venueId),
        start_time: new Date(startTime).toISOString(),
        end_time: new Date(endTime).toISOString(),
        priority: parseInt(priority),
        notes
    };

    try {
        let result;
        if (id) {
            bookingData.version = parseInt(version);
            result = await apiRequest(`/bookings/${id}`, {
                method: 'PUT',
                body: JSON.stringify(bookingData)
            });

            if (!asDraft && bookingData.status !== 'pending') {
                result = await apiRequest(`/bookings/${id}/status`, {
                    method: 'PATCH',
                    body: JSON.stringify({
                        status: 'pending',
                        version: result.version
                    })
                });
            }
        } else {
            bookingData.status = asDraft ? 'draft' : 'pending';
            result = await apiRequest('/bookings', {
                method: 'POST',
                body: JSON.stringify(bookingData)
            });
        }

        showToast(asDraft ? '草稿已保存' : '预约已提交审批', 'success');
        resetBookingForm();
        switchTab('bookings');
        loadBookings(1);
        return true;
    } catch (e) {
        handleApiError(e);
        return false;
    }
}

function resetBookingForm() {
    document.getElementById('booking-id').value = '';
    document.getElementById('booking-version').value = '';
    document.getElementById('booking-title').value = '';
    document.getElementById('booking-production').value = '';
    document.getElementById('booking-venue').value = '';
    document.getElementById('booking-priority').value = '10';
    document.getElementById('booking-start').value = '';
    document.getElementById('booking-end').value = '';
    document.getElementById('booking-notes').value = '';
    document.getElementById('conflict-warning').style.display = 'none';
    document.getElementById('form-title').textContent = '新建预约';
}

async function loadConfig() {
    await loadClosedDates();
    await loadClosedWindows();
    await loadPriorityRules();
}

async function loadClosedWindows() {
    try {
        const data = await apiRequest('/config/closed-windows');
        renderClosedWindows(data);
    } catch (e) {
        console.error('加载封场窗口失败', e);
    }
}

function renderClosedWindows(windows) {
    const listEl = document.getElementById('closed-window-list');
    if (!listEl) return;
    if (windows.length === 0) {
        listEl.innerHTML = '<div style="color:#999;font-size:13px;">暂无临时封场窗口</div>';
        return;
    }

    listEl.innerHTML = windows.map(w => {
        const venueText = w.venue ? w.venue.name : '全部场地';
        const revokedClass = w.is_revoked ? 'config-item-revoked' : '';
        const revokedBadge = w.is_revoked ? '<span class="status-badge status-cancelled">已撤销</span>' : '';
        return `
        <div class="config-item ${revokedClass}">
            <div>
                <div class="config-item-name">
                    ${formatDateTime(w.start_time)} ~ ${formatDateTime(w.end_time)}
                    ${revokedBadge}
                </div>
                <div class="config-item-desc">
                    ${venueText} | ${escapeHtml(w.reason || '')}
                    ${w.created_by_name ? ` | 创建人: ${escapeHtml(w.created_by_name)}` : ''}
                    ${w.revoked_by_name ? ` | 撤销人: ${escapeHtml(w.revoked_by_name)}` : ''}
                </div>
            </div>
            ${!w.is_revoked && currentUser.role === 'admin' ? `
                <button class="btn btn-danger" style="padding:4px 10px;font-size:12px;" onclick="revokeClosedWindow(${w.id})">撤销</button>
            ` : ''}
        </div>
    `}).join('');
}

async function addClosedWindow() {
    const venueId = document.getElementById('new-window-venue').value;
    const startTime = document.getElementById('new-window-start').value;
    const endTime = document.getElementById('new-window-end').value;
    const reason = document.getElementById('new-window-reason').value;

    if (!startTime || !endTime) {
        showToast('请选择开始和结束时间', 'warning');
        return;
    }

    try {
        await apiRequest('/config/closed-windows', {
            method: 'POST',
            body: JSON.stringify({
                venue_id: venueId ? parseInt(venueId) : null,
                start_time: new Date(startTime).toISOString(),
                end_time: new Date(endTime).toISOString(),
                reason: reason,
                apply_all_venues: !venueId
            })
        });
        showToast('添加成功');
        document.getElementById('new-window-start').value = '';
        document.getElementById('new-window-end').value = '';
        document.getElementById('new-window-reason').value = '';
        loadClosedWindows();
    } catch (e) {
        handleApiError(e);
    }
}

async function revokeClosedWindow(id) {
    if (!confirm('确定撤销此封场窗口吗？撤销后该时段可重新预约。')) return;
    try {
        await apiRequest(`/config/closed-windows/${id}`, { method: 'DELETE' });
        showToast('已撤销');
        loadClosedWindows();
    } catch (e) {
        handleApiError(e);
    }
}

async function loadClosedDates() {
    try {
        const data = await apiRequest('/config/closed-dates');
        renderClosedDates(data);
    } catch (e) {
        console.error('加载封场日期失败', e);
    }
}

function renderClosedDates(dates) {
    const listEl = document.getElementById('closed-date-list');
    if (dates.length === 0) {
        listEl.innerHTML = '<div style="color:#999;font-size:13px;">暂无封场日期</div>';
        return;
    }

    listEl.innerHTML = dates.map(d => `
        <div class="config-item">
            <div>
                <div class="config-item-name">${formatDate(d.date)}</div>
                <div class="config-item-desc">
                    ${d.venue ? d.venue.name : '全部场地'} | ${escapeHtml(d.reason || '')}
                </div>
            </div>
            <button class="btn btn-danger" style="padding:4px 10px;font-size:12px;" onclick="deleteClosedDate(${d.id})">删除</button>
        </div>
    `).join('');
}

async function addClosedDate() {
    const date = document.getElementById('new-closed-date').value;
    const venueId = document.getElementById('new-closed-venue').value;
    const reason = document.getElementById('new-closed-reason').value;

    if (!date) {
        showToast('请选择日期', 'warning');
        return;
    }

    try {
        await apiRequest('/config/closed-dates', {
            method: 'POST',
            body: JSON.stringify({
                date: date,
                venue_id: venueId ? parseInt(venueId) : null,
                reason: reason
            })
        });
        showToast('添加成功');
        document.getElementById('new-closed-date').value = '';
        document.getElementById('new-closed-reason').value = '';
        loadClosedDates();
    } catch (e) {
        handleApiError(e);
    }
}

async function deleteClosedDate(id) {
    if (!confirm('确定删除此封场日期吗？')) return;
    try {
        await apiRequest(`/config/closed-dates/${id}`, { method: 'DELETE' });
        showToast('删除成功');
        loadClosedDates();
    } catch (e) {
        handleApiError(e);
    }
}

async function loadPriorityRules() {
    try {
        const data = await apiRequest('/config/priority-rules');
        renderPriorityRules(data);
    } catch (e) {
        console.error('加载优先级规则失败', e);
    }
}

function renderPriorityRules(rules) {
    const listEl = document.getElementById('priority-list');
    if (rules.length === 0) {
        listEl.innerHTML = '<div style="color:#999;font-size:13px;">暂无优先级规则</div>';
        return;
    }

    listEl.innerHTML = rules.map(r => `
        <div class="config-item">
            <div>
                <div class="config-item-name">${escapeHtml(r.name)} (优先级: ${r.priority_level})</div>
                <div class="config-item-desc">${escapeHtml(r.description || '')}</div>
            </div>
        </div>
    `).join('');
}

function renderConfigVenues() {
    const listEl = document.getElementById('venue-list');
    if (venues.length === 0) {
        listEl.innerHTML = '<div style="color:#999;font-size:13px;">暂无场地</div>';
        return;
    }

    listEl.innerHTML = venues.map(v => `
        <div class="config-item">
            <div>
                <div class="config-item-name">${escapeHtml(v.name)}</div>
                <div class="config-item-desc">${escapeHtml(v.description || '')} | 容量: ${v.capacity}人</div>
            </div>
        </div>
    `).join('');
}

function exportCSV() {
    const params = new URLSearchParams();
    if (filterParams.production) params.append('production', filterParams.production);
    if (filterParams.venue_id) params.append('venue_id', filterParams.venue_id);
    if (filterParams.status) params.append('status', filterParams.status);

    const token = getToken();
    const url = `${API_BASE}/exports/bookings.csv?${params.toString()}`;

    fetch(url, {
        headers: { 'Authorization': `Bearer ${token}` }
    })
    .then(response => response.blob())
    .then(blob => {
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `bookings_${Date.now()}.csv`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);
        showToast('导出成功');
    })
    .catch(() => {
        showToast('导出失败', 'error');
    });
}

function switchTab(tabName) {
    document.querySelectorAll('.nav-tab').forEach(tab => {
        tab.classList.toggle('active', tab.dataset.tab === tabName);
    });

    document.querySelectorAll('.tab-content').forEach(content => {
        content.classList.toggle('active', content.id === `tab-${tabName}`);
    });

    if (tabName === 'bookings') {
        loadBookings(1);
    } else if (tabName === 'waitlist') {
        loadWaitlist(1);
    } else if (tabName === 'config') {
        loadConfig();
    } else if (tabName === 'new-booking') {
        if (!document.getElementById('booking-id').value) {
            resetBookingForm();
        }
        loadProductions();
    }
}

function closeModal(modalId) {
    document.getElementById(modalId).style.display = 'none';
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('login-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        const username = document.getElementById('username').value;
        const password = document.getElementById('password').value;

        try {
            await login(username, password);
            await loadUserInfo();
            showMainApp();
            await loadVenues();
            loadBookings(1);
        } catch (e) {
            showToast('登录失败，请检查用户名和密码', 'error');
        }
    });

    document.getElementById('logout-btn').addEventListener('click', () => {
        clearToken();
        currentUser = null;
        showLoginPage();
    });

    document.querySelectorAll('.nav-tab').forEach(tab => {
        tab.addEventListener('click', () => {
            switchTab(tab.dataset.tab);
        });
    });

    document.getElementById('search-btn').addEventListener('click', () => {
        filterParams.production = document.getElementById('filter-production').value;
        filterParams.venue_id = document.getElementById('filter-venue').value;
        filterParams.status = document.getElementById('filter-status').value;
        loadBookings(1);
    });

    document.getElementById('reset-btn').addEventListener('click', () => {
        document.getElementById('filter-production').value = '';
        document.getElementById('filter-venue').value = '';
        document.getElementById('filter-status').value = '';
        filterParams = { production: '', venue_id: '', status: '' };
        loadBookings(1);
    });

    document.getElementById('export-btn').addEventListener('click', exportCSV);

    const wlSearchBtn = document.getElementById('wl-search-btn');
    if (wlSearchBtn) {
        wlSearchBtn.addEventListener('click', () => {
            wlFilter.production = document.getElementById('wl-filter-production').value;
            wlFilter.venue_id = document.getElementById('wl-filter-venue').value;
            wlFilter.status = document.getElementById('wl-filter-status').value;
            loadWaitlist(1);
        });
    }
    const wlResetBtn = document.getElementById('wl-reset-btn');
    if (wlResetBtn) {
        wlResetBtn.addEventListener('click', () => {
            document.getElementById('wl-filter-production').value = '';
            document.getElementById('wl-filter-venue').value = '';
            document.getElementById('wl-filter-status').value = '';
            wlFilter = { production: '', venue_id: '', status: '' };
            loadWaitlist(1);
        });
    }
    const wlCreateBtn = document.getElementById('wl-create-btn');
    if (wlCreateBtn) wlCreateBtn.addEventListener('click', openWaitlistCreateModal);

    const wlExportBtn = document.getElementById('wl-export-btn');
    if (wlExportBtn) wlExportBtn.addEventListener('click', exportWaitlistCSV);

    const wlSubmitBtn = document.getElementById('wl-submit-btn');
    if (wlSubmitBtn) wlSubmitBtn.addEventListener('click', submitWaitlistCreate);

    document.getElementById('check-conflict-btn').addEventListener('click', checkBookingConflicts);

    document.getElementById('save-draft-btn').addEventListener('click', (e) => {
        e.preventDefault();
        saveBooking(true);
    });

    document.getElementById('booking-form').addEventListener('submit', (e) => {
        e.preventDefault();
        saveBooking(false);
    });

    document.getElementById('add-closed-date-btn').addEventListener('click', addClosedDate);
    document.getElementById('add-closed-window-btn').addEventListener('click', addClosedWindow);

    document.getElementById('reschedule-submit-btn').addEventListener('click', submitReschedule);

    document.querySelectorAll('.modal-close').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const modal = e.target.closest('.modal');
            modal.style.display = 'none';
        });
    });

    document.querySelectorAll('.modal-close-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const modal = e.target.closest('.modal');
            modal.style.display = 'none';
        });
    });

    document.querySelectorAll('.modal').forEach(modal => {
        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                modal.style.display = 'none';
            }
        });
    });

    (async function init() {
        const token = getToken();
        if (token) {
            const user = await loadUserInfo();
            if (user) {
                showMainApp();
                await loadVenues();
                loadBookings(1);
                return;
            }
        }
        showLoginPage();
    })();
});
