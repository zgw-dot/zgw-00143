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
        const errorInfo = handleApiError(e, '候补登记-弹层提交');

        let detailHtml = '';
        if (errorInfo.category === 'CONFLICT') {
            detailHtml = '<div style="font-size:12px;color:#e67e22;">该时段存在冲突，请调整时间或增加浮动范围</div>';
        } else if (errorInfo.category === 'PERMISSION') {
            detailHtml = '<div style="font-size:12px;color:#e74c3c;">您没有权限在此场地登记候补，请联系管理员</div>';
        } else {
            detailHtml = `<div style="font-size:12px;color:#666;">${errorInfo.suggestion}</div>`;
        }

        const info = ERROR_CATEGORY_INFO[errorInfo.category] || ERROR_CATEGORY_INFO.UNKNOWN;
        warnEl.innerHTML = `
            <h3>${info.icon} ${info.label}：${escapeHtml(errorInfo.message)}</h3>
            ${detailHtml}
            <div style="margin-top:8px;padding:6px;background:#f8f9fa;border-radius:4px;font-size:11px;color:#999;">
                错误分类：${errorInfo.category} | ${new Date().toLocaleString()}
            </div>
        `;
        warnEl.style.display = 'block';
    }
}

async function cancelWaitlist(id) {
    if (!confirm('确定取消此候补？')) return;
    try {
        await apiRequest(`/waitlist/${id}`, { method: 'DELETE' });
        showToast('已取消候补');
        loadWaitlist(wlPage);
    } catch (e) { handleApiError(e, '撤销候补-取消操作'); }
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
    } catch (e) { handleApiError(e, '手动补位-冲突校验'); }
}

function exportWaitlistCSV() {
    const token = getToken();
    fetch(`${API_BASE}/exports/waitlist.csv`, {
        headers: { 'Authorization': `Bearer ${token}` }
    })
    .then(async response => {
        if (!response.ok) {
            const txt = await response.text().catch(() => '');
            const error = new Error('导出失败 ' + response.status + ' ' + txt.slice(0, 100));
            error.statusCode = response.status;
            error.detail = txt;
            throw error;
        }
        return response.blob();
    })
    .then(blob => {
        if (blob.size < 50) {
            throw new Error('CSV文件内容为空，可能是数据筛选条件不正确');
        }
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
        handleApiError({ detail: err.message, statusCode: err.statusCode }, 'CSV下载-导出验证');
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

const ERROR_CATEGORY_INFO = {
    PERMISSION: { icon: '🔒', label: '权限错误', color: '#e74c3c', suggestion: '请检查您的账号权限，或联系管理员' },
    CONFLICT: { icon: '⚔️', label: '冲突错误', color: '#e67e22', suggestion: '该时段存在资源冲突，请调整时间或联系管理员' },
    CANCEL: { icon: '↩️', label: '撤销/取消错误', color: '#95a5a6', suggestion: '撤销或取消操作失败，请检查数据状态' },
    MODAL: { icon: '🪟', label: '弹层错误', color: '#3498db', suggestion: '页面弹层显示异常，请刷新后重试' },
    TABLE: { icon: '📋', label: '表格列错误', color: '#2ecc71', suggestion: '表格数据展示异常，请检查筛选条件或刷新' },
    DOWNLOAD: { icon: '📥', label: '下载错误', color: '#9b59b6', suggestion: '文件下载失败，请检查网络或稍后重试' },
    RESTART: { icon: '🔄', label: '重启验证错误', color: '#e74c3c', suggestion: '服务重启后数据不一致，请检查服务状态' },
    DATA_QUALITY: { icon: '❌', label: '数据质量错误', color: '#f39c12', suggestion: '数据校验失败，请检查数据完整性' },
    UNKNOWN: { icon: '⚠️', label: '未知错误', color: '#7f8c8d', suggestion: '发生未知错误，请联系技术支持' }
};

function classifyApiError(error) {
    let category = 'UNKNOWN';
    let statusCode = error.statusCode || 0;

    if (typeof error.detail === 'string') {
        const msg = error.detail.toLowerCase();
        if (msg.includes('403') || msg.includes('forbidden') || msg.includes('权限') || msg.includes('permission')) {
            category = 'PERMISSION';
        } else if (msg.includes('409') || msg.includes('冲突') || msg.includes('conflict') || msg.includes('duplicate') || msg.includes('重复')) {
            category = 'CONFLICT';
        } else if (msg.includes('撤销') || msg.includes('取消') || msg.includes('cancel') || msg.includes('revoke')) {
            category = 'CANCEL';
        } else if (msg.includes('弹层') || msg.includes('modal') || msg.includes('弹窗')) {
            category = 'MODAL';
        } else if (msg.includes('表格') || msg.includes('列') || msg.includes('table') || msg.includes('column')) {
            category = 'TABLE';
        } else if (msg.includes('下载') || msg.includes('csv') || msg.includes('export')) {
            category = 'DOWNLOAD';
        } else if (msg.includes('重启') || msg.includes('restart')) {
            category = 'RESTART';
        } else if (msg.includes('数据') || msg.includes('data')) {
            category = 'DATA_QUALITY';
        }
    }

    if (statusCode === 403 || statusCode === 401) {
        category = 'PERMISSION';
    } else if (statusCode === 409) {
        category = 'CONFLICT';
    }

    return category;
}

function handleApiError(error, context = '') {
    let message = '操作失败';
    let detail = '';
    let category = 'UNKNOWN';

    if (typeof error.detail === 'string') {
        message = error.detail;
        detail = error.detail;
    } else if (error.detail && error.detail.message) {
        message = error.detail.message;
        detail = error.detail.message;
        if (error.detail.conflicts && error.detail.conflicts.length > 0) {
            message += '：存在时间冲突';
            detail += '，冲突预约：' + error.detail.conflicts.map(c => c.title || '').join(', ');
        }
        if (error.detail.closed_dates && error.detail.closed_dates.length > 0) {
            message += '：包含封场日期';
            detail += '，封场日期：' + error.detail.closed_dates.join(', ');
        }
        if (error.detail.closed_windows && error.detail.closed_windows.length > 0) {
            message += '（撞上封场窗口）';
            detail += '，封场窗口：' + error.detail.closed_windows.map(w => w.reason || '').join(', ');
        }
    }

    if (error.statusCode) {
        category = classifyApiError(error);
    } else if (context) {
        const ctx = context.toLowerCase();
        if (ctx.includes('权限')) category = 'PERMISSION';
        else if (ctx.includes('冲突')) category = 'CONFLICT';
        else if (ctx.includes('撤销') || ctx.includes('取消')) category = 'CANCEL';
        else if (ctx.includes('弹层')) category = 'MODAL';
        else if (ctx.includes('表格')) category = 'TABLE';
        else if (ctx.includes('下载')) category = 'DOWNLOAD';
        else if (ctx.includes('重启')) category = 'RESTART';
    }

    const info = ERROR_CATEGORY_INFO[category] || ERROR_CATEGORY_INFO.UNKNOWN;
    const fullMessage = `${info.icon} ${info.label}：${message}\n💡 ${info.suggestion}`;

    showToast(fullMessage, 'error');

    console.error(`[API错误] 分类: ${category}, 上下文: ${context}, 详情:`, error);

    return {
        category,
        message,
        detail,
        suggestion: info.suggestion
    };
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

    function escapeHtml(str) {
        if (!str) return '';
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    let drillScripts = [];
    let drillBatches = [];
    let scriptFilter = { keyword: '', is_active: '' };
    let batchFilter = { script_id: '', status: '' };

    function getBatchStatusText(status) {
        const map = {
            pending: '待执行',
            running: '执行中',
            completed: '已完成',
            failed: '失败',
            rolled_back: '已回滚',
            recovering: '恢复中'
        };
        return map[status] || status;
    }

    function getBatchStatusClass(status) {
        return `status-batch-${status}`;
    }

    function getArtifactTypeText(type) {
        const map = {
            screenshot: '失败截图',
            fill_result: '补位结果',
            download_summary: '下载摘要',
            op_log: '操作日志',
            step_result: '步骤结果'
        };
        return map[type] || type;
    }

    async function loadDrillScripts() {
        try {
            const params = new URLSearchParams();
            if (scriptFilter.keyword) params.append('keyword', scriptFilter.keyword);
            if (scriptFilter.is_active !== '') params.append('is_active', scriptFilter.is_active);

            const data = await apiRequest(`/drill-center/scripts?${params.toString()}`);
            drillScripts = data;
            renderDrillScripts();
            renderScriptSelectOptions();
            renderBatchScriptFilter();
        } catch (e) {
            showToast('加载剧本列表失败', 'error');
            console.error(e);
        }
    }

    function renderDrillScripts() {
        const listEl = document.getElementById('script-list');
        const countEl = document.getElementById('script-count');

        countEl.textContent = `共 ${drillScripts.length} 个`;

        if (drillScripts.length === 0) {
            listEl.innerHTML = '<div style="text-align:center;padding:40px;color:#999;">暂无演练剧本，点击"新建剧本"或"使用默认模板"开始</div>';
            return;
        }

        listEl.innerHTML = drillScripts.map(s => {
            const venueRules = s.venue_rules || {};
            const samples = s.drill_samples || [];
            const members = s.member_accounts || [];
            const checkpoints = s.checkpoints || [];

            return `
            <div class="script-card">
                <div class="script-card-header">
                    <span class="script-card-title">📜 ${escapeHtml(s.name)}
                        <span style="font-size:12px;color:#999;font-weight:normal;">v${escapeHtml(s.version || '1.0')}</span>
                        <span class="status-badge ${s.is_active ? 'status-confirmed' : 'status-cancelled'}"
                              style="font-size:11px;margin-left:8px;">
                            ${s.is_active ? '启用' : '停用'}
                        </span>
                    </span>
                </div>
                <div class="script-card-meta">
                    <span>📝 ${escapeHtml(s.description || '无描述')}</span>
                    <span>👤 创建人: ${escapeHtml(s.created_by_name || '-')}</span>
                    <span>🕐 ${formatDateTime(s.created_at)}</span>
                </div>
                <div class="script-card-stats">
                    <div>🎯 样本数: <strong>${samples.length}</strong></div>
                    <div>👥 成员数: <strong>${members.length}</strong></div>
                    <div>✅ 检查点: <strong>${checkpoints.length}</strong></div>
                    <div>🏢 场地规则: <strong>${venueRules.venue_ids ? venueRules.venue_ids.length : 0}</strong> 个指定</div>
                </div>
                <div class="script-card-actions">
                    <button class="btn btn-outline" onclick="showScriptDetail(${s.id})">查看</button>
                    <button class="btn btn-primary" onclick="openScriptEditModal(${s.id})">编辑</button>
                    <button class="btn btn-secondary" onclick="exportScript(${s.id})">📤 导出JSON</button>
                    <button class="btn btn-success" onclick="openBatchCreateModal(${s.id})">▶ 创建批次</button>
                    ${currentUser.role === 'admin' ? `<button class="btn btn-danger" onclick="deleteScript(${s.id})">删除</button>` : ''}
                </div>
            </div>
            `;
        }).join('');
    }

    function renderScriptSelectOptions() {
        const sel = document.getElementById('batch-create-script');
        if (!sel) return;
        const options = drillScripts
            .filter(s => s.is_active)
            .map(s => `<option value="${s.id}">${escapeHtml(s.name)}</option>`)
            .join('');
        sel.innerHTML = options;
    }

    function renderBatchScriptFilter() {
        const sel = document.getElementById('batch-filter-script');
        if (!sel) return;
        const options = drillScripts.map(s =>
            `<option value="${s.id}">${escapeHtml(s.name)}</option>`
        ).join('');
        sel.innerHTML = '<option value="">全部剧本</option>' + options;
    }

    async function showScriptDetail(scriptId) {
        try {
            const s = await apiRequest(`/drill-center/scripts/${scriptId}`);
            document.getElementById('script-detail-title').textContent = `剧本详情: ${s.name}`;

            const prettyJson = (obj) => JSON.stringify(obj, null, 2);

            document.getElementById('script-detail-body').innerHTML = `
                <div class="detail-section">
                    <h3>基本信息</h3>
                    <div class="detail-row"><span class="detail-label">名称</span><span class="detail-value">${escapeHtml(s.name)}</span></div>
                    <div class="detail-row"><span class="detail-label">版本</span><span class="detail-value">${escapeHtml(s.version || '-')}</span></div>
                    <div class="detail-row"><span class="detail-label">状态</span><span class="detail-value">${s.is_active ? '启用' : '停用'}</span></div>
                    <div class="detail-row"><span class="detail-label">描述</span><span class="detail-value">${escapeHtml(s.description || '-')}</span></div>
                    <div class="detail-row"><span class="detail-label">创建人</span><span class="detail-value">${escapeHtml(s.created_by_name || '-')}</span></div>
                    <div class="detail-row"><span class="detail-label">创建时间</span><span class="detail-value">${formatDateTime(s.created_at)}</span></div>
                </div>
                <div class="detail-section">
                    <h3>🏢 场地规则</h3>
                    <pre style="background:#f9fafb;padding:12px;border-radius:6px;overflow:auto;">${escapeHtml(prettyJson(s.venue_rules || {}))}</pre>
                </div>
                <div class="detail-section">
                    <h3>🎯 演练样本</h3>
                    <pre style="background:#f9fafb;padding:12px;border-radius:6px;overflow:auto;">${escapeHtml(prettyJson(s.drill_samples || []))}</pre>
                </div>
                <div class="detail-section">
                    <h3>👥 成员账号</h3>
                    <pre style="background:#f9fafb;padding:12px;border-radius:6px;overflow:auto;">${escapeHtml(prettyJson(s.member_accounts || []))}</pre>
                </div>
                <div class="detail-section">
                    <h3>✅ 检查点</h3>
                    <pre style="background:#f9fafb;padding:12px;border-radius:6px;overflow:auto;">${escapeHtml(prettyJson(s.checkpoints || []))}</pre>
                </div>
                <div class="detail-section">
                    <h3>🧹 清理策略</h3>
                    <pre style="background:#f9fafb;padding:12px;border-radius:6px;overflow:auto;">${escapeHtml(prettyJson(s.cleanup_strategy || {}))}</pre>
                </div>
            `;

            let footer = '';
            if (currentUser.role === 'admin') {
                footer += `<button class="btn btn-primary" onclick="openScriptEditModal(${s.id});closeModal('script-detail-modal');">编辑</button>`;
                footer += `<button class="btn btn-secondary" onclick="exportScript(${s.id})">📤 导出JSON</button>`;
                footer += `<button class="btn btn-success" onclick="openBatchCreateModal(${s.id});closeModal('script-detail-modal');">▶ 创建批次</button>`;
            }
            footer += '<button class="btn btn-outline modal-close-btn">关闭</button>';
            document.getElementById('script-detail-footer').innerHTML = footer;

            document.getElementById('script-detail-modal').style.display = 'flex';
        } catch (e) {
            handleApiError(e);
        }
    }

    function openScriptCreateModal() {
        document.getElementById('script-modal-title').textContent = '新建演练剧本';
        document.getElementById('script-id').value = '';
        document.getElementById('script-name').value = '';
        document.getElementById('script-version').value = '1.0';
        document.getElementById('script-description').value = '';
        document.getElementById('script-venue-rules').value = JSON.stringify({
            venue_ids: [],
            auto_find_slot: true,
            search_days: 30,
            preferred_hours: [9, 10, 11, 14, 15, 16, 17, 19, 20]
        }, null, 2);
        document.getElementById('script-drill-samples').value = JSON.stringify([
            { name: '低优先级候补', type: 'low_priority', priority: 5, float_before_minutes: 30, float_after_minutes: 30 },
            { name: '高优先级候补', type: 'high_priority', priority: 15, float_before_minutes: 60, float_after_minutes: 60 }
        ], null, 2);
        document.getElementById('script-member-accounts').value = JSON.stringify([
            { username: 'drill_member1', password: 'drill1234', full_name: '演练成员1', role: 'member' },
            { username: 'drill_member2', password: 'drill1234', full_name: '演练成员2', role: 'member' },
            { username: 'drill_admin', password: 'admin1234', full_name: '演练管理员', role: 'admin' }
        ], null, 2);
        document.getElementById('script-checkpoints').value = JSON.stringify([
            { name: '用户创建验证', description: '验证演练账号正确创建', expected: 'passed' },
            { name: '候补排队验证', description: '验证优先级和排队顺序', expected: 'passed' },
            { name: '自动补位验证', description: '验证释放资源后自动补位', expected: 'passed' }
        ], null, 2);
        document.getElementById('script-cleanup-strategy').value = JSON.stringify({
            auto_cleanup_on_success: false,
            keep_screenshots: true,
            keep_logs: true,
            keep_fill_results: true
        }, null, 2);
        document.getElementById('script-create-warn').style.display = 'none';
        document.getElementById('script-create-modal').style.display = 'flex';
    }

    async function openScriptEditModal(scriptId) {
        try {
            const s = await apiRequest(`/drill-center/scripts/${scriptId}`);
            document.getElementById('script-modal-title').textContent = '编辑演练剧本';
            document.getElementById('script-id').value = s.id;
            document.getElementById('script-name').value = s.name;
            document.getElementById('script-version').value = s.version || '1.0';
            document.getElementById('script-description').value = s.description || '';
            document.getElementById('script-venue-rules').value = JSON.stringify(s.venue_rules || {}, null, 2);
            document.getElementById('script-drill-samples').value = JSON.stringify(s.drill_samples || [], null, 2);
            document.getElementById('script-member-accounts').value = JSON.stringify(s.member_accounts || [], null, 2);
            document.getElementById('script-checkpoints').value = JSON.stringify(s.checkpoints || [], null, 2);
            document.getElementById('script-cleanup-strategy').value = JSON.stringify(s.cleanup_strategy || {}, null, 2);
            document.getElementById('script-create-warn').style.display = 'none';
            document.getElementById('script-create-modal').style.display = 'flex';
        } catch (e) {
            handleApiError(e);
        }
    }

    function _tryParseJSON(text, fieldName) {
        try {
            return JSON.parse(text || '{}');
        } catch (e) {
            throw new Error(`${fieldName} JSON格式错误: ${e.message}`);
        }
    }

    async function submitScriptSave() {
        const id = document.getElementById('script-id').value;
        const name = document.getElementById('script-name').value.trim();
        const version = document.getElementById('script-version').value.trim() || '1.0';
        const description = document.getElementById('script-description').value.trim();

        if (!name) {
            showToast('请填写剧本名称', 'warning');
            return;
        }

        try {
            const venue_rules = _tryParseJSON(document.getElementById('script-venue-rules').value, '场地规则');
            const drill_samples = _tryParseJSON(document.getElementById('script-drill-samples').value, '演练样本');
            const member_accounts = _tryParseJSON(document.getElementById('script-member-accounts').value, '成员账号');
            const checkpoints = _tryParseJSON(document.getElementById('script-checkpoints').value, '检查点');
            const cleanup_strategy = _tryParseJSON(document.getElementById('script-cleanup-strategy').value, '清理策略');

            const payload = { name, version, description, venue_rules, drill_samples, member_accounts, checkpoints, cleanup_strategy };

            let result;
            if (id) {
                result = await apiRequest(`/drill-center/scripts/${id}`, {
                    method: 'PUT',
                    body: JSON.stringify(payload)
                });
            } else {
                result = await apiRequest('/drill-center/scripts', {
                    method: 'POST',
                    body: JSON.stringify(payload)
                });
            }

            showToast(id ? '剧本更新成功' : '剧本创建成功');
            closeModal('script-create-modal');
            loadDrillScripts();
        } catch (e) {
            const warnEl = document.getElementById('script-create-warn');
            warnEl.innerHTML = `<h3>❌ ${escapeHtml(e.detail?.message || e.detail || e.message || '保存失败')}</h3>
                ${e.detail?.errors ? `<div style="margin-top:8px;color:#e74c3c;">${escapeHtml(e.detail.errors.join('; '))}</div>` : ''}`;
            warnEl.style.display = 'block';
        }
    }

    async function deleteScript(scriptId) {
        if (!confirm('确定删除此剧本？删除后不可恢复，关联的已完成批次不受影响。')) return;
        try {
            await apiRequest(`/drill-center/scripts/${scriptId}`, { method: 'DELETE' });
            showToast('剧本已删除');
            loadDrillScripts();
        } catch (e) {
            handleApiError(e);
        }
    }

    async function createDefaultScript() {
        if (!confirm('确定使用默认模板创建一个新剧本？')) return;
        try {
            await apiRequest('/drill-center/scripts/default', { method: 'POST' });
            showToast('默认剧本创建成功');
            loadDrillScripts();
        } catch (e) {
            handleApiError(e);
        }
    }

    async function exportScript(scriptId) {
        try {
            const data = await apiRequest(`/drill-center/scripts/${scriptId}/export`);
            const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `drill_script_${scriptId}.json`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            window.URL.revokeObjectURL(url);
            showToast('导出成功');
        } catch (e) {
            handleApiError(e);
        }
    }

    function triggerScriptImport() {
        document.getElementById('script-import-file').click();
    }

    async function handleScriptImportFile(e) {
        const file = e.target.files[0];
        if (!file) return;

        try {
            const formData = new FormData();
            formData.append('file', file);

            const token = getToken();
            const validateRes = await fetch(`${API_BASE}/drill-center/scripts/validate`, {
                method: 'POST',
                headers: token ? { 'Authorization': `Bearer ${token}` } : {},
                body: formData
            });

            const validation = await validateRes.json();
            if (!validation.valid) {
                alert(`导入校验失败:\n${validation.errors.join('\n')}${validation.warnings.length ? '\n\n警告:\n' + validation.warnings.join('\n') : ''}`);
                return;
            }
            if (validation.warnings.length) {
                if (!confirm(`校验通过，但有警告:\n${validation.warnings.join('\n')}\n\n是否继续导入？`)) {
                    return;
                }
            }

            formData.delete('file');
            formData.append('file', file);
            const importRes = await fetch(`${API_BASE}/drill-center/scripts/import`, {
                method: 'POST',
                headers: token ? { 'Authorization': `Bearer ${token}` } : {},
                body: formData
            });

            if (!importRes.ok) {
                const errData = await importRes.json().catch(() => ({}));
                throw new Error(errData.detail || '导入失败');
            }

            showToast('剧本导入成功');
            loadDrillScripts();
        } catch (e) {
            showToast(e.message || '导入失败', 'error');
        } finally {
            e.target.value = '';
        }
    }

    async function loadDrillBatches() {
        try {
            const params = new URLSearchParams();
            if (batchFilter.script_id) params.append('script_id', batchFilter.script_id);
            if (batchFilter.status) params.append('status', batchFilter.status);

            const data = await apiRequest(`/drill-center/batches?${params.toString()}`);
            drillBatches = data;
            renderDrillBatches();
        } catch (e) {
            showToast('加载批次列表失败', 'error');
            console.error(e);
        }
    }

    function renderDrillBatches() {
        const listEl = document.getElementById('batch-list');
        const countEl = document.getElementById('batch-count');

        countEl.textContent = `共 ${drillBatches.length} 个`;

        if (drillBatches.length === 0) {
            listEl.innerHTML = '<div style="text-align:center;padding:40px;color:#999;">暂无演练批次，在剧本列表中点击"创建批次"开始</div>';
            return;
        }

        listEl.innerHTML = drillBatches.map(b => {
            return `
            <div class="batch-card">
                <div class="batch-card-header">
                    <span class="script-card-title">📦 ${escapeHtml(b.batch_id)}
                        <span class="status-badge ${getBatchStatusClass(b.status)}" style="font-size:12px;margin-left:8px;">
                            ${getBatchStatusText(b.status)}
                        </span>
                    </span>
                </div>
                <div class="batch-card-meta">
                    <span>📜 剧本: ${escapeHtml(b.script_name || '-')}</span>
                    <span>🏢 场地: ${escapeHtml(b.venue_name || '默认')}</span>
                    <span>👤 创建人: ${escapeHtml(b.created_by_name || '-')}</span>
                    <span>🕐 创建: ${formatDateTime(b.created_at)}</span>
                    ${b.completed_at ? `<span>✅ 完成: ${formatDateTime(b.completed_at)}</span>` : ''}
                </div>
                <div class="batch-card-stats">
                    <div>📊 总步骤: <strong>${b.total_steps || 0}</strong></div>
                    <div style="color:#10b981;">✅ 通过: <strong>${b.passed_steps || 0}</strong></div>
                    <div style="color:#ef4444;">❌ 失败: <strong>${b.failed_steps || 0}</strong></div>
                    <div>🧪 会话数: <strong>${(b.drill_session_ids || []).length}</strong></div>
                </div>
                ${b.error_message ? `<div style="background:#fef2f2;color:#b91c1c;padding:8px 12px;border-radius:4px;font-size:13px;margin-bottom:10px;">
                    ❌ 错误: ${escapeHtml(b.error_message)}
                </div>` : ''}
                <div class="batch-card-actions">
                    <button class="btn btn-outline" onclick="showBatchDetail('${escapeHtml(b.batch_id)}')">查看详情</button>
                    ${currentUser.role === 'admin' && b.status === 'pending' ?
                        `<button class="btn btn-success" onclick="executeBatch('${escapeHtml(b.batch_id)}')">▶ 执行</button>` : ''}
                    ${currentUser.role === 'admin' && (b.status === 'failed' || b.status === 'running') ?
                        `<button class="btn btn-warning" onclick="recoverBatch('${escapeHtml(b.batch_id)}')">🔄 恢复</button>` : ''}
                    ${currentUser.role === 'admin' && (b.status === 'completed' || b.status === 'failed') ?
                        `<button class="btn btn-danger" onclick="rollbackBatch('${escapeHtml(b.batch_id)}')">↩️ 回滚清理</button>` : ''}
                </div>
            </div>
            `;
        }).join('');
    }

    async function showBatchDetail(batchId) {
        try {
            const b = await apiRequest(`/drill-center/batches/${batchId}`);
            document.getElementById('batch-detail-title').textContent = `批次详情: ${b.batch_id}`;

            let artifactsHtml = '';
            if (b.artifacts && b.artifacts.length > 0) {
                const screenshotArtifacts = b.artifacts.filter(a => a.artifact_type === 'screenshot');
                const summaryArtifacts = b.artifacts.filter(a => a.artifact_type === 'download_summary');
                const logArtifacts = b.artifacts.filter(a => a.artifact_type === 'op_log');
                const otherArtifacts = b.artifacts.filter(a => !['screenshot','download_summary','op_log'].includes(a.artifact_type));

                artifactsHtml = `
                <div class="detail-section">
                    <h3>📁 执行产物 (${b.artifacts.length})</h3>
                    ${screenshotArtifacts.length > 0 ? `
                    <div style="margin-bottom:12px;">
                        <h4 style="font-size:13px;color:#ef4444;margin-bottom:6px;">📸 失败截图 (${screenshotArtifacts.length})</h4>
                        ${screenshotArtifacts.map(a => `
                            <div class="artifact-item screenshot">
                                <div class="artifact-title">
                                    ${escapeHtml(a.title || '(无标题)')}
                                    <span class="artifact-type-label status-batch-failed">失败截图</span>
                                </div>
                                ${a.content ? `<div class="artifact-content">${escapeHtml(a.content)}</div>` : ''}
                                ${a.file_path ? `<div style="font-size:11px;color:#888;margin-top:4px;">📁 ${escapeHtml(a.file_path)}</div>` : ''}
                            </div>
                        `).join('')}
                    </div>` : ''}
                    ${summaryArtifacts.length > 0 ? `
                    <div style="margin-bottom:12px;">
                        <h4 style="font-size:13px;color:#8b5cf6;margin-bottom:6px;">📥 下载摘要 (${summaryArtifacts.length})</h4>
                        ${summaryArtifacts.map(a => `
                            <div class="artifact-item download_summary">
                                <div class="artifact-title">${escapeHtml(a.title || '(无标题)')}</div>
                                ${a.content ? `<div class="artifact-content">${escapeHtml(a.content)}</div>` : ''}
                            </div>
                        `).join('')}
                    </div>` : ''}
                    ${logArtifacts.length > 0 ? `
                    <div style="margin-bottom:12px;">
                        <h4 style="font-size:13px;color:#f59e0b;margin-bottom:6px;">📝 执行日志 (${logArtifacts.length})</h4>
                        ${logArtifacts.map(a => `
                            <div class="artifact-item op_log">
                                <div class="artifact-title">${escapeHtml(a.title || '(无标题)')}</div>
                                ${a.content ? `<div class="artifact-content">${escapeHtml(a.content)}</div>` : ''}
                            </div>
                        `).join('')}
                    </div>` : ''}
                    ${otherArtifacts.length > 0 ? `
                    <div style="margin-bottom:12px;">
                        <h4 style="font-size:13px;color:#0ea5e9;margin-bottom:6px;">📊 其他产物 (${otherArtifacts.length})</h4>
                        ${otherArtifacts.map(a => `
                            <div class="artifact-item ${a.artifact_type}">
                                <div class="artifact-title">
                                    ${escapeHtml(a.title || '(无标题)')}
                                    <span class="artifact-type-label status-batch-pending">${getArtifactTypeText(a.artifact_type)}</span>
                                </div>
                                ${a.content ? `<div class="artifact-content">${escapeHtml(a.content)}</div>` : ''}
                            </div>
                        `).join('')}
                    </div>` : ''}
                </div>`;
            }

            let memberDownloadBtn = '';
            if (b.status === 'completed' || b.status === 'failed') {
                memberDownloadBtn = `<button class="btn btn-secondary" onclick="downloadMemberData('${escapeHtml(b.batch_id)}')">📥 下载摘要与日志</button>`;
            }

            document.getElementById('batch-detail-body').innerHTML = `
                <div class="detail-section">
                    <h3>基本信息</h3>
                    <div class="detail-row"><span class="detail-label">批次ID</span><span class="detail-value"><code>${escapeHtml(b.batch_id)}</code></span></div>
                    <div class="detail-row"><span class="detail-label">剧本</span><span class="detail-value">${escapeHtml(b.script_name || '-')}</span></div>
                    <div class="detail-row"><span class="detail-label">状态</span><span class="detail-value">
                        <span class="status-badge ${getBatchStatusClass(b.status)}">${getBatchStatusText(b.status)}</span>
                    </span></div>
                    <div class="detail-row"><span class="detail-label">场地</span><span class="detail-value">${escapeHtml(b.venue_name || '默认')}</span></div>
                    <div class="detail-row"><span class="detail-label">创建人</span><span class="detail-value">${escapeHtml(b.created_by_name || '-')}</span></div>
                    <div class="detail-row"><span class="detail-label">创建时间</span><span class="detail-value">${formatDateTime(b.created_at)}</span></div>
                    <div class="detail-row"><span class="detail-label">开始时间</span><span class="detail-value">${b.started_at ? formatDateTime(b.started_at) : '-'}</span></div>
                    <div class="detail-row"><span class="detail-label">完成时间</span><span class="detail-value">${b.completed_at ? formatDateTime(b.completed_at) : '-'}</span></div>
                    ${b.rolled_back_at ? `<div class="detail-row"><span class="detail-label">回滚时间</span><span class="detail-value">${formatDateTime(b.rolled_back_at)}</span></div>` : ''}
                </div>
                <div class="detail-section">
                    <h3>执行结果</h3>
                    <div class="detail-row"><span class="detail-label">总步骤</span><span class="detail-value">${b.total_steps || 0}</span></div>
                    <div class="detail-row"><span class="detail-label">通过</span><span class="detail-value" style="color:#10b981;">${b.passed_steps || 0}</span></div>
                    <div class="detail-row"><span class="detail-label">失败</span><span class="detail-value" style="color:#ef4444;">${b.failed_steps || 0}</span></div>
                    <div class="detail-row"><span class="detail-label">演练会话</span><span class="detail-value">${(b.drill_session_ids || []).join(', ') || '-'}</span></div>
                    ${b.error_message ? `<div class="detail-row"><span class="detail-label">错误信息</span><span class="detail-value" style="color:#ef4444;">${escapeHtml(b.error_message)}</span></div>` : ''}
                </div>
                ${artifactsHtml}
            `;

            let footer = '';
            if (currentUser.role === 'admin') {
                if (b.status === 'pending') {
                    footer += `<button class="btn btn-success" onclick="executeBatch('${escapeHtml(b.batch_id)}');closeModal('batch-detail-modal');">▶ 执行</button>`;
                }
                if (b.status === 'failed' || b.status === 'running' || b.status === 'recovering') {
                    footer += `<button class="btn btn-warning" onclick="recoverBatch('${escapeHtml(b.batch_id)}');closeModal('batch-detail-modal');">🔄 恢复</button>`;
                }
                if (b.status === 'completed' || b.status === 'failed') {
                    footer += `<button class="btn btn-danger" onclick="rollbackBatch('${escapeHtml(b.batch_id)}');closeModal('batch-detail-modal');">↩️ 回滚清理</button>`;
                }
            }
            if (b.status === 'completed' || b.status === 'failed') {
                footer += `<button class="btn btn-secondary" onclick="downloadMemberData('${escapeHtml(b.batch_id)}')">📥 下载摘要与日志</button>`;
            }
            footer += '<button class="btn btn-outline modal-close-btn">关闭</button>';
            document.getElementById('batch-detail-footer').innerHTML = footer;

            document.getElementById('batch-detail-modal').style.display = 'flex';
        } catch (e) {
            handleApiError(e);
        }
    }

    function openBatchCreateModal(scriptId) {
        renderScriptSelectOptions();
        if (scriptId) {
            document.getElementById('batch-create-script').value = scriptId;
        }
        const venueSelect = document.getElementById('batch-create-venue');
        venueSelect.innerHTML = '<option value="">使用剧本默认</option>' +
            venues.map(v => `<option value="${v.id}">${escapeHtml(v.name)}</option>`).join('');
        document.getElementById('batch-create-modal').style.display = 'flex';
    }

    async function submitBatchCreate() {
        const script_id = parseInt(document.getElementById('batch-create-script').value);
        const venue_val = document.getElementById('batch-create-venue').value;
        const venue_id = venue_val ? parseInt(venue_val) : null;

        if (!script_id) {
            showToast('请选择剧本', 'warning');
            return;
        }

        try {
            const result = await apiRequest('/drill-center/batches', {
                method: 'POST',
                body: JSON.stringify({ script_id, venue_id })
            });
            showToast('批次创建成功');
            closeModal('batch-create-modal');
            loadDrillBatches();
            switchDrillSubtab('batches');
        } catch (e) {
            handleApiError(e);
        }
    }

    async function executeBatch(batchId) {
        if (!confirm(`确定执行批次 ${batchId}？执行可能需要较长时间。`)) return;
        try {
            showToast('开始执行，请稍候...');
            const result = await apiRequest(`/drill-center/batches/${batchId}/execute`, {
                method: 'POST'
            });
            showToast(result.status === 'completed' ? '批次执行完成' :
                      result.status === 'failed' ? '批次执行失败，请查看详情' : '批次执行中');
            loadDrillBatches();
        } catch (e) {
            handleApiError(e);
        }
    }

    async function rollbackBatch(batchId) {
        if (!confirm(`确定回滚并清理批次 ${batchId}？所有演练数据将被清除。`)) return;
        try {
            const result = await apiRequest(`/drill-center/batches/${batchId}/rollback`, {
                method: 'POST'
            });
            if (result.success) {
                showToast(`回滚成功，清理 ${result.removed_count} 条数据`);
            } else {
                showToast(result.message || '回滚失败', 'error');
            }
            loadDrillBatches();
        } catch (e) {
            handleApiError(e);
        }
    }

    async function recoverBatch(batchId) {
        if (!confirm(`确定恢复批次 ${batchId}？将验证数据完整性并重置状态。`)) return;
        try {
            const result = await apiRequest(`/drill-center/batches/${batchId}/recover`, {
                method: 'POST'
            });
            showToast(result.message || (result.success ? '恢复成功' : '恢复失败'));
            loadDrillBatches();
        } catch (e) {
            handleApiError(e);
        }
    }

    async function downloadMemberData(batchId) {
        try {
            const result = await apiRequest(`/drill-center/batches/${batchId}/member-download`);
            if (result.downloads && result.downloads.length > 0) {
                const content = JSON.stringify(result, null, 2);
                const blob = new Blob([content], { type: 'application/json' });
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `batch_${batchId}_download.json`;
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                window.URL.revokeObjectURL(url);
                showToast(`已下载 ${result.downloads.length} 项数据`);
            } else {
                showToast('暂无可下载的数据', 'warning');
            }
        } catch (e) {
            handleApiError(e);
        }
    }

    function switchDrillSubtab(name) {
        document.querySelectorAll('.drill-subtab').forEach(t => {
            t.classList.toggle('active', t.dataset.subtab === name);
        });
        document.querySelectorAll('.drill-subtab-content').forEach(c => {
            c.classList.toggle('active', c.id === `drill-subtab-${name}`);
        });
        if (name === 'scripts') loadDrillScripts();
        if (name === 'batches') loadDrillBatches();
    }

    function closeModal(modalId) {
        document.getElementById(modalId).style.display = 'none';
    }

    document.querySelectorAll('.drill-subtab').forEach(t => {
        t.addEventListener('click', () => switchDrillSubtab(t.dataset.subtab));
    });

    document.getElementById('script-search-btn').addEventListener('click', () => {
        scriptFilter.keyword = document.getElementById('script-keyword').value.trim();
        scriptFilter.is_active = document.getElementById('script-status').value;
        loadDrillScripts();
    });

    document.getElementById('script-reset-btn').addEventListener('click', () => {
        document.getElementById('script-keyword').value = '';
        document.getElementById('script-status').value = '';
        scriptFilter = { keyword: '', is_active: '' };
        loadDrillScripts();
    });

    document.getElementById('batch-search-btn').addEventListener('click', () => {
        batchFilter.script_id = document.getElementById('batch-filter-script').value;
        batchFilter.status = document.getElementById('batch-filter-status').value;
        loadDrillBatches();
    });

    document.getElementById('batch-reset-btn').addEventListener('click', () => {
        document.getElementById('batch-filter-script').value = '';
        document.getElementById('batch-filter-status').value = '';
        batchFilter = { script_id: '', status: '' };
        loadDrillBatches();
    });

    document.getElementById('script-create-btn').addEventListener('click', openScriptCreateModal);
    document.getElementById('script-default-btn').addEventListener('click', createDefaultScript);
    document.getElementById('script-import-btn').addEventListener('click', triggerScriptImport);
    document.getElementById('script-import-file').addEventListener('change', handleScriptImportFile);
    document.getElementById('script-submit-btn').addEventListener('click', submitScriptSave);
    document.getElementById('batch-submit-btn').addEventListener('click', submitBatchCreate);

    const DS_API = '/drill-schedule';
    let dsTemplates = [];
    let dsSchedules = [];
    let dsAuditLogs = [];
    let dsMineSchedules = [];
    let dsCalendarDate = new Date();
    let dsTemplateFilter = { keyword: '', ttype: '', is_active: '' };
    let dsScheduleFilter = { keyword: '', status: '', venue_id: '', from_date: '', to_date: '' };
    let dsAuditFilter = { resource_type: '', action: '', operator: '', from_date: '', to_date: '' };
    let dsEditingScheduleId = null;
    let dsEditingTemplateId = null;
    let dsCancelSchedId = null;
    let dsCopySchedId = null;
    let dsDrillScriptsCache = [];
    let dsVenuesCache = [];

    const DSTypeLabel = { venue: '场地模板', group: '成员分组', checklist: '检查清单', cleanup: '清理规则' };
    const DSTypeIcon = { venue: '🏢', group: '👥', checklist: '✅', cleanup: '🧹' };
    const DSScheduleStatusLabel = { draft: '草稿', published: '已发布', locked: '已锁定', executing: '执行中', completed: '已完成', cancelled: '已撤销' };
    const DSScheduleStatusClass = { draft: 'status-batch-pending', published: 'status-batch-ready', locked: 'status-batch-created', executing: 'status-batch-running', completed: 'status-batch-completed', cancelled: 'status-batch-failed' };

    function switchDsSubtab(subtab) {
        document.querySelectorAll('.ds-subtab').forEach(t => t.classList.toggle('active', t.dataset.subtab === subtab));
        document.querySelectorAll('.ds-subtab-content').forEach(c => c.classList.toggle('active', c.id === `ds-subtab-${subtab}`));
        if (subtab === 'templates') loadDsTemplates();
        if (subtab === 'calendar') loadDsSchedules();
        if (subtab === 'mine') loadDsMine();
        if (subtab === 'audit' && currentUser?.role === 'admin') loadDsAudit();
        if (subtab === 'audit' && currentUser?.role !== 'admin') showToast('仅管理员可查看审计日志', 'warning');
    }

    function formatDsTimeHHMM(t) {
        if (!t) return '-';
        const s = String(t);
        if (s.includes(':')) return s.substring(0, 5);
        return s;
    }

    async function loadDsDrillScriptsCache() {
        try {
            dsDrillScriptsCache = await apiRequest('/drill-center/scripts');
        } catch (e) { /* 忽略 */ }
    }

    async function loadDsVenuesCache() {
        try {
            dsVenuesCache = venues || await apiRequest('/venues');
        } catch (e) { /* 忽略 */ }
    }

    function populateDsVenueOptions(selectId, includeEmpty = true) {
        const sel = document.getElementById(selectId);
        if (!sel) return;
        const opts = dsVenuesCache.map(v => `<option value="${v.id}">${escapeHtml(v.name)} (${escapeHtml(v.location || '')})</option>`);
        sel.innerHTML = (includeEmpty ? '<option value="">请选择</option>' : '') + opts.join('');
    }

    function populateDsScriptOptions(selectId, includeEmpty = true) {
        const sel = document.getElementById(selectId);
        if (!sel) return;
        const opts = dsDrillScriptsCache.map(s => `<option value="${s.id}">${escapeHtml(s.name)} v${escapeHtml(s.version || '')}</option>`);
        sel.innerHTML = (includeEmpty ? '<option value="">未关联</option>' : '') + opts.join('');
    }

    function populateDsTemplateOptions(selectId, ttype) {
        const sel = document.getElementById(selectId);
        if (!sel) return;
        const matched = dsTemplates.filter(t => t.template_type === ttype && t.is_active);
        const opts = matched.map(t => `<option value="${t.id}">${escapeHtml(t.name)} [${escapeHtml(t.version || '1.0')}]</option>`);
        sel.innerHTML = '<option value="">未使用</option>' + opts.join('');
    }

    async function loadDrillSchedulePage() {
        await loadDsDrillScriptsCache();
        await loadDsVenuesCache();
        populateDsVenueOptions('ds-sched-venue');
        populateDsVenueOptions('ds-cal-venue');
        populateDsScriptOptions('ds-sched-script');
        populateDsScriptOptions('ds-batch-script');
        await loadDsTemplates();
        switchDsSubtab('calendar');
    }

    function setDsElText(elId, value) {
        const el = document.getElementById(elId);
        if (el) el.textContent = value;
    }

    const originalSwitchTab = (tabName) => {
        document.querySelectorAll('.nav-tab').forEach(t => {
            t.classList.toggle('active', t.dataset.tab === tabName);
        });
        document.querySelectorAll('.tab-content').forEach(c => {
            c.classList.toggle('active', c.id === `tab-${tabName}`);
        });
        if (tabName === 'drill-center') {
            loadDrillScripts();
            loadDrillBatches();
        }
        if (tabName === 'drill-schedule') {
            loadDrillSchedulePage();
        }
    };

    document.querySelectorAll('.nav-tab').forEach(t => {
        t.addEventListener('click', () => originalSwitchTab(t.dataset.tab));
    });

    async function loadDsTemplates() {
        try {
            const params = new URLSearchParams();
            if (dsTemplateFilter.keyword) params.append('keyword', dsTemplateFilter.keyword);
            if (dsTemplateFilter.ttype) params.append('template_type', dsTemplateFilter.ttype);
            if (dsTemplateFilter.is_active !== '') params.append('is_active', dsTemplateFilter.is_active);

            dsTemplates = await apiRequest(`${DS_API}/templates?${params.toString()}`);
            renderDsTemplates();
            populateDsTemplateOptions('ds-sched-venue-tpl', 'venue');
            populateDsTemplateOptions('ds-sched-group-tpl', 'group');
            populateDsTemplateOptions('ds-sched-check-tpl', 'checklist');
            populateDsTemplateOptions('ds-sched-clean-tpl', 'cleanup');
            populateDsTemplateOptions('ds-batch-venue-tpl', 'venue');
            populateDsTemplateOptions('ds-batch-group-tpl', 'group');
        } catch (e) {
            showToast('加载模板列表失败: ' + (e.detail?.message || e.detail || e.message), 'error');
        }
    }

    function renderDsTemplates() {
        const listEl = document.getElementById('ds-template-list');
        setDsElText('ds-template-count', `共 ${dsTemplates.length} 个`);

        if (dsTemplates.length === 0) {
            listEl.innerHTML = '<div style="text-align:center;padding:40px;color:#999;">暂无模板，点击"新建模板"开始创建</div>';
            return;
        }

        listEl.innerHTML = dsTemplates.map(t => {
            const cfg = typeof t.config_json === 'string' ? t.config_json : JSON.stringify(t.config_json || {});
            return `
            <div class="script-card">
                <div class="script-card-header">
                    <span class="script-card-title">${DSTypeIcon[t.template_type] || '📄'} ${escapeHtml(t.name)}
                        <span style="font-size:12px;color:#888;margin-left:6px;">v${escapeHtml(t.version || '1.0')}</span>
                        <span class="status-badge ${t.is_active ? 'status-batch-ready' : 'status-batch-failed'}" style="font-size:12px;margin-left:8px;">
                            ${t.is_active ? '启用' : '停用'}
                        </span>
                    </span>
                    <span style="font-size:12px;color:#666;">${escapeHtml(DSTypeLabel[t.template_type] || t.template_type)}</span>
                </div>
                <div class="script-card-meta">
                    ${t.description ? `<span>📝 ${escapeHtml(t.description)}</span>` : ''}
                    <span>👤 创建人: ${escapeHtml(t.created_by_name || '-')}</span>
                    <span>🕐 创建: ${formatDateTime(t.created_at)}</span>
                    ${t.updated_at ? `<span>🔄 更新: ${formatDateTime(t.updated_at)}</span>` : ''}
                </div>
                <div class="script-card-actions">
                    <button class="btn btn-outline" onclick="showDsTemplateDetail(${t.id})">📋 详情/版本</button>
                    <button class="btn btn-primary" onclick="openDsTemplateModal(${t.id})">✏️ 编辑</button>
                    <button class="btn btn-outline" onclick="toggleDsTemplateActive(${t.id})">${t.is_active ? '⏸️ 停用' : '▶️ 启用'}</button>
                    <button class="btn btn-outline" onclick="exportDsTemplate(${t.id})">📥 导出JSON</button>
                    <button class="btn btn-danger" onclick="deleteDsTemplate(${t.id})">🗑️ 删除</button>
                </div>
            </div>`;
        }).join('');
    }

    function openDsTemplateModal(templateId = null) {
        dsEditingTemplateId = templateId;
        document.getElementById('ds-tpl-id').value = '';
        document.getElementById('ds-tpl-name').value = '';
        document.getElementById('ds-tpl-ttype').value = 'venue';
        document.getElementById('ds-tpl-version').value = '1.0';
        document.getElementById('ds-tpl-active').value = 'true';
        document.getElementById('ds-tpl-desc').value = '';
        document.getElementById('ds-tpl-config').value = '';
        document.getElementById('ds-tpl-changenote').value = '';
        document.getElementById('ds-tpl-warn').style.display = 'none';

        if (templateId) {
            const t = dsTemplates.find(x => x.id === templateId);
            if (t) {
                document.getElementById('ds-tpl-modal-title').textContent = '编辑模板';
                document.getElementById('ds-tpl-id').value = t.id;
                document.getElementById('ds-tpl-name').value = t.name;
                document.getElementById('ds-tpl-ttype').value = t.template_type;
                document.getElementById('ds-tpl-version').value = t.version || '1.0';
                document.getElementById('ds-tpl-active').value = String(t.is_active);
                document.getElementById('ds-tpl-desc').value = t.description || '';
                const cfg = typeof t.config_json === 'string' ? t.config_json : JSON.stringify(t.config_json || {}, null, 2);
                document.getElementById('ds-tpl-config').value = cfg;
            }
        } else {
            document.getElementById('ds-tpl-modal-title').textContent = '新建模板';
            const sampleCfg = { venue: '{"venue_ids":[],"time_slots":[{"start":"09:00","end":"12:00"},{"start":"14:00","end":"17:00"}]}',
                group: '{"groups":[{"name":"红队","members":[]},{"name":"蓝队","members":[]}]}',
                checklist: '{"items":[{"name":"登录系统","required":true},{"name":"打开浏览器控制台","required":false}]}',
                cleanup: '{"cleanup_types":["samples","temp_files","placeholders"],"delete_artifacts":true}' };
            document.getElementById('ds-tpl-config').value = sampleCfg.venue;
        }
        openModal('ds-template-modal');
    }

    async function submitDsTemplate() {
        const id = document.getElementById('ds-tpl-id').value;
        const name = document.getElementById('ds-tpl-name').value.trim();
        const template_type = document.getElementById('ds-tpl-ttype').value;
        const version = document.getElementById('ds-tpl-version').value.trim() || '1.0';
        const is_active = document.getElementById('ds-tpl-active').value === 'true';
        const description = document.getElementById('ds-tpl-desc').value.trim();
        const change_note = document.getElementById('ds-tpl-changenote').value.trim() || undefined;
        let config_json;
        try {
            config_json = JSON.parse(document.getElementById('ds-tpl-config').value || '{}');
        } catch (e) {
            const warnEl = document.getElementById('ds-tpl-warn');
            warnEl.innerHTML = `<h3>❌ 配置JSON格式错误: ${escapeHtml(e.message)}</h3>`;
            warnEl.style.display = 'block';
            return;
        }

        if (!name) { showToast('请填写模板名称', 'warning'); return; }

        const payload = { name, template_type, version, is_active, description, config_json };
        if (change_note) payload.change_note = change_note;

        try {
            if (id) {
                await apiRequest(`${DS_API}/templates/${id}`, { method: 'PUT', body: JSON.stringify(payload) });
                showToast('模板更新成功');
            } else {
                await apiRequest(`${DS_API}/templates`, { method: 'POST', body: JSON.stringify(payload) });
                showToast('模板创建成功');
            }
            closeModal('ds-template-modal');
            loadDsTemplates();
        } catch (e) {
            const warnEl = document.getElementById('ds-tpl-warn');
            const errors = e.detail?.errors ? e.detail.errors.join('; ') : '';
            warnEl.innerHTML = `<h3>❌ ${escapeHtml(e.detail?.message || e.detail || e.message || '保存失败')}</h3>${errors ? `<div style="margin-top:6px;color:#ef4444;">${escapeHtml(errors)}</div>` : ''}`;
            warnEl.style.display = 'block';
        }
    }

    async function toggleDsTemplateActive(tid) {
        try {
            const r = await apiRequest(`${DS_API}/templates/${tid}/toggle`, { method: 'POST' });
            showToast('模板状态已切换为: ' + (r.is_active ? '启用' : '停用'));
            loadDsTemplates();
        } catch (e) { handleApiError(e); }
    }

    async function deleteDsTemplate(tid) {
        if (!confirm('确定删除该模板？版本快照会保留，但新排期将不能再选它。')) return;
        try {
            await apiRequest(`${DS_API}/templates/${tid}`, { method: 'DELETE' });
            showToast('模板已删除');
            loadDsTemplates();
        } catch (e) { handleApiError(e); }
    }

    async function exportDsTemplate(tid) {
        try {
            const data = await apiRequest(`${DS_API}/templates/${tid}/export`);
            const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `ds_template_${data.template_type}_${escapeHtml(data.name || tid)}.json`;
            document.body.appendChild(a); a.click();
            document.body.removeChild(a); window.URL.revokeObjectURL(url);
            showToast('模板导出成功');
        } catch (e) { handleApiError(e); }
    }

    function triggerDsTemplateImport() { document.getElementById('ds-tpl-import-file').click(); }

    async function handleDsTemplateImportFile(e) {
        const file = e.target.files[0];
        if (!file) return;
        try {
            const formData = new FormData(); formData.append('file', file);
            const token = getToken();
            const vh = token ? { 'Authorization': `Bearer ${token}` } : {};
            const valRes = await fetch(`${API_BASE}${DS_API}/templates/validate`, { method: 'POST', headers: vh, body: formData });
            const validation = await valRes.json();

            if (validation.blocking_errors && validation.blocking_errors.length) {
                alert('导入被拦截：\n' + validation.blocking_errors.join('\n') +
                    (validation.warnings && validation.warnings.length ? '\n\n同时有警告：\n' + validation.warnings.join('\n') : ''));
                e.target.value = ''; return;
            }

            let cont = true;
            if (validation.warnings && validation.warnings.length) {
                cont = confirm('校验通过，存在以下警告：\n' + validation.warnings.join('\n') + '\n\n是否继续导入？');
            }
            if (!cont) { e.target.value = ''; return; }

            const fd2 = new FormData(); fd2.append('file', file);
            const impRes = await fetch(`${API_BASE}${DS_API}/templates/import`, { method: 'POST', headers: vh, body: fd2 });
            if (!impRes.ok) {
                const err = await impRes.json().catch(() => ({}));
                throw new Error(err.detail || '导入失败');
            }
            const imported = await impRes.json();
            showToast(`导入成功，模板ID=${imported.id}，已保存 ${imported.version_snapshot ? '版本快照' : ''}`);
            loadDsTemplates();
        } catch (e) { showToast('导入失败: ' + (e.message || e), 'error'); }
        finally { e.target.value = ''; }
    }

    async function showDsTemplateDetail(tid) {
        try {
            const t = await apiRequest(`${DS_API}/templates/${tid}`);
            const versions = await apiRequest(`${DS_API}/templates/${tid}/versions`);
            document.getElementById('ds-tpldetail-title').textContent = `模板详情: ${t.name} v${t.version || '1.0'}`;

            const cfgStr = typeof t.config_json === 'string' ? t.config_json : JSON.stringify(t.config_json || {}, null, 2);
            let vsHtml = '';
            if (versions && versions.length) {
                vsHtml = `<div class="detail-section"><h3>📜 版本快照 (${versions.length})</h3>
                    <div style="max-height:260px;overflow:auto;">${versions.map(v => `
                    <div style="padding:10px 12px;border:1px solid #e5e7eb;border-radius:6px;margin-bottom:8px;">
                        <div style="display:flex;justify-content:space-between;margin-bottom:4px;">
                            <strong>v${escapeHtml(v.version)} ${escapeHtml(v.change_note || '')}</strong>
                            <span style="color:#666;font-size:12px;">${formatDateTime(v.created_at)}</span>
                        </div>
                        <div style="font-size:12px;color:#666;">操作人: ${escapeHtml(v.created_by_name || '-')}</div>
                        <pre style="background:#f3f4f6;padding:6px 8px;border-radius:4px;font-size:11px;max-height:100px;overflow:auto;margin-top:4px;">${escapeHtml(typeof v.config_snapshot==='string'?v.config_snapshot:JSON.stringify(v.config_snapshot||{}))}</pre>
                    </div>`).join('')}</div></div>`;
            }

            document.getElementById('ds-tpldetail-body').innerHTML = `
                <div class="detail-section">
                    <h3>📝 基本信息</h3>
                    <div class="detail-row"><span>类型:</span><strong>${DSTypeIcon[t.template_type]} ${DSTypeLabel[t.template_type]}</strong></div>
                    <div class="detail-row"><span>版本:</span><code>${escapeHtml(t.version || '1.0')}</code></div>
                    <div class="detail-row"><span>状态:</span><span class="status-badge ${t.is_active ? 'status-batch-ready' : 'status-batch-failed'}">${t.is_active ? '启用' : '停用'}</span></div>
                    <div class="detail-row"><span>描述:</span>${escapeHtml(t.description || '-')}</div>
                    <div class="detail-row"><span>创建:</span>${formatDateTime(t.created_at)} by ${escapeHtml(t.created_by_name || '-')}</div>
                </div>
                <div class="detail-section"><h3>⚙️ 配置</h3>
                    <pre style="background:#f3f4f6;padding:10px 12px;border-radius:6px;font-size:12px;max-height:280px;overflow:auto;">${escapeHtml(cfgStr)}</pre>
                </div>${vsHtml}`;
            document.getElementById('ds-tpldetail-footer').innerHTML = `<button class="btn btn-outline modal-close-btn">关闭</button>`;
            bindModalClose(); openModal('ds-template-detail-modal');
        } catch (e) { handleApiError(e); }
    }

    async function loadDsSchedules() {
        try {
            const params = new URLSearchParams();
            if (dsScheduleFilter.keyword) params.append('keyword', dsScheduleFilter.keyword);
            if (dsScheduleFilter.status) params.append('status', dsScheduleFilter.status);
            if (dsScheduleFilter.venue_id) params.append('venue_id', dsScheduleFilter.venue_id);
            if (dsScheduleFilter.from_date) params.append('from_date', dsScheduleFilter.from_date);
            if (dsScheduleFilter.to_date) params.append('to_date', dsScheduleFilter.to_date);

            dsSchedules = await apiRequest(`${DS_API}/schedules?${params.toString()}`);
            renderDsSchedules();
            renderDsCalendar();
        } catch (e) { showToast('加载排期失败: ' + (e.detail?.message || e.detail || e.message), 'error'); }
    }

    function renderDsSchedules() {
        const listEl = document.getElementById('ds-schedule-list');
        setDsElText('ds-schedule-count', `共 ${dsSchedules.length} 条`);

        if (dsSchedules.length === 0) {
            listEl.innerHTML = '<div style="text-align:center;padding:40px;color:#999;">暂无排期，点击"新建排期"或"批量生成"开始</div>';
            return;
        }

        listEl.innerHTML = dsSchedules.map(s => {
            const stCls = DSScheduleStatusClass[s.status] || 'status-batch-pending';
            const stLabel = DSScheduleStatusLabel[s.status] || s.status;
            const conflict = s.conflicts && s.conflicts.length;
            return `
            <div class="script-card ${conflict ? 'schedule-card-conflict' : ''}">
                <div class="script-card-header">
                    <span class="script-card-title">📅 ${escapeHtml(s.title)}
                        <span class="status-badge ${stCls}" style="font-size:12px;margin-left:8px;">${stLabel}</span>
                        <span style="font-size:12px;margin-left:8px;">#${escapeHtml(s.schedule_no || s.id)}</span>
                    </span>
                    <span style="font-size:12px;color:#666;">${escapeHtml(s.venue_name || '-')}</span>
                </div>
                <div class="script-card-meta">
                    <span>🗓 ${escapeHtml(s.schedule_date || '-')}</span>
                    <span>⏰ ${formatDsTimeHHMM(s.start_time)} ~ ${formatDsTimeHHMM(s.end_time)}</span>
                    <span>👤 创建人: ${escapeHtml(s.created_by_name || '-')}</span>
                    ${s.batch_id ? `<span>📦 批次: ${escapeHtml(s.batch_id)}</span>` : ''}
                </div>
                ${conflict ? `<div style="background:#fef2f2;color:#b91c1c;padding:6px 10px;border-radius:4px;font-size:12px;margin:6px 0;">⚠️ ${s.conflicts.length}个冲突: ${escapeHtml(s.conflicts.map(c=>c.reason||'').slice(0,2).join(' / '))}</div>` : ''}
                ${s.template_snapshot_fields ? `<div style="font-size:12px;color:#6b7280;">📸 快照隔离: ${s.template_snapshot_fields.map(f=>escapeHtml(f)).join(', ')}</div>` : ''}
                <div class="script-card-actions">
                    <button class="btn btn-outline" onclick="showDsScheduleDetail(${s.id})">📋 详情</button>
                    ${s.status === 'draft' ? `<button class="btn btn-outline" onclick="openDsScheduleModal(${s.id})">✏️ 编辑</button>` : ''}
                    ${s.status === 'draft' ? `<button class="btn btn-success" onclick="dsPublishSchedule(${s.id})">📢 发布</button>` : ''}
                    ${s.status === 'published' ? `<button class="btn btn-warning" onclick="dsLockSchedule(${s.id})">🔒 锁定</button>` : ''}
                    ${s.status === 'locked' ? `<button class="btn btn-outline" onclick="dsUnlockSchedule(${s.id})">🔓 解锁</button>` : ''}
                    ${['draft', 'published'].includes(s.status) ? `<button class="btn btn-danger" onclick="dsCancelScheduleConfirm(${s.id})">⏹ 撤销</button>` : ''}
                    <button class="btn btn-outline" onclick="dsCopyScheduleConfirm(${s.id})">📑 复制</button>
                    ${['published', 'locked', 'executing'].includes(s.status) && !s.batch_id ? `<button class="btn btn-primary" onclick="dsGenerateBatch(${s.id})">▶️ 生成批次</button>` : ''}
                    ${s.batch_id ? `<button class="btn btn-outline" onclick="openBatchDetailFromSchedule('${escapeHtml(s.batch_id)}')">📦 查看批次</button>` : ''}
                    ${['draft', 'cancelled'].includes(s.status) ? `<button class="btn btn-danger" onclick="dsDeleteSchedule(${s.id})">🗑️ 删除</button>` : ''}
                    ${s.status === 'cancelled' ? `<button class="btn btn-outline" onclick="dsCleanupSchedule(${s.id})">🧹 清理资源</button>` : ''}
                </div>
            </div>`;
        }).join('');
    }

    function openBatchDetailFromSchedule(bid) { showBatchDetail(bid); }

    function renderDsCalendar() {
        const calEl = document.getElementById('ds-calendar');
        if (!calEl) return;

        const y = dsCalendarDate.getFullYear();
        const m = dsCalendarDate.getMonth();
        const first = new Date(y, m, 1);
        const last = new Date(y, m + 1, 0);
        const startDow = first.getDay();
        const daysInMonth = last.getDate();

        document.getElementById('ds-cal-title').textContent = `${y}年${m + 1}月`;

        let html = '<div class="calendar-grid-header">日一二三四五六</div><div class="calendar-grid">';
        for (let i = 0; i < startDow; i++) html += '<div class="calendar-cell calendar-cell-empty"></div>';

        const pad = n => String(n).padStart(2, '0');
        const todayStr = new Date();
        const todayStrS = `${todayStr.getFullYear()}-${pad(todayStr.getMonth() + 1)}-${pad(todayStr.getDate())}`;

        for (let d = 1; d <= daysInMonth; d++) {
            const ds = `${y}-${pad(m + 1)}-${pad(d)}`;
            const daySched = dsSchedules.filter(s => s.schedule_date === ds);
            const hasConflict = daySched.some(s => s.conflicts && s.conflicts.length);
            html += `<div class="calendar-cell ${ds === todayStrS ? 'calendar-cell-today' : ''} ${hasConflict ? 'calendar-cell-conflict' : ''}" onclick="dsSelectCalendarDay('${ds}')">
                <div class="calendar-cell-date">${d}</div>
                <div class="calendar-cell-events">
                    ${daySched.slice(0, 3).map(s => {
                        const cls = DSScheduleStatusClass[s.status] || 'status-batch-pending';
                        return `<div class="cal-event cal-event-${s.status}" title="${escapeHtml(s.title)}&#10;${formatDsTimeHHMM(s.start_time)}-${formatDsTimeHHMM(s.end_time)}&#10;${escapeHtml(s.venue_name||'')}">
                            <span class="cal-event-time">${formatDsTimeHHMM(s.start_time)}</span> ${escapeHtml(s.title.length > 6 ? s.title.substring(0, 6) + '…' : s.title)}
                        </div>`;
                    }).join('')}
                    ${daySched.length > 3 ? `<div class="cal-event-more">+${daySched.length - 3} 更多</div>` : ''}
                </div>
            </div>`;
        }
        html += '</div>';
        calEl.innerHTML = html;
    }

    function dsPrevMonth() { dsCalendarDate.setMonth(dsCalendarDate.getMonth() - 1); renderDsCalendar(); }
    function dsNextMonth() { dsCalendarDate.setMonth(dsCalendarDate.getMonth() + 1); renderDsCalendar(); }
    function dsGoToday() { dsCalendarDate = new Date(); renderDsCalendar(); }
    function dsSelectCalendarDay(dateStr) {
        if (document.getElementById('ds-cal-start')) document.getElementById('ds-cal-start').value = dateStr;
        if (document.getElementById('ds-cal-end')) document.getElementById('ds-cal-end').value = dateStr;
        dsScheduleFilter.from_date = dateStr;
        dsScheduleFilter.to_date = dateStr;
        renderDsSchedules();
    }

    function openDsScheduleModal(scheduleId = null) {
        dsEditingScheduleId = scheduleId;
        document.getElementById('ds-sched-warn').style.display = 'none';
        document.getElementById('ds-sched-id').value = '';
        document.getElementById('ds-sched-title').value = '';
        document.getElementById('ds-sched-notes').value = '';

        const today = new Date(); const pad = n => String(n).padStart(2, '0');
        document.getElementById('ds-sched-date').value = scheduleId ? '' : `${today.getFullYear()}-${pad(today.getMonth() + 1)}-${pad(today.getDate())}`;
        document.getElementById('ds-sched-start').value = '09:00';
        document.getElementById('ds-sched-end').value = '12:00';
        document.getElementById('ds-sched-venue-tpl').value = '';
        document.getElementById('ds-sched-group-tpl').value = '';
        document.getElementById('ds-sched-check-tpl').value = '';
        document.getElementById('ds-sched-clean-tpl').value = '';
        document.getElementById('ds-sched-script').value = '';
        document.getElementById('ds-sched-venue').value = '';

        if (scheduleId) {
            const s = dsSchedules.find(x => x.id === scheduleId);
            if (s) {
                document.getElementById('ds-sched-modal-title').textContent = '编辑排期';
                document.getElementById('ds-sched-id').value = s.id;
                document.getElementById('ds-sched-title').value = s.title;
                document.getElementById('ds-sched-date').value = s.schedule_date;
                document.getElementById('ds-sched-start').value = s.start_time;
                document.getElementById('ds-sched-end').value = s.end_time;
                document.getElementById('ds-sched-venue').value = s.venue_id || '';
                document.getElementById('ds-sched-venue-tpl').value = s.venue_template_id || '';
                document.getElementById('ds-sched-group-tpl').value = s.group_template_id || '';
                document.getElementById('ds-sched-check-tpl').value = s.checklist_template_id || '';
                document.getElementById('ds-sched-clean-tpl').value = s.cleanup_template_id || '';
                document.getElementById('ds-sched-script').value = s.script_id || '';
                document.getElementById('ds-sched-notes').value = s.notes || '';
                if (s.status !== 'draft') {
                    showToast('已发布的排期仅能修改标题和备注，其他字段需先撤销', 'warning');
                }
            }
        } else {
            document.getElementById('ds-sched-modal-title').textContent = '新建排期';
        }
        openModal('ds-schedule-modal');
    }

    async function submitDsSchedule() {
        const id = document.getElementById('ds-sched-id').value;
        const title = document.getElementById('ds-sched-title').value.trim();
        if (!title) { showToast('请填写排期标题', 'warning'); return; }

        const payload = {
            title,
            schedule_date: document.getElementById('ds-sched-date').value,
            start_time: document.getElementById('ds-sched-start').value,
            end_time: document.getElementById('ds-sched-end').value,
            venue_id: Number(document.getElementById('ds-sched-venue').value) || null,
            venue_template_id: Number(document.getElementById('ds-sched-venue-tpl').value) || null,
            group_template_id: Number(document.getElementById('ds-sched-group-tpl').value) || null,
            checklist_template_id: Number(document.getElementById('ds-sched-check-tpl').value) || null,
            cleanup_template_id: Number(document.getElementById('ds-sched-clean-tpl').value) || null,
            script_id: Number(document.getElementById('ds-sched-script').value) || null,
            notes: document.getElementById('ds-sched-notes').value.trim() || null
        };

        try {
            if (id) {
                await apiRequest(`${DS_API}/schedules/${id}`, { method: 'PUT', body: JSON.stringify(payload) });
                showToast('排期更新成功');
            } else {
                await apiRequest(`${DS_API}/schedules`, { method: 'POST', body: JSON.stringify(payload) });
                showToast('排期创建成功');
            }
            closeModal('ds-schedule-modal');
            loadDsSchedules();
        } catch (e) {
            const warnEl = document.getElementById('ds-sched-warn');
            const errors = e.detail?.errors ? e.detail.errors.join('; ') : '';
            let conflictsHtml = '';
            if (e.detail?.conflicts && e.detail.conflicts.length) {
                conflictsHtml = `<div style="margin-top:6px;color:#ef4444;"><strong>冲突详情:</strong><ul style="margin:4px 0 0 16px;">${e.detail.conflicts.map(c => `<li>${escapeHtml(c.reason||'未知冲突')} (${escapeHtml(c.type||'')})</li>`).join('')}</ul></div>`;
            }
            warnEl.innerHTML = `<h3>❌ ${escapeHtml(e.detail?.message || e.detail || e.message || '保存失败')}</h3>${errors ? `<div style="margin-top:6px;color:#ef4444;">${escapeHtml(errors)}</div>` : ''}${conflictsHtml}`;
            warnEl.style.display = 'block';
        }
    }

    async function dsCheckConflict() {
        const venueId = Number(document.getElementById('ds-sched-venue').value) || null;
        const d = document.getElementById('ds-sched-date').value;
        const st = document.getElementById('ds-sched-start').value;
        const et = document.getElementById('ds-sched-end').value;
        if (!d || !st || !et || !venueId) { showToast('请先选择日期、时间和场地再检测', 'warning'); return; }
        const sid = document.getElementById('ds-sched-id').value || null;
        try {
            const r = await apiRequest(`${DS_API}/schedules/check-conflicts?schedule_date=${d}&start_time=${st}&end_time=${et}&venue_id=${venueId}${sid ? '&exclude_schedule_id=' + sid : ''}`);
            const warnEl = document.getElementById('ds-sched-warn');
            if (r.ok) {
                warnEl.innerHTML = `<h3 style="color:#059669;">✅ 检测通过，无冲突 (检测了 ${r.checked_scopes?.join(', ') || '排期+预约+封场'})</h3>`;
            } else {
                warnEl.innerHTML = `<h3>⚠️ 检测到 ${r.conflicts?.length || 0} 个冲突</h3>
                    <ul style="margin:6px 0 0 16px;color:#ef4444;">${(r.conflicts || []).map(c => `<li>${escapeHtml(c.reason || '未知')} [${escapeHtml(c.type || '')}]</li>`).join('')}</ul>`;
            }
            warnEl.style.display = 'block';
        } catch (e) { handleApiError(e); }
    }

    async function showDsScheduleDetail(sid) {
        try {
            const s = await apiRequest(`${DS_API}/schedules/${sid}`);
            document.getElementById('ds-detail-modal-title').textContent = `排期详情: ${s.title} #${s.schedule_no || s.id}`;
            const snap = typeof s.template_snapshot === 'string' ? s.template_snapshot : JSON.stringify(s.template_snapshot || {}, null, 2);
            const stCls = DSScheduleStatusClass[s.status] || 'status-batch-pending';
            const stLabel = DSScheduleStatusLabel[s.status] || s.status;

            let membersHtml = '';
            if (s.members && s.members.length) {
                membersHtml = `<div class="detail-section"><h3>👥 成员 (${s.members.length})</h3>
                    <div style="display:grid;grid-template-columns:repeat(2,1fr);gap:6px;">
                    ${s.members.map(m => `<div style="padding:6px 8px;background:#f3f4f6;border-radius:4px;font-size:13px;">
                        ${escapeHtml(m.role_in_schedule || '成员')}: <strong>${escapeHtml(m.user_full_name || m.user_username || '?')}</strong>
                        ${m.group_name ? ` <span style="color:#666;">[${escapeHtml(m.group_name)}]</span>` : ''}
                        ${m.user_email ? `<div style="font-size:11px;color:#888;">${escapeHtml(m.user_email)}</div>` : ''}
                    </div>`).join('')}</div></div>`;
            }
            let conflictHtml = '';
            if (s.conflicts && s.conflicts.length) {
                conflictHtml = `<div class="detail-section"><h3 style="color:#ef4444;">⚠️ 冲突 (${s.conflicts.length})</h3>
                    ${s.conflicts.map(c => `<div style="padding:8px 10px;background:#fef2f2;border-radius:4px;margin-bottom:6px;">
                        <strong>[${escapeHtml(c.type || '')}]</strong> ${escapeHtml(c.reason || '')}
                        ${c.with_schedule_no ? `<div style="font-size:11px;color:#b91c1c;margin-top:2px;">撞车排期: #${escapeHtml(c.with_schedule_no)}</div>` : ''}
                    </div>`).join('')}</div>`;
            }
            let auditHtml = '';
            if (s.recent_audits && s.recent_audits.length) {
                auditHtml = `<div class="detail-section"><h3>📝 近期变更 (${s.recent_audits.length})</h3>
                    ${s.recent_audits.map(a => `<div style="padding:6px 10px;border-left:3px solid #3b82f6;background:#eff6ff;border-radius:0 4px 4px 0;margin-bottom:4px;">
                        <div style="font-size:12px;"><strong>${escapeHtml(a.action_name || a.action || '')}</strong> by ${escapeHtml(a.operator_name || '-')} @ ${formatDateTime(a.created_at)}</div>
                        ${a.old_value ? `<div style="font-size:11px;color:#666;margin-top:2px;"><strong>旧值:</strong> ${escapeHtml(JSON.stringify(a.old_value).substring(0,200))}</div>` : ''}
                        ${a.new_value ? `<div style="font-size:11px;color:#10b981;margin-top:2px;"><strong>新值:</strong> ${escapeHtml(JSON.stringify(a.new_value).substring(0,200))}</div>` : ''}
                        ${a.ip_address ? `<div style="font-size:11px;color:#999;">IP: ${escapeHtml(a.ip_address)}</div>` : ''}
                    </div>`).join('')}</div>`;
            }
            let artifactsHtml = '';
            if (s.downloads && s.downloads.length) {
                artifactsHtml = `<div class="detail-section"><h3>📥 下载摘要</h3>${s.downloads.map(d => `<a href="${escapeHtml(d.url)}" target="_blank" class="btn btn-outline" style="display:inline-block;margin:2px;">${escapeHtml(d.title)}</a>`).join('')}</div>`;
            }
            let resultHtml = '';
            if (s.execution_result) {
                resultHtml = `<div class="detail-section"><h3>📊 执行结果</h3>
                    <pre style="background:#f3f4f6;padding:10px;border-radius:6px;font-size:12px;max-height:180px;overflow:auto;">${escapeHtml(typeof s.execution_result==='string'?s.execution_result:JSON.stringify(s.execution_result,null,2))}</pre></div>`;
            }

            document.getElementById('ds-detail-body').innerHTML = `
                <div class="detail-section">
                    <div class="detail-row"><span>状态:</span><span class="status-badge ${stCls}">${stLabel}</span></div>
                    <div class="detail-row"><span>日期:</span><strong>${escapeHtml(s.schedule_date || '-')}</strong></div>
                    <div class="detail-row"><span>时段:</span>${formatDsTimeHHMM(s.start_time)} ~ ${formatDsTimeHHMM(s.end_time)}</div>
                    <div class="detail-row"><span>场地:</span>${escapeHtml(s.venue_name || '-')}</div>
                    <div class="detail-row"><span>创建:</span>${formatDateTime(s.created_at)} by ${escapeHtml(s.created_by_name || '-')}</div>
                    ${s.batch_id ? `<div class="detail-row"><span>执行批次:</span><a href="javascript:void(0)" onclick="openBatchDetailFromSchedule('${escapeHtml(s.batch_id)}')">${escapeHtml(s.batch_id)}</a></div>` : ''}
                    ${s.published_at ? `<div class="detail-row"><span>发布时间:</span>${formatDateTime(s.published_at)}</div>` : ''}
                    ${s.notes ? `<div class="detail-row"><span>备注:</span>${escapeHtml(s.notes)}</div>` : ''}
                </div>
                ${s.template_snapshot ? `<div class="detail-section"><h3>📸 模板快照(发布时隔离，已不受后续模板改动影响)</h3>
                    <pre style="background:#f0fdf4;padding:10px;border-radius:6px;font-size:11px;max-height:200px;overflow:auto;">${escapeHtml(snap)}</pre></div>` : ''}
                ${membersHtml}${conflictHtml}${resultHtml}${artifactsHtml}${auditHtml}`;

            const isAdmin = currentUser?.role === 'admin';
            let footerBtns = `<button class="btn btn-outline modal-close-btn">关闭</button>`;
            if (isAdmin) {
                if (s.status === 'draft') footerBtns += `<button class="btn btn-success" onclick="dsPublishSchedule(${s.id});closeModal('ds-schedule-detail-modal');">📢 发布</button>`;
                if (s.status === 'published') footerBtns += `<button class="btn btn-warning" onclick="dsLockSchedule(${s.id});closeModal('ds-schedule-detail-modal');">🔒 锁定</button>`;
                if (s.status === 'locked') footerBtns += `<button class="btn btn-outline" onclick="dsUnlockSchedule(${s.id});closeModal('ds-schedule-detail-modal');">🔓 解锁</button>`;
                if (['draft', 'published'].includes(s.status)) footerBtns += `<button class="btn btn-danger" onclick="dsCancelScheduleConfirm(${s.id});closeModal('ds-schedule-detail-modal');">⏹ 撤销</button>`;
                if (['published', 'locked', 'executing'].includes(s.status) && !s.batch_id) footerBtns += `<button class="btn btn-primary" onclick="dsGenerateBatch(${s.id});closeModal('ds-schedule-detail-modal');">▶️ 生成批次</button>`;
                footerBtns += `<button class="btn btn-outline" onclick="dsCopyScheduleConfirm(${s.id});closeModal('ds-schedule-detail-modal');">📑 复制</button>`;
                if (s.status === 'cancelled') footerBtns += `<button class="btn btn-danger" onclick="dsCleanupSchedule(${s.id});closeModal('ds-schedule-detail-modal');">🧹 清理资源</button>`;
            }
            document.getElementById('ds-detail-footer').innerHTML = footerBtns;
            bindModalClose(); openModal('ds-schedule-detail-modal');
        } catch (e) { handleApiError(e); }
    }

    async function dsPublishSchedule(sid) {
        try {
            await apiRequest(`${DS_API}/schedules/${sid}/publish`, { method: 'POST' });
            showToast('排期已发布，模板快照已保存');
            loadDsSchedules();
        } catch (e) { handleApiError(e); }
    }
    async function dsLockSchedule(sid) {
        try { await apiRequest(`${DS_API}/schedules/${sid}/lock`, { method: 'POST' }); showToast('排期已锁定'); loadDsSchedules(); }
        catch (e) { handleApiError(e); }
    }
    async function dsUnlockSchedule(sid) {
        try { await apiRequest(`${DS_API}/schedules/${sid}/unlock`, { method: 'POST' }); showToast('排期已解锁'); loadDsSchedules(); }
        catch (e) { handleApiError(e); }
    }
    function dsCancelScheduleConfirm(sid) {
        const s = dsSchedules.find(x => x.id === sid); dsCancelSchedId = sid;
        document.getElementById('ds-cancel-hint').textContent = s ? `确定要撤销 "${s.title}" (#${s.schedule_no||sid}) 吗？所有关联资源(样本数据、占位记录)将被清理，该操作不可恢复。` : '确定撤销？';
        document.getElementById('ds-cancel-reason').value = '';
        openModal('ds-cancel-modal');
    }
    async function dsCancelScheduleSubmit() {
        if (!dsCancelSchedId) return;
        const reason = document.getElementById('ds-cancel-reason').value.trim();
        try {
            const r = await apiRequest(`${DS_API}/schedules/${dsCancelSchedId}/cancel`, {
                method: 'POST', body: JSON.stringify({ reason: reason || null })
            });
            showToast(`排期已撤销，清理结果：占位${r.cleanup_result?.placeholders_deleted||0}条，临时文件${r.cleanup_result?.temp_files_deleted||0}个，样本${r.cleanup_result?.samples_cleared||0}条`);
            closeModal('ds-cancel-modal');
            dsCancelSchedId = null;
            loadDsSchedules();
        } catch (e) { handleApiError(e); }
    }
    function dsCopyScheduleConfirm(sid) {
        const s = dsSchedules.find(x => x.id === sid); dsCopySchedId = sid;
        document.getElementById('ds-copy-hint').textContent = s ? `将复制排期 "${s.title}" (#${s.schedule_no||sid})，系统会自动分配新的唯一编号。` : '';
        document.getElementById('ds-copy-date').value = s?.schedule_date || '';
        openModal('ds-copy-modal');
    }
    async function dsCopyScheduleSubmit() {
        if (!dsCopySchedId) return;
        const newDate = document.getElementById('ds-copy-date').value || null;
        try {
            const r = await apiRequest(`${DS_API}/schedules/${dsCopySchedId}/copy`, {
                method: 'POST', body: JSON.stringify(newDate ? { new_schedule_date: newDate } : {})
            });
            showToast(`复制成功！新排期编号: ${r.new_schedule_no} (ID=${r.new_schedule_id})`);
            closeModal('ds-copy-modal');
            dsCopySchedId = null;
            loadDsSchedules();
        } catch (e) { handleApiError(e); }
    }
    async function dsGenerateBatch(sid) {
        try {
            const r = await apiRequest(`${DS_API}/schedules/${sid}/generate-batch`, { method: 'POST' });
            showToast(`执行批次已生成: ${r.batch_id} (${r.status})`);
            loadDsSchedules();
        } catch (e) { handleApiError(e); }
    }
    async function dsCleanupSchedule(sid) {
        if (!confirm('清理该排期的残余资源(样本、临时文件、占位记录)？')) return;
        try {
            const r = await apiRequest(`${DS_API}/schedules/${sid}/cleanup`, { method: 'POST' });
            showToast(`清理完成: 占位${r.placeholders_deleted||0}，文件${r.temp_files_deleted||0}，样本${r.samples_cleared||0}`);
            loadDsSchedules();
        } catch (e) { handleApiError(e); }
    }
    async function dsDeleteSchedule(sid) {
        if (!confirm('确定删除此排期？(建议先撤销，会联动清理)')) return;
        try {
            await apiRequest(`${DS_API}/schedules/${sid}`, { method: 'DELETE' });
            showToast('排期已删除');
            loadDsSchedules();
        } catch (e) { handleApiError(e); }
    }

    async function loadDsMine() {
        try {
            dsMineSchedules = await apiRequest(`${DS_API}/schedules/mine`);
            renderDsMine();
        } catch (e) { showToast('加载我的排期失败: ' + (e.detail?.message || e.detail || e.message), 'error'); }
    }

    function renderDsMine() {
        const listEl = document.getElementById('ds-mine-list');
        setDsElText('ds-mine-count', `共 ${dsMineSchedules.length} 场`);
        if (dsMineSchedules.length === 0) {
            listEl.innerHTML = '<div style="text-align:center;padding:40px;color:#999;">暂无您参与的排期</div>';
            return;
        }
        listEl.innerHTML = dsMineSchedules.map(s => {
            const stCls = DSScheduleStatusClass[s.status] || 'status-batch-pending';
            const stLabel = DSScheduleStatusLabel[s.status] || s.status;
            let clHtml = '';
            if (s.member_checklist && s.member_checklist.length) {
                clHtml = `<div style="margin-top:6px;"><h4 style="font-size:12px;margin:4px 0;">✅ 准备清单 (点击勾选)</h4>
                    ${s.member_checklist.map((c,i) => `
                    <label style="display:block;font-size:12px;padding:3px 0;">
                        <input type="checkbox" ${c.checked?'checked':''} onchange="dsMineCheckItem(${s.id},${i},this.checked)" ${s.status==='cancelled'||s.status==='completed'?'disabled':''}>
                        <strong>${escapeHtml(c.name)}</strong> ${c.required?'<span style="color:#ef4444;">*</span>':''}
                        ${c.description?`<span style="color:#666;"> - ${escapeHtml(c.description)}</span>`:''}
                    </label>`).join('')}</div>`;
            }
            let dwHtml = '';
            if (s.downloads && s.downloads.length) {
                dwHtml = `<div style="margin-top:6px;font-size:12px;">📥 ${s.downloads.map(d => `<a href="${escapeHtml(d.url)}" target="_blank" style="margin-right:8px;color:#2563eb;">${escapeHtml(d.title)}</a>`).join('')}</div>`;
            }
            let resHtml = '';
            if (s.execution_result) {
                resHtml = `<div style="margin-top:6px;background:#f0fdf4;padding:6px 8px;border-radius:4px;font-size:11px;">📊 ${escapeHtml(typeof s.execution_result==='string'?s.execution_result:JSON.stringify(s.execution_result))}</div>`;
            }
            return `<div class="script-card">
                <div class="script-card-header">
                    <span class="script-card-title">📍 ${escapeHtml(s.title)}<span class="status-badge ${stCls}" style="font-size:12px;margin-left:8px;">${stLabel}</span></span>
                    <span style="font-size:12px;color:#666;">#${escapeHtml(s.schedule_no || s.id)}</span>
                </div>
                <div class="script-card-meta">
                    <span>🗓 ${escapeHtml(s.schedule_date||'-')}</span>
                    <span>⏰ ${formatDsTimeHHMM(s.start_time)}~${formatDsTimeHHMM(s.end_time)}</span>
                    <span>🏢 ${escapeHtml(s.venue_name||'-')}</span>
                    <span>👥 ${escapeHtml(s.my_role || '成员')}${s.my_group ? ` [${escapeHtml(s.my_group)}]` : ''}</span>
                </div>
                ${clHtml}${resHtml}${dwHtml}
                ${s.batch_id ? `<div class="script-card-actions" style="margin-top:8px;"><button class="btn btn-primary" onclick="openBatchDetailFromSchedule('${escapeHtml(s.batch_id)}')">▶️ 进入执行</button></div>` : ''}
            </div>`;
        }).join('');
    }

    async function dsMineCheckItem(sid, idx, checked) {
        try {
            await apiRequest(`${DS_API}/schedules/mine/checklist/${idx}`, {
                method: 'POST', body: JSON.stringify({ checked })
            });
        } catch (e) { handleApiError(e); }
    }

    async function loadDsAudit() {
        try {
            const params = new URLSearchParams();
            if (dsAuditFilter.resource_type) params.append('resource_type', dsAuditFilter.resource_type);
            if (dsAuditFilter.action) params.append('action', dsAuditFilter.action);
            if (dsAuditFilter.operator) params.append('operator_keyword', dsAuditFilter.operator);
            if (dsAuditFilter.from_date) params.append('from_date', dsAuditFilter.from_date);
            if (dsAuditFilter.to_date) params.append('to_date', dsAuditFilter.to_date);

            dsAuditLogs = await apiRequest(`${DS_API}/audit-logs?${params.toString()}`);
            renderDsAudit();
        } catch (e) { showToast('加载审计日志失败', 'error'); }
    }

    function renderDsAudit() {
        const listEl = document.getElementById('ds-audit-list');
        setDsElText('ds-audit-count', `共 ${dsAuditLogs.length} 条`);
        if (dsAuditLogs.length === 0) { listEl.innerHTML = '<div style="text-align:center;padding:40px;color:#999;">暂无审计日志</div>'; return; }
        listEl.innerHTML = dsAuditLogs.map(a => `
            <div style="padding:10px 12px;border:1px solid #e5e7eb;border-radius:6px;margin-bottom:8px;">
                <div style="display:flex;justify-content:space-between;margin-bottom:4px;flex-wrap:wrap;">
                    <span><strong style="color:#3b82f6;">${escapeHtml(a.action_name || a.action || '')}</strong>
                        <span style="color:#666;">[${escapeHtml(a.resource_type || '')}]</span>
                        ${a.resource_id ? `<code>#${escapeHtml(a.resource_id)}</code>` : ''}
                        ${a.resource_title ? ` - ${escapeHtml(a.resource_title)}` : ''}
                    </span>
                    <span style="font-size:12px;color:#666;">${formatDateTime(a.created_at)} · ${escapeHtml(a.operator_name || '-')} · ${escapeHtml(a.ip_address || '-')}</span>
                </div>
                ${a.old_value ? `<div style="font-size:11px;color:#9ca3af;">旧: ${escapeHtml(JSON.stringify(a.old_value).substring(0,200))}</div>` : ''}
                ${a.new_value ? `<div style="font-size:11px;color:#10b981;">新: ${escapeHtml(JSON.stringify(a.new_value).substring(0,200))}</div>` : ''}
                ${a.reason ? `<div style="font-size:12px;color:#ef4444;">原因: ${escapeHtml(a.reason)}</div>` : ''}
            </div>`).join('');
    }

    async function dsTriggerRecover() {
        if (!confirm('手动触发待执行排期的恢复检测(通常服务启动时自动执行)？')) return;
        try {
            const r = await apiRequest(`${DS_API}/schedules/recover`, { method: 'POST' });
            showToast(`恢复完成: 共 ${r.items?.length || 0} 条，已恢复 ${r.recovered_count || 0} 条` + (r.message ? `\n${r.message}` : ''));
            loadDsSchedules();
        } catch (e) { handleApiError(e); }
    }

    function openDsBatchModal() {
        document.getElementById('ds-batch-warn').style.display = 'none';
        const today = new Date(); const pad = n => String(n).padStart(2, '0');
        document.getElementById('ds-batch-start').value = `${today.getFullYear()}-${pad(today.getMonth() + 1)}-${pad(today.getDate())}`;
        const end = new Date(today); end.setDate(end.getDate() + 13);
        document.getElementById('ds-batch-end').value = `${end.getFullYear()}-${pad(end.getMonth() + 1)}-${pad(end.getDate())}`;
        openModal('ds-batch-modal');
    }

    async function submitDsBatchGenerate() {
        const venue_tpl_id = Number(document.getElementById('ds-batch-venue-tpl').value) || null;
        const start = document.getElementById('ds-batch-start').value;
        const end = document.getElementById('ds-batch-end').value;
        const prefix = document.getElementById('ds-batch-prefix').value.trim();
        const group_tpl_id = Number(document.getElementById('ds-batch-group-tpl').value) || null;
        const script_id = Number(document.getElementById('ds-batch-script').value) || null;
        if (!venue_tpl_id || !start || !end) { showToast('请填写场地模板和日期范围', 'warning'); return; }
        try {
            const r = await apiRequest(`${DS_API}/schedules/batch-generate`, {
                method: 'POST',
                body: JSON.stringify({
                    venue_template_id: venue_tpl_id,
                    start_date: start,
                    end_date: end,
                    base_title: prefix || '演练',
                    group_template_id: group_tpl_id,
                    drill_script_id: script_id,
                    exclude_weekends: true
                })
            });
            showToast(`批量生成完成: 成功${r.created_count||0}，跳过冲突${r.skipped_conflicts||0}`);
            closeModal('ds-batch-modal');
            loadDsSchedules();
        } catch (e) {
            const warn = document.getElementById('ds-batch-warn');
            warn.innerHTML = `<h3>❌ ${escapeHtml(e.detail?.message || e.detail || e.message || '生成失败')}</h3>`;
            warn.style.display = 'block';
        }
    }

    document.querySelectorAll('.ds-subtab').forEach(t => {
        t.addEventListener('click', () => switchDsSubtab(t.dataset.subtab));
    });
    document.getElementById('ds-tpl-new-btn')?.addEventListener('click', () => openDsTemplateModal());
    document.getElementById('ds-tpl-submit-btn')?.addEventListener('click', submitDsTemplate);
    document.getElementById('ds-tpl-import-btn')?.addEventListener('click', triggerDsTemplateImport);
    document.getElementById('ds-tpl-import-file')?.addEventListener('change', handleDsTemplateImportFile);
    document.getElementById('ds-tpl-search-btn')?.addEventListener('click', () => {
        dsTemplateFilter.keyword = (document.getElementById('ds-tpl-keyword')?.value || '').trim();
        dsTemplateFilter.ttype = document.getElementById('ds-tpl-type')?.value || '';
        dsTemplateFilter.is_active = document.getElementById('ds-tpl-status')?.value || '';
        loadDsTemplates();
    });
    document.getElementById('ds-tpl-reset-btn')?.addEventListener('click', () => {
        if (document.getElementById('ds-tpl-keyword')) document.getElementById('ds-tpl-keyword').value = '';
        if (document.getElementById('ds-tpl-type')) document.getElementById('ds-tpl-type').value = '';
        if (document.getElementById('ds-tpl-status')) document.getElementById('ds-tpl-status').value = '';
        dsTemplateFilter = { keyword: '', ttype: '', is_active: '' };
        loadDsTemplates();
    });
    document.getElementById('ds-cal-create-btn')?.addEventListener('click', () => openDsScheduleModal());
    document.getElementById('ds-tpl-create-btn')?.addEventListener('click', () => openDsTemplateModal());
    document.getElementById('ds-cal-batch-btn')?.addEventListener('click', openDsBatchModal);
    document.getElementById('ds-sched-submit-btn')?.addEventListener('click', submitDsSchedule);
    document.getElementById('ds-sched-check-btn')?.addEventListener('click', dsCheckConflict);
    document.getElementById('ds-batch-submit-btn')?.addEventListener('click', submitDsBatchGenerate);
    document.getElementById('ds-cancel-submit-btn')?.addEventListener('click', dsCancelScheduleSubmit);
    document.getElementById('ds-copy-submit-btn')?.addEventListener('click', dsCopyScheduleSubmit);
    document.getElementById('ds-cal-refresh-btn')?.addEventListener('click', () => {
        dsScheduleFilter.keyword = (document.getElementById('ds-sched-f-keyword')?.value || '').trim();
        dsScheduleFilter.status = document.getElementById('ds-sched-f-status')?.value || '';
        dsScheduleFilter.venue_id = document.getElementById('ds-cal-venue')?.value || '';
        dsScheduleFilter.from_date = document.getElementById('ds-cal-start')?.value || '';
        dsScheduleFilter.to_date = document.getElementById('ds-cal-end')?.value || '';
        loadDsSchedules();
    });
    document.getElementById('ds-cal-prev')?.addEventListener('click', dsPrevMonth);
    document.getElementById('ds-cal-next')?.addEventListener('click', dsNextMonth);
    document.getElementById('ds-cal-today')?.addEventListener('click', dsGoToday);
    document.getElementById('ds-audit-recover-btn')?.addEventListener('click', dsTriggerRecover);
    document.getElementById('ds-audit-refresh-btn')?.addEventListener('click', () => {
        dsAuditFilter.resource_type = '';
        dsAuditFilter.action = document.getElementById('ds-audit-action')?.value || '';
        dsAuditFilter.operator = '';
        dsAuditFilter.from_date = '';
        dsAuditFilter.to_date = '';
        loadDsAudit();
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
