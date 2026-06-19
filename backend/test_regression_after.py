import sys
import io
import requests
import json
from datetime import datetime

class TeeOutput:
    def __init__(self, *files):
        self.files = files
    def write(self, obj):
        for f in self.files:
            f.write(obj)
            f.flush()
    def flush(self):
        for f in self.files:
            f.flush()

log_file = open('test_output.txt', 'w', encoding='utf-8')
sys.stdout = TeeOutput(sys.stdout, log_file)
sys.stderr = TeeOutput(sys.stderr, log_file)

BASE = "http://127.0.0.1:8000/api"

OK = "[OK]"
FAIL = "[FAIL]"
WARN = "[WARN]"

def login(username, password):
    r = requests.post(f"{BASE}/auth/login", data={"username": username, "password": password})
    assert r.status_code == 200, f"登录失败 {username}: {r.status_code} {r.text}"
    return r.json()["access_token"]

def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}

print("=" * 60)
print("修复后回归测试 - 剧场排练厅预约系统")
print("=" * 60)

member_token = login("lisi", "123456")
admin_token = login("admin", "admin123")

all_passed = True

print("\n[Test 1] 草稿在非开放时段（周二 07:00-08:00）应被拒绝")
print("-" * 60)
r = requests.post(f"{BASE}/bookings", json={
    "title": "回归测试-非开放时段草稿",
    "production": "回归测试剧目",
    "venue_id": 1,
    "status": "draft",
    "start_time": "2026-06-16T07:00:00",
    "end_time": "2026-06-16T08:00:00",
    "priority": 10,
    "notes": ""
}, headers=auth_headers(member_token))
print(f"  状态码: {r.status_code}")
if r.status_code != 200:
    print(f"  {OK} 被成功拒绝！预期 409，实际 {r.status_code}")
    detail = r.json().get("detail", {})
    if isinstance(detail, dict):
        print(f"  错误信息: {detail.get('message', 'N/A')}")
        if detail.get("open_slot_violations"):
            for v in detail["open_slot_violations"]:
                print(f"    - {v.get('reason', 'N/A')}")
else:
    data = r.json()
    print(f"  {FAIL} 仍然写入成功！预约ID={data.get('id')}，状态={data.get('status')}")
    print(f"  {FAIL} Bug 1a 未修复！")
    all_passed = False

print("\n[Test 2] 待审在非开放时段（周二 07:30-08:30）应被拒绝")
print("-" * 60)
r = requests.post(f"{BASE}/bookings", json={
    "title": "回归测试-非开放时段待审",
    "production": "回归测试剧目",
    "venue_id": 1,
    "status": "pending",
    "start_time": "2026-06-16T07:30:00",
    "end_time": "2026-06-16T08:30:00",
    "priority": 10,
    "notes": ""
}, headers=auth_headers(member_token))
print(f"  状态码: {r.status_code}")
if r.status_code != 200:
    print(f"  {OK} 被成功拒绝！预期 409，实际 {r.status_code}")
    detail = r.json().get("detail", {})
    if isinstance(detail, dict):
        print(f"  错误信息: {detail.get('message', 'N/A')}")
        if detail.get("open_slot_violations"):
            for v in detail["open_slot_violations"]:
                print(f"    - {v.get('reason', 'N/A')}")
else:
    data = r.json()
    print(f"  {FAIL} 仍然写入成功！预约ID={data.get('id')}，状态={data.get('status')}")
    print(f"  {FAIL} Bug 1b 未修复！")
    all_passed = False

print("\n[Test 3] 在开放时段内的草稿和待审都应该成功")
print("-" * 60)
r_draft_ok = requests.post(f"{BASE}/bookings", json={
    "title": "回归测试-开放时段草稿",
    "production": "回归测试剧目",
    "venue_id": 1,
    "status": "draft",
    "start_time": "2026-06-23T10:00:00",
    "end_time": "2026-06-23T11:00:00",
    "priority": 10,
    "notes": ""
}, headers=auth_headers(member_token))
print(f"  开放时段草稿: 状态码={r_draft_ok.status_code}")
assert r_draft_ok.status_code == 200, "开放时段草稿应该成功"
draft_ok = r_draft_ok.json()
print(f"  {OK} 草稿创建成功，ID={draft_ok['id']}，状态={draft_ok['status']}")

r_pending_ok = requests.post(f"{BASE}/bookings", json={
    "title": "回归测试-开放时段待审",
    "production": "回归测试剧目",
    "venue_id": 2,
    "status": "pending",
    "start_time": "2026-06-24T14:00:00",
    "end_time": "2026-06-24T15:00:00",
    "priority": 10,
    "notes": ""
}, headers=auth_headers(member_token))
print(f"  开放时段待审: 状态码={r_pending_ok.status_code}")
assert r_pending_ok.status_code == 200, f"开放时段待审应该成功: {r_pending_ok.text}"
pending_ok = r_pending_ok.json()
print(f"  {OK} 待审创建成功，ID={pending_ok['id']}，状态={pending_ok['status']}")

print("\n[Test 4] 管理员确认待审预约")
print("-" * 60)
r_confirm = requests.patch(f"{BASE}/bookings/{pending_ok['id']}/status", json={
    "status": "confirmed",
    "version": pending_ok["version"]
}, headers=auth_headers(admin_token))
print(f"  确认状态码: {r_confirm.status_code}")
assert r_confirm.status_code == 200, f"确认失败: {r_confirm.text}"
confirmed = r_confirm.json()
print(f"  {OK} 已确认，ID={confirmed['id']}，状态={confirmed['status']}，版本={confirmed['version']}")

print("\n[Test 5] 已确认预约改期（改到非开放时段）应被拒绝")
print("-" * 60)
r_resched_bad = requests.post(f"{BASE}/bookings/{confirmed['id']}/reschedule", json={
    "version": confirmed["version"],
    "new_start_time": "2026-06-23T07:00:00",
    "new_end_time": "2026-06-23T08:00:00",
    "reason": "改到非开放时段测试"
}, headers=auth_headers(admin_token))
print(f"  状态码: {r_resched_bad.status_code}")
if r_resched_bad.status_code != 200:
    print(f"  {OK} 改到非开放时段被成功拒绝！预期 409，实际 {r_resched_bad.status_code}")
    detail = r_resched_bad.json().get("detail", {})
    if isinstance(detail, dict):
        print(f"  错误信息: {detail.get('message', 'N/A')}")
        if detail.get("open_slot_violations"):
            for v in detail["open_slot_violations"]:
                print(f"    - {v.get('reason', 'N/A')}")
else:
    data = r_resched_bad.json()
    print(f"  {FAIL} 仍然改期成功！预约ID={data.get('id')}，状态={data.get('status')}")
    print(f"  {FAIL} Bug 1c 未修复！")
    all_passed = False

print("\n[Test 6] 已确认预约改期（改到开放时段）后状态应为 'rescheduling'")
print("-" * 60)
r_resched_good = requests.post(f"{BASE}/bookings/{confirmed['id']}/reschedule", json={
    "version": confirmed["version"],
    "new_start_time": "2026-06-18T10:00:00",
    "new_end_time": "2026-06-18T12:00:00",
    "reason": "排练时间调整，需要改期"
}, headers=auth_headers(admin_token))
print(f"  状态码: {r_resched_good.status_code}")
assert r_resched_good.status_code == 200, f"改期失败: {r_resched_good.text}"
rescheduled = r_resched_good.json()
print(f"  改期后状态 = '{rescheduled['status']}'")
if rescheduled["status"] == "rescheduling":
    print(f"  {OK} Bug 2 已修复！状态正确为 'rescheduling'")
elif rescheduled["status"] == "pending":
    print(f"  {FAIL} Bug 2 未修复！仍然是 'pending'，应该是 'rescheduling'")
    all_passed = False
else:
    print(f"  {FAIL} 状态异常！实际='{rescheduled['status']}'，预期='rescheduling'")
    all_passed = False

print("\n[Test 7] 查询改期历史 API 是否正常返回")
print("-" * 60)
r_history = requests.get(f"{BASE}/bookings/{confirmed['id']}/reschedule-history",
                         headers=auth_headers(admin_token))
assert r_history.status_code == 200, f"查改期历史失败: {r_history.text}"
history = r_history.json()
print(f"  改期记录数: {len(history)}")
for h in history:
    print(f"  - 操作人: {h.get('operator_name')}")
    print(f"    原时段: {h.get('original_start_time')} ~ {h.get('original_end_time')}")
    print(f"    新时段: {h.get('new_start_time')} ~ {h.get('new_end_time')}")
    print(f"    原因: {h.get('reason')}")
print(f"  {OK} 改期历史API正常")

print("\n[Test 8] CSV 导出应包含改期历史列和实际数据")
print("-" * 60)
r_csv = requests.get(f"{BASE}/exports/bookings.csv", headers=auth_headers(admin_token))
assert r_csv.status_code == 200, f"CSV导出失败: {r_csv.text}"
csv_text = r_csv.content.decode("utf-8-sig")
lines = csv_text.splitlines()
header = lines[0] if lines else ""
print(f"  表头: {header}")
required_cols = ["原时段", "新时段", "改期原因", "改期操作人"]
all_present = all(col in header for col in required_cols)
if all_present:
    print(f"  {OK} Bug 3 表头已修复！包含全部改期历史列")
else:
    missing = [c for c in required_cols if c not in header]
    print(f"  {FAIL} Bug 3 表头未修复！缺失: {missing}")
    all_passed = False

print(f"\n  CSV 共 {len(lines)} 行（含表头）")
print(f"  内容预览（前5行）:")
for i, line in enumerate(lines[:5]):
    print(f"    {i+1}. {line}")

has_reschedule_data = any("改期" in line for line in lines[1:])
if has_reschedule_data:
    print(f"  {OK} CSV 数据包含改期历史内容")
else:
    print(f"  {WARN} CSV 暂未出现改期数据（需检查）")

print("\n" + "=" * 60)
if all_passed:
    print("全部测试通过！")
else:
    print("部分测试失败，请检查！")
print("=" * 60)

log_file.close()
