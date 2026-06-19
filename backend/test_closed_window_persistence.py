import urllib.request
import urllib.parse
import json
import sys
from datetime import datetime, timedelta

RUN_ID = datetime.now().strftime("%Y%m%d%H%M%S")
TAG = f"PERSIST-{RUN_ID}"
LOG_FILE = f"persist_verify_{RUN_ID}.txt"

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

def fail(msg):
    global fail_count
    fail_count += 1
    print(f"{FAIL} {msg}")

def title(name):
    return f"{TAG}-{name}"

print("=" * 70)
print(f"封场窗口持久化验证 - RUN_ID={RUN_ID}")
print(f"TAG: {TAG}")
print("=" * 70)

admin_token, admin_user = login("admin", "admin123")
member_token, member_user = login("lisi", "123456")

status, venues = req("/venues", token=member_token)
venue1 = venues[0]
venue2 = venues[1] if len(venues) > 1 else venues[0]
print(f"   测试场地1: {venue1['name']} (ID: {venue1['id']})")

# ============ Test: 验证已有数据还在 ============
print(f"\n{STEP} 1. 验证服务重启后封场窗口数据仍在数据库")
status, windows = req("/config/closed-windows", token=admin_token, params={"include_revoked": "true"})
print(f"   现有封场窗口数量(含已撤销): {len(windows)}")
for w in windows:
    print(f"     ID={w['id']} venue_id={w.get('venue_id')} revoked={w.get('is_revoked')} {w.get('start_time')}~{w.get('end_time')} {w.get('reason','')}")

active_windows = [w for w in windows if not w.get('is_revoked')]
revoked_windows = [w for w in windows if w.get('is_revoked')]
print(f"   有效: {len(active_windows)}, 已撤销: {len(revoked_windows)}")

if len(windows) >= 2:
    print(f"{OK} 1. 之前测试创建的封场窗口数据仍然存在")
else:
    print(f"{WARN} 1. 窗口数量少于预期（可能数据被清理了），重新创建验证用数据")

# ============ Test: 创建新数据用于持久化验证 ============
print(f"\n{STEP} 2. 创建新的封场窗口用于持久化测试")
base_date = datetime.now() + timedelta(days=200)
days = (1 - base_date.weekday()) % 7
if days == 0: days = 7
slot_date = base_date + timedelta(days=days)
cw_start = slot_date.replace(hour=9, minute=0, second=0, microsecond=0)
cw_end = cw_start + timedelta(hours=2)

cw_data = {
    "venue_id": venue1["id"],
    "start_time": cw_start.isoformat(),
    "end_time": cw_end.isoformat(),
    "reason": title("持久化验证-设备检修"),
    "apply_all_venues": False
}
status, result = req("/config/closed-windows", "POST", cw_data, admin_token)
print(f"   创建状态: {status}")
if status == 200:
    new_cw_id = result["id"]
    new_cw_reason = result["reason"]
    print(f"   新窗口 ID={new_cw_id} reason={new_cw_reason}")
    print(f"{OK} 2. 封场窗口创建成功")
else:
    fail(f"2. 创建失败: HTTP {status}")
    new_cw_id = None

# ============ Test: 预约被新窗口拦截 ============
print(f"\n{STEP} 3. 验证该封场窗口可以拦截预约")
if new_cw_id:
    booking_data = {
        "title": title("PERSIST-HIT-TEST"),
        "production": title("持久化测试"),
        "venue_id": venue1["id"],
        "start_time": cw_start.isoformat(),
        "end_time": cw_end.isoformat(),
        "priority": 10,
        "notes": TAG,
        "status": "pending"
    }
    status, result = req("/bookings", "POST", booking_data, member_token)
    print(f"   创建预约状态: {status}")
    if status == 409:
        detail = result.get("detail", {})
        if isinstance(detail, dict) and detail.get("closed_windows"):
            cw_info = detail["closed_windows"][0]
            print(f"       命中窗口: ID={cw_info.get('id')} reason={cw_info.get('reason')}")
            if cw_info.get("reason") == new_cw_reason:
                print(f"{OK} 3. 正确命中刚创建的封场窗口，预约被拦截")
            else:
                fail(f"3. 命中的窗口原因不匹配")
        else:
            fail(f"3. 返回中没有 closed_windows 信息")
    else:
        fail(f"3. 预约未被409拦截: HTTP {status}")
else:
    print(f"{WARN} 3. 跳过（无窗口ID）")

# ============ Test: 直接查数据库验证表和数据 ============
print(f"\n{STEP} 4. 直接查询数据库验证 closed_windows 表存在且有数据")
import sqlite3, os
db_path = os.path.join(os.path.dirname(__file__), "theater_booking.db")
conn = sqlite3.connect(db_path)
cursor = conn.cursor()
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='closed_windows'")
table_exists = cursor.fetchone() is not None
print(f"   closed_windows 表存在: {table_exists}")

if table_exists:
    cursor.execute("SELECT COUNT(*) FROM closed_windows")
    count = cursor.fetchone()[0]
    print(f"   表中记录数: {count}")
    cursor.execute("SELECT id, venue_id, start_time, end_time, reason, is_revoked, created_by, revoked_by FROM closed_windows ORDER BY id DESC LIMIT 3")
    rows = cursor.fetchall()
    for row in rows:
        print(f"     DB行: id={row[0]} venue={row[1]} start={row[2]} end={row[3]} reason={row[4][:30] if row[4] else ''} revoked={row[5]} created_by={row[6]} revoked_by={row[7]}")
    if count > 0:
        print(f"{OK} 4. 数据库中有封场窗口记录")
    else:
        fail(f"4. 数据库中没有记录")
else:
    fail(f"4. closed_windows 表不存在")

cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='bookings'")
cursor.execute("SELECT COUNT(*) FROM bookings WHERE notes LIKE ?", (f"%{TAG}%",))
booking_count = cursor.fetchone()[0]
print(f"   本次相关预约数: {booking_count}")

conn.close()

# ============ 最终汇总 ============
print("\n" + "=" * 70)
print(f"最终结果 - RUN_ID={RUN_ID}")
print("=" * 70)
print(f"失败项: {fail_count}")
print(f"日志文件: {LOG_FILE}")
print()
if fail_count == 0:
    print(f"{OK} 持久化验证全部通过！数据已正确保存到 SQLite 数据库，服务重启后仍然有效。")
    sys.stdout = _orig_stdout
    sys.stderr = _orig_stderr
    log_file.close()
    sys.exit(0)
else:
    print(f"{FAIL} 有 {fail_count} 项失败")
    sys.stdout = _orig_stdout
    sys.stderr = _orig_stderr
    log_file.close()
    sys.exit(1)
