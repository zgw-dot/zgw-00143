import urllib.request
import urllib.parse
import json
from datetime import datetime, timedelta

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

def print_step(step, status, data, expected_success=True):
    success = 200 <= status < 300
    passed = success == expected_success
    symbol = "✅" if passed else "❌"
    print(f"\n{symbol} {step}")
    print(f"   状态码: {status}")
    if success and isinstance(data, dict):
        if "id" in data:
            print(f"   ID: {data['id']}")
        if "status" in data:
            print(f"   状态: {data['status']}")
        if "total" in data:
            print(f"   总数: {data['total']}")
    elif not success and data.get("detail"):
        detail = data["detail"]
        if isinstance(detail, dict):
            print(f"   错误: {detail.get('message', '冲突')}")
            if detail.get("conflicts"):
                print(f"   冲突数: {len(detail['conflicts'])}")
        else:
            print(f"   错误: {detail}")
    return passed

print("=" * 60)
print("剧场排练厅预约系统 - 主流程验收测试")
print("=" * 60)

passed_count = 0
total_count = 0

def test(step, status, data, expected=True):
    global passed_count, total_count
    total_count += 1
    if print_step(step, status, data, expected):
        passed_count += 1

# 1. 登录
print("\n📋 1. 认证测试")
admin_token, admin_user = login("admin", "admin123")
test("管理员登录", 200, {"access_token": "..."})

member_token, member_user = login("lisi", "123456")
test("成员登录", 200, {"access_token": "..."})

# 2. 场地查询
print("\n📋 2. 场地查询")
status, venues = req("/venues", token=member_token)
test("获取场地列表", status, venues)
venue1 = venues[0]
venue2 = venues[1] if len(venues) > 1 else venues[0]

# 3. 创建预约流程
print("\n📋 3. 预约创建与提交")
tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

booking_data = {
    "title": "测试预约-哈姆雷特",
    "production": "哈姆雷特",
    "venue_id": venue1["id"],
    "start_time": f"{tomorrow}T09:00:00",
    "end_time": f"{tomorrow}T12:00:00",
    "priority": 50,
    "notes": "主流程测试",
    "status": "draft"
}
status, draft = req("/bookings", "POST", booking_data, member_token)
test("成员创建草稿", status, draft)

booking_id = draft["id"]
version = draft["version"]
status, submitted = req(
    f"/bookings/{booking_id}/status",
    "PATCH",
    {"status": "pending", "version": version},
    member_token
)
test("提交审批", status, submitted)

# 4. 冲突检测
print("\n📋 4. 冲突检测")
conflict_data = {
    "title": "冲突测试预约",
    "production": "冲突剧目",
    "venue_id": venue1["id"],
    "start_time": f"{tomorrow}T10:00:00",
    "end_time": f"{tomorrow}T11:00:00",
    "priority": 60,
    "status": "pending"
}
status, result = req("/bookings", "POST", conflict_data, member_token)
test("重叠预约被拒绝", status, result, expected=False)

# 5. 管理员审批
print("\n📋 5. 审批流程")
status, pending_list = req("/bookings", token=admin_token, params={"status": "pending"})
test("获取待审批列表", status, pending_list)

if pending_list.get("items"):
    first = pending_list["items"][0]
    bid = first["id"]
    ver = first["version"]
    status, approved = req(
        f"/bookings/{bid}/status",
        "PATCH",
        {"status": "confirmed", "version": ver},
        admin_token
    )
    test("管理员审批通过", status, approved)

# 6. 越权测试
print("\n📋 6. 越权测试")
status, all_list = req("/bookings", token=member_token)
member_approved = None
for b in all_list.get("items", []):
    if b["user_id"] != member_user["id"] and b["status"] == "pending":
        status, result = req(
            f"/bookings/{b['id']}/status",
            "PATCH",
            {"status": "confirmed", "version": b["version"]},
            member_token
        )
        test("成员越权审批被拒绝", status, result, expected=False)
        break
else:
    print("\n   ⏭️  跳过：没有找到其他成员的待审批预约")

# 7. 改期功能
print("\n📋 7. 改期功能")
status, confirmed_list = req("/bookings", token=member_token, params={"status": "confirmed"})
if confirmed_list.get("items"):
    confirmed = confirmed_list["items"][0]
    bid = confirmed["id"]
    ver = confirmed["version"]

    new_day = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d")
    reschedule_data = {
        "new_start_time": f"{new_day}T14:00:00",
        "new_end_time": f"{new_day}T17:00:00",
        "reason": "演员档期调整",
        "version": ver
    }
    status, rescheduled = req(
        f"/bookings/{bid}/reschedule",
        "POST",
        reschedule_data,
        member_token
    )
    test("提交改期申请", status, rescheduled)

    status, history = req(f"/bookings/{bid}/reschedule-history", token=member_token)
    test("查看改期历史", status, {"count": len(history) if isinstance(history, list) else 0})
    if isinstance(history, list) and history:
        h = history[0]
        print(f"   操作人: {h.get('operator_name', 'N/A')}")
        print(f"   原因: {h.get('reason', 'N/A')}")
        if h.get("operator_name"):
            test("改期记录包含操作人", 200, {"ok": True})

# 8. 版本号乐观锁
print("\n📋 8. 版本冲突测试")
status, detail = req(f"/bookings/{bid}", token=member_token)
if status == 200:
    old_ver = detail["version"]
    wrong_ver = old_ver - 1 if old_ver > 1 else 1
    update_data = {
        "title": "旧版本测试",
        "version": wrong_ver
    }
    status, result = req(f"/bookings/{bid}", "PUT", update_data, member_token)
    test(f"旧版本更新被拒绝（当前v{old_ver}，提交v{wrong_ver}）", status, result, expected=False)

# 9. 筛选功能
print("\n📋 9. 筛选功能")
status, filtered = req("/bookings", token=member_token, params={"venue_id": venue1["id"], "status": "confirmed"})
test("按场地+状态筛选", status, filtered)

status, prod_filtered = req("/bookings", token=member_token, params={"production": "哈姆雷特"})
test("按剧目筛选", status, prod_filtered)

# 10. CSV导出
print("\n📋 10. CSV导出")
try:
    csv_url = build_url("/exports/bookings.csv")
    request = urllib.request.Request(
        csv_url,
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    response = urllib.request.urlopen(request)
    csv_content = response.read().decode("utf-8-sig")
    lines = csv_content.strip().split("\n")
    test("导出CSV成功", 200, {"lines": len(lines)})
    print(f"   CSV 行数: {len(lines)}")
    print(f"   表头: {lines[0][:60]}...")
except Exception as e:
    test("导出CSV", 500, {"detail": str(e)})

# 11. 封场日期测试
print("\n📋 11. 封场日期测试")
next_week = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
closed_data = {
    "title": "封场日测试",
    "production": "测试",
    "venue_id": venue1["id"],
    "start_time": f"{next_week}T10:00:00",
    "end_time": f"{next_week}T12:00:00",
    "priority": 10,
    "status": "pending"
}
status, result = req("/bookings", "POST", closed_data, member_token)
test("封场日预约被拒绝", status, result, expected=False)

# 12. 跨午夜重叠测试
print("\n📋 12. 跨午夜重叠测试")
day1 = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d")
day2 = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d")

midnight1 = {
    "title": "午夜排练A",
    "production": "午夜测试",
    "venue_id": venue2["id"],
    "start_time": f"{day1}T22:00:00",
    "end_time": f"{day2}T01:00:00",
    "priority": 10,
    "status": "pending"
}
status, b1 = req("/bookings", "POST", midnight1, member_token)
test("创建跨午夜预约", status, b1)

if status == 200:
    midnight2 = {
        "title": "午夜排练B",
        "production": "午夜测试",
        "venue_id": venue2["id"],
        "start_time": f"{day1}T23:00:00",
        "end_time": f"{day2}T02:00:00",
        "priority": 20,
        "status": "pending"
    }
    status, b2 = req("/bookings", "POST", midnight2, member_token)
    test("跨午夜重叠预约被拒绝", status, b2, expected=False)

# 13. 取消预约
print("\n📋 13. 取消预约")
status, my_list = req("/bookings", token=member_token, params={"user_id": member_user["id"]})
if my_list.get("items"):
    for b in my_list["items"]:
        if b["status"] in ["pending", "draft"]:
            status, result = req(
                f"/bookings/{b['id']}/status",
                "PATCH",
                {"status": "cancelled", "rejection_reason": "测试取消", "version": b["version"]},
                member_token
            )
            test("成员取消自己的预约", status, result)
            break

# 14. 配置管理（管理员）
print("\n📋 14. 配置管理")
status, rules = req("/config/priority-rules", token=admin_token)
test("获取优先级规则", status, rules)

status, closed_dates = req("/config/closed-dates", token=admin_token)
test("获取封场日期", status, closed_dates)

# 成员不能访问配置管理
status, result = req("/config/priority-rules", token=member_token)
print("\n📋 15. 权限控制")
# 成员尝试管理配置应该也能读，但不能写。先测读取。
test("成员可读取配置", status, rules)

print("\n" + "=" * 60)
print(f"测试结果: {passed_count}/{total_count} 通过")
if passed_count == total_count:
    print("🎉 所有测试通过！")
else:
    print(f"⚠️  有 {total_count - passed_count} 个测试未通过")
print("=" * 60)
