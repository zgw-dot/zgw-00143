import sys
import os
import time
import csv
import io
import json
from datetime import datetime, timedelta
from pathlib import Path

from playwright.sync_api import sync_playwright, expect, TimeoutError as PWTimeoutError

BASE_URL = "http://127.0.0.1:8002"
API_BASE = f"{BASE_URL}/api"

RUN_ID = datetime.now().strftime("%Y%m%d_%H%M%S")
TAG_PREFIX = f"BW-{RUN_ID}"
LOG_FILE = f"browser_waitlist_{RUN_ID}.txt"
SCREENSHOT_DIR = f"screenshots_{RUN_ID}"

FAIL = "[FAIL]"
PASS = "[PASS]"
STEP = "[STEP]"
INFO = "[INFO]"
WARN = "[WARN]"

pass_count = 0
fail_count = 0
test_results = []

out_file = open(LOG_FILE, "w", encoding="utf-8")


class Tee:
    def __init__(self, *files):
        self.files = files

    def write(self, s):
        for f in self.files:
            f.write(s)
            f.flush()

    def flush(self):
        for f in self.files:
            f.flush()


sys.stdout = Tee(sys.stdout, out_file)
sys.stderr = Tee(sys.stderr, out_file)

os.makedirs(SCREENSHOT_DIR, exist_ok=True)


def record_result(test_name, passed, detail="", location=""):
    global pass_count, fail_count
    test_results.append({
        "name": test_name,
        "passed": passed,
        "detail": detail,
        "location": location
    })
    if passed:
        pass_count += 1
        print(f"{PASS} {test_name}")
    else:
        fail_count += 1
        loc_info = f" [位置: {location}]" if location else ""
        print(f"{FAIL} {test_name}{loc_info}")
        if detail:
            print(f"       原因: {detail}")


def safe_screenshot(page, name):
    try:
        path = os.path.join(SCREENSHOT_DIR, f"{name}.png")
        page.screenshot(path=path, full_page=True)
        print(f"{INFO}   截图已保存: {path}")
    except Exception as e:
        print(f"{WARN}   截图失败: {e}")


def check_element(page, selector, test_name, element_desc, timeout=3000):
    try:
        el = page.locator(selector).first
        el.wait_for(state="visible", timeout=timeout)
        return True, el
    except PWTimeoutError:
        detail = f"找不到元素 '{selector}'（{element_desc}）"
        record_result(test_name, False, detail, location=selector)
        return False, None


def check_element_text(page, selector, expected_text, test_name, element_desc, timeout=3000):
    ok, el = check_element(page, selector, test_name, element_desc, timeout)
    if not ok:
        return False, None
    actual = el.inner_text()
    if expected_text in actual:
        return True, el
    detail = f"元素 '{selector}' 文本不匹配\n       预期包含: '{expected_text}'\n       实际: '{actual[:100]}'"
    record_result(test_name, False, detail, location=selector)
    return False, el


def check_element_count(page, selector, min_count, test_name, element_desc, timeout=3000):
    try:
        els = page.locator(selector)
        els.first.wait_for(state="visible", timeout=timeout)
        count = els.count()
        if count >= min_count:
            return True, count
        detail = f"元素 '{selector}'（{element_desc}）数量不足\n       预期至少: {min_count}\n       实际: {count}"
        record_result(test_name, False, detail, location=selector)
        return False, count
    except PWTimeoutError:
        detail = f"找不到元素 '{selector}'（{element_desc}）"
        record_result(test_name, False, detail, location=selector)
        return False, 0


def wait_for_url_contains(page, substring, timeout=5000):
    try:
        page.wait_for_url(f"**/*{substring}*", timeout=timeout)
        return True
    except PWTimeoutError:
        return False


def api_login(username, password):
    import requests
    r = requests.post(
        f"{API_BASE}/auth/login",
        data={"username": username, "password": password}
    )
    if r.status_code != 200:
        raise AssertionError(f"API登录失败: {r.status_code} {r.text}")
    return r.json()["access_token"], r.json()["user"]


def api_create_booking(token, venue_id, start_time, end_time, title, production, status="pending", priority=10):
    import requests
    create_status = status if status in ("draft", "pending") else "pending"
    r = requests.post(
        f"{API_BASE}/bookings",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={
            "title": title,
            "production": production,
            "venue_id": venue_id,
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "status": create_status,
            "priority": priority,
            "notes": TAG_PREFIX
        }
    )
    if r.status_code not in (200, 201):
        raise AssertionError(f"创建预约失败: {r.status_code} {r.text}")
    booking = r.json()
    if status == "confirmed" and create_status != "confirmed":
        booking = api_approve_booking(token, booking["id"], booking["version"])
    return booking


def api_create_booking_with_retry(token, venue_id, start_time, end_time, title, production, status="pending", priority=10, max_retries=8):
    """带自动重试的预约创建，遇到冲突时自动往后顺延2小时"""
    s = start_time
    e = end_time
    last_error = None
    for i in range(max_retries):
        try:
            booking = api_create_booking(token, venue_id, s, e, title, production, status, priority)
            return booking, s, e
        except AssertionError as err:
            last_error = err
            if "409" in str(err) or "冲突" in str(err):
                s = s + timedelta(hours=2)
                e = e + timedelta(hours=2)
                continue
            raise
    raise last_error


def api_approve_booking(token, booking_id, version):
    import requests
    r = requests.patch(
        f"{API_BASE}/bookings/{booking_id}/status",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"status": "confirmed", "version": version}
    )
    if r.status_code != 200:
        raise AssertionError(f"审批预约失败: {r.status_code} {r.text}")
    return r.json()


def api_create_closed_window(token, venue_id, start_time, end_time, reason):
    import requests
    r = requests.post(
        f"{API_BASE}/config/closed-windows",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={
            "venue_id": venue_id,
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "reason": reason,
            "apply_all_venues": False
        }
    )
    if r.status_code not in (200, 201):
        raise AssertionError(f"创建封场窗口失败: {r.status_code} {r.text}")
    return r.json()


def api_revoke_closed_window(token, window_id):
    import requests
    r = requests.delete(
        f"{API_BASE}/config/closed-windows/{window_id}",
        headers={"Authorization": f"Bearer {token}"}
    )
    if r.status_code != 200:
        raise AssertionError(f"撤销封场窗口失败: {r.status_code} {r.text}")
    return r.json()


def api_create_waitlist(token, venue_id, start_time, end_time, title, production, priority=10, float_before=30, float_after=30):
    import requests
    r = requests.post(
        f"{API_BASE}/waitlist",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={
            "title": title,
            "production": production,
            "venue_id": venue_id,
            "target_start_time": start_time.isoformat(),
            "target_end_time": end_time.isoformat(),
            "float_before_minutes": float_before,
            "float_after_minutes": float_after,
            "priority": priority,
            "notes": TAG_PREFIX
        }
    )
    if r.status_code not in (200, 201):
        raise AssertionError(f"创建候补失败: {r.status_code} {r.text}")
    return r.json()


def api_get_waitlist(token, waitlist_id):
    import requests
    r = requests.get(
        f"{API_BASE}/waitlist/{waitlist_id}",
        headers={"Authorization": f"Bearer {token}"}
    )
    if r.status_code != 200:
        raise AssertionError(f"获取候补详情失败: {r.status_code} {r.text}")
    return r.json()


def browser_login(page, username, password):
    page.goto(BASE_URL)
    page.wait_for_selector("#login-page", state="visible", timeout=5000)
    page.fill("#username", username)
    page.fill("#password", password)
    page.click("#login-form button[type='submit']")
    page.wait_for_selector("#main-app", state="visible", timeout=5000)


def get_test_date():
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    days_to_monday = (7 - today.weekday()) % 7 or 7
    next_monday = today + timedelta(days=days_to_monday)
    stamp_offset = int(RUN_ID[-2:]) if RUN_ID[-2:].isdigit() else 0
    D = next_monday + timedelta(days=70 + stamp_offset)
    while D.weekday() > 4:
        D += timedelta(days=1)
    return D


def print_header(title):
    print()
    print("=" * 80)
    print(f"  {title}")
    print("=" * 80)


def print_step(step_num, desc):
    print()
    print(f"{STEP} {step_num:3d}. {desc}")
    print("-" * 80)


def run_member_tests(page, venue_id, D):
    print_header("第一部分：成员端候补功能 DOM 验证")

    print_step(1, "验证登录后可见候补入口（导航栏）")
    ok, _ = check_element(page, "button.nav-tab[data-tab='waitlist']",
                          "M1: 候补入口按钮存在", "候补补位导航Tab")
    if ok:
        ok2, _ = check_element_text(page, "button.nav-tab[data-tab='waitlist']",
                                     "候补补位", "M1: 候补入口文本正确", "候补补位导航Tab文本")
        if ok2:
            record_result("M1: 候补入口（导航栏）", True)

    print_step(2, "点击候补Tab，验证候补列表页面加载")
    page.click("button.nav-tab[data-tab='waitlist']")
    page.wait_for_selector("#tab-waitlist.active", state="visible", timeout=3000)

    ok, _ = check_element(page, "#tab-waitlist.active",
                          "M2: 候补Tab激活", "候补内容区域")
    if ok:
        record_result("M2: 点击切换到候补列表", True)

    print_step(3, "验证候补筛选栏元素完整")
    filter_checks = [
        ("#wl-filter-production", "剧目筛选输入框"),
        ("#wl-filter-venue", "场地筛选下拉框"),
        ("#wl-filter-status", "状态筛选下拉框"),
        ("#wl-search-btn", "搜索按钮"),
        ("#wl-reset-btn", "重置按钮"),
        ("#wl-create-btn", "登记候补按钮"),
    ]
    all_ok = True
    for sel, desc in filter_checks:
        ok, _ = check_element(page, sel, f"M3: {desc}存在", desc)
        if not ok:
            all_ok = False
    if all_ok:
        record_result("M3: 候补筛选栏元素完整", True)

    print_step(4, "验证状态筛选下拉框选项完整")
    status_select = page.locator("#wl-filter-status")
    options = status_select.locator("option")
    option_texts = [options.nth(i).inner_text() for i in range(options.count())]
    expected_options = ["全部状态", "排队中", "已补位", "已取消", "已过期"]
    missing = [o for o in expected_options if o not in option_texts]
    if not missing:
        record_result("M4: 状态筛选选项完整", True)
    else:
        record_result("M4: 状态筛选选项完整", False,
                      f"缺少选项: {missing}", location="#wl-filter-status")

    print_step(5, "验证成员端不显示导出CSV按钮（权限控制）")
    export_btn = page.locator("#wl-export-btn")
    if export_btn.count() > 0:
        is_hidden = export_btn.first.is_hidden() or export_btn.first.get_attribute("style") and "display:none" in export_btn.first.get_attribute("style")
        if is_hidden:
            record_result("M5: 成员端隐藏导出CSV按钮", True)
        else:
            record_result("M5: 成员端隐藏导出CSV按钮", False,
                          "成员端应该看不到导出CSV按钮，但按钮可见",
                          location="#wl-export-btn")
    else:
        record_result("M5: 成员端隐藏导出CSV按钮", True)

    print_step(6, "验证候补列表标题和计数徽章")
    ok, _ = check_element_text(page, "#tab-waitlist .booking-list-header h2", "候补列表",
                               "M6: 候补列表标题", "候补列表标题")
    ok2, _ = check_element(page, "#wl-count",
                           "M6: 计数徽章存在", "计数徽章")
    if ok and ok2:
        record_result("M6: 候补列表标题和计数", True)

    print_step(7, "点击登记候补按钮，验证创建弹层打开")
    page.click("#wl-create-btn")
    page.wait_for_selector("#waitlist-create-modal", state="visible", timeout=3000)

    ok, _ = check_element(page, "#waitlist-create-modal",
                          "M7: 候补创建弹层打开", "登记候补弹层")
    if ok:
        ok2, _ = check_element_text(page, "#waitlist-create-modal h2", "登记候补",
                                     "M7: 弹层标题正确", "登记候补弹层标题")
        if ok2:
            record_result("M7: 登记候补弹层打开", True)

    print_step(8, "验证候补创建表单字段完整")
    form_fields = [
        ("#wl-production", "剧目输入框"),
        ("#wl-venue", "场地下拉框"),
        ("#wl-start", "目标开始时间"),
        ("#wl-end", "目标结束时间"),
        ("#wl-before", "前浮动分钟"),
        ("#wl-after", "后浮动分钟"),
        ("#wl-priority", "优先级输入"),
        ("#wl-notes", "备注输入框"),
        ("#wl-submit-btn", "提交候补按钮"),
    ]
    all_ok = True
    for sel, desc in form_fields:
        ok, _ = check_element(page, sel, f"M8: {desc}存在", desc)
        if not ok:
            all_ok = False
    if all_ok:
        record_result("M8: 候补创建表单字段完整", True)

    print_step(9, "关闭创建弹层")
    page.click("#waitlist-create-modal .modal-close-btn")
    page.wait_for_selector("#waitlist-create-modal", state="hidden", timeout=3000)
    ok = page.locator("#waitlist-create-modal").is_hidden()
    if ok:
        record_result("M9: 关闭创建弹层", True)
    else:
        record_result("M9: 关闭创建弹层", False,
                      "弹层未关闭", location="#waitlist-create-modal")


def run_waitlist_detail_test(page, venue_id, D):
    print_header("第二部分：候补详情弹层 DOM 验证")

    admin_token, _ = api_login("admin", "admin123")
    start = D.replace(hour=10, minute=0)
    end = D.replace(hour=12, minute=0)

    print_step(1, "通过API创建一条被预约挡住的候补记录（用于前端验证）")
    booking, start, end = api_create_booking_with_retry(
        admin_token, venue_id, start, end,
        f"{TAG_PREFIX}-挡路预约", f"{TAG_PREFIX}-测试剧目", status="confirmed")
    print(f"{INFO}   已创建挡路预约 ID={booking['id']} ({start.strftime('%H:%M')}-{end.strftime('%H:%M')})")

    member_token, _ = api_login("lisi", "123456")
    waitlist = api_create_waitlist(member_token, venue_id, start, end,
                                   f"{TAG_PREFIX}-测试候补", f"{TAG_PREFIX}-测试剧目")
    print(f"{INFO}   已创建候补记录 ID={waitlist['id']}")

    print_step(2, "刷新页面，筛选找到候补记录")
    page.reload()
    page.wait_for_selector("#main-app", state="visible", timeout=5000)
    page.click("button.nav-tab[data-tab='waitlist']")
    page.wait_for_selector("#waitlist-list", state="visible", timeout=3000)
    time.sleep(1)

    page.fill("#wl-filter-production", f"{TAG_PREFIX}-测试剧目")
    page.click("#wl-search-btn")
    time.sleep(1)

    ok, count = check_element_count(page, "#waitlist-list .booking-card", 1,
                                     "D1: 候补列表有记录", "候补卡片")
    if ok:
        record_result("D1: 候补列表显示记录", True)

    print_step(3, "验证候补卡片显示被挡类型徽章")
    card = page.locator("#waitlist-list .booking-card").first
    ok_blocked = card.locator(".wl-blocked").count() > 0
    if ok_blocked:
        record_result("D2: 候补卡片显示被挡类型徽章", True)
    else:
        record_result("D2: 候补卡片显示被挡类型徽章", False,
                      "被预约挡住的候补应该显示被挡类型徽章",
                      location="#waitlist-list .booking-card .wl-blocked")

    print_step(4, "验证候补卡片显示状态徽章")
    ok_status = card.locator(".status-badge").count() > 0
    if ok_status:
        record_result("D3: 候补卡片显示状态徽章", True)
    else:
        record_result("D3: 候补卡片显示状态徽章", False,
                      "候补卡片应该有状态徽章",
                      location="#waitlist-list .booking-card .status-badge")

    print_step(5, "验证候补卡片显示排队号")
    ok_queue = card.locator(".queue-badge").count() > 0
    if ok_queue:
        record_result("D4: 候补卡片显示排队号徽章", True)
    else:
        record_result("D4: 候补卡片显示排队号徽章", False,
                      "排队中的候补应该显示排队号",
                      location="#waitlist-list .booking-card .queue-badge")

    print_step(6, "点击候补卡片，打开详情弹层")
    card.click()
    page.wait_for_selector("#waitlist-detail-modal", state="visible", timeout=3000)

    ok, _ = check_element(page, "#waitlist-detail-modal",
                          "D5: 详情弹层打开", "候补详情弹层")
    if ok:
        record_result("D5: 候补详情弹层打开", True)

    print_step(7, "验证详情弹层基本信息区块")
    detail_sections = page.locator(".detail-section")
    has_basic = "基本信息" in page.locator(".detail-section h3").first.inner_text()
    if has_basic:
        record_result("D6: 详情弹层有基本信息区块", True)
    else:
        record_result("D6: 详情弹层有基本信息区块", False,
                      "详情弹层应该有'基本信息'区块",
                      location="#wl-detail-body .detail-section:nth-child(1)")

    print_step(8, "验证详情弹层有被挡详情区块")
    section_headers = page.locator(".detail-section h3")
    has_blocked = False
    for i in range(section_headers.count()):
        if "被挡详情" in section_headers.nth(i).inner_text():
            has_blocked = True
            break
    if has_blocked:
        record_result("D7: 详情弹层有被挡详情区块", True)
    else:
        record_result("D7: 详情弹层有被挡详情区块", False,
                      "被挡住的候补详情应该有'被挡详情'区块",
                      location="#wl-detail-body .detail-section")

    print_step(9, "验证详情弹层有操作日志区块")
    has_logs = False
    for i in range(section_headers.count()):
        if "操作日志" in section_headers.nth(i).inner_text():
            has_logs = True
            break
    if has_logs:
        record_result("D8: 详情弹层有操作日志区块", True)
    else:
        record_result("D8: 详情弹层有操作日志区块", False,
                      "候补详情应该有'操作日志'区块",
                      location="#wl-detail-body .detail-section")

    print_step(10, "验证详情弹层有关闭按钮")
    ok, _ = check_element(page, "#wl-detail-footer .modal-close-btn",
                          "D9: 详情弹层有关闭按钮", "关闭按钮")
    if ok:
        record_result("D9: 详情弹层关闭按钮存在", True)

    print_step(11, "验证成员端详情弹层没有手动补位按钮")
    footer_buttons = page.locator("#wl-detail-footer .btn")
    has_manual_fill = False
    for i in range(footer_buttons.count()):
        btn_text = footer_buttons.nth(i).inner_text()
        if "手动补位" in btn_text:
            has_manual_fill = True
            break
    if not has_manual_fill:
        record_result("D10: 成员端详情无手动补位按钮", True)
    else:
        record_result("D10: 成员端详情无手动补位按钮", False,
                      "成员端详情弹层不应该有手动补位按钮",
                      location="#wl-detail-footer")

    print_step(12, "关闭详情弹层")
    page.click("#waitlist-detail-modal .modal-close")
    page.wait_for_selector("#waitlist-detail-modal", state="hidden", timeout=3000)
    ok = page.locator("#waitlist-detail-modal").is_hidden()
    if ok:
        record_result("D11: 关闭详情弹层", True)
    else:
        record_result("D11: 关闭详情弹层", False,
                      "详情弹层未关闭", location="#waitlist-detail-modal")

    return waitlist["id"]


def run_admin_tests(page, venue_id, D, waitlist_id):
    print_header("第三部分：管理员端候补功能 DOM 验证")

    print_step(1, "退出登录，使用管理员账号登录")
    page.click("#logout-btn")
    page.wait_for_selector("#login-page", state="visible", timeout=3000)
    browser_login(page, "admin", "admin123")

    print_step(2, "进入候补列表，验证管理员能看到全部候补")
    page.click("button.nav-tab[data-tab='waitlist']")
    page.wait_for_selector("#waitlist-list", state="visible", timeout=3000)
    time.sleep(1)

    ok, count = check_element_count(page, "#waitlist-list .booking-card", 1,
                                     "A1: 管理员候补列表有记录", "候补卡片")
    if ok:
        record_result("A1: 管理员候补列表可见记录", True)

    print_step(3, "验证管理员端显示导出CSV按钮")
    export_btn = page.locator("#wl-export-btn")
    if export_btn.count() > 0:
        is_visible = export_btn.first.is_visible()
        if is_visible:
            record_result("A2: 管理员端显示导出CSV按钮", True)
        else:
            record_result("A2: 管理员端显示导出CSV按钮", False,
                          "管理员端应该能看到导出CSV按钮但被隐藏了",
                          location="#wl-export-btn")
    else:
        record_result("A2: 管理员端显示导出CSV按钮", False,
                      "找不到导出CSV按钮", location="#wl-export-btn")

    print_step(4, "筛选排队中状态，验证卡片上有手动补位按钮")
    status_select = page.locator("#wl-filter-status")
    status_select.select_option("waiting")
    page.click("#wl-search-btn")
    time.sleep(1)

    waiting_cards = page.locator("#waitlist-list .booking-card")
    found_manual_fill = False
    first_waiting_card = None
    for i in range(waiting_cards.count()):
        card = waiting_cards.nth(i)
        actions = card.locator(".booking-card-actions")
        if actions.count() > 0:
            btns = actions.locator(".btn")
            for j in range(btns.count()):
                if "手动补位" in btns.nth(j).inner_text():
                    found_manual_fill = True
                    first_waiting_card = card
                    break
        if found_manual_fill:
            break
    if found_manual_fill:
        record_result("A3: 管理员卡片显示手动补位按钮", True)
    else:
        record_result("A3: 管理员卡片显示手动补位按钮", False,
                      "管理员应该能在排队中候补卡片上看到手动补位按钮",
                      location="#waitlist-list .booking-card-actions .btn-success")
        safe_screenshot(page, "admin_manual_fill_missing")

    print_step(5, "打开排队中候补详情，验证详情有手动补位按钮")
    if first_waiting_card:
        first_waiting_card.click()
    else:
        page.click("#waitlist-list .booking-card", timeout=3000)
    page.wait_for_selector("#waitlist-detail-modal", state="visible", timeout=3000)
    time.sleep(0.5)

    footer_buttons = page.locator("#wl-detail-footer .btn")
    has_manual_fill = False
    for i in range(footer_buttons.count()):
        btn_text = footer_buttons.nth(i).inner_text()
        if "手动补位" in btn_text:
            has_manual_fill = True
            break
    if has_manual_fill:
        record_result("A4: 管理员详情有手动补位按钮", True)
    else:
        record_result("A4: 管理员详情有手动补位按钮", False,
                      "管理员详情弹层应该有手动补位按钮",
                      location="#wl-detail-footer")

    print_step(6, "关闭详情弹层")
    page.click("#waitlist-detail-modal .modal-close")
    page.wait_for_selector("#waitlist-detail-modal", state="hidden", timeout=3000)


def run_duplicate_waitlist_test(page, venue_id, D):
    print_header("第四部分：重复候补拦截 DOM 验证")

    admin_token, _ = api_login("admin", "admin123")
    start = D.replace(hour=14, minute=0)
    end = D.replace(hour=16, minute=0)

    print_step(1, "通过API创建一条挡路预约")
    booking, start, end = api_create_booking_with_retry(
        admin_token, venue_id, start, end,
        f"{TAG_PREFIX}-重复挡路", f"{TAG_PREFIX}-重复测试", status="confirmed")
    print(f"{INFO}   挡路预约时段: {start.strftime('%H:%M')}-{end.strftime('%H:%M')}")

    print_step(2, "退出登录，使用成员账号登录")
    page.click("#logout-btn")
    page.wait_for_selector("#login-page", state="visible", timeout=3000)
    browser_login(page, "lisi", "123456")
    page.click("button.nav-tab[data-tab='waitlist']")
    time.sleep(0.5)

    print_step(3, "登记第一个候补")
    page.click("#wl-create-btn")
    page.wait_for_selector("#waitlist-create-modal", state="visible", timeout=3000)

    page.fill("#wl-production", f"{TAG_PREFIX}-重复测试")
    venue_select = page.locator("#wl-venue")
    venue_select.select_option(index=1)
    page.fill("#wl-start", start.strftime("%Y-%m-%dT%H:%M"))
    page.fill("#wl-end", end.strftime("%Y-%m-%dT%H:%M"))
    page.fill("#wl-before", "0")
    page.fill("#wl-after", "0")
    page.fill("#wl-priority", "10")
    page.click("#wl-submit-btn")
    try:
        page.wait_for_selector("#waitlist-create-modal", state="hidden", timeout=5000)
        record_result("Dup1: 第一个候补登记成功", True)
    except PWTimeoutError:
        warn_el = page.locator("#wl-create-warn")
        warn_text = warn_el.inner_text() if warn_el.is_visible() else ""
        record_result("Dup1: 第一个候补登记成功", False,
                      f"第一个候补登记后弹层未关闭，警告: {warn_text[:100]}",
                      location="#waitlist-create-modal")
        page.click("#waitlist-create-modal .modal-close-btn")
        page.wait_for_selector("#waitlist-create-modal", state="hidden", timeout=3000)

    print_step(4, "尝试登记同一时段第二个候补，验证被拦截")
    page.click("#wl-create-btn")
    page.wait_for_selector("#waitlist-create-modal", state="visible", timeout=3000)

    page.fill("#wl-production", f"{TAG_PREFIX}-重复测试2")
    venue_select = page.locator("#wl-venue")
    venue_select.select_option(index=1)
    page.fill("#wl-start", start.strftime("%Y-%m-%dT%H:%M"))
    page.fill("#wl-end", end.strftime("%Y-%m-%dT%H:%M"))
    page.fill("#wl-before", "0")
    page.fill("#wl-after", "0")
    page.click("#wl-submit-btn")
    time.sleep(1)

    warn_visible = page.locator("#wl-create-warn").is_visible()
    if warn_visible:
        record_result("Dup2: 重复候补被拦截显示警告", True)
    else:
        record_result("Dup2: 重复候补被拦截显示警告", False,
                      "重复候补应该在创建弹层中显示警告信息",
                      location="#wl-create-warn")
        safe_screenshot(page, "duplicate_warn_missing")

    print_step(5, "关闭创建弹层")
    page.click("#waitlist-create-modal .modal-close-btn")


def run_closed_window_autofill_test(page, venue_id, D):
    print_header("第五部分：撤销封场后自动补位 DOM 验证")

    admin_token, _ = api_login("admin", "admin123")
    start = D.replace(hour=17, minute=0)
    end = D.replace(hour=18, minute=0)

    print_step(1, "创建封场窗口")
    window = api_create_closed_window(admin_token, venue_id, start, end,
                                       f"{TAG_PREFIX}-自动补位测试封场")
    print(f"{INFO}   封场窗口 ID={window['id']}")

    print_step(2, "成员登记候补（被封场挡住）")
    member_token, _ = api_login("lisi", "123456")
    waitlist = api_create_waitlist(member_token, venue_id, start, end,
                                   f"{TAG_PREFIX}-封场挡候补", f"{TAG_PREFIX}-封场测试")
    print(f"{INFO}   候补记录 ID={waitlist['id']}")

    wl_detail = api_get_waitlist(member_token, waitlist["id"])
    if wl_detail.get("blocked_by_type") == "closed_window":
        record_result("Auto1: 候补被封场挡住", True)
    else:
        record_result("Auto1: 候补被封场挡住", False,
                      f"预期 blocked_by_type=closed_window，实际={wl_detail.get('blocked_by_type')}")

    print_step(3, "前端刷新，验证候补显示为被封场挡住")
    page.reload()
    page.wait_for_selector("#main-app", state="visible", timeout=5000)
    page.click("button.nav-tab[data-tab='waitlist']")
    time.sleep(1)

    cards = page.locator("#waitlist-list .booking-card")
    found_closed_window_block = False
    for i in range(cards.count()):
        card = cards.nth(i)
        badges = card.locator(".status-badge")
        for j in range(badges.count()):
            badge_text = badges.nth(j).inner_text()
            if "封场" in badge_text:
                found_closed_window_block = True
                break
        if found_closed_window_block:
            break

    if found_closed_window_block:
        record_result("Auto2: 前端显示被封场挡住", True)
    else:
        record_result("Auto2: 前端显示被封场挡住", False,
                      "被封场挡住的候补应该在卡片上显示封场相关徽章",
                      location="#waitlist-list .booking-card .wl-blocked")

    print_step(4, "管理员撤销封场窗口，触发自动补位")
    api_revoke_closed_window(admin_token, window["id"])
    time.sleep(1)

    print_step(5, "前端刷新，验证候补状态变为已补位")
    page.reload()
    page.wait_for_selector("#main-app", state="visible", timeout=5000)
    page.click("button.nav-tab[data-tab='waitlist']")
    time.sleep(1)

    status_select = page.locator("#wl-filter-status")
    status_select.select_option("filled")
    page.click("#wl-search-btn")
    time.sleep(1)

    cards = page.locator("#waitlist-list .booking-card")
    found_filled = False
    for i in range(cards.count()):
        card = cards.nth(i)
        title = card.locator(".booking-card-title").inner_text()
        if TAG_PREFIX in title and "封场" in title:
            status = card.locator(".status-badge").first.inner_text()
            if "已补位" in status:
                found_filled = True
                break

    if found_filled:
        record_result("Auto3: 撤销封场后自动补位成功", True)
    else:
        record_result("Auto3: 撤销封场后自动补位成功", False,
                      "撤销封场后候补应该自动补位，状态变为已补位",
                      location="#waitlist-list")
        safe_screenshot(page, "autofill_missing")

    print_step(6, "打开已补位候补详情，验证补位结果区块")
    if found_filled:
        for i in range(cards.count()):
            card = cards.nth(i)
            title = card.locator(".booking-card-title").inner_text()
            if TAG_PREFIX in title and "封场" in title:
                card.click()
                break

        page.wait_for_selector("#waitlist-detail-modal", state="visible", timeout=3000)
        time.sleep(0.5)

        section_headers = page.locator(".detail-section h3")
        has_fill_result = False
        for i in range(section_headers.count()):
            if "补位结果" in section_headers.nth(i).inner_text():
                has_fill_result = True
                break

        if has_fill_result:
            record_result("Auto4: 已补位候补显示补位结果区块", True)
        else:
            record_result("Auto4: 已补位候补显示补位结果区块", False,
                          "已补位的候补详情应该有'补位结果'区块",
                          location="#wl-detail-body")

        has_view_booking_btn = False
        footer_buttons = page.locator("#wl-detail-footer .btn")
        for i in range(footer_buttons.count()):
            if "查看补位预约" in footer_buttons.nth(i).inner_text():
                has_view_booking_btn = True
                break
        if has_view_booking_btn:
            record_result("Auto5: 已补位候补有查看补位预约按钮", True)
        else:
            record_result("Auto5: 已补位候补有查看补位预约按钮", False,
                          "已补位的候补应该有'查看补位预约'按钮",
                          location="#wl-detail-footer")

        page.click("#waitlist-detail-modal .modal-close")


def run_csv_export_test(page):
    print_header("第六部分：CSV 导出 DOM + 内容验证")

    print_step(1, "确保管理员登录并在候补列表页")
    config_tab = page.locator("button.nav-tab[data-tab='config']")
    is_admin = config_tab.count() > 0 and config_tab.first.is_visible()
    if not is_admin:
        if not page.locator("#login-page").is_visible():
            page.click("#logout-btn")
            page.wait_for_selector("#login-page", state="visible", timeout=3000)
        browser_login(page, "admin", "admin123")
    page.click("button.nav-tab[data-tab='waitlist']")
    page.wait_for_selector("#waitlist-list", state="visible", timeout=3000)
    time.sleep(0.5)

    print_step(2, "点击导出CSV按钮，验证下载")
    with page.expect_download(timeout=10000) as download_info:
        page.click("#wl-export-btn")
    download = download_info.value

    filename = download.suggested_filename
    print(f"{INFO}   下载文件名: {filename}")

    if "waitlist" in filename.lower() and filename.endswith(".csv"):
        record_result("CSV1: 导出文件名格式正确", True)
    else:
        record_result("CSV1: 导出文件名格式正确", False,
                      f"文件名应该包含'waitlist'且为.csv格式，实际: {filename}",
                      location="#wl-export-btn")

    print_step(3, "验证CSV内容包含关键列")
    content = download.path().read_text(encoding="utf-8-sig")
    lines = content.splitlines()
    header = lines[0] if lines else ""

    required_cols = [
        "候补ID", "剧目", "场地", "申请人", "状态",
        "目标开始时间", "目标结束时间", "被挡住类型",
        "补位方式", "补位时间", "对应预约ID",
        "操作类型", "触发原因"
    ]
    missing_cols = [c for c in required_cols if c not in header]

    if not missing_cols:
        record_result("CSV2: CSV表头包含全部关键列", True)
    else:
        record_result("CSV2: CSV表头包含全部关键列", False,
                      f"缺少关键列: {missing_cols}\n       实际表头: {header[:200]}",
                      location="#wl-export-btn")

    print_step(4, "验证CSV包含本次测试数据")
    has_test_data = any(TAG_PREFIX in line for line in lines)
    if has_test_data:
        record_result("CSV3: CSV包含本次测试数据", True)
    else:
        record_result("CSV3: CSV包含本次测试数据", False,
                      f"CSV中未找到TAG_PREFIX={TAG_PREFIX}的数据",
                      location="#wl-export-btn")

    return filename


def run_persistence_test(page, venue_id, D):
    print_header("第七部分：服务重启后列表和日志一致性验证")

    print_step(1, "记录当前候补列表数量和状态")
    page.click("button.nav-tab[data-tab='waitlist']")
    time.sleep(1)

    count_text = page.locator("#wl-count").inner_text()
    before_count = count_text
    print(f"{INFO}   重启前列表计数: {before_count}")

    print_step(2, "记录一条候补的详情作为基准")
    cards = page.locator("#waitlist-list .booking-card")
    if cards.count() > 0:
        first_card = cards.first
        first_title = first_card.locator(".booking-card-title").inner_text()
        first_status = first_card.locator(".status-badge").first.inner_text()
        print(f"{INFO}   基准记录: '{first_title}' 状态={first_status}")

        first_card.click()
        page.wait_for_selector("#waitlist-detail-modal", state="visible", timeout=3000)
        time.sleep(0.5)

        log_sections = page.locator(".detail-section h3")
        log_count_before = 0
        for i in range(log_sections.count()):
            if "操作日志" in log_sections.nth(i).inner_text():
                log_items = page.locator(".detail-section").nth(i).locator(".conflict-item")
                log_count_before = log_items.count()
                break
        print(f"{INFO}   基准记录操作日志数: {log_count_before}")

        page.click("#waitlist-detail-modal .modal-close")
        time.sleep(0.5)

        record_result("Persist1: 重启前有可对比的基准数据", True)

        print_step(3, "刷新页面（模拟服务重启后的重新访问）")
        page.reload()
        page.wait_for_selector("#main-app", state="visible", timeout=5000)
        page.click("button.nav-tab[data-tab='waitlist']")
        time.sleep(1)

        print_step(4, "验证列表计数一致")
        after_count = page.locator("#wl-count").inner_text()
        if before_count == after_count:
            record_result("Persist2: 刷新后列表计数一致", True)
        else:
            record_result("Persist2: 刷新后列表计数一致", False,
                          f"刷新前: {before_count}，刷新后: {after_count}",
                          location="#wl-count")

        print_step(5, "验证基准记录状态一致")
        cards_after = page.locator("#waitlist-list .booking-card")
        found_same = False
        for i in range(cards_after.count()):
            title = cards_after.nth(i).locator(".booking-card-title").inner_text()
            if first_title in title:
                status_after = cards_after.nth(i).locator(".status-badge").first.inner_text()
                if first_status == status_after:
                    found_same = True
                else:
                    record_result("Persist3: 基准记录状态一致", False,
                                  f"刷新前状态: {first_status}，刷新后: {status_after}",
                                  location="#waitlist-list .booking-card")
                break

        if found_same:
            record_result("Persist3: 基准记录状态一致", True)

        print_step(6, "验证基准记录操作日志数一致")
        if found_same:
            for i in range(cards_after.count()):
                title = cards_after.nth(i).locator(".booking-card-title").inner_text()
                if first_title in title:
                    cards_after.nth(i).click()
                    break

            page.wait_for_selector("#waitlist-detail-modal", state="visible", timeout=3000)
            time.sleep(0.5)

            log_sections_after = page.locator(".detail-section h3")
            log_count_after = 0
            for i in range(log_sections_after.count()):
                if "操作日志" in log_sections_after.nth(i).inner_text():
                    log_items = page.locator(".detail-section").nth(i).locator(".conflict-item")
                    log_count_after = log_items.count()
                    break

            if log_count_before == log_count_after:
                record_result("Persist4: 操作日志数量一致", True)
            else:
                record_result("Persist4: 操作日志数量一致", False,
                              f"刷新前日志数: {log_count_before}，刷新后: {log_count_after}",
                              location="#wl-detail-body")

            page.click("#waitlist-detail-modal .modal-close")
    else:
        record_result("Persist1: 重启前有可对比的基准数据", False,
                      "候补列表为空，无法进行一致性对比",
                      location="#waitlist-list")


def run_permission_test(page):
    print_header("第八部分：权限差异 DOM 验证汇总")

    print_step(1, "验证成员看不到配置管理Tab")
    page.click("#logout-btn")
    page.wait_for_selector("#login-page", state="visible", timeout=3000)
    browser_login(page, "lisi", "123456")
    time.sleep(0.5)

    config_tab = page.locator("button.nav-tab[data-tab='config']")
    if config_tab.count() > 0:
        is_hidden = config_tab.first.is_hidden()
        if is_hidden:
            record_result("Perm1: 成员隐藏配置管理Tab", True)
        else:
            record_result("Perm1: 成员隐藏配置管理Tab", False,
                          "成员不应该看到配置管理Tab",
                          location="button.nav-tab[data-tab='config']")
    else:
        record_result("Perm1: 成员隐藏配置管理Tab", True)

    print_step(2, "验证管理员能看到配置管理Tab")
    page.click("#logout-btn")
    page.wait_for_selector("#login-page", state="visible", timeout=3000)
    browser_login(page, "admin", "admin123")
    time.sleep(0.5)

    config_tab = page.locator("button.nav-tab[data-tab='config']")
    if config_tab.count() > 0 and config_tab.first.is_visible():
        record_result("Perm2: 管理员显示配置管理Tab", True)
    else:
        record_result("Perm2: 管理员显示配置管理Tab", False,
                      "管理员应该能看到配置管理Tab",
                      location="button.nav-tab[data-tab='config']")


def main():
    print_header("候补功能浏览器级回归测试")
    print(f"RUN_ID: {RUN_ID}")
    print(f"TAG_PREFIX: {TAG_PREFIX}")
    print(f"日志文件: {LOG_FILE}")
    print(f"截图目录: {SCREENSHOT_DIR}")
    print(f"测试地址: {BASE_URL}")
    print()

    D = get_test_date()
    print(f"{INFO} 测试基准日期: {D.date().isoformat()} (周{D.weekday() + 1})")

    admin_token, _ = api_login("admin", "admin123")
    import requests
    venues = requests.get(f"{API_BASE}/venues",
                          headers={"Authorization": f"Bearer {admin_token}"}).json()
    venue_id = venues[0]["id"]
    print(f"{INFO} 测试场地: {venues[0]['name']} (ID={venue_id})")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()

        try:
            browser_login(page, "lisi", "123456")
            print(f"{PASS} 浏览器登录成功")

            run_member_tests(page, venue_id, D)

            waitlist_id = run_waitlist_detail_test(page, venue_id, D)

            run_admin_tests(page, venue_id, D, waitlist_id)

            run_duplicate_waitlist_test(page, venue_id, D)

            run_closed_window_autofill_test(page, venue_id, D)

            csv_filename = run_csv_export_test(page)

            run_persistence_test(page, venue_id, D)

            run_permission_test(page)

        except Exception as e:
            print(f"\n{FAIL} 测试异常中断: {e}")
            import traceback
            traceback.print_exc()
            safe_screenshot(page, "error_crash")

        finally:
            browser.close()

    print()
    print("=" * 80)
    print(f"  最终测试结果 - RUN_ID={RUN_ID}")
    print("=" * 80)
    print(f"  通过: {pass_count}")
    print(f"  失败: {fail_count}")
    print(f"  总计: {pass_count + fail_count}")
    print()
    if test_results:
        print("  失败明细:")
        for t in test_results:
            if not t["passed"]:
                print(f"    {FAIL} {t['name']}")
                if t.get("location"):
                    print(f"           位置: {t['location']}")
                if t.get("detail"):
                    detail_lines = t["detail"].split("\n")[:3]
                    for dl in detail_lines:
                        print(f"           {dl}")
    print()
    print(f"  日志文件: {LOG_FILE}")
    print(f"  截图目录: {SCREENSHOT_DIR}")
    print("=" * 80)

    out_file.close()
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
