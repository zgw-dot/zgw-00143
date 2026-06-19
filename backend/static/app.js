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

    const optionsHtml = venues.map(v => `<option value="${v.id}">${v.name}</option>`).join('');

    filterSelect.innerHTML = '<option value="">全部场地</option>' + optionsHtml;
    bookingSelect.innerHTML = '<option value="">请选择场地</option>' + optionsHtml;
    closedVenueSelect.innerHTML = '<option value="">全部场地</option>' + optionsHtml;
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

    listEl.innerHTML = data.items.map(booking => `
        <div class="booking-card" onclick="showBookingDetail(${booking.id})">
            <div class="booking-card-header">
                <span class="booking-card-title">${escapeHtml(booking.title)}</span>
                <span class="status-badge ${getStatusClass(booking.status)}">${getStatusText(booking.status)}</span>
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
    `).join('');
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
    await loadPriorityRules();
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
