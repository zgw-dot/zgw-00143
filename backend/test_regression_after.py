import sys
import io
import requests
import json
from datetime import datetime, timedelta

# ============ 加固部分：唯一标识 + 日志 ============
RUN_ID = datetime.now().strftime("%Y%m%d%H%M%S")
TAG = f"REG-AFTER-{RUN_ID}"
LOG_FILE = f"reg_after_{RUN_ID}.txt"

log_file = open(LOG_FILE, "w", encoding="utf-8")
_orig_stdout = sys.stdout
_orig_stderr = sys.stderr

class Tee:
    def __init__(self, *files): self.files = files
    def write(self, s):
        for f in self.files:
            try:
                if getattr(f, 'closed', False): continue
                f.write(s); f.flush()
            except: pass
    def flush(self):
        for f in self.files:
            try:
                if getattr(f, 'closed', False): continue
                f.flush()
            except: pass

sys.stdout = Tee(_orig_stdout, log_file)
sys.stderr = Tee(_orig_stderr, log_file)

BASE = "http://127.0.0.1:8000/api"
OK = "[OK]"
FAIL = "[FAIL]"
WARN = "[WARN]"
STEP = "[STEP]"

created_ids = []  # 追踪本次创建的预约ID
fail_count = 0

def login(username, password):
    r = requests.post(f"{BASE}/auth/login", data={"username": username, "password": password})
    if r.status_code != 200:
        fail(f"登录失败 {username}: HTTP {r.status_code} {r.text}")
        sys.exit(1)
    return r.json()["access_token"]

def auth_headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

def fail(msg):
    global fail_count
    fail_count += 1
    print(f"{FAIL} {msg}")

def title(name):
    """生成带唯一标识的标题"""
    return f"{TAG}-{name}"

def find_conflicts(token, venue_id, start, end, exclude_ids=None):
    """检查给定时段是否有冲突，返回冲突列表"""
    exclude_ids = exclude_ids or []
    s = start.isoformat() if isinstance(start, datetime) else start
    e = end.isoformat() if isinstance(end, datetime) else end
    s_dt = datetime.fromisoformat(s)
    e_dt = datetime.fromisoformat(e)
    r = requests.get(f"{BASE}/bookings", headers=auth_headers(token), params={"page_size": 200})
    if r.status_code != 200:
        print(f"{WARN} 查询预约列表失败: HTTP {r.status_code} {r.text}")
        return []
    data = r.json()
    bookings = data["items"] if isinstance(data, dict) and "items" in data else (data if isinstance(data, list) else [])
    conflicts = []
    for b in bookings:
        if b["id"] in exclude_ids: continue
        if b["venue_id"] != venue_id: continue
        if b["status"] == "cancelled": continue
        bs = datetime.fromisoformat(b["start_time"])
        be = datetime.fromisoformat(b["end_time"])
        if s_dt < be and bs < e_dt:
            conflicts.append(b)
    return conflicts

def safe_slot(token, venue_id, base_date, hour, minute=0, outside=False, exclude_ids=None, duration=timedelta(hours=1)):
    """找到安全时段，冲突则自动后移重试（最多10次）"""
    # 找下一个周二（1=周二）
    days = (1 - base_date.weekday()) % 7
    if days == 0: days = 7
    slot_date = base_date + timedelta(days=days)

    for attempt in range(10):
        if outside:
            # 07:00-08:00，非开放时段
            start = slot_date.replace(hour=7, minute=0, second=0, microsecond=0)
        else:
            start = slot_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
        end = start + duration
        conflicts = find_conflicts(token, venue_id, start, end, exclude_ids)
        if not conflicts:
            return start, end
        print(f"{WARN}   时段 {start} ~ {end} 与 {len(conflicts)} 条预约冲突，后移重试...")
        for c in conflicts[:3]:
            print(f"       挡住: ID={c['id']} {c['status']:10s} {c['title'][:40]}  {c['start_time']}~{c['end_time']}")
        slot_date += timedelta(hours=2)
    raise AssertionError(f"场地{venue_id}重试10次仍找不到空闲时段，最后尝试: {start} ~ {end}")

def track(b):
    """记录本次创建的预约"""
    if isinstance(b, dict) and "id" in b:
        bid = b["id"]
        if bid not in created_ids:
            created_ids.append(bid)
            print(f"{STEP}   追踪预约 ID={bid}")

def cleanup(token):
    """测试后清理：只取消本次创建的预约，不动业务数据"""
    print()
    print("=" * 60)
    print(f"{STEP} 清理本次测试数据（共 {len(created_ids)} 条）")
    print("=" * 60)
    ok = 0
    for bid in created_ids:
        try:
            r = requests.get(f"{BASE}/bookings/{bid}", headers=auth_headers(token))
            if r.status_code != 200:
                print(f"{WARN} 预约{bid}不存在，跳过")
                continue
            b = r.json()
            if b["status"] == "cancelled":
                ok += 1
                print(f"{OK} 预约{bid}已取消")
                continue
            r2 = requests.patch(f"{BASE}/bookings/{bid}/status",
                headers=auth_headers(token),
                json={"status": "cancelled", "version": b["version"]})
            if r2.status_code == 200:
                ok += 1
                print(f"{OK} 已取消预约 {bid} ({b['title'][:50]})")
            else:
                print(f"{WARN} 取消{bid}失败: HTTP {r2.status_code}")
        except Exception as e:
            print(f"{WARN} 清理{bid}异常: {e}")
    print(f"\n{OK if ok == len(created_ids) else WARN} 清理完成: {ok}/{len(created_ids)} 已取消")

def print_detail(r):
    """打印409响应的详细信息"""
    try:
        d = r.json().get("detail", {})
        if isinstance(d, dict):
            msg = d.get("message", "")
            if msg: print(f"       原因: {msg}")
            if d.get("open_slot_violations"):
                print(f"       ---- 开放时段违规 ----")
                for v in d["open_slot_violations"]:
                    print(f"       - {v.get('reason', 'N/A')}")
            if d.get("conflicts"):
                print(f"       ---- 时间冲突详情 ----")
                for c in d["conflicts"]:
                    print(f"       - ID={c.get('booking_id')} {c.get('title','')[:40]} {c.get('start_time','')}~{c.get('end_time','')} 申请人={c.get('user_name','')}")
    except:
        pass

# ============ 时间基准：当前+180天，避开历史数据 ============
TIME_BASE = datetime.now() + timedelta(days=180)

print("=" * 60)
print(f"修复后回归测试 - RUN_ID={RUN_ID}")
print(f"时间基准: {TIME_BASE.date().isoformat()}")
print(f"TAG: {TAG}")
print("=" * 60)

member_token = login("lisi", "123456")
admin_token = login("admin", "admin123")
print(f"{OK} 登录成功")

try:
    # 找两个不同场地的安全日期（第1轮和第2轮错开2周）
    base1 = TIME_BASE
    base2 = TIME_BASE + timedelta(days=14)

    # =======================================================
    # Part 1: 验证 Bug 已修复（非开放时段被正确拦截）
    # =======================================================
    print("\n" + "=" * 60)
    print(f"{STEP} Part 1: 验证 Bug 已修复（非开放时段拦截）")
    print("=" * 60)

    # Test 1: 草稿在非开放时段应返回 409
    print(f"\n{STEP} 1. 草稿在非开放时段（周二 07:00-08:00）应被 409 拒绝")
    start, end = safe_slot(admin_token, 1, base1, 7, outside=True)
    r = requests.post(f"{BASE}/bookings",
        headers=auth_headers(member_token),
        json={
            "title": title("DRAFT-OUTSIDE"),
            "production": title("回归测试剧目"),
            "venue_id": 1, "status": "draft", "priority": 10, "notes": TAG,
            "start_time": start.isoformat(), "end_time": end.isoformat()
        })
    print(f"       状态码: {r.status_code}")
    if r.status_code == 409:
        print(f"{OK} Bug 1a 已修复：草稿在非开放时段被正确拦截")
        print_detail(r)
    elif r.status_code == 200:
        track(r.json())
        fail(f"Bug 1a 未修复：草稿在非开放时段仍然写入成功！ID={r.json()['id']}")
    else:
        fail(f"Bug 1a 异常：预期 409，实际 {r.status_code}")
        print_detail(r)

    # Test 2: 待审在非开放时段应返回 409
    print(f"\n{STEP} 2. 待审在非开放时段（周二 07:00-08:00）应被 409 拒绝")
    start, end = safe_slot(admin_token, 1, base1, 7, outside=True)
    r = requests.post(f"{BASE}/bookings",
        headers=auth_headers(member_token),
        json={
            "title": title("PENDING-OUTSIDE"),
            "production": title("回归测试剧目"),
            "venue_id": 1, "status": "pending", "priority": 10, "notes": TAG,
            "start_time": start.isoformat(), "end_time": end.isoformat()
        })
    print(f"       状态码: {r.status_code}")
    if r.status_code == 409:
        print(f"{OK} Bug 1b 已修复：待审在非开放时段被正确拦截")
        print_detail(r)
    elif r.status_code == 200:
        track(r.json())
        fail(f"Bug 1b 未修复：待审在非开放时段仍然写入成功！ID={r.json()['id']}")
    else:
        fail(f"Bug 1b 异常：预期 409，实际 {r.status_code}")
        print_detail(r)

    # Test 3: 开放时段创建草稿应成功（验证正常链路可用）
    print(f"\n{STEP} 3. 开放时段创建草稿应成功")
    start, end = safe_slot(admin_token, 1, base1, 10)
    r = requests.post(f"{BASE}/bookings",
        headers=auth_headers(member_token),
        json={
            "title": title("DRAFT-OK"),
            "production": title("回归测试剧目"),
            "venue_id": 1, "status": "draft", "priority": 10, "notes": TAG,
            "start_time": start.isoformat(), "end_time": end.isoformat()
        })
    print(f"       状态码: {r.status_code}")
    if r.status_code == 200:
        draft = r.json()
        track(draft)
        print(f"{OK} 草稿创建成功，ID={draft['id']} status={draft['status']}")
    else:
        fail(f"草稿创建失败：HTTP {r.status_code}")
        print_detail(r)
        raise RuntimeError("链路中断")

    # Test 4: 草稿提交待审（验证状态流转 + 开放时段校验）
    print(f"\n{STEP} 4. 草稿提交待审（状态 draft → pending）")
    r = requests.patch(f"{BASE}/bookings/{draft['id']}/status",
        headers=auth_headers(member_token),
        json={"status": "pending", "version": draft["version"]})
    print(f"       状态码: {r.status_code}")
    if r.status_code == 200:
        pending = r.json()
        print(f"{OK} 提交待审成功，ID={pending['id']} status={pending['status']} version={pending['version']}")
    else:
        fail(f"提交待审失败：HTTP {r.status_code}")
        print_detail(r)
        raise RuntimeError("链路中断")

    # Test 5: 管理员确认待审
    print(f"\n{STEP} 5. 管理员确认待审（状态 pending → confirmed）")
    r = requests.patch(f"{BASE}/bookings/{pending['id']}/status",
        headers=auth_headers(admin_token),
        json={"status": "confirmed", "version": pending["version"]})
    print(f"       状态码: {r.status_code}")
    if r.status_code == 200:
        confirmed = r.json()
        print(f"{OK} 确认成功，ID={confirmed['id']} status={confirmed['status']} version={confirmed['version']}")
    else:
        fail(f"确认失败：HTTP {r.status_code}")
        print_detail(r)
        raise RuntimeError("链路中断")

    # Test 6: 改期到非开放时段应被 409 拒绝
    print(f"\n{STEP} 6. 已确认预约改期到非开放时段应被 409 拒绝")
    start, end = safe_slot(admin_token, 1, base2, 7, outside=True)
    r = requests.post(f"{BASE}/bookings/{confirmed['id']}/reschedule",
        headers=auth_headers(admin_token),
        json={
            "version": confirmed["version"],
            "new_start_time": start.isoformat(),
            "new_end_time": end.isoformat(),
            "reason": title("改期到非开放时段测试")
        })
    print(f"       状态码: {r.status_code}")
    if r.status_code == 409:
        print(f"{OK} Bug 1c 已修复：改期到非开放时段被正确拦截")
        print_detail(r)
    elif r.status_code == 200:
        fail(f"Bug 1c 未修复：改期到非开放时段仍然成功！ID={r.json()['id']}")
    else:
        fail(f"Bug 1c 异常：预期 409，实际 {r.status_code}")
        print_detail(r)

    # Test 7: 改期到开放时段，状态应为 rescheduling（不是 pending）
    print(f"\n{STEP} 7. 已确认预约改期到开放时段，状态应为 rescheduling")
    start, end = safe_slot(admin_token, 1, base2, 14, exclude_ids=[confirmed["id"]])
    r = requests.post(f"{BASE}/bookings/{confirmed['id']}/reschedule",
        headers=auth_headers(admin_token),
        json={
            "version": confirmed["version"],
            "new_start_time": start.isoformat(),
            "new_end_time": end.isoformat(),
            "reason": title("排练时间调整，需要改期")
        })
    print(f"       状态码: {r.status_code}")
    if r.status_code == 200:
        rescheduled = r.json()
        status = rescheduled["status"]
        print(f"       返回状态: '{status}'")
        if status == "rescheduling":
            print(f"{OK} Bug 2 已修复：改期后状态正确为 'rescheduling'")
        elif status == "pending":
            fail(f"Bug 2 未修复：状态还是 'pending'，应该是 'rescheduling'")
        else:
            fail(f"Bug 2 异常：状态 '{status}'，预期 'rescheduling'")
    else:
        fail(f"改期失败：HTTP {r.status_code}")
        print_detail(r)
        raise RuntimeError("链路中断")

    # Test 8: 改期重提（rescheduling → pending → confirmed）
    print(f"\n{STEP} 8. 改期重提链路：rescheduling → pending → confirmed")

    # 8a: rescheduling → pending
    r = requests.patch(f"{BASE}/bookings/{rescheduled['id']}/status",
        headers=auth_headers(member_token),
        json={"status": "pending", "version": rescheduled["version"]})
    print(f"       8a 状态码: {r.status_code}")
    if r.status_code == 200:
        re_pending = r.json()
        if re_pending["status"] == "pending":
            print(f"{OK} 8a 改期后重提待审成功，status={re_pending['status']}")
        else:
            fail(f"8a 状态应为 pending，实际 {re_pending['status']}")
    else:
        fail(f"8a 重提待审失败：HTTP {r.status_code}")
        print_detail(r)
        raise RuntimeError("链路中断")

    # 8b: pending → confirmed
    r = requests.patch(f"{BASE}/bookings/{re_pending['id']}/status",
        headers=auth_headers(admin_token),
        json={"status": "confirmed", "version": re_pending["version"]})
    print(f"       8b 状态码: {r.status_code}")
    if r.status_code == 200:
        re_confirmed = r.json()
        if re_confirmed["status"] == "confirmed":
            print(f"{OK} 8b 改期后重提审批成功，status={re_confirmed['status']}")
        else:
            fail(f"8b 状态应为 confirmed，实际 {re_confirmed['status']}")
    else:
        fail(f"8b 重提审批失败：HTTP {r.status_code}")
        print_detail(r)
        raise RuntimeError("链路中断")

    # Test 9: 改期历史字段检查
    print(f"\n{STEP} 9. 改期历史字段：原时段/新时段/原因/操作人")
    r = requests.get(f"{BASE}/bookings/{confirmed['id']}/reschedule-history",
                     headers=auth_headers(admin_token))
    if r.status_code == 200:
        history = r.json()
        if len(history) >= 1:
            h = history[0]
            required = ["original_start_time", "original_end_time", "new_start_time", "new_end_time", "reason", "operator_name"]
            missing = [k for k in required if k not in h]
            if not missing and h["operator_name"] == "系统管理员":
                print(f"{OK} 改期历史字段完整，共 {len(history)} 条记录")
            else:
                fail(f"改期历史字段缺失: {missing}")
        else:
            fail(f"改期历史记录数应为 >=1，实际 {len(history)}")
    else:
        fail(f"查改期历史失败：HTTP {r.status_code}")

    # Test 10: CSV 导出检查
    print(f"\n{STEP} 10. CSV 导出：表头含改期列，数据含本次测试记录")
    r = requests.get(f"{BASE}/exports/bookings.csv", headers=auth_headers(admin_token))
    if r.status_code == 200:
        csv_text = r.content.decode("utf-8-sig")
        lines = csv_text.splitlines()
        header = lines[0] if lines else ""
        print(f"       表头: {header[:100]}...")
        required_cols = ["原时段", "新时段", "改期原因", "改期操作人"]
        missing = [c for c in required_cols if c not in header]
        if not missing:
            print(f"{OK} Bug 3 表头已修复：包含全部改期历史列")
        else:
            fail(f"Bug 3 表头未修复：缺失 {missing}")
        has_this_run = any(TAG in line for line in lines)
        if has_this_run:
            print(f"{OK} CSV 包含本次测试数据")
        else:
            fail(f"CSV 未包含本次测试数据（TAG={TAG}）")
        has_resched = any("改期" in line for line in lines[1:])
        if has_resched:
            print(f"{OK} CSV 包含改期历史数据")
        else:
            fail(f"CSV 未包含改期历史数据")
    else:
        fail(f"CSV 导出失败：HTTP {r.status_code}")

    # =======================================================
    # Part 2: 第二轮完整链路（验证可重复性）
    # =======================================================
    print("\n" + "=" * 60)
    print(f"{STEP} Part 2: 第二轮完整链路（验证可重复性）")
    print("=" * 60)

    print(f"\n{STEP} 2-1. 第二轮：开放时段创建草稿")
    start, end = safe_slot(admin_token, 2, base2, 10)
    r = requests.post(f"{BASE}/bookings",
        headers=auth_headers(member_token),
        json={
            "title": title("ROUND2-DRAFT"),
            "production": title("回归测试剧目-第二轮"),
            "venue_id": 2, "status": "draft", "priority": 10, "notes": TAG,
            "start_time": start.isoformat(), "end_time": end.isoformat()
        })
    if r.status_code == 200:
        draft2 = r.json()
        track(draft2)
        print(f"{OK} 第二轮草稿创建成功，ID={draft2['id']}")
    else:
        fail(f"第二轮草稿创建失败：HTTP {r.status_code}")
        print_detail(r)
        raise RuntimeError("第二轮链路中断")

    print(f"\n{STEP} 2-2. 第二轮：草稿→待审→确认→改期→重提")
    r = requests.patch(f"{BASE}/bookings/{draft2['id']}/status",
        headers=auth_headers(member_token),
        json={"status": "pending", "version": draft2["version"]})
    if r.status_code != 200:
        fail(f"第二轮提交待审失败：{r.status_code}")
        raise RuntimeError("第二轮链路中断")
    pending2 = r.json()
    print(f"{OK} 第二轮待审提交成功")

    r = requests.patch(f"{BASE}/bookings/{pending2['id']}/status",
        headers=auth_headers(admin_token),
        json={"status": "confirmed", "version": pending2["version"]})
    if r.status_code != 200:
        fail(f"第二轮确认失败：{r.status_code}")
        raise RuntimeError("第二轮链路中断")
    confirmed2 = r.json()
    print(f"{OK} 第二轮确认成功")

    start, end = safe_slot(admin_token, 2, base2 + timedelta(days=7), 15, exclude_ids=[confirmed2["id"]])
    r = requests.post(f"{BASE}/bookings/{confirmed2['id']}/reschedule",
        headers=auth_headers(admin_token),
        json={
            "version": confirmed2["version"],
            "new_start_time": start.isoformat(),
            "new_end_time": end.isoformat(),
            "reason": title("第二轮改期")
        })
    if r.status_code != 200:
        fail(f"第二轮改期失败：{r.status_code}")
        print_detail(r)
        raise RuntimeError("第二轮链路中断")
    rescheduled2 = r.json()
    if rescheduled2["status"] == "rescheduling":
        print(f"{OK} 第二轮改期成功，status={rescheduled2['status']}")
    else:
        fail(f"第二轮改期状态错误：{rescheduled2['status']}")

    r = requests.patch(f"{BASE}/bookings/{rescheduled2['id']}/status",
        headers=auth_headers(member_token),
        json={"status": "pending", "version": rescheduled2["version"]})
    if r.status_code != 200:
        fail(f"第二轮重提待审失败：{r.status_code}")
        raise RuntimeError("第二轮链路中断")
    re_pending2 = r.json()

    r = requests.patch(f"{BASE}/bookings/{re_pending2['id']}/status",
        headers=auth_headers(admin_token),
        json={"status": "confirmed", "version": re_pending2["version"]})
    if r.status_code != 200:
        fail(f"第二轮重提确认失败：{r.status_code}")
        raise RuntimeError("第二轮链路中断")
    re_confirmed2 = r.json()
    print(f"{OK} 第二轮重提确认成功，status={re_confirmed2['status']}")

    # 两轮结果一致性对比
    print("\n" + "=" * 60)
    print(f"{STEP} 两轮一致性对比")
    print("=" * 60)
    if re_confirmed["status"] == re_confirmed2["status"] == "confirmed":
        print(f"{OK} 两轮最终状态一致：都是 confirmed")
    else:
        fail(f"两轮最终状态不一致：第一轮={re_confirmed['status']} 第二轮={re_confirmed2['status']}")

    r_csv2 = requests.get(f"{BASE}/exports/bookings.csv", headers=auth_headers(admin_token))
    if r_csv2.status_code == 200:
        header2 = r_csv2.content.decode("utf-8-sig").splitlines()[0]
        if header == header2:
            print(f"{OK} 两轮 CSV 表头完全一致")
        else:
            fail(f"两轮 CSV 表头不一致")

    # 清理
    cleanup(admin_token)

except Exception as e:
    print(f"\n{FAIL} 测试异常中断: {e}")
    import traceback
    traceback.print_exc()
    fail_count += 1
    try:
        cleanup(admin_token)
    except:
        pass

# 最终汇总
print("\n" + "=" * 60)
print(f"最终结果 - RUN_ID={RUN_ID}")
print("=" * 60)
print(f"失败项: {fail_count}")
print(f"创建并清理: {len(created_ids)} 条预约")
print(f"日志文件: {LOG_FILE}")
print()
if fail_count == 0:
    print(f"{OK} 全部测试通过！退出码=0")
    sys.stdout = _orig_stdout
    sys.stderr = _orig_stderr
    log_file.close()
    sys.exit(0)
else:
    print(f"{FAIL} 有 {fail_count} 项失败，请查看日志 {LOG_FILE}")
    sys.stdout = _orig_stdout
    sys.stderr = _orig_stderr
    log_file.close()
    sys.exit(1)
