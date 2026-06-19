import sys
import os
import time
import csv
import io
import json
import argparse
from datetime import datetime, timedelta
from pathlib import Path

from playwright.sync_api import sync_playwright, expect, TimeoutError as PWTimeoutError

BASE_URL = "http://127.0.0.1:8002"
API_BASE = f"{BASE_URL}/api"

RUN_ID = datetime.now().strftime("%Y%m%d_%H%M%S")
TAG_PREFIX = f"BWD-{RUN_ID}"
LOG_FILE = f"browser_waitlist_drill_{RUN_ID}.txt"
SCREENSHOT_DIR = f"screenshots_drill_{RUN_ID}"

FAIL = "[FAIL]"
PASS = "[PASS]"
STEP = "[STEP]"
INFO = "[INFO]"
WARN = "[WARN]"

pass_count = 0
fail_count = 0
test_results = []
drill_sessions_to_cleanup = []

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


def record_result(test_name, passed, detail="", location="", category=""):
    global pass_count, fail_count
    test_results.append({
        "name": test_name,
        "passed": passed,
        "detail": detail,
        "location": location,
        "category": category
    })
    if passed:
        pass_count += 1
        cat_info = f" [{category}]" if category else ""
        print(f"{PASS} {test_name}{cat_info}")
    else:
        fail_count += 1
        loc_info = f" [位置: {location}]" if location else ""
        cat_info = f" [{category}]" if category else ""
        print(f"{FAIL} {test_name}{cat_info}{loc_info}")
        if detail:
            print(f"       原因: {detail}")


def safe_screenshot(page, name):
    try:
        path = os.path.join(SCREENSHOT_DIR, f"{name}.png")
        page.screenshot(path=path, full_page=True)
        print(f"{INFO}   截图已保存: {path}")
    except Exception as e:
        print(f"{WARN}   截图失败: {e}")


def check_element(page, selector, test_name, element_desc, timeout=3000, category=""):
    try:
        el = page.locator(selector).first
        el.wait_for(state="visible", timeout=timeout)
        return True, el
    except PWTimeoutError:
        detail = f"找不到元素 '{selector}'（{element_desc}）"
        record_result(test_name, False, detail, location=selector, category=category)
        return False, None


def check_element_text(page, selector, expected_text, test_name, element_desc, timeout=3000, category=""):
    ok, el = check_element(page, selector, test_name, element_desc, timeout, category)
    if not ok:
        return False, None
    actual = el.inner_text()
    if expected_text in actual:
        return True, el
    detail = f"元素 '{selector}' 文本不匹配\n       预期包含: '{expected_text}'\n       实际: '{actual[:100]}'"
    record_result(test_name, False, detail, location=selector, category=category)
    return False, el


def check_element_count(page, selector, min_count, test_name, element_desc, timeout=3000, category=""):
    try:
        els = page.locator(selector)
        els.first.wait_for(state="visible", timeout=timeout)
        count = els.count()
        if count >= min_count:
            return True, count
        detail = f"元素 '{selector}'（{element_desc}）数量不足\n       预期至少: {min_count}\n       实际: {count}"
        record_result(test_name, False, detail, location=selector, category=category)
        return False, count
    except PWTimeoutError:
        detail = f"找不到元素 '{selector}'（{element_desc}）"
        record_result(test_name, False, detail, location=selector, category=category)
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


def api_create_drill_session(token, venue_id, offset_days=90):
    import requests
    r = requests.post(
        f"{API_BASE}/waitlist-drill/session",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={
            "venue_id": venue_id,
            "auto_find_slot": True,
            "target_date_offset_days": offset_days
        }
    )
    if r.status_code not in (200, 201):
        raise AssertionError(f"创建演练会话失败: {r.status_code} {r.text}")
    return r.json()


def api_get_drill_snapshot(token, drill_session_id):
    import requests
    r = requests.get(
        f"{API_BASE}/waitlist-drill/session/{drill_session_id}/snapshot",
        headers={"Authorization": f"Bearer {token}"}
    )
    if r.status_code != 200:
        raise AssertionError(f"获取演练快照失败: {r.status_code} {r.text}")
    return r.json()


def api_cleanup_drill(token, drill_session_id):
    import requests
    r = requests.delete(
        f"{API_BASE}/waitlist-drill/session/{drill_session_id}",
        headers={"Authorization": f"Bearer {token}"}
    )
    if r.status_code != 200:
        raise AssertionError(f"清理演练失败: {r.status_code} {r.text}")
    return r.json()


def api_get_drill_member_view(token, drill_session_id):
    import requests
    r = requests.get(
        f"{API_BASE}/waitlist-drill/session/{drill_session_id}/member-view",
        headers={"Authorization": f"Bearer {token}"}
    )
    if r.status_code != 200:
        raise AssertionError(f"获取成员视图失败: {r.status_code} {r.text}")
    return r.json()


def api_get_error_categories(token):
    import requests
    r = requests.get(
        f"{API_BASE}/waitlist-drill/error-categories",
        headers={"Authorization": f"Bearer {token}"}
    )
    if r.status_code != 200:
        raise AssertionError(f"获取错误分类失败: {r.status_code} {r.text}")
    return r.json()


def api_export_waitlist_csv(token):
    import requests
    r = requests.get(
        f"{API_BASE}/waitlist/export",
        headers={"Authorization": f"Bearer {token}"}
    )
    if r.status_code != 200:
        raise AssertionError(f"导出CSV失败: {r.status_code} {r.text}")
    return r.content.decode("utf-8-sig")


def browser_login(page, username, password):
    page.goto(BASE_URL)
    page.wait_for_selector("#login-page", state="visible", timeout=5000)
    page.fill("#username", username)
    page.fill("#password", password)
    page.click("#login-form button[type='submit']")
    page.wait_for_selector("#main-app", state="visible", timeout=5000)


def get_current_server_pid():
    try:
        import psutil
        for proc in psutil.process_iter(['pid', 'cmdline', 'cwd']):
            try:
                cmdline = ' '.join(proc.info['cmdline'] or [])
                cwd = proc.info['cwd'] or ''
                if 'uvicorn' in cmdline and 'main:app' in cmdline and 'zgw-00143' in cwd:
                    return proc.pid
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except ImportError:
        print(f"{WARN} psutil 未安装，无法获取服务器PID")
    return None


def verify_process_belongs_to_project(pid):
    try:
        import psutil
        proc = psutil.Process(pid)
        cmdline = ' '.join(proc.cmdline() or [])
        cwd = proc.cwd() or ''
        project_path = os.path.abspath(os.path.dirname(__file__))
        belongs = ('uvicorn' in cmdline and 'main:app' in cmdline and
                   ('zgw-00143' in cwd or 'zgw-00143' in project_path))
        if belongs:
            print(f"{INFO}   PID={pid} 验证通过")
            print(f"{INFO}   命令行: {cmdline[:100]}")
            print(f"{INFO}   工作目录: {cwd}")
        return belongs
    except ImportError:
        return False
    except Exception as e:
        print(f"{WARN} 进程验证失败: {e}")
        return False


def print_header(title):
    print()
    print("=" * 80)
    print(f"  {title}")
    print("=" * 80)


def print_step(step_num, desc):
    print()
    print(f"{STEP} {step_num:3d}. {desc}")
    print("-" * 80)


def run_drill_entry_tests(page, venue_id):
    print_header("第一部分：演练入口 DOM 验证")

    print_step(1, "验证管理员登录后可见演练管理Tab")
    ok, _ = check_element(page, "button.nav-tab[data-tab='drill']",
                          "BD1: 演练管理Tab存在", "演练管理导航Tab",
                          category="PERMISSION")
    if ok:
        ok2, _ = check_element_text(page, "button.nav-tab[data-tab='drill']",
                                     "演练管理", "BD1: 演练管理Tab文本正确",
                                     "演练管理导航Tab文本", category="PERMISSION")
        if ok2:
            record_result("BD1: 管理员可见演练管理入口", True, category="PERMISSION")

    print_step(2, "点击演练管理Tab，验证演练列表页面加载")
    page.click("button.nav-tab[data-tab='drill']")
    page.wait_for_selector("#tab-drill.active", state="visible", timeout=3000)

    ok, _ = check_element(page, "#tab-drill.active",
                          "BD2: 演练Tab激活", "演练内容区域",
                          category="MODAL")
    if ok:
        record_result("BD2: 点击切换到演练列表", True, category="MODAL")

    print_step(3, "验证演练页面操作栏元素完整")
    action_checks = [
        ("#drill-create-btn", "创建演练按钮"),
        ("#drill-refresh-btn", "刷新列表按钮"),
        ("#drill-filter-status", "状态筛选下拉框"),
        ("#drill-search-btn", "搜索按钮"),
    ]
    all_ok = True
    for sel, desc in action_checks:
        ok, _ = check_element(page, sel, f"BD3: {desc}存在", desc,
                              category="TABLE")
        if not ok:
            all_ok = False
    if all_ok:
        record_result("BD3: 演练操作栏元素完整", True, category="TABLE")

    print_step(4, "验证演练列表表头列完整")
    header_checks = [
        ("#drill-list .drill-table th.col-session-id", "会话ID列"),
        ("#drill-list .drill-table th.col-status", "状态列"),
        ("#drill-list .drill-table th.col-venue", "场地列"),
        ("#drill-list .drill-table th.col-date", "日期列"),
        ("#drill-list .drill-table th.col-passed", "通过列"),
        ("#drill-list .drill-table th.col-failed", "失败列"),
        ("#drill-list .drill-table th.col-actions", "操作列"),
    ]
    all_ok = True
    for sel, desc in header_checks:
        ok, _ = check_element(page, sel, f"BD4: {desc}存在", desc,
                              category="TABLE")
        if not ok:
            all_ok = False
    if all_ok:
        record_result("BD4: 演练列表表头列完整", True, category="TABLE")


def run_create_drill_modal_tests(page, venue_id):
    print_header("第二部分：创建演练弹层 DOM 验证")

    print_step(1, "点击创建演练按钮，验证弹层打开")
    page.click("#drill-create-btn")
    page.wait_for_selector("#drill-create-modal", state="visible", timeout=3000)

    ok, _ = check_element(page, "#drill-create-modal",
                          "BD5: 创建演练弹层打开", "创建演练弹层",
                          category="MODAL")
    if ok:
        ok2, _ = check_element_text(page, "#drill-create-modal h2", "创建回归演练",
                                     "BD5: 弹层标题正确", "创建演练弹层标题",
                                     category="MODAL")
        if ok2:
            record_result("BD5: 创建演练弹层打开", True, category="MODAL")

    print_step(2, "验证创建演练表单字段完整")
    form_fields = [
        ("#drill-venue", "场地下拉框"),
        ("#drill-auto-find", "自动找空档复选框"),
        ("#drill-offset-days", "日期偏移天数"),
        ("#drill-target-date", "目标日期"),
        ("#drill-target-start", "目标开始时间"),
        ("#drill-target-end", "目标结束时间"),
        ("#drill-submit-btn", "开始演练按钮"),
        ("#drill-cancel-btn", "取消按钮"),
    ]
    all_ok = True
    for sel, desc in form_fields:
        ok, _ = check_element(page, sel, f"BD6: {desc}存在", desc,
                              category="MODAL")
        if not ok:
            all_ok = False
    if all_ok:
        record_result("BD6: 创建演练表单字段完整", True, category="MODAL")

    print_step(3, "验证自动找空档开关交互")
    auto_find_cb = page.locator("#drill-auto-find")
    is_checked = auto_find_cb.is_checked()
    if not is_checked:
        auto_find_cb.check()
    date_input = page.locator("#drill-target-date")
    is_disabled = date_input.is_disabled()
    if is_disabled:
        record_result("BD7: 自动找空档开启时禁用日期输入", True, category="MODAL")
    else:
        record_result("BD7: 自动找空档开启时禁用日期输入", False,
                      "自动找空档开启时应该禁用手动日期输入",
                      location="#drill-target-date", category="MODAL")

    print_step(4, "取消创建弹层")
    page.click("#drill-cancel-btn")
    page.wait_for_selector("#drill-create-modal", state="hidden", timeout=3000)
    ok = page.locator("#drill-create-modal").is_hidden()
    if ok:
        record_result("BD8: 取消创建弹层", True, category="MODAL")
    else:
        record_result("BD8: 取消创建弹层", False,
                      "弹层未关闭", location="#drill-create-modal", category="MODAL")


def run_drill_execution_tests(page, venue_id, admin_token):
    print_header("第三部分：演练执行 DOM 验证")

    print_step(1, "通过API创建演练会话（后台执行）")
    try:
        drill_result = api_create_drill_session(admin_token, venue_id, offset_days=90)
        drill_session_id = drill_result["drill_session_id"]
        drill_sessions_to_cleanup.append(drill_session_id)
        print(f"{INFO}   演练会话ID: {drill_session_id}")
        print(f"{INFO}   演练状态: {drill_result['status']}")
        print(f"{INFO}   通过步骤: {drill_result['total_passed']}/{drill_result['total_passed'] + drill_result['total_failed']}")
        record_result("BD9: API创建演练会话成功", True, category="DATA_QUALITY")
    except Exception as e:
        record_result("BD9: API创建演练会话成功", False, str(e), category="DATA_QUALITY")
        return None

    print_step(2, "刷新演练列表，验证新演练出现在列表中")
    page.reload()
    page.wait_for_selector("#main-app", state="visible", timeout=5000)
    page.click("button.nav-tab[data-tab='drill']")
    page.wait_for_selector("#drill-list", state="visible", timeout=5000)
    time.sleep(2)

    rows = page.locator("#drill-list .drill-table tbody tr")
    found_drill = False
    for i in range(rows.count()):
        row_text = rows.nth(i).inner_text()
        if drill_session_id in row_text:
            found_drill = True
            break

    if found_drill:
        record_result("BD10: 演练出现在列表中", True, category="TABLE")
    else:
        record_result("BD10: 演练出现在列表中", False,
                      f"列表中未找到演练会话 {drill_session_id}",
                      location="#drill-list .drill-table tbody", category="TABLE")
        safe_screenshot(page, "drill_not_in_list")

    print_step(3, "点击查看演练详情，验证详情弹层")
    if found_drill:
        for i in range(rows.count()):
            row = rows.nth(i)
            if drill_session_id in row.inner_text():
                row.locator(".drill-view-btn").click()
                break

        page.wait_for_selector("#drill-detail-modal", state="visible", timeout=3000)

        ok, _ = check_element(page, "#drill-detail-modal",
                              "BD11: 演练详情弹层打开", "演练详情弹层",
                              category="MODAL")
        if ok:
            record_result("BD11: 演练详情弹层打开", True, category="MODAL")

        print_step(4, "验证演练详情包含步骤列表")
        ok, count = check_element_count(page, "#drill-detail-modal .drill-step-item", 10,
                                         "BD12: 演练步骤列表完整", "演练步骤项",
                                         category="TABLE")
        if ok:
            record_result(f"BD12: 演练包含 {count} 个步骤", True, category="TABLE")

        print_step(5, "验证演练详情包含统计信息")
        stats_checks = [
            ("#drill-detail-total-passed", "通过数"),
            ("#drill-detail-total-failed", "失败数"),
            ("#drill-detail-cleanup-status", "清理状态"),
        ]
        all_ok = True
        for sel, desc in stats_checks:
            ok, _ = check_element(page, sel, f"BD13: {desc}存在", desc,
                                  category="TABLE")
            if not ok:
                all_ok = False
        if all_ok:
            record_result("BD13: 演练统计信息完整", True, category="TABLE")

        print_step(6, "关闭演练详情弹层")
        page.click("#drill-detail-modal .modal-close")
        page.wait_for_selector("#drill-detail-modal", state="hidden", timeout=3000)

    return drill_session_id


def run_member_drill_view_tests(page, venue_id, drill_session_id, member_token):
    print_header("第四部分：成员端演练数据视图 DOM 验证")

    print_step(1, "退出登录，使用成员账号登录")
    page.click("#logout-btn")
    page.wait_for_selector("#login-page", state="visible", timeout=3000)
    browser_login(page, "lisi", "123456")

    print_step(2, "验证成员看不到演练管理Tab（权限控制）")
    drill_tab = page.locator("button.nav-tab[data-tab='drill']")
    if drill_tab.count() > 0:
        is_hidden = drill_tab.first.is_hidden()
        if is_hidden:
            record_result("BD14: 成员隐藏演练管理Tab", True, category="PERMISSION")
        else:
            record_result("BD14: 成员隐藏演练管理Tab", False,
                          "成员不应该看到演练管理Tab",
                          location="button.nav-tab[data-tab='drill']", category="PERMISSION")
    else:
        record_result("BD14: 成员隐藏演练管理Tab", True, category="PERMISSION")

    print_step(3, "进入候补列表，验证能看到演练候补数据")
    page.click("button.nav-tab[data-tab='waitlist']")
    page.wait_for_selector("#waitlist-list", state="visible", timeout=3000)
    time.sleep(1)

    try:
        member_view = api_get_drill_member_view(member_token, drill_session_id)
        print(f"{INFO}   成员视图候补记录数: {len(member_view.get('waitlist_entries', []))}")

        if member_view.get("waitlist_entries"):
            record_result("BD15: API获取成员视图成功", True, category="DATA_QUALITY")

            print_step(4, "筛选找到演练数据，验证显示被挡原因")
            first_entry = member_view["waitlist_entries"][0]
            page.fill("#wl-filter-production", f"DRILL_{drill_session_id[-8:]}")
            page.click("#wl-search-btn")
            time.sleep(1)

            cards = page.locator("#waitlist-list .booking-card")
            found_drill_card = cards.count() > 0

            if found_drill_card:
                record_result("BD16: 成员能看到演练候补数据", True, category="TABLE")

                print_step(5, "验证演练候补卡片显示演练标记")
                first_card = cards.first
                drill_badge = first_card.locator(".drill-badge")
                if drill_badge.count() > 0 and drill_badge.first.is_visible():
                    record_result("BD17: 演练候补卡片显示演练标记", True, category="TABLE")
                else:
                    record_result("BD17: 演练候补卡片显示演练标记", False,
                                  "演练数据应该显示演练标记徽章",
                                  location="#waitlist-list .booking-card .drill-badge",
                                  category="TABLE")

                print_step(6, "打开演练候补详情，验证显示被挡原因")
                first_card.click()
                page.wait_for_selector("#waitlist-detail-modal", state="visible", timeout=3000)
                time.sleep(0.5)

                blocked_section = page.locator(".detail-section h3", has_text="被挡详情")
                if blocked_section.count() > 0:
                    record_result("BD18: 详情显示被挡详情区块", True, category="TABLE")
                else:
                    record_result("BD18: 详情显示被挡详情区块", False,
                                  "被挡住的候补应该显示被挡详情区块",
                                  location="#wl-detail-body .detail-section",
                                  category="TABLE")

                page.click("#waitlist-detail-modal .modal-close")

    except Exception as e:
        record_result("BD15: API获取成员视图成功", False, str(e), category="DATA_QUALITY")


def run_admin_drill_management_tests(page, venue_id, drill_session_id, admin_token):
    print_header("第五部分：管理员端演练管理 DOM 验证")

    print_step(1, "退出登录，使用管理员账号登录")
    page.click("#logout-btn")
    page.wait_for_selector("#login-page", state="visible", timeout=3000)
    browser_login(page, "admin", "admin123")

    print_step(2, "进入演练管理页面")
    page.click("button.nav-tab[data-tab='drill']")
    page.wait_for_selector("#drill-list", state="visible", timeout=3000)
    time.sleep(1)

    print_step(3, "验证演练列表显示操作按钮")
    rows = page.locator("#drill-list .drill-table tbody tr")
    found_row = None
    for i in range(rows.count()):
        row = rows.nth(i)
        if drill_session_id in row.inner_text():
            found_row = row
            break

    if found_row:
        action_btns = found_row.locator("button")
        has_view = action_btns.filter(has_text="查看").count() > 0
        has_snapshot = action_btns.filter(has_text="快照").count() > 0
        has_cleanup = action_btns.filter(has_text="清理").count() > 0

        all_present = has_view and has_snapshot and has_cleanup
        if all_present:
            record_result("BD19: 演练列表操作按钮完整", True, category="TABLE")
        else:
            missing = []
            if not has_view:
                missing.append("查看")
            if not has_snapshot:
                missing.append("快照")
            if not has_cleanup:
                missing.append("清理")
            record_result("BD19: 演练列表操作按钮完整", False,
                          f"缺少按钮: {missing}",
                          location="#drill-list .drill-table tbody tr button",
                          category="TABLE")

    print_step(4, "点击快照按钮，验证快照弹层")
    if found_row:
        found_row.locator("button", has_text="快照").click()
        page.wait_for_selector("#drill-snapshot-modal", state="visible", timeout=3000)

        ok, _ = check_element(page, "#drill-snapshot-modal",
                              "BD20: 快照弹层打开", "快照弹层",
                              category="MODAL")
        if ok:
            record_result("BD20: 快照弹层打开", True, category="MODAL")

        snapshot_sections = [
            "#snapshot-waitlist-count",
            "#snapshot-booking-count",
            "#snapshot-closed-window-count",
        ]
        all_ok = True
        for sel in snapshot_sections:
            ok, _ = check_element(page, sel, f"BD21: 快照统计 {sel} 存在", sel,
                                  category="TABLE")
            if not ok:
                all_ok = False
        if all_ok:
            record_result("BD21: 快照统计信息完整", True, category="TABLE")

        page.click("#drill-snapshot-modal .modal-close")


def run_drill_csv_export_tests(page, venue_id, drill_session_id, admin_token):
    print_header("第六部分：演练数据 CSV 导出 DOM + 内容验证")

    print_step(1, "进入候补列表页面，导出完整CSV")
    page.click("button.nav-tab[data-tab='waitlist']")
    page.wait_for_selector("#waitlist-list", state="visible", timeout=3000)
    time.sleep(1)

    print_step(2, "点击导出CSV按钮，验证下载")
    with page.expect_download(timeout=10000) as download_info:
        page.click("#wl-export-btn")
    download = download_info.value

    filename = download.suggested_filename
    print(f"{INFO}   下载文件名: {filename}")

    if "waitlist" in filename.lower() and filename.endswith(".csv"):
        record_result("BD22: 导出文件名格式正确", True, category="DOWNLOAD")
    else:
        record_result("BD22: 导出文件名格式正确", False,
                      f"文件名应该包含'waitlist'且为.csv格式，实际: {filename}",
                      location="#wl-export-btn", category="DOWNLOAD")

    print_step(3, "验证CSV内容包含演练标记列和数据")
    content = download.path().read_text(encoding="utf-8-sig")
    lines = content.splitlines()
    header = lines[0] if lines else ""

    required_cols = [
        "候补ID", "剧目", "场地", "申请人", "状态",
        "目标开始时间", "目标结束时间", "被挡住类型",
        "是否演练数据", "演练会话ID"
    ]
    missing_cols = [c for c in required_cols if c not in header]

    if not missing_cols:
        record_result("BD23: CSV表头包含演练标记列", True, category="DOWNLOAD")
    else:
        record_result("BD23: CSV表头包含演练标记列", False,
                      f"缺少关键列: {missing_cols}\n       实际表头: {header[:200]}",
                      location="#wl-export-btn", category="DOWNLOAD")

    print_step(4, "验证CSV包含演练数据且标记正确")
    has_drill_data = False
    drill_data_correct = True
    for line in lines[1:]:
        if drill_session_id in line:
            has_drill_data = True
            cols = next(csv.reader(io.StringIO(line)))
            header_cols = next(csv.reader(io.StringIO(header)))
            drill_col_idx = header_cols.index("是否演练数据") if "是否演练数据" in header_cols else -1
            session_col_idx = header_cols.index("演练会话ID") if "演练会话ID" in header_cols else -1

            if drill_col_idx >= 0 and cols[drill_col_idx] not in ("是", "True", "1"):
                drill_data_correct = False
            if session_col_idx >= 0 and drill_session_id not in cols[session_col_idx]:
                drill_data_correct = False
            break

    if has_drill_data:
        record_result("BD24: CSV包含演练数据", True, category="DOWNLOAD")
        if drill_data_correct:
            record_result("BD25: CSV演练数据标记正确", True, category="DOWNLOAD")
        else:
            record_result("BD25: CSV演练数据标记正确", False,
                          "演练数据的标记列不正确",
                          location="#wl-export-btn", category="DOWNLOAD")
    else:
        record_result("BD24: CSV包含演练数据", False,
                      f"CSV中未找到演练会话 {drill_session_id} 的数据",
                      location="#wl-export-btn", category="DOWNLOAD")

    return filename


def run_drill_error_hint_tests(page, venue_id, admin_token):
    print_header("第七部分：精细化错误提示 DOM 验证")

    print_step(1, "获取错误分类配置，验证8类错误完整")
    try:
        error_cats = api_get_error_categories(admin_token)
        expected_cats = ["PERMISSION", "CONFLICT", "CANCEL", "MODAL", "TABLE", "DOWNLOAD", "RESTART", "DATA_QUALITY"]
        cat_keys = list(error_cats.keys()) if isinstance(error_cats, dict) else [c["code"] for c in error_cats]
        missing = [c for c in expected_cats if c not in cat_keys]
        if not missing:
            record_result("BD26: 8类错误分类配置完整", True, category="DATA_QUALITY")
        else:
            record_result("BD26: 8类错误分类配置完整", False,
                          f"缺少错误分类: {missing}", category="DATA_QUALITY")
    except Exception as e:
        record_result("BD26: 8类错误分类配置完整", False, str(e), category="DATA_QUALITY")

    print_step(2, "创建演练时故意触发冲突，验证错误提示")
    page.click("button.nav-tab[data-tab='drill']")
    time.sleep(1)
    page.click("#drill-create-btn")
    page.wait_for_selector("#drill-create-modal", state="visible", timeout=3000)

    venue_select = page.locator("#drill-venue")
    if venue_select.count() > 0:
        venue_select.select_option(index=0)

    page.locator("#drill-auto-find").uncheck()
    page.fill("#drill-offset-days", "0")
    page.fill("#drill-target-date", "2020-01-01")
    page.fill("#drill-target-start", "10:00")
    page.fill("#drill-target-end", "12:00")

    page.click("#drill-submit-btn")
    time.sleep(2)

    error_alert = page.locator(".error-alert, .alert-danger, #drill-create-error")
    if error_alert.count() > 0 and error_alert.first.is_visible():
        error_text = error_alert.first.inner_text()
        has_category = any(cat in error_text for cat in ["PERMISSION", "CONFLICT", "CANCEL", "MODAL", "TABLE", "DOWNLOAD", "RESTART", "DATA_QUALITY", "权限", "冲突", "数据"])
        if has_category:
            record_result("BD27: 错误提示包含错误分类", True, category="MODAL")
        else:
            record_result("BD27: 错误提示包含错误分类", False,
                          f"错误提示未包含分类信息: {error_text[:100]}",
                          location=".error-alert", category="MODAL")

        has_suggestion = any(s in error_text for s in ["建议", "请", "应该", "检查"])
        if has_suggestion:
            record_result("BD28: 错误提示包含改进建议", True, category="MODAL")
        else:
            record_result("BD28: 错误提示包含改进建议", False,
                          f"错误提示未包含改进建议: {error_text[:100]}",
                          location=".error-alert", category="MODAL")
    else:
        record_result("BD27: 错误提示包含错误分类", False,
                      "未看到错误提示弹层", location=".error-alert", category="MODAL")
        safe_screenshot(page, "error_hint_missing")

    page.click("#drill-create-modal .modal-close-btn")


def run_drill_restart_verify_tests(page, venue_id, drill_session_id, admin_token):
    print_header("第八部分：服务重启一致性 DOM 验证")

    print_step(1, "获取演练重启前快照作为基准")
    try:
        snapshot_before = api_get_drill_snapshot(admin_token, drill_session_id)
        print(f"{INFO}   重启前候补数: {snapshot_before['waitlist_count']}")
        print(f"{INFO}   重启前预约数: {snapshot_before['booking_count']}")
        print(f"{INFO}   重启前封场数: {snapshot_before['closed_window_count']}")
        print(f"{INFO}   重启前步骤通过数: {snapshot_before['total_passed']}")
        print(f"{INFO}   重启前步骤失败数: {snapshot_before['total_failed']}")
        record_result("BD29: 获取重启前快照成功", True, category="RESTART")
    except Exception as e:
        record_result("BD29: 获取重启前快照成功", False, str(e), category="RESTART")
        return

    print_step(2, "验证浏览器显示的数据与快照一致")
    page.click("button.nav-tab[data-tab='drill']")
    time.sleep(1)

    rows = page.locator("#drill-list .drill-table tbody tr")
    for i in range(rows.count()):
        row = rows.nth(i)
        if drill_session_id in row.inner_text():
            passed_cell = row.locator("td.col-passed").inner_text()
            failed_cell = row.locator("td.col-failed").inner_text()

            passed_match = str(snapshot_before['total_passed']) in passed_cell
            failed_match = str(snapshot_before['total_failed']) in failed_cell

            if passed_match and failed_match:
                record_result("BD30: 浏览器显示与快照一致", True, category="RESTART")
            else:
                record_result("BD30: 浏览器显示与快照一致", False,
                              f"快照通过={snapshot_before['total_passed']}, 页面显示={passed_cell}; "
                              f"快照失败={snapshot_before['total_failed']}, 页面显示={failed_cell}",
                              location="#drill-list .drill-table tbody tr", category="RESTART")
            break

    print_step(3, "获取当前服务PID并验证归属")
    pid_before = get_current_server_pid()
    if pid_before:
        belongs = verify_process_belongs_to_project(pid_before)
        if belongs:
            record_result("BD31: 服务PID验证通过", True, category="RESTART")
            print(f"{INFO}   当前服务PID: {pid_before}")
        else:
            record_result("BD31: 服务PID验证通过", False,
                          f"PID={pid_before} 不属于当前项目", category="RESTART")
            return
    else:
        record_result("BD31: 服务PID验证通过", False,
                      "无法获取服务PID，请确保psutil已安装", category="RESTART")
        return

    print_step(4, "真实停止服务（单PID精确停止）")
    try:
        import psutil
        proc = psutil.Process(pid_before)
        proc.terminate()
        time.sleep(2)
        if proc.is_running():
            proc.kill()
        time.sleep(1)
        print(f"{INFO}   已停止服务 PID={pid_before}")
        record_result("BD32: 服务停止成功", True, category="RESTART")
    except Exception as e:
        record_result("BD32: 服务停止成功", False, str(e), category="RESTART")
        return

    print_step(5, "验证服务已停止")
    pid_after_stop = get_current_server_pid()
    if pid_after_stop is None:
        record_result("BD33: 验证服务已停止", True, category="RESTART")
    else:
        record_result("BD33: 验证服务已停止", False,
                      f"服务仍在运行 PID={pid_after_stop}", category="RESTART")
        return

    print_step(6, "重新启动服务")
    import subprocess
    backend_dir = os.path.dirname(os.path.abspath(__file__))
    try:
        new_proc = subprocess.Popen(
            ["python", "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8002"],
            cwd=backend_dir,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        print(f"{INFO}   新服务启动中 PID={new_proc.pid}")
        time.sleep(5)

        import requests
        max_retries = 10
        for i in range(max_retries):
            try:
                r = requests.get(f"{API_BASE}/health", timeout=2)
                if r.status_code == 200:
                    print(f"{INFO}   服务健康检查通过 (尝试 {i+1}/{max_retries})")
                    break
            except requests.exceptions.RequestException:
                time.sleep(1)
        else:
            record_result("BD34: 服务重启成功", False, "服务重启后健康检查失败", category="RESTART")
            return

        record_result("BD34: 服务重启成功", True, category="RESTART")
    except Exception as e:
        record_result("BD34: 服务重启成功", False, str(e), category="RESTART")
        return

    print_step(7, "验证重启后服务PID已变化")
    pid_after_restart = get_current_server_pid()
    if pid_after_restart and pid_after_restart != pid_before:
        record_result("BD35: 重启后PID已变化", True, category="RESTART")
        print(f"{INFO}   重启前PID: {pid_before}, 重启后PID: {pid_after_restart}")
    else:
        record_result("BD35: 重启后PID已变化", False,
                      f"重启前PID={pid_before}, 重启后PID={pid_after_restart}", category="RESTART")

    print_step(8, "获取重启后快照，验证数据一致性")
    try:
        snapshot_after = api_get_drill_snapshot(admin_token, drill_session_id)
        print(f"{INFO}   重启后候补数: {snapshot_after['waitlist_count']}")
        print(f"{INFO}   重启后预约数: {snapshot_after['booking_count']}")
        print(f"{INFO}   重启后封场数: {snapshot_after['closed_window_count']}")

        waitlist_match = snapshot_before['waitlist_count'] == snapshot_after['waitlist_count']
        booking_match = snapshot_before['booking_count'] == snapshot_after['booking_count']
        closed_match = snapshot_before['closed_window_count'] == snapshot_after['closed_window_count']
        passed_match = snapshot_before['total_passed'] == snapshot_after['total_passed']
        failed_match = snapshot_before['total_failed'] == snapshot_after['total_failed']

        all_match = waitlist_match and booking_match and closed_match and passed_match and failed_match

        if all_match:
            record_result("BD36: 重启前后数据完全一致", True, category="RESTART")
        else:
            mismatch = []
            if not waitlist_match:
                mismatch.append(f"候补数: {snapshot_before['waitlist_count']} → {snapshot_after['waitlist_count']}")
            if not booking_match:
                mismatch.append(f"预约数: {snapshot_before['booking_count']} → {snapshot_after['booking_count']}")
            if not closed_match:
                mismatch.append(f"封场数: {snapshot_before['closed_window_count']} → {snapshot_after['closed_window_count']}")
            if not passed_match:
                mismatch.append(f"通过数: {snapshot_before['total_passed']} → {snapshot_after['total_passed']}")
            if not failed_match:
                mismatch.append(f"失败数: {snapshot_before['total_failed']} → {snapshot_after['total_failed']}")

            record_result("BD36: 重启前后数据完全一致", False,
                          f"数据不一致: {'; '.join(mismatch)}", category="RESTART")
    except Exception as e:
        record_result("BD36: 重启前后数据完全一致", False, str(e), category="RESTART")

    print_step(9, "验证浏览器显示的数据与重启后快照一致")
    page.reload()
    page.wait_for_selector("#main-app", state="visible", timeout=5000)
    page.click("button.nav-tab[data-tab='drill']")
    page.wait_for_selector("#drill-list", state="visible", timeout=3000)
    time.sleep(1)

    rows = page.locator("#drill-list .drill-table tbody tr")
    for i in range(rows.count()):
        row = rows.nth(i)
        if drill_session_id in row.inner_text():
            status_cell = row.locator("td.col-status").inner_text()
            passed_cell = row.locator("td.col-passed").inner_text()
            failed_cell = row.locator("td.col-failed").inner_text()

            try:
                snapshot_after = api_get_drill_snapshot(admin_token, drill_session_id)
                passed_match = str(snapshot_after['total_passed']) in passed_cell
                failed_match = str(snapshot_after['total_failed']) in failed_cell

                if passed_match and failed_match:
                    record_result("BD37: 重启后浏览器显示与快照一致", True, category="RESTART")
                else:
                    record_result("BD37: 重启后浏览器显示与快照一致", False,
                                  f"快照通过={snapshot_after['total_passed']}, 页面显示={passed_cell}; "
                                  f"快照失败={snapshot_after['total_failed']}, 页面显示={failed_cell}",
                                  location="#drill-list .drill-table tbody tr", category="RESTART")
            except Exception as e:
                record_result("BD37: 重启后浏览器显示与快照一致", False, str(e), category="RESTART")
            break


def run_drill_cleanup_tests(page, venue_id, drill_session_id, admin_token):
    print_header("第九部分：演练样本清理 DOM 验证")

    print_step(1, "点击清理按钮，验证确认弹层")
    page.click("button.nav-tab[data-tab='drill']")
    time.sleep(1)

    rows = page.locator("#drill-list .drill-table tbody tr")
    for i in range(rows.count()):
        row = rows.nth(i)
        if drill_session_id in row.inner_text():
            row.locator("button", has_text="清理").click()
            break

    page.wait_for_selector("#drill-cleanup-confirm-modal", state="visible", timeout=3000)

    ok, _ = check_element(page, "#drill-cleanup-confirm-modal",
                          "BD38: 清理确认弹层打开", "清理确认弹层",
                          category="MODAL")
    if ok:
        ok2, _ = check_element_text(page, "#drill-cleanup-confirm-modal",
                                     "确认清理", "BD38: 弹层包含确认提示",
                                     "清理确认弹层文本", category="MODAL")
        if ok2:
            record_result("BD38: 清理确认弹层打开", True, category="MODAL")

    print_step(2, "确认清理，验证清理成功")
    page.click("#drill-cleanup-confirm-btn")
    time.sleep(2)

    try:
        cleanup_result = api_get_drill_snapshot(admin_token, drill_session_id)
        cleanup_done = cleanup_result.get("cleanup_completed", False)
        if cleanup_done:
            record_result("BD39: 演练数据清理成功", True, category="DATA_QUALITY")
        else:
            record_result("BD39: 演练数据清理成功", False,
                          f"清理状态: {cleanup_result.get('cleanup_completed')}",
                          category="DATA_QUALITY")
    except Exception as e:
        if "404" in str(e) or "不存在" in str(e):
            record_result("BD39: 演练数据清理成功", True, category="DATA_QUALITY")
        else:
            record_result("BD39: 演练数据清理成功", False, str(e), category="DATA_QUALITY")

    print_step(3, "验证清理后候补列表中无演练数据")
    page.click("button.nav-tab[data-tab='waitlist']")
    time.sleep(1)
    page.fill("#wl-filter-production", f"DRILL_{drill_session_id[-8:]}")
    page.click("#wl-search-btn")
    time.sleep(1)

    cards = page.locator("#waitlist-list .booking-card")
    if cards.count() == 0:
        record_result("BD40: 清理后候补列表无演练数据", True, category="DATA_QUALITY")
    else:
        record_result("BD40: 清理后候补列表无演练数据", False,
                      f"清理后仍有 {cards.count()} 条演练数据",
                      location="#waitlist-list", category="DATA_QUALITY")
        safe_screenshot(page, "cleanup_leftover")


def run_drill_dirty_data_resilience_tests(page, venue_id, admin_token):
    print_header("第十部分：脏数据环境下主回归入口韧性验证")

    print_step(1, "创建第一个演练会话（制造脏数据环境）")
    try:
        drill1 = api_create_drill_session(admin_token, venue_id, offset_days=95)
        drill_sessions_to_cleanup.append(drill1["drill_session_id"])
        print(f"{INFO}   演练1: {drill1['drill_session_id']}")
        record_result("BD41: 创建第一个演练（脏数据）", True, category="DATA_QUALITY")
    except Exception as e:
        record_result("BD41: 创建第一个演练（脏数据）", False, str(e), category="DATA_QUALITY")

    print_step(2, "创建第二个演练会话（制造更多脏数据）")
    try:
        drill2 = api_create_drill_session(admin_token, venue_id, offset_days=100)
        drill_sessions_to_cleanup.append(drill2["drill_session_id"])
        print(f"{INFO}   演练2: {drill2['drill_session_id']}")
        record_result("BD42: 创建第二个演练（脏数据）", True, category="DATA_QUALITY")
    except Exception as e:
        record_result("BD42: 创建第二个演练（脏数据）", False, str(e), category="DATA_QUALITY")

    print_step(3, "验证主回归入口仍能正常创建演练")
    try:
        drill3 = api_create_drill_session(admin_token, venue_id, offset_days=105)
        drill_sessions_to_cleanup.append(drill3["drill_session_id"])
        print(f"{INFO}   演练3: {drill3['drill_session_id']}")
        print(f"{INFO}   演练状态: {drill3['status']}")
        print(f"{INFO}   通过步骤: {drill3['total_passed']}/{drill3['total_passed'] + drill3['total_failed']}")

        steps_passed = drill3["total_passed"] >= 10
        if steps_passed:
            record_result("BD43: 脏数据环境下主回归正常执行", True, category="DATA_QUALITY")
        else:
            record_result("BD43: 脏数据环境下主回归正常执行", False,
                          f"仅通过 {drill3['total_passed']} 个步骤，预期至少10个",
                          category="DATA_QUALITY")
    except Exception as e:
        record_result("BD43: 脏数据环境下主回归正常执行", False,
                      f"脏数据环境下创建演练失败: {e}", category="DATA_QUALITY")

    print_step(4, "验证浏览器列表仍能正常显示所有演练")
    page.reload()
    page.wait_for_selector("#main-app", state="visible", timeout=5000)
    page.click("button.nav-tab[data-tab='drill']")
    page.wait_for_selector("#drill-list", state="visible", timeout=3000)
    time.sleep(2)

    rows = page.locator("#drill-list .drill-table tbody tr")
    if rows.count() >= 3:
        record_result(f"BD44: 浏览器列表正常显示 {rows.count()} 条演练", True, category="TABLE")
    else:
        record_result("BD44: 浏览器列表正常显示所有演练", False,
                      f"预期至少3条，实际显示 {rows.count()} 条",
                      location="#drill-list .drill-table tbody", category="TABLE")


def main():
    parser = argparse.ArgumentParser(description="候补演练浏览器级回归测试")
    parser.add_argument("--restart", action="store_true", help="启用真实服务重启校验")
    parser.add_argument("--headless", action="store_true", default=True, help="无头模式运行")
    args = parser.parse_args()

    print_header("候补回归演练 - 浏览器级测试")
    print(f"RUN_ID: {RUN_ID}")
    print(f"TAG_PREFIX: {TAG_PREFIX}")
    print(f"日志文件: {LOG_FILE}")
    print(f"截图目录: {SCREENSHOT_DIR}")
    print(f"测试地址: {BASE_URL}")
    print(f"重启校验: {'启用' if args.restart else '禁用'}")
    print()

    import requests
    try:
        health = requests.get(f"{API_BASE}/health", timeout=5)
        print(f"{PASS} 服务健康检查通过 status={health.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"{FAIL} 服务未启动或不可访问: {e}")
        print('       请先启动服务: cd backend ; python -m uvicorn main:app --host 127.0.0.1 --port 8002')
        sys.exit(1)

    print_step(0, "准备测试账号和场地")
    try:
        admin_token, admin_user = api_login("admin", "admin123")
        member_token, member_user = api_login("lisi", "123456")
        print(f"{INFO} 管理员: {admin_user['username']} (ID={admin_user['id']})")
        print(f"{INFO} 成员: {member_user['username']} (ID={member_user['id']})")

        venues = requests.get(f"{API_BASE}/venues", headers={"Authorization": f"Bearer {admin_token}"}).json()
        if not venues:
            nv = requests.post(f"{API_BASE}/venues",
                               headers={"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"},
                               json={"name": "DRILL剧场", "capacity": 100}).json()
            venue_id = nv["id"]
        else:
            venue_id = venues[0]["id"]
        print(f"{INFO} 测试场地ID: {venue_id}")
    except Exception as e:
        print(f"{FAIL} 准备测试环境失败: {e}")
        sys.exit(1)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=args.headless)
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()

        drill_session_id = None
        try:
            browser_login(page, "admin", "admin123")
            print(f"{PASS} 浏览器登录成功")

            run_drill_entry_tests(page, venue_id)

            run_create_drill_modal_tests(page, venue_id)

            drill_session_id = run_drill_execution_tests(page, venue_id, admin_token)

            if drill_session_id:
                run_member_drill_view_tests(page, venue_id, drill_session_id, member_token)

                run_admin_drill_management_tests(page, venue_id, drill_session_id, admin_token)

                run_drill_csv_export_tests(page, venue_id, drill_session_id, admin_token)

                run_drill_error_hint_tests(page, venue_id, admin_token)

                if args.restart:
                    run_drill_restart_verify_tests(page, venue_id, drill_session_id, admin_token)

                run_drill_cleanup_tests(page, venue_id, drill_session_id, admin_token)

                run_drill_dirty_data_resilience_tests(page, venue_id, admin_token)

        except Exception as e:
            print(f"\n{FAIL} 测试异常中断: {e}")
            import traceback
            traceback.print_exc()
            safe_screenshot(page, "error_crash")

        finally:
            browser.close()

    print_step(99, "清理所有演练会话")
    for session_id in drill_sessions_to_cleanup:
        try:
            api_cleanup_drill(admin_token, session_id)
            print(f"{INFO}   已清理演练: {session_id}")
        except Exception as e:
            print(f"{WARN}   清理演练 {session_id} 失败: {e}")

    print()
    print("=" * 80)
    print(f"  最终测试结果 - RUN_ID={RUN_ID}")
    print("=" * 80)
    print(f"  通过: {pass_count}")
    print(f"  失败: {fail_count}")
    print(f"  总计: {pass_count + fail_count}")
    print()

    category_stats = {}
    for t in test_results:
        cat = t.get("category", "UNKNOWN")
        if cat not in category_stats:
            category_stats[cat] = {"passed": 0, "failed": 0}
        if t["passed"]:
            category_stats[cat]["passed"] += 1
        else:
            category_stats[cat]["failed"] += 1

    if len(category_stats) > 1:
        print("  按错误分类统计:")
        for cat, stats in sorted(category_stats.items()):
            total = stats["passed"] + stats["failed"]
            if total > 0:
                rate = stats["passed"] / total * 100
                print(f"    {cat:15s} 通过:{stats['passed']:2d} 失败:{stats['failed']:2d} 通过率:{rate:5.1f}%")
        print()

    if test_results:
        print("  失败明细:")
        for t in test_results:
            if not t["passed"]:
                cat_info = f" [{t.get('category', '')}]" if t.get("category") else ""
                print(f"    {FAIL} {t['name']}{cat_info}")
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
    sys.exit(main())
