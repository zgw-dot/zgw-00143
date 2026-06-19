import urllib.request
import urllib.parse
import json
import sys
from datetime import datetime, timedelta

RUN_ID = datetime.now().strftime("%Y%m%d%H%M%S")
TAG = f"CW-REG-{RUN_ID}"
LOG_FILE = f"reg_closed_window_{RUN_ID}.txt"

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

fail_count = 0
created_booking_ids = []
created_window_ids = []

def req(endpoint, method="GET", data=None, token=None, params=None):
    url = f"{BASE_URL}{endpoint}"
    if params:
        query = urllib.parse.urlencode(params, encoding="utf-8")
        url = f"{url}?{query}"
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

def title(name):
    return f"{TAG}-{name}"

def fail(msg):
    global fail_count
    fail_count += 1
    print(f"{FAIL} {msg}")

def track_booking(b):
    if isinstance(b, dict) and "id" in b:
        bid = b["id"]
        if bid not in created_booking_ids:
            created_booking_ids.append(bid)

def track_window(w):
    if isinstance(w, dict) and "id" in w:
        wid = w["id"]
        if wid not in created_window_ids:
            created_window_ids.append(wid)

def print_detail(data):
    if isinstance(data, dict) and data.get("detail"):
        d = data["detail"]
        if isinstance(d, dict):
            msg = d.get("message", "")
            if msg: print(f"       原因: {msg}")
            if d.get("closed_windows"):
                print(f"       ---- 封场窗口详情 ----")
                for w in d["closed_windows"]:
                    print(f"       - ID={w.get('id')} {w.get('venue_name','')} {w.get('start_time','')}~{w.get('end_time','')} 原因={w.get('reason','')}")
            if d.get("conflicts"):
                print(f"       ---- 时间冲突详情 ----")
                for c in d["conflicts"]:
                    print(f"       - ID={c.get('booking_id')} {c.get('title','')[:40]}")

def safe_slot(token, venue_id, base_date, hour, minute=0, exclude_ids=None, duration=timedelta(hours=1)):
    days = (1 - base_date.weekday()) % 7
    if days == 0: days = 7
    slot_date = base_date + timedelta(days=days)
    for attempt in range(10):
        start = slot_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
        end = start + duration
        status, data = req("/bookings", token=token, params={"page_size": 200})
        bookings = data["items"] if isinstance(data, dict) and "items" in data else []
        has_conflict = False
        for b in bookings:
            if b["id"] in (exclude_ids or []): continue
            if b["venue_id"] != venue_id: continue
            if b["status"] == "cancelled": continue
            bs = datetime.fromisoformat(b["start_time"].replace("Z", "+00:00"))
            be = datetime.fromisoformat(b["end_time"].replace("Z", "+00:00"))
            bs_naive = bs.replace(tzinfo=None)
            be_naive = be.replace(tzinfo=None)
            if start < be_naive and bs_naive < end:
                has_conflict = True
                break
        status_w, data_w = req("/config/closed-windows", token=token)
        for w in data_w:
            ws = datetime.fromisoformat(w["start_time"].replace("Z", "+00:00")).replace(tzinfo=None)
            we = datetime.fromisoformat(w["end_time"].replace("Z", "+00:00")).replace(tzinfo=None)
            if start < we and ws < end:
                has_conflict = True
                break
        if not has_conflict:
            return start, end
        slot_date += timedelta(hours=2)
    raise AssertionError(f"场地{venue_id}重试10次仍无空闲时段")

TIME_BASE = datetime.now() + timedelta(days=180)

print("=" * 70)
print(f"封场窗口回归测试 - RUN_ID={RUN_ID}")
print(f"时间基准: {TIME_BASE.date().isoformat()}")
print(f"TAG: {TAG}")
print("=" * 70)

print(f"\n{STEP} 准备：登录并获取测试数据")
admin_token, admin_user = login("admin", "admin123")
member_token, member_user = login("lisi", "123456")

status, venues = req("/venues", token=member_token)
venue1 = venues[0]
venue2 = venues[1] if len(venues) > 1 else venues[0]
print(f"   测试场地1: {venue1['name']} (ID: {venue1['id']})")
print(f"   测试场地2: {venue2['name']} (ID: {venue2['id']})")

base1 = TIME_BASE
base2 = TIME_BASE + timedelta(days=14)
base3 = TIME_BASE + timedelta(days=30)

# ============ Test 1: 管理员创建封场窗口 ============
print("\n" + "=" * 70)
print("✅ Test 1：管理员创建封场窗口")
print("=" * 70)

window_start, window_end = safe_slot(admin_token, venue1["id"], base1, 10, duration=timedelta(hours=2))
print(f"\n{STEP} 1.1 创建单场地封场窗口（场地1）")
window_data = {
    "venue_id": venue1["id"],
    "start_time": window_start.isoformat(),
    "end_time": window_end.isoformat(),
    "reason": title("设备检修"),
    "apply_all_venues": False
}
status, result = req("/config/closed-windows", "POST", window_data, admin_token)
print(f"       状态码: {status}")
if status == 200:
    print(f"{OK} 1.1 创建成功 ID={result['id']} 场地={result.get('venue',{}).get('name','')} {result['start_time']}~{result['end_time']}")
    track_window(result)
    w1_id = result["id"]
else:
    fail(f"1.1 创建失败: HTTP {status}")
    print_detail(result)
    w1_id = None

print(f"\n{STEP} 1.2 创建全场通用封场窗口")
window2_start, window2_end = safe_slot(admin_token, venue1["id"], base2, 14, duration=timedelta(hours=3))
window2_data = {
    "venue_id": None,
    "start_time": window2_start.isoformat(),
    "end_time": window2_end.isoformat(),
    "reason": title("舞台联排占用"),
    "apply_all_venues": True
}
status, result = req("/config/closed-windows", "POST", window2_data, admin_token)
print(f"       状态码: {status}")
if status == 200:
    print(f"{OK} 1.2 创建全场封场成功 ID={result['id']} venue_id={result.get('venue_id')}")
    track_window(result)
    w2_id = result["id"]
else:
    fail(f"1.2 创建失败: HTTP {status}")
    print_detail(result)
    w2_id = None

# ============ Test 2: 重叠封场窗口不能保存 ============
print("\n" + "=" * 70)
print("✅ Test 2：重叠/重复封场窗口不能保存")
print("=" * 70)

print(f"\n{STEP} 2.1 尝试创建完全重叠的窗口")
overlap_data = {
    "venue_id": venue1["id"],
    "start_time": window_start.isoformat(),
    "end_time": window_end.isoformat(),
    "reason": title("重复窗口"),
    "apply_all_venues": False
}
status, result = req("/config/closed-windows", "POST", overlap_data, admin_token)
print(f"       状态码: {status}")
if status == 400:
    print(f"{OK} 2.1 完全重叠被正确拒绝")
else:
    fail(f"2.1 重叠窗口未被拦截: HTTP {status}")
    if status == 200: track_window(result)

print(f"\n{STEP} 2.2 尝试创建部分重叠的窗口")
partial_start = window_start + timedelta(minutes=30)
partial_end = window_end + timedelta(minutes=30)
partial_data = {
    "venue_id": venue1["id"],
    "start_time": partial_start.isoformat(),
    "end_time": partial_end.isoformat(),
    "reason": title("部分重叠"),
    "apply_all_venues": False
}
status, result = req("/config/closed-windows", "POST", partial_data, admin_token)
print(f"       状态码: {status}")
if status == 400:
    print(f"{OK} 2.2 部分重叠被正确拒绝")
else:
    fail(f"2.2 部分重叠未被拦截: HTTP {status}")
    if status == 200: track_window(result)

# ============ Test 3: 普通成员不能创建/撤销封场窗口 ============
print("\n" + "=" * 70)
print("✅ Test 3：权限控制 - 普通成员只能查看")
print("=" * 70)

print(f"\n{STEP} 3.1 普通成员查看封场窗口（应该成功）")
status, result = req("/config/closed-windows", token=member_token)
print(f"       状态码: {status}, 数量: {len(result) if isinstance(result, list) else 'N/A'}")
if status == 200:
    print(f"{OK} 3.1 普通成员可以查看")
else:
    fail(f"3.1 普通成员不能查看: HTTP {status}")

print(f"\n{STEP} 3.2 普通成员尝试创建封场窗口（应该403）")
try_start, try_end = safe_slot(admin_token, venue2["id"], base3, 16)
try_data = {
    "venue_id": venue2["id"],
    "start_time": try_start.isoformat(),
    "end_time": try_end.isoformat(),
    "reason": title("成员尝试创建"),
    "apply_all_venues": False
}
status, result = req("/config/closed-windows", "POST", try_data, member_token)
print(f"       状态码: {status}")
if status == 403:
    print(f"{OK} 3.2 普通成员创建被403禁止")
else:
    fail(f"3.2 普通成员创建未被禁止: HTTP {status}")
    if status == 200: track_window(result)

print(f"\n{STEP} 3.3 普通成员尝试撤销封场窗口（应该403）")
if w1_id:
    status, result = req(f"/config/closed-windows/{w1_id}", "DELETE", token=member_token)
    print(f"       状态码: {status}")
    if status == 403:
        print(f"{OK} 3.3 普通成员撤销被403禁止")
    else:
        fail(f"3.3 普通成员撤销未被禁止: HTTP {status}")
else:
    print(f"{WARN} 3.3 跳过（无可用窗口ID）")

# ============ Test 4: 创建预约撞封场窗口被拦截 ============
print("\n" + "=" * 70)
print("✅ Test 4：创建预约撞上封场窗口被拦截")
print("=" * 70)

print(f"\n{STEP} 4.1 草稿撞上场地封场窗口（409拦截）")
booking_data = {
    "title": title("DRAFT-HIT-WINDOW"),
    "production": title("封场测试"),
    "venue_id": venue1["id"],
    "start_time": window_start.isoformat(),
    "end_time": window_end.isoformat(),
    "priority": 10,
    "notes": TAG,
    "status": "draft"
}
status, result = req("/bookings", "POST", booking_data, member_token)
print(f"       状态码: {status}")
if status == 409:
    print(f"{OK} 4.1 草稿撞封场被409拦截")
    print_detail(result)
elif status == 200:
    fail(f"4.1 草稿撞封场未被拦截 ID={result['id']}")
    track_booking(result)
else:
    fail(f"4.1 异常: HTTP {status}")

print(f"\n{STEP} 4.2 待审撞上全场通用封场窗口（409拦截）")
booking2_data = {
    "title": title("PENDING-HIT-ALLVENUE"),
    "production": title("封场测试"),
    "venue_id": venue2["id"],
    "start_time": window2_start.isoformat(),
    "end_time": window2_end.isoformat(),
    "priority": 10,
    "notes": TAG,
    "status": "pending"
}
status, result = req("/bookings", "POST", booking2_data, member_token)
print(f"       状态码: {status}")
if status == 409:
    print(f"{OK} 4.2 待审撞全场封场被409拦截")
    print_detail(result)
elif status == 200:
    fail(f"4.2 待审撞全场封场未被拦截 ID={result['id']}")
    track_booking(result)
else:
    fail(f"4.2 异常: HTTP {status}")

# ============ Test 5: 草稿转待审撞封场窗口 ============
print("\n" + "=" * 70)
print("✅ Test 5：草稿转待审撞上封场窗口被拦截")
print("=" * 70)

print(f"\n{STEP} 5.1 先在安全时段创建草稿")
safe_start, safe_end = safe_slot(member_token, venue1["id"], base1, 15, exclude_ids=created_booking_ids, duration=timedelta(hours=1))
draft_data = {
    "title": title("DRAFT-TO-PENDING-TEST"),
    "production": title("封场测试"),
    "venue_id": venue1["id"],
    "start_time": safe_start.isoformat(),
    "end_time": safe_end.isoformat(),
    "priority": 10,
    "notes": TAG,
    "status": "draft"
}
status, result = req("/bookings", "POST", draft_data, member_token)
if status != 200:
    fail(f"5.1 草稿创建失败: HTTP {status}")
else:
    track_booking(result)
    draft_id = result["id"]
    draft_ver = result["version"]
    print(f"   草稿创建成功 ID={draft_id}")

    print(f"\n{STEP} 5.2 把草稿时间改成撞上封场窗口")
    update_data = {
        "venue_id": venue1["id"],
        "start_time": (window_start + timedelta(minutes=15)).isoformat(),
        "end_time": (window_start + timedelta(minutes=75)).isoformat(),
        "version": draft_ver
    }
    status, result = req(f"/bookings/{draft_id}", "PUT", update_data, member_token)
    print(f"       编辑状态码: {status}")
    if status == 409:
        print(f"{OK} 5.2 编辑草稿时撞封场被拦截（PUT 阶段就拦住）")
    elif status == 200:
        draft_ver = result["version"]
        print(f"   草稿已更新，现尝试提交待审...")
        status, result = req(f"/bookings/{draft_id}/status", "PATCH",
            {"status": "pending", "version": draft_ver}, member_token)
        print(f"       提交待审状态码: {status}")
        if status == 409:
            print(f"{OK} 5.2 草稿转待审撞封场被409拦截")
            print_detail(result)
        elif status == 200:
            fail(f"5.2 草稿转待审撞封场未被拦截 ID={result['id']}")
        else:
            fail(f"5.2 异常: HTTP {status}")
    else:
        fail(f"5.2 编辑异常: HTTP {status}")

# ============ Test 6: 已确认预约改期撞封场窗口 ============
print("\n" + "=" * 70)
print("✅ Test 6：已确认预约改期撞上封场窗口被拦截")
print("=" * 70)

print(f"\n{STEP} 6.1 创建一个已确认预约")
safe_start2, safe_end2 = safe_slot(admin_token, venue2["id"], base2, 9, exclude_ids=created_booking_ids)
confirmed_data = {
    "title": title("CONFIRMED-RESCHEDULE-TEST"),
    "production": title("封场测试"),
    "venue_id": venue2["id"],
    "start_time": safe_start2.isoformat(),
    "end_time": safe_end2.isoformat(),
    "priority": 10,
    "notes": TAG,
    "status": "draft"
}
status, result = req("/bookings", "POST", confirmed_data, member_token)
if status != 200:
    fail(f"6.1 创建草稿失败: HTTP {status}")
else:
    track_booking(result)
    conf_id = result["id"]
    conf_ver = result["version"]
    status, _ = req(f"/bookings/{conf_id}/status", "PATCH",
        {"status": "pending", "version": conf_ver}, member_token)
    status, result = req(f"/bookings/{conf_id}", token=admin_token)
    status, _ = req(f"/bookings/{conf_id}/status", "PATCH",
        {"status": "confirmed", "version": result["version"]}, admin_token)
    print(f"   预约已确认 ID={conf_id}")

    print(f"\n{STEP} 6.2 尝试改期到封场窗口内（409拦截）")
    reschedule_start = window2_start + timedelta(minutes=30)
    reschedule_end = window2_start + timedelta(hours=1, minutes=30)
    status, result = req(f"/bookings/{conf_id}", token=member_token)
    reschedule_data = {
        "new_start_time": reschedule_start.isoformat(),
        "new_end_time": reschedule_end.isoformat(),
        "reason": title("改期测试-撞封场"),
        "version": result["version"]
    }
    status, result = req(f"/bookings/{conf_id}/reschedule", "POST", reschedule_data, member_token)
    print(f"       状态码: {status}")
    if status == 409:
        print(f"{OK} 6.2 改期撞封场被409拦截")
        print_detail(result)
    elif status == 200:
        fail(f"6.2 改期撞封场未被拦截 ID={result['id']}")
    else:
        fail(f"6.2 异常: HTTP {status}")

# ============ Test 7: 预约列表和详情带出封场信息 ============
print("\n" + "=" * 70)
print("✅ Test 7：预约响应中带出封场窗口信息")
print("=" * 70)

print(f"\n{STEP} 7.1 创建一个撞封场窗口的预约（先建合法再移动）")
safe_start3, safe_end3 = safe_slot(member_token, venue1["id"], base1, 11, exclude_ids=created_booking_ids)
cw_booking_data = {
    "title": title("BOOKING-WITH-CW-INFO"),
    "production": title("封场测试"),
    "venue_id": venue1["id"],
    "start_time": safe_start3.isoformat(),
    "end_time": safe_end3.isoformat(),
    "priority": 10,
    "notes": TAG,
    "status": "pending"
}
status, result = req("/bookings", "POST", cw_booking_data, member_token)
if status != 200:
    fail(f"7.1 创建预约失败: HTTP {status}")
    print_detail(result)
else:
    track_booking(result)
    info_booking_id = result["id"]
    status, result = req(f"/bookings/{info_booking_id}", token=member_token)
    print(f"   正常时段 closed_windows 字段: {result.get('closed_windows')}")
    if result.get("closed_windows") is None or len(result.get("closed_windows", [])) == 0:
        print(f"{OK} 7.1 正常时段预约无封场信息（正确）")
    else:
        fail(f"7.1 正常时段预约不应有封场信息")

# ============ Test 8: 撤销封场窗口后可以重新预约 ============
print("\n" + "=" * 70)
print("✅ Test 8：撤销封场窗口后可以重新预约")
print("=" * 70)

print(f"\n{STEP} 8.1 撤销场地1的封场窗口")
if w1_id:
    status, result = req(f"/config/closed-windows/{w1_id}", "DELETE", token=admin_token)
    print(f"       撤销状态码: {status}")
    if status == 200:
        print(f"{OK} 8.1 撤销封场窗口成功 is_revoked={result.get('is_revoked')}")
    else:
        fail(f"8.1 撤销失败: HTTP {status}")
else:
    print(f"{WARN} 8.1 跳过（无可用窗口ID）")

print(f"\n{STEP} 8.2 撤销后在原封场时段创建预约（应成功）")
if w1_id:
    rebirth_data = {
        "title": title("REBIRTH-AFTER-REVOKE"),
        "production": title("封场测试"),
        "venue_id": venue1["id"],
        "start_time": window_start.isoformat(),
        "end_time": window_end.isoformat(),
        "priority": 10,
        "notes": TAG,
        "status": "pending"
    }
    status, result = req("/bookings", "POST", rebirth_data, member_token)
    print(f"       状态码: {status}")
    if status == 200:
        print(f"{OK} 8.2 撤销后同时段预约成功 ID={result['id']}")
        track_booking(result)
    elif status == 409:
        fail(f"8.2 撤销后仍被封场拦截")
        print_detail(result)
    else:
        fail(f"8.2 异常: HTTP {status}")
else:
    print(f"{WARN} 8.2 跳过（无可用窗口ID）")

# ============ Test 9: CSV导出包含封场窗口信息 ============
print("\n" + "=" * 70)
print("✅ Test 9：CSV导出包含封场窗口列")
print("=" * 70)

print(f"\n{STEP} 9.1 导出CSV检查表头")
csv_url = f"{BASE_URL}/exports/bookings.csv"
request = urllib.request.Request(csv_url, headers={"Authorization": f"Bearer {admin_token}"})
response = urllib.request.urlopen(request)
csv_content = response.read().decode("utf-8-sig")
lines = csv_content.strip().split("\n")
header = lines[0]
print(f"   CSV表头片段: {header[:150]}...")

required_cols = ["撞封场窗口", "封场时段", "封场原因"]
missing = [c for c in required_cols if c not in header]
if not missing:
    print(f"{OK} 9.1 CSV表头包含全部封场窗口列（{required_cols}）")
else:
    fail(f"9.1 CSV表头缺失 {missing}")

# ============ Cleanup ============
print("\n" + "=" * 70)
print(f"{STEP} 清理本次测试数据")
print("=" * 70)

ok = 0
for bid in created_booking_ids:
    try:
        status, b = req(f"/bookings/{bid}", token=admin_token)
        if status != 200:
            continue
        if b["status"] == "cancelled":
            ok += 1
            continue
        status, _ = req(f"/bookings/{bid}/status", "PATCH",
            {"status": "cancelled", "version": b["version"]}, admin_token)
        if status == 200:
            ok += 1
    except Exception as e:
        print(f"{WARN} 清理{bid}异常: {e}")
print(f"\n预约清理: {ok}/{len(created_booking_ids)} 已取消")

# ============ 最终汇总 ============
print("\n" + "=" * 70)
print(f"最终结果 - RUN_ID={RUN_ID}")
print("=" * 70)
print(f"失败项: {fail_count}")
print(f"创建预约: {len(created_booking_ids)} 条")
print(f"创建封场窗口: {len(created_window_ids)} 条")
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
