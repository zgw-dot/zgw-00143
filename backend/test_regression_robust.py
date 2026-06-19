import sys
import io
import requests
import json
import hashlib
from datetime import datetime, timedelta
from typing import Tuple, Optional, List, Dict, Any

# ============ 配置区 ============
RUN_ID = datetime.now().strftime("%Y%m%d%H%M%S")
TAG_PREFIX = f"REGRESSION-{RUN_ID}"
LOG_FILE = f"regression_{RUN_ID}.txt"

# 时间窗起点：当前时间 + 180天，避开已有业务数据
TIME_BASE = datetime.now() + timedelta(days=180)
# 每次预约时长 1 小时
SLOT_DURATION = timedelta(hours=1)
# 冲突时后移步长
RETRY_STEP = timedelta(hours=2)
# 最大重试次数
MAX_RETRIES = 10

# ============ 日志输出 ============
out_file = open(LOG_FILE, "w", encoding="utf-8")
class Tee:
    def __init__(self, *files): self.files = files
    def write(self, s):
        for f in self.files: f.write(s); f.flush()
    def flush(self):
        for f in self.files: f.flush()

sys.stdout = Tee(sys.stdout, out_file)
sys.stderr = Tee(sys.stderr, out_file)

BASE = "http://127.0.0.1:8000/api"
FAIL = "[FAIL]"
PASS = "[PASS]"
WARN = "[WARN]"
STEP = "[STEP]"
INFO = "[INFO]"

created_booking_ids: List[int] = []  # 本次测试创建的预约ID
pass_count = 0
fail_count = 0
test_results: List[Dict[str, Any]] = []

def login(username, password):
    r = requests.post(f"{BASE}/auth/login", data={"username": username, "password": password})
    if r.status_code != 200:
        raise AssertionError(f"登录失败 {username}: HTTP {r.status_code} {r.text}")
    return r.json()["access_token"]

def auth_headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

def print_header(title):
    print()
    print("=" * 80)
    print(f"  {title}")
    print("=" * 80)

def print_step(step_num, desc):
    print()
    print(f"{STEP} {step_num:3d}. {desc}")
    print("-" * 80)

def record_result(test_name, passed, detail=""):
    global pass_count, fail_count
    test_results.append({"name": test_name, "passed": passed, "detail": detail})
    if passed:
        pass_count += 1
        print(f"{PASS} {test_name}")
    else:
        fail_count += 1
        print(f"{FAIL} {test_name}")
        if detail:
            print(f"       原因: {detail}")

def find_conflicts(db_token, venue_id, start_time, end_time, exclude_ids=None):
    """检查给定时段在指定场地是否有冲突，返回冲突的预约列表"""
    exclude_ids = exclude_ids or []
    s = start_time.isoformat() if isinstance(start_time, datetime) else start_time
    e = end_time.isoformat() if isinstance(end_time, datetime) else end_time
    r = requests.get(f"{BASE}/bookings", headers=auth_headers(db_token), params={"page_size": 200})
    if r.status_code != 200:
        raise AssertionError(f"查询预约列表失败: HTTP {r.status_code} {r.text}")
    bookings = r.json()["items"]
    conflicts = []
    s_dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    e_dt = datetime.fromisoformat(e.replace("Z", "+00:00"))
    for b in bookings:
        if b["id"] in exclude_ids:
            continue
        if b["venue_id"] != venue_id:
            continue
        if b["status"] in ("cancelled",):
            continue
        bs = datetime.fromisoformat(b["start_time"].replace("Z", "+00:00"))
        be = datetime.fromisoformat(b["end_time"].replace("Z", "+00:00"))
        if s_dt < be and bs < e_dt:
            conflicts.append(b)
    return conflicts

def find_safe_slot(admin_token, venue_id, base_date, target_hour, target_minute=0, duration=SLOT_DURATION, is_outside_hours=False, exclude_ids=None):
    """
    找到一个安全的时段，避开已有预约。
    如果 is_outside_hours=True，找一个不在开放时段内的时段（周二 07:00-08:00 类似）
    """
    # 找下一个周二（0=周一, 1=周二）
    days_ahead = (1 - base_date.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7  # 下周周二，避免当天
    slot_date = base_date + timedelta(days=days_ahead)

    for attempt in range(MAX_RETRIES):
        if is_outside_hours:
            # 开放时段是 9-12, 14-18, 19-22。选 07:00-08:00 绝对非开放
            start = slot_date.replace(hour=7, minute=0, second=0, microsecond=0)
            end = start + duration
        else:
            start = slot_date.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)
            end = start + duration

        conflicts = find_conflicts(admin_token, venue_id, start, end, exclude_ids)
        if not conflicts:
            return start, end

        # 冲突，后移步长
        print(f"{INFO}   时段 {start} ~ {end} 与 {len(conflicts)} 条预约冲突，后移 {RETRY_STEP} 重试...")
        for c in conflicts:
            print(f"{INFO}     - 挡住预约: ID={c['id']} {c['title'][:50]} {c['status']} {c['start_time']}~{c['end_time']}")
        slot_date += RETRY_STEP

    raise AssertionError(f"在 {venue_id} 场地尝试 {MAX_RETRIES} 次仍未找到空闲时段，最后尝试: {start} ~ {end}")

def make_title(short_name):
    """生成带唯一标识的标题"""
    return f"{TAG_PREFIX}-{short_name}"

def assert_http(test_name, response, expected_status, detail_if_fail=""):
    """断言 HTTP 状态码，失败时输出完整响应"""
    global pass_count, fail_count
    if response.status_code == expected_status:
        return True
    detail = f"预期 HTTP {expected_status}，实际 HTTP {response.status_code}"
    if detail_if_fail:
        detail += f" | {detail_if_fail}"
    try:
        resp_json = response.json()
        detail += f"\n       响应体: {json.dumps(resp_json, ensure_ascii=False, indent=10)}"
        # 如果是开放时段冲突，特别格式化显示
        if isinstance(resp_json, dict) and resp_json.get("detail"):
            d = resp_json["detail"]
            if isinstance(d, dict) and d.get("open_slot_violations"):
                detail += "\n       ---- 开放时段违规详情 ----"
                for v in d["open_slot_violations"]:
                    detail += f"\n       - {v.get('reason', 'N/A')}"
            if isinstance(d, dict) and d.get("conflicts"):
                detail += "\n       ---- 时间冲突详情 ----"
                for c in d["conflicts"]:
                    detail += f"\n       - ID={c.get('booking_id')} {c.get('title')[:40]} {c.get('start_time')}~{c.get('end_time')} 申请人={c.get('user_name')}"
    except Exception:
        detail += f"\n       响应体(非JSON): {response.text[:500]}"
    record_result(test_name, False, detail)
    return False

def track_booking(booking_id):
    """记录本次创建的预约ID，用于清理"""
    if booking_id not in created_booking_ids:
        created_booking_ids.append(booking_id)
        print(f"{INFO}   追踪预约 ID={booking_id}")

def cleanup_test_data(admin_token):
    """测试结束后，只清理本次测试创建的预约"""
    print()
    print_header("测试数据清理")
    if not created_booking_ids:
        print(f"{INFO} 本次无测试数据需要清理")
        return

    cancelled_count = 0
    for bid in created_booking_ids:
        try:
            # 先查版本号
            r = requests.get(f"{BASE}/bookings/{bid}", headers=auth_headers(admin_token))
            if r.status_code != 200:
                print(f"{WARN} 无法查询预约 {bid}: {r.status_code}")
                continue
            b = r.json()
            version = b["version"]
            if b["status"] == "cancelled":
                print(f"{INFO} 预约 {bid} 已取消，跳过")
                continue

            # 取消预约
            r2 = requests.patch(f"{BASE}/bookings/{bid}/status",
                headers=auth_headers(admin_token),
                json={"status": "cancelled", "version": version})
            if r2.status_code == 200:
                cancelled_count += 1
                print(f"{PASS} 已取消预约 ID={bid} ({b['title'][:50]})")
            else:
                print(f"{WARN} 取消预约 {bid} 失败: HTTP {r2.status_code} {r2.text[:200]}")
        except Exception as e:
            print(f"{WARN} 清理预约 {bid} 异常: {e}")

    print(f"\n{INFO} 清理完成：成功取消 {cancelled_count}/{len(created_booking_ids)} 条预约")
    # 验证清理结果
    remaining = []
    for bid in created_booking_ids:
        r = requests.get(f"{BASE}/bookings/{bid}", headers=auth_headers(admin_token))
        if r.status_code == 200 and r.json()["status"] != "cancelled":
            remaining.append(bid)
    if remaining:
        print(f"{WARN} 仍有 {len(remaining)} 条预约未取消: {remaining}")
    else:
        print(f"{PASS} 所有测试预约已成功取消")

def run_regression_suite(pass_num, member_token, admin_token):
    """执行一遍完整的回归测试套件"""
    print_header(f"第 {pass_num} 轮回归测试 - RUN_ID={RUN_ID}")

    # ---- 基础日期 ----
    base_week1 = TIME_BASE + timedelta(days=pass_num * 14)  # 每轮错开2周
    base_week2 = base_week1 + timedelta(days=7)

    # =============================================================
    # 第一组：验证 Bug 已修复（非开放时段被正确拒绝）
    # =============================================================
    print_header(f"第 {pass_num} 轮 - Bug 修复验证")

    # Test 1: 草稿在非开放时段应被 409 拒绝
    print_step(1, "草稿在非开放时段（周二 07:00-08:00）应被拒绝")
    start, end = find_safe_slot(admin_token, 1, base_week1, 7, is_outside_hours=True)
    r = requests.post(f"{BASE}/bookings",
        headers=auth_headers(member_token),
        json={
            "title": make_title(f"DRAFT-OUTSIDE-{pass_num}"),
            "production": make_title("回归测试剧目"),
            "venue_id": 1, "status": "draft", "priority": 10, "notes": TAG_PREFIX,
            "start_time": start.isoformat(), "end_time": end.isoformat()
        })
    if not assert_http(f"Test{pass_num}-1 草稿非开放时段校验", r, 409):
        if r.status_code == 200:
            track_booking(r.json()["id"])
    else:
        detail = r.json().get("detail", {})
        msg = detail.get("message", "") if isinstance(detail, dict) else str(detail)
        if "不在开放时段内" in msg:
            record_result(f"Test{pass_num}-1 草稿非开放时段校验", True, f"正确拦截，原因: {msg[:80]}")
        else:
            record_result(f"Test{pass_num}-1 草稿非开放时段校验", False,
                f"409但原因不包含'不在开放时段内': {msg}")

    # Test 2: 待审在非开放时段应被 409 拒绝
    print_step(2, "待审在非开放时段（周二 07:00-08:00）应被拒绝")
    start, end = find_safe_slot(admin_token, 1, base_week1, 7, is_outside_hours=True)
    r = requests.post(f"{BASE}/bookings",
        headers=auth_headers(member_token),
        json={
            "title": make_title(f"PENDING-OUTSIDE-{pass_num}"),
            "production": make_title("回归测试剧目"),
            "venue_id": 1, "status": "pending", "priority": 10, "notes": TAG_PREFIX,
            "start_time": start.isoformat(), "end_time": end.isoformat()
        })
    if not assert_http(f"Test{pass_num}-2 待审非开放时段校验", r, 409):
        if r.status_code == 200:
            track_booking(r.json()["id"])
    else:
        detail = r.json().get("detail", {})
        msg = detail.get("message", "") if isinstance(detail, dict) else str(detail)
        if "不在开放时段内" in msg:
            record_result(f"Test{pass_num}-2 待审非开放时段校验", True, f"正确拦截，原因: {msg[:80]}")
        else:
            record_result(f"Test{pass_num}-2 待审非开放时段校验", False,
                f"409但原因不包含'不在开放时段内': {msg}")

    # =============================================================
    # 第二组：验证正常链路可用
    # =============================================================
    print_header(f"第 {pass_num} 轮 - 正常链路 + 改期状态流转 + 改期重提")

    # Test 3: 开放时段创建草稿
    print_step(3, "开放时段创建草稿应成功")
    start_draft, end_draft = find_safe_slot(admin_token, 1, base_week1, 10)
    r = requests.post(f"{BASE}/bookings",
        headers=auth_headers(member_token),
        json={
            "title": make_title(f"DRAFT-OK-{pass_num}"),
            "production": make_title("回归测试剧目"),
            "venue_id": 1, "status": "draft", "priority": 10, "notes": TAG_PREFIX,
            "start_time": start_draft.isoformat(), "end_time": end_draft.isoformat()
        })
    if not assert_http(f"Test{pass_num}-3 创建草稿（开放时段）", r, 200):
        return None, None
    draft = r.json()
    track_booking(draft["id"])
    record_result(f"Test{pass_num}-3 创建草稿（开放时段）", True,
        f"ID={draft['id']} status={draft['status']}")

    # Test 4: 草稿提交待审（状态流转为 pending）
    print_step(4, "草稿提交待审（改期重提链路也用这个）")
    r = requests.patch(f"{BASE}/bookings/{draft['id']}/status",
        headers=auth_headers(member_token),
        json={"status": "pending", "version": draft["version"]})
    if not assert_http(f"Test{pass_num}-4 草稿→待审", r, 200):
        return None, None
    pending = r.json()
    record_result(f"Test{pass_num}-4 草稿→待审", True,
        f"ID={pending['id']} status={pending['status']} version={pending['version']}")

    # Test 5: 管理员审批确认
    print_step(5, "管理员确认待审预约")
    r = requests.patch(f"{BASE}/bookings/{pending['id']}/status",
        headers=auth_headers(admin_token),
        json={"status": "confirmed", "version": pending["version"]})
    if not assert_http(f"Test{pass_num}-5 管理员确认", r, 200):
        return None, None
    confirmed = r.json()
    record_result(f"Test{pass_num}-5 管理员确认", True,
        f"ID={confirmed['id']} status={confirmed['status']} version={confirmed['version']}")

    # Test 6: 已确认预约改期到非开放时段应被拒绝
    print_step(6, "已确认预约改期到非开放时段应被拒绝")
    start_bad, end_bad = find_safe_slot(admin_token, 1, base_week2, 7, is_outside_hours=True)
    r = requests.post(f"{BASE}/bookings/{confirmed['id']}/reschedule",
        headers=auth_headers(admin_token),
        json={
            "version": confirmed["version"],
            "new_start_time": start_bad.isoformat(),
            "new_end_time": end_bad.isoformat(),
            "reason": make_title(f"改期到非开放时段测试-{pass_num}")
        })
    if not assert_http(f"Test{pass_num}-6 改期到非开放时段", r, 409):
        pass  # 断言已处理
    else:
        detail = r.json().get("detail", {})
        msg = detail.get("message", "") if isinstance(detail, dict) else str(detail)
        if "不在开放时段内" in msg:
            record_result(f"Test{pass_num}-6 改期到非开放时段", True, f"正确拦截，原因: {msg[:80]}")
        else:
            record_result(f"Test{pass_num}-6 改期到非开放时段", False,
                f"409但原因不包含'不在开放时段内': {msg}")

    # Test 7: 已确认预约改期到开放时段，状态应为 rescheduling（不是 pending）
    print_step(7, "已确认预约改期到开放时段，状态应为 'rescheduling'")
    start_good, end_good = find_safe_slot(admin_token, 1, base_week2, 14,
        exclude_ids=[confirmed["id"]])
    r = requests.post(f"{BASE}/bookings/{confirmed['id']}/reschedule",
        headers=auth_headers(admin_token),
        json={
            "version": confirmed["version"],
            "new_start_time": start_good.isoformat(),
            "new_end_time": end_good.isoformat(),
            "reason": make_title(f"排练时间调整，需要改期-{pass_num}")
        })
    if not assert_http(f"Test{pass_num}-7 改期到开放时段", r, 200):
        return None, None
    rescheduled = r.json()
    status = rescheduled["status"]
    if status == "rescheduling":
        record_result(f"Test{pass_num}-7 改期状态", True,
            f"ID={rescheduled['id']} status={status} 正确！不是 pending")
    elif status == "pending":
        record_result(f"Test{pass_num}-7 改期状态", False,
            f"状态还是 pending！应该是 rescheduling。预约 {rescheduled['id']}")
    else:
        record_result(f"Test{pass_num}-7 改期状态", False,
            f"状态异常！实际='{status}'，预期='rescheduling'")

    # Test 8: 改期重提（rescheduling → pending → confirmed）
    print_step(8, "改期重提链路：rescheduling → pending → confirmed")

    # 8a: 改期后状态是 rescheduling，提交审批 → pending
    r = requests.patch(f"{BASE}/bookings/{rescheduled['id']}/status",
        headers=auth_headers(member_token),
        json={"status": "pending", "version": rescheduled["version"]})
    if not assert_http(f"Test{pass_num}-8a 改期后重提待审", r, 200):
        return rescheduled, None
    re_pending = r.json()
    if re_pending["status"] == "pending":
        record_result(f"Test{pass_num}-8a 改期后重提待审", True,
            f"ID={re_pending['id']} status={re_pending['status']}")
    else:
        record_result(f"Test{pass_num}-8a 改期后重提待审", False,
            f"状态应为 pending，实际={re_pending['status']}")
        return rescheduled, None

    # 8b: 管理员再次确认 → confirmed
    r = requests.patch(f"{BASE}/bookings/{re_pending['id']}/status",
        headers=auth_headers(admin_token),
        json={"status": "confirmed", "version": re_pending["version"]})
    if not assert_http(f"Test{pass_num}-8b 改期后重提审批", r, 200):
        return rescheduled, None
    re_confirmed = r.json()
    if re_confirmed["status"] == "confirmed":
        record_result(f"Test{pass_num}-8b 改期后重提审批", True,
            f"ID={re_confirmed['id']} status={re_confirmed['status']} version={re_confirmed['version']}")
    else:
        record_result(f"Test{pass_num}-8b 改期后重提审批", False,
            f"状态应为 confirmed，实际={re_confirmed['status']}")
        return rescheduled, None

    # Test 9: 改期历史查询
    print_step(9, "查询改期历史，验证原时段/新时段/原因/操作人")
    r = requests.get(f"{BASE}/bookings/{confirmed['id']}/reschedule-history",
                     headers=auth_headers(admin_token))
    if not assert_http(f"Test{pass_num}-9 改期历史API", r, 200):
        return re_confirmed, None
    history = r.json()
    if len(history) >= 1:
        h = history[0]
        has_all = all(k in h for k in ["original_start_time", "original_end_time",
                                         "new_start_time", "new_end_time",
                                         "reason", "operator_name", "created_at"])
        if has_all and h["operator_name"] == "系统管理员":
            record_result(f"Test{pass_num}-9 改期历史字段", True,
                f"共{len(history)}条记录，字段完整")
        else:
            missing = [k for k in ["original_start_time", "original_end_time",
                                     "new_start_time", "new_end_time",
                                     "reason", "operator_name"] if k not in h]
            record_result(f"Test{pass_num}-9 改期历史字段", False,
                f"缺少字段: {missing}")
    else:
        record_result(f"Test{pass_num}-9 改期历史字段", False,
            f"改期记录数应为>=1，实际={len(history)}")

    # Test 10: CSV 导出验证
    print_step(10, "CSV 导出应包含改期历史列和数据")
    r = requests.get(f"{BASE}/exports/bookings.csv", headers=auth_headers(admin_token))
    if not assert_http(f"Test{pass_num}-10 CSV导出", r, 200):
        return re_confirmed, None
    csv_text = r.content.decode("utf-8-sig")
    lines = csv_text.splitlines()
    header = lines[0] if lines else ""
    required_cols = ["原时段", "新时段", "改期原因", "改期操作人"]
    all_cols = all(c in header for c in required_cols)
    has_data = any(TAG_PREFIX in line for line in lines)
    if all_cols and has_data:
        record_result(f"Test{pass_num}-10 CSV导出", True,
            f"共{len(lines)}行，表头完整，含本次测试数据")
    else:
        reasons = []
        if not all_cols:
            missing = [c for c in required_cols if c not in header]
            reasons.append(f"表头缺失: {missing}")
        if not has_data:
            reasons.append(f"CSV中无本次测试数据(TAG={TAG_PREFIX})")
        record_result(f"Test{pass_num}-10 CSV导出", False, "; ".join(reasons))

    return re_confirmed, csv_text

# ============ 主流程 ============
print_header(f"剧场排练厅预约系统 - 稳固版回归测试")
print(f"RUN_ID: {RUN_ID}")
print(f"测试时间: {datetime.now().isoformat()}")
print(f"TAG_PREFIX: {TAG_PREFIX}")
print(f"时间基准: {TIME_BASE.isoformat()}")
print(f"日志文件: {LOG_FILE}")
print()
print(f"{INFO} 登录中...")
member_token = login("lisi", "123456")
admin_token = login("admin", "admin123")
print(f"{PASS} 登录成功")

try:
    # 第 1 轮
    result1, csv1 = run_regression_suite(1, member_token, admin_token)

    # 第 2 轮
    print()
    print_header("第 2 轮回归测试（验证一致性）")
    result2, csv2 = run_regression_suite(2, member_token, admin_token)

    # 两轮结果对比
    print_header("两轮测试一致性对比")
    if result1 and result2:
        # 验证两轮状态流转一致
        if result1["status"] == result2["status"] == "confirmed":
            print(f"{PASS} 两轮最终状态一致：都是 confirmed")
        else:
            print(f"{FAIL} 两轮最终状态不一致")
            print(f"       第1轮: {result1['status']}")
            print(f"       第2轮: {result2['status']}")
            fail_count += 1

        # 验证 CSV 表头一致
        if csv1 and csv2:
            header1 = csv1.splitlines()[0]
            header2 = csv2.splitlines()[0]
            if header1 == header2:
                print(f"{PASS} 两轮 CSV 表头完全一致")
            else:
                print(f"{FAIL} 两轮 CSV 表头不一致")
                print(f"       第1轮: {header1}")
                print(f"       第2轮: {header2}")
                fail_count += 1

            # 验证每轮都有改期数据
            has_resched1 = any("改期" in line for line in csv1.splitlines()[1:])
            has_resched2 = any("改期" in line for line in csv2.splitlines()[1:])
            if has_resched1 and has_resched2:
                print(f"{PASS} 两轮 CSV 都包含改期历史数据")
            else:
                print(f"{FAIL} CSV 改期数据缺失")
                print(f"       第1轮含改期数据: {has_resched1}")
                print(f"       第2轮含改期数据: {has_resched2}")
                fail_count += 1

    # 清理测试数据
    cleanup_test_data(admin_token)

except Exception as e:
    print(f"\n{FAIL} 测试异常中断: {e}")
    import traceback
    traceback.print_exc()
    # 异常时也尝试清理
    try:
        cleanup_test_data(admin_token)
    except:
        pass

# 最终汇总
print()
print("=" * 80)
print(f"  最终测试结果 - RUN_ID={RUN_ID}")
print("=" * 80)
print(f"  通过: {pass_count}")
print(f"  失败: {fail_count}")
print(f"  总计: {pass_count + fail_count}")
print()
if test_results:
    print("  明细:")
    for t in test_results:
        status = PASS if t["passed"] else FAIL
        print(f"    {status} {t['name']}")
        if not t["passed"] and t["detail"]:
            print(f"           {t['detail'][:200]}")
print()
if fail_count == 0:
    print(f"{PASS} 全部测试通过！RUN_ID={RUN_ID}")
else:
    print(f"{FAIL} 有 {fail_count} 项测试失败，请检查日志 {LOG_FILE}")
print("=" * 80)

out_file.close()

sys.exit(0 if fail_count == 0 else 1)
