import urllib.request
import urllib.parse
import json
import sys
from datetime import datetime, timedelta, time

# ============ 加固部分（最小改动） ============
RUN_ID = datetime.now().strftime("%Y%m%d%H%M%S")
TAG = f"REG-BEFORE-{RUN_ID}"
LOG_FILE = f"reg_before_{RUN_ID}.txt"

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

BASE_URL = "http://localhost:8000/api"
FAIL = "[FAIL]"
OK = "[OK]"
WARN = "[WARN]"
STEP = "[STEP]"

created_ids = []
fail_count = 0

def build_url(endpoint, params=None):
    url = f"{BASE_URL}{endpoint}"
    if params:
        query = urllib.parse.urlencode(params, encoding="utf-8")
        url = f"{url}?{query}"
    return url

def req(endpoint, method="GET", data=None, token=None, params=None):
    url = build_url(endpoint, params)
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = None
    if data:
        body = json.dumps(data).encode()
    request = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        response = urllib.request.urlopen(request)
        resp_body = response.read().decode()
        result = json.loads(resp_body) if resp_body else None
        return response.status, result
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode()
            err_data = json.loads(err_body) if err_body else {}
        except:
            err_data = {"detail": str(e)}
        return e.code, err_data

def login(username, password):
    data = urllib.parse.urlencode({"username": username, "password": password}).encode()
    request = urllib.request.Request(
        f"{BASE_URL}/auth/login",
        data=data,
        method="POST"
    )
    request.add_header("Content-Type", "application/x-www-form-urlencoded")
    response = urllib.request.urlopen(request)
    result = json.loads(response.read().decode())
    return result["access_token"], result["user"]

def fail(msg):
    global fail_count
    fail_count += 1
    print(f"{FAIL} {msg}")

def title(name):
    return f"{TAG}-{name}"

def find_conflicts(token, venue_id, start, end, exclude_ids=None):
    exclude_ids = exclude_ids or []
    s = start.isoformat() if isinstance(start, datetime) else start
    e = end.isoformat() if isinstance(end, datetime) else end
    s_dt = datetime.fromisoformat(s)
    e_dt = datetime.fromisoformat(e)
    status, data = req("/bookings", token=token, params={"page_size": 200})
    if status != 200:
        print(f"{WARN} 查询预约列表失败: HTTP {status} {data}")
        return []
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
    days = (1 - base_date.weekday()) % 7
    if days == 0: days = 7
    slot_date = base_date + timedelta(days=days)
    for attempt in range(10):
        if outside:
            start = slot_date.replace(hour=7, minute=0, second=0, microsecond=0)
        else:
            start = slot_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
        end = start + duration
        conflicts = find_conflicts(token, venue_id, start, end, exclude_ids)
        if not conflicts:
            return start, end
        print(f"{WARN}   时段 {start} ~ {end} 与 {len(conflicts)} 条冲突，后移重试...")
        for c in conflicts[:3]:
            print(f"       挡住: ID={c['id']} {c['status']:10s} {c['title'][:40]}  {c['start_time']}~{c['end_time']}")
        slot_date += timedelta(hours=2)
    raise AssertionError(f"场地{venue_id}重试10次仍无空闲时段，最后: {start} ~ {end}")

def track(b):
    if isinstance(b, dict) and "id" in b:
        bid = b["id"]
        if bid not in created_ids:
            created_ids.append(bid)
            print(f"{STEP}   追踪预约 ID={bid}")

def cleanup(token):
    print()
    print("=" * 70)
    print(f"{STEP} 清理本次测试数据（共 {len(created_ids)} 条）")
    print("=" * 70)
    ok = 0
    for bid in created_ids:
        try:
            status, b = req(f"/bookings/{bid}", token=token)
            if status != 200:
                print(f"{WARN} 预约{bid}不存在，跳过")
                continue
            if b["status"] == "cancelled":
                ok += 1
                print(f"{OK} 预约{bid}已取消")
                continue
            status, _ = req(f"/bookings/{bid}/status", "PATCH",
                {"status": "cancelled", "version": b["version"]}, token)
            if status == 200:
                ok += 1
                print(f"{OK} 已取消预约 {bid} ({b['title'][:50]})")
            else:
                print(f"{WARN} 取消{bid}失败: HTTP {status}")
        except Exception as e:
            print(f"{WARN} 清理{bid}异常: {e}")
    print(f"\n{OK if ok == len(created_ids) else WARN} 清理完成: {ok}/{len(created_ids)} 已取消")

def print_detail(data):
    if isinstance(data, dict) and data.get("detail"):
        d = data["detail"]
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

TIME_BASE = datetime.now() + timedelta(days=180)

# ============ 测试内容 ============
print("=" * 70)
print(f"Bug 修复验证 - RUN_ID={RUN_ID}")
print(f"时间基准: {TIME_BASE.date().isoformat()}")
print(f"TAG: {TAG}")
print("=" * 70)
print("\n📋 说明：代码已修复，本脚本验证旧 bug 已被修复（非开放时段应被 409 拒绝）")
print("   旧代码（修复前）会返回 200 写入数据库，现在应返回 409 拦截")

# ============ 准备工作 ============
print(f"\n{STEP} 准备：登录并获取测试数据")
admin_token, admin_user = login("admin", "admin123")
member_token, member_user = login("lisi", "123456")

status, venues = req("/venues", token=member_token)
venue1 = venues[0]
venue2 = venues[1] if len(venues) > 1 else venues[0]
print(f"   测试场地1: {venue1['name']} (ID: {venue1['id']})")
print(f"   测试场地2: {venue2['name']} (ID: {venue2['id']})")

# 先查看场地已配置的开放时段
status, open_slots = req("/config/open-slots", token=admin_token, params={"venue_id": venue1["id"]})
print(f"   场地1现有开放时段: {len(open_slots)} 条")
for s in open_slots[:3]:
    print(f"     周{s['day_of_week'] + 1} {s['start_time']}-{s['end_time']}")

base1 = TIME_BASE
base2 = TIME_BASE + timedelta(days=14)

# ============ Bug 1 修复验证 ============
print("\n" + "=" * 70)
print("✅ Bug 1 验证：开放时段校验已生效（非开放时段应被 409 拒绝）")
print("=" * 70)

# 找到一个不在开放时段的时间点：周二 07:00-08:00
print(f"\n   测试时段: 周二 07:00-08:00 (不在开放时段 9-12/14-18/19-22 内)")

# Test 1: 草稿在非开放时段
print(f"\n{STEP} 1. 草稿在非开放时段（修复前=200写入，修复后=409拒绝）")
start, end = safe_slot(admin_token, venue1["id"], base1, 7, outside=True)
draft_data = {
    "title": title("DRAFT-OUTSIDE"),
    "production": title("Bug测试"),
    "venue_id": venue1["id"],
    "start_time": start.isoformat(),
    "end_time": end.isoformat(),
    "priority": 10,
    "notes": TAG,
    "status": "draft"
}
status, result = req("/bookings", "POST", draft_data, member_token)
print(f"       状态码: {status}")
if status == 409:
    print(f"{OK} Bug 1a 已修复：草稿在非开放时段被正确拦截")
    print_detail(result)
elif status == 200:
    track(result)
    fail(f"Bug 1a 未修复：草稿在非开放时段仍然写入成功！ID={result['id']}")
else:
    fail(f"Bug 1a 异常：预期 409，实际 {status}")
    print_detail(result)

# Test 2: 待审在非开放时段
print(f"\n{STEP} 2. 待审在非开放时段（修复前=200写入，修复后=409拒绝）")
start, end = safe_slot(admin_token, venue1["id"], base1, 7, outside=True)
pending_data = {
    "title": title("PENDING-OUTSIDE"),
    "production": title("Bug测试"),
    "venue_id": venue1["id"],
    "start_time": start.isoformat(),
    "end_time": end.isoformat(),
    "priority": 10,
    "notes": TAG,
    "status": "pending"
}
status, result = req("/bookings", "POST", pending_data, member_token)
print(f"       状态码: {status}")
if status == 409:
    print(f"{OK} Bug 1b 已修复：待审在非开放时段被正确拦截")
    print_detail(result)
elif status == 200:
    track(result)
    fail(f"Bug 1b 未修复：待审在非开放时段仍然写入成功！ID={result['id']}")
else:
    fail(f"Bug 1b 异常：预期 409，实际 {status}")
    print_detail(result)

# Test 3: 改期到非开放时段
print(f"\n{STEP} 3. 改期到非开放时段（修复前=200成功，修复后=409拒绝）")
# 先创建一个正常的 confirmed 预约
start, end = safe_slot(admin_token, venue2["id"], base1, 10)
confirmed_data = {
    "title": title("改期测试-基础预约"),
    "production": title("改期测试"),
    "venue_id": venue2["id"],
    "start_time": start.isoformat(),
    "end_time": end.isoformat(),
    "priority": 50,
    "notes": TAG,
    "status": "draft"
}
status, base_booking = req("/bookings", "POST", confirmed_data, member_token)
track(base_booking)
base_booking_id = base_booking["id"]

# 提交审批
status, _ = req(f"/bookings/{base_booking_id}/status", "PATCH",
    {"status": "pending", "version": base_booking["version"]}, member_token)
# 管理员审批
status, base_booking = req(f"/bookings/{base_booking_id}", token=admin_token)
status, _ = req(f"/bookings/{base_booking_id}/status", "PATCH",
    {"status": "confirmed", "version": base_booking["version"]}, admin_token)
print(f"   基础预约已确认，准备改期到非开放时段...")

# 改期到非开放时段
start, end = safe_slot(admin_token, venue2["id"], base2, 7, outside=True)
status, base_booking = req(f"/bookings/{base_booking_id}", token=member_token)
reschedule_data = {
    "new_start_time": start.isoformat(),
    "new_end_time": end.isoformat(),
    "reason": title("改期到非开放时段测试"),
    "version": base_booking["version"]
}
status, result = req(f"/bookings/{base_booking_id}/reschedule", "POST", reschedule_data, member_token)
print(f"       状态码: {status}")
if status == 409:
    print(f"{OK} Bug 1c 已修复：改期到非开放时段被正确拦截")
    print_detail(result)
elif status == 200:
    fail(f"Bug 1c 未修复：改期到非开放时段仍然成功！ID={result['id']}")
else:
    fail(f"Bug 1c 异常：预期 409，实际 {status}")
    print_detail(result)

# ============ Bug 2 修复验证 ============
print("\n" + "=" * 70)
print("✅ Bug 2 验证：改期后状态应该是'rescheduling'而不是'pending'")
print("=" * 70)

# 创建一个已确认的预约
start, end = safe_slot(admin_token, venue2["id"], base1, 14)
reschedule_test_data = {
    "title": title("Bug2测试-改期状态"),
    "production": title("Bug测试"),
    "venue_id": venue2["id"],
    "start_time": start.isoformat(),
    "end_time": end.isoformat(),
    "priority": 50,
    "notes": TAG,
    "status": "draft"
}
status, bug2_booking = req("/bookings", "POST", reschedule_test_data, member_token)
track(bug2_booking)
bug2_id = bug2_booking["id"]
bug2_ver = bug2_booking["version"]

# 提交并审批
status, _ = req(f"/bookings/{bug2_id}/status", "PATCH",
    {"status": "pending", "version": bug2_ver}, member_token)
status, bug2_booking = req(f"/bookings/{bug2_id}", token=admin_token)
status, _ = req(f"/bookings/{bug2_id}/status", "PATCH",
    {"status": "confirmed", "version": bug2_booking["version"]}, admin_token)
print(f"   预约已确认，准备发起改期...")

# 发起改期到合法时段
start, end = safe_slot(admin_token, venue2["id"], base2, 15, exclude_ids=[bug2_id])
status, bug2_booking = req(f"/bookings/{bug2_id}", token=member_token)
bug2_reschedule = {
    "new_start_time": start.isoformat(),
    "new_end_time": end.isoformat(),
    "reason": title("Bug2测试：检查改期后状态"),
    "version": bug2_booking["version"]
}
status, result = req(f"/bookings/{bug2_id}/reschedule", "POST", bug2_reschedule, member_token)
print(f"       状态码: {status}")
if status == 200:
    actual_status = result.get("status", "")
    print(f"       返回状态: '{actual_status}'")
    if actual_status == "rescheduling":
        print(f"{OK} Bug 2 已修复：改期后状态正确为 'rescheduling'")
    elif actual_status == "pending":
        fail(f"Bug 2 未修复：状态还是 'pending'，应该是 'rescheduling'")
    else:
        fail(f"Bug 2 异常：状态 '{actual_status}'，预期 'rescheduling'")
else:
    fail(f"改期失败：HTTP {status}")
    print_detail(result)

# ============ Bug 3 修复验证 ============
print("\n" + "=" * 70)
print("✅ Bug 3 验证：CSV导出应包含改期历史列")
print("=" * 70)

# 导出CSV检查是否有改期相关列
csv_url = build_url("/exports/bookings.csv")
request = urllib.request.Request(
    csv_url,
    headers={"Authorization": f"Bearer {admin_token}"}
)
response = urllib.request.urlopen(request)
csv_content = response.read().decode("utf-8-sig")
lines = csv_content.strip().split("\n")
header = lines[0]
print(f"   CSV表头: {header[:100]}...")

required_cols = ["原时段", "新时段", "改期原因", "改期操作人"]
missing = [c for c in required_cols if c not in header]
if not missing:
    print(f"{OK} Bug 3 已修复：CSV 表头包含全部改期历史列（{required_cols}）")
else:
    fail(f"Bug 3 未修复：CSV 表头缺失 {missing}")

# 验证有改期数据
has_resched = any("改期" in line for line in lines[1:])
if has_resched:
    print(f"{OK} CSV 包含改期历史数据")
else:
    fail(f"CSV 未包含改期历史数据")

# 清理
cleanup(admin_token)

# ============ 最终汇总 ============
print("\n" + "=" * 70)
print(f"最终结果 - RUN_ID={RUN_ID}")
print("=" * 70)
print(f"失败项: {fail_count}")
print(f"创建并清理: {len(created_ids)} 条预约")
print(f"日志文件: {LOG_FILE}")
print()
if fail_count == 0:
    print(f"{OK} 全部 Bug 已修复！退出码=0")
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
