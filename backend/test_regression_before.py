import urllib.request
import urllib.parse
import json
from datetime import datetime, timedelta, time

BASE_URL = "http://localhost:8000/api"

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

def test_step(name, status, data, expected_status=None, expected_success=None, extra_check=None):
    success = 200 <= status < 300
    if expected_status is not None:
        passed = status == expected_status
    elif expected_success is not None:
        passed = success == expected_success
    else:
        passed = success

    extra_result = True
    if extra_check and passed:
        extra_result = extra_check(data)
        passed = passed and extra_result

    symbol = "✅" if passed else "❌"
    expected_desc = ""
    if expected_status is not None:
        expected_desc = f" (期望状态码: {expected_status})"
    elif expected_success is not None:
        expected_desc = f" (期望{'成功' if expected_success else '失败'})"

    print(f"\n{symbol} {name}{expected_desc}")
    print(f"   状态码: {status}")

    if not passed:
        if isinstance(data, dict) and data.get("detail"):
            d = data["detail"]
            if isinstance(d, dict):
                print(f"   错误: {d.get('message', str(d))}")
            else:
                print(f"   错误: {d}")
    elif isinstance(data, dict):
        if "status" in data:
            print(f"   返回状态: {data['status']}")
        if "id" in data:
            print(f"   ID: {data['id']}")

    return passed

print("=" * 70)
print("剧场排练厅预约系统 - 回归测试（先证明Bug存在，再验证修复）")
print("=" * 70)

# ============ 准备工作 ============
print("\n📋 准备：登录并获取测试数据")
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

# ============ Bug 1: 开放时段校验缺失 ============
print("\n" + "=" * 70)
print("🔴 Bug 1 验证：开放时段校验形同虚设")
print("=" * 70)
bug1_passed = 0
bug1_total = 0

# 找到一个不在开放时段的时间点：周二 07:00-08:00（开放时段是 9-12, 14-18, 19-22）
# 先计算下周二的日期
today = datetime.now().date()
days_until_tuesday = (1 - today.weekday()) % 7
if days_until_tuesday == 0:
    days_until_tuesday = 7
next_tuesday = today + timedelta(days=days_until_tuesday)
print(f"\n   测试日期: 下周二 {next_tuesday}")
print(f"   测试时段: 07:00-08:00 (不在开放时段 9-12/14-18/19-22 内)")

# Bug 1a: 创建草稿预约在非开放时段 - 现在不校验，应该返回200（bug存在的表现）
bug1_total += 1
draft_data = {
    "title": "BUG复现-草稿非开放时段",
    "production": "Bug测试",
    "venue_id": venue1["id"],
    "start_time": f"{next_tuesday}T07:00:00",
    "end_time": f"{next_tuesday}T08:00:00",
    "priority": 10,
    "notes": "测试草稿在非开放时段是否被拦截",
    "status": "draft"
}
status, result = req("/bookings", "POST", draft_data, member_token)

# 现在的bug是：草稿不校验，直接200写库
# 修复后期望：返回409
# 测试逻辑：如果现在返回200，证明bug存在（bug复现）
# 修复后期望返回409，说明修复成功
bug_detected_1a = status == 200  # bug存在时为True
if bug_detected_1a:
    print("\n   🔴 发现Bug 1a: 草稿预约未校验开放时段，直接写入数据库！")
    # 记录这个预约ID后面清理
    bad_draft_id = result["id"]
    bug1_passed += 1  # 证明bug存在就算这个测试通过
test_step(
    "Bug1a: 草稿在非开放时段 (应被拦截，当前bug=200写入)",
    status, result,
    expected_status=200,  # 先证明bug存在
    extra_check=lambda d: d.get("status") == "draft"
)

# Bug 1b: 提交待审预约在非开放时段 - 现在不校验开放时段
bug1_total += 1
pending_data = {
    "title": "BUG复现-待审非开放时段",
    "production": "Bug测试",
    "venue_id": venue1["id"],
    "start_time": f"{next_tuesday}T07:30:00",
    "end_time": f"{next_tuesday}T08:30:00",
    "priority": 10,
    "notes": "测试待审在非开放时段是否被拦截",
    "status": "pending"
}
status, result = req("/bookings", "POST", pending_data, member_token)

bug_detected_1b = status == 200
if bug_detected_1b:
    print("\n   🔴 发现Bug 1b: 待审预约未校验开放时段，直接写入数据库！")
    bug1_passed += 1
test_step(
    "Bug1b: 待审在非开放时段 (应被拦截，当前bug=200写入)",
    status, result,
    expected_status=200,  # 先证明bug存在
    extra_check=lambda d: d.get("status") == "pending"
)

# Bug 1c: 改期到非开放时段 - 现在不校验开放时段
# 先创建一个正常的confirmed预约
confirmed_data = {
    "title": "改期测试-基础预约",
    "production": "改期测试",
    "venue_id": venue2["id"],
    "start_time": f"{next_tuesday}T10:00:00",
    "end_time": f"{next_tuesday}T11:00:00",
    "priority": 50,
    "status": "draft"
}
status, base_booking = req("/bookings", "POST", confirmed_data, member_token)
base_booking_id = base_booking["id"]
base_ver = base_booking["version"]

# 提交审批
status, _ = req(
    f"/bookings/{base_booking_id}/status",
    "PATCH",
    {"status": "pending", "version": base_ver},
    member_token
)
# 管理员审批
status, base_booking = req(f"/bookings/{base_booking_id}", token=admin_token)
status, _ = req(
    f"/bookings/{base_booking_id}/status",
    "PATCH",
    {"status": "confirmed", "version": base_booking["version"]},
    admin_token
)

# 现在尝试改期到非开放时段
bug1_total += 1
status, base_booking = req(f"/bookings/{base_booking_id}", token=member_token)
reschedule_data = {
    "new_start_time": f"{next_tuesday}T07:00:00",
    "new_end_time": f"{next_tuesday}T08:00:00",
    "reason": "测试改期到非开放时段是否被拦截",
    "version": base_booking["version"]
}
status, result = req(f"/bookings/{base_booking_id}/reschedule", "POST", reschedule_data, member_token)

bug_detected_1c = status == 200
if bug_detected_1c:
    print("\n   🔴 发现Bug 1c: 改期到非开放时段未被拦截！")
    bug1_passed += 1
test_step(
    "Bug1c: 改期到非开放时段 (应被拦截，当前bug=200)",
    status, result,
    expected_status=200  # 先证明bug存在
)

print(f"\n📊 Bug 1 复现情况: {bug1_passed}/{bug1_total} 个入口绕过了开放时段校验")
if bug1_passed == bug1_total:
    print("   🔴 Bug 1 确认：三条入口（草稿/待审/改期）均未校验开放时段！")

# ============ Bug 2: 改期后状态错误 ============
print("\n" + "=" * 70)
print("🔴 Bug 2 验证：改期后状态应该是'改期中'而不是'待审'")
print("=" * 70)

# 创建一个已确认的预约
reschedule_test_data = {
    "title": "Bug2测试-改期状态",
    "production": "Bug测试",
    "venue_id": venue2["id"],
    "start_time": f"{next_tuesday}T14:00:00",
    "end_time": f"{next_tuesday}T15:00:00",
    "priority": 50,
    "status": "draft"
}
status, bug2_booking = req("/bookings", "POST", reschedule_test_data, member_token)
bug2_id = bug2_booking["id"]
bug2_ver = bug2_booking["version"]

# 提交并审批
status, _ = req(
    f"/bookings/{bug2_id}/status", "PATCH",
    {"status": "pending", "version": bug2_ver}, member_token
)
status, bug2_booking = req(f"/bookings/{bug2_id}", token=admin_token)
status, _ = req(
    f"/bookings/{bug2_id}/status", "PATCH",
    {"status": "confirmed", "version": bug2_booking["version"]}, admin_token
)
print(f"   预约已确认，准备发起改期...")

# 发起改期到合法时段
status, bug2_booking = req(f"/bookings/{bug2_id}", token=member_token)
bug2_reschedule = {
    "new_start_time": f"{next_tuesday}T15:00:00",
    "new_end_time": f"{next_tuesday}T16:00:00",
    "reason": "Bug2测试：检查改期后状态",
    "version": bug2_booking["version"]
}
status, result = req(f"/bookings/{bug2_id}/reschedule", "POST", bug2_reschedule, member_token)

bug2_detected = status == 200 and result.get("status") == "pending"
if bug2_detected:
    print("\n   🔴 发现Bug 2: 已确认预约改期后状态变为'pending'（待审），应该是'rescheduling'（改期中）！")

test_step(
    "Bug2: 改期后状态应为'rescheduling'，当前bug='pending'",
    status, result,
    expected_success=True,
    extra_check=lambda d: d.get("status") == "pending"  # 先证明bug存在
)

# ============ Bug 3: CSV导出缺失改期历史 ============
print("\n" + "=" * 70)
print("🔴 Bug 3 验证：CSV导出缺失改期历史")
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
print(f"   CSV表头: {header}")

bug3_detected = "原时段" not in header and "改期原因" not in header and "操作人" not in header
if bug3_detected:
    print("\n   🔴 发现Bug 3: CSV导出完全没有改期历史列（原时段/新时段/原因/操作人）！")

test_step(
    "Bug3: CSV表头无改期相关列",
    200, {"header": header},
    extra_check=lambda d: "原时段" not in d.get("header", "")
)

# ============ 总结：Bug确认 ============
print("\n" + "=" * 70)
print("📋 Bug 复现总结")
print("=" * 70)
bugs_found = 0
if bug1_passed > 0:
    bugs_found += 1
    print("   🔴 Bug 1: 开放时段校验缺失（草稿/待审/改期均可绕过）")
if bug2_detected:
    bugs_found += 1
    print("   🔴 Bug 2: 改期后状态错误（pending 应为 rescheduling）")
if bug3_detected:
    bugs_found += 1
    print("   🔴 Bug 3: CSV导出缺失改期历史")

print(f"\n共发现 {bugs_found} 个Bug，准备开始修复...")
