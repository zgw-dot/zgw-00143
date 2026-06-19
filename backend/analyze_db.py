import requests
import sys
from datetime import datetime, timedelta

out_file = open("analyze_db.txt", "w", encoding="utf-8")

class Tee:
    def __init__(self, *files): self.files = files
    def write(self, s):
        for f in self.files: f.write(s); f.flush()
    def flush(self):
        for f in self.files: f.flush()

sys.stdout = Tee(sys.stdout, out_file)
sys.stderr = Tee(sys.stderr, out_file)

BASE = "http://127.0.0.1:8000/api"

def login(username, password):
    r = requests.post(f"{BASE}/auth/login", data={"username": username, "password": password})
    assert r.status_code == 200, f"login failed: {r.text}"
    return r.json()["access_token"]

token = login("admin", "admin123")
headers = {"Authorization": f"Bearer {token}"}

r = requests.get(f"{BASE}/bookings", headers=headers, params={"page_size": 200})
data = r.json()

print("=" * 80)
print("数据库已有预约分析")
print("=" * 80)
print(f"总预约数: {data['total']}")
print(f"当前时间: {datetime.now().isoformat()}")
print()

# 按场地分组的时间分布
venues = {}
for b in data["items"]:
    v = b["venue_name"]
    if v not in venues:
        venues[v] = []
    venues[v].append(b)

print("按场地时间分布:")
for v, bookings in venues.items():
    print(f"\n  【{v}】共 {len(bookings)} 条:")
    bookings.sort(key=lambda x: x["start_time"])
    for b in bookings:
        print(f"    [{b['id']:3d}] {b['status']:10s} {b['start_time']} ~ {b['end_time']}  {b['title'][:50]}")

print("\n" + "=" * 80)
print("测试脚本不稳定性根因分析:")
print("=" * 80)

# 检查测试用固定时间是否有冲突
test_times = [
    ("Test1 草稿非开放", "2026-06-16T07:00:00", "2026-06-16T08:00:00", 1),
    ("Test2 待审非开放", "2026-06-16T07:30:00", "2026-06-16T08:30:00", 1),
    ("Test3 草稿开放", "2026-06-23T10:00:00", "2026-06-23T11:00:00", 1),
    ("Test3 待审开放", "2026-06-24T14:00:00", "2026-06-24T15:00:00", 2),
    ("Test6 改期目标", "2026-06-18T10:00:00", "2026-06-18T12:00:00", 2),
    ("Test5 改期非开放", "2026-06-23T07:00:00", "2026-06-23T08:00:00", 2),
]

def has_overlap(venue_id, start, end, exclude_id=None):
    s = datetime.fromisoformat(start)
    e = datetime.fromisoformat(end)
    for b in data["items"]:
        if exclude_id and b["id"] == exclude_id:
            continue
        if b["venue_id"] != venue_id:
            continue
        if b["status"] in ("cancelled",):
            continue
        bs = datetime.fromisoformat(b["start_time"])
        be = datetime.fromisoformat(b["end_time"])
        if s < be and bs < e:
            return b
    return None

for name, start, end, venue_id in test_times:
    conflict = has_overlap(venue_id, start, end)
    if conflict:
        print(f"  ❌ {name} ({venue_id}) 有冲突!")
        print(f"       测试时段: {start} ~ {end}")
        print(f"       被预约ID={conflict['id']} 挡住: {conflict['title'][:40]}")
        print(f"       对方时段: {conflict['start_time']} ~ {conflict['end_time']}")
    else:
        print(f"  ✅ {name} 目前无冲突")

print("\n" + "=" * 80)
print("加固方案:")
print("=" * 80)
print("  1. 用 RUN_ID + 时间戳做唯一标识（title/notes 前缀）")
print("  2. 测试前检查时段，冲突则后移1小时重试（最多5次）")
print("  3. 用足够远的未来日期（如 当前时间+365天以上）避开业务数据")
print("  4. 测试后根据唯一标识清理本次生成的所有预约/改期记录")
print("  5. 断言失败时，自动列出冲突的预约详情（ID/时段/标题）")
print("  6. 每次测试生成独立时间窗，不依赖硬编码固定日期")

out_file.close()
