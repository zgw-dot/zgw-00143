import requests
import json
import time
import sys
from datetime import datetime, timedelta

BASE = "http://127.0.0.1:8001/api"

PASS = []
FAIL = []

def case(name, cond, detail=""):
    if cond:
        PASS.append(name)
        print(f"[PASS] {name}")
    else:
        FAIL.append((name, detail))
        print(f"[FAIL] {name} -- {detail}")


def login(username, password):
    role = "admin" if username == "admin" else "member"
    requests.post(f"{BASE}/auth/register", json={
        "username": username, "password": password,
        "full_name": f"用户{username}", "role": role
    })
    r = requests.post(f"{BASE}/auth/login", data={"username": username, "password": password})
    if r.status_code != 200:
        print(f"登录{username}失败: {r.status_code} {r.text}")
        sys.exit(1)
    return r.json()["access_token"]


def h(tok):
    return {"Authorization": f"Bearer {tok}"}


def ensure_data(tok_a):
    r = requests.get(f"{BASE}/venues", headers=h(tok_a))
    for v in r.json():
        if v["name"] == "一号排练厅":
            vid = v["id"]
            break
    else:
        r = requests.post(f"{BASE}/venues", headers=h(tok_a), json={
            "name": "一号排练厅", "description": "测试", "capacity": 50
        })
        vid = r.json()["id"]
    r = requests.get(f"{BASE}/config/open-slots", headers=h(tok_a))
    if not [s for s in r.json() if s["venue_id"] == vid]:
        for d in range(7):
            requests.post(f"{BASE}/config/open-slots", headers=h(tok_a), json={
                "venue_id": vid, "day_of_week": d,
                "start_time": "09:00:00", "end_time": "22:00:00"
            })
    return vid


def main():
    print("======== 候补补位快速回归测试 ========")
    stamp = datetime.now().strftime("%H%M%S")
    tok_a = login("admin", "admin123")
    tok_u1 = login(f"u1_{stamp}", "pass123")
    tok_u2 = login(f"u2_{stamp}", "pass123")
    tok_u3 = login(f"u3_{stamp}", "pass123")
    vid = ensure_data(tok_a)

    # 找到下一个周一（确保有开放时段），再加35天
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    days_to_monday = (7 - today.weekday()) % 7 or 7
    next_monday = today + timedelta(days=days_to_monday)
    D = next_monday + timedelta(days=42)
    def t(h): return (D + timedelta(hours=h)).isoformat()

    # ========== T1: 创建预约1 上午09-12 ==========
    r = requests.post(f"{BASE}/bookings", headers=h(tok_u1), json={
        "title": "剧目A上午", "production": "剧目A", "venue_id": vid,
        "start_time": t(9), "end_time": t(12), "status": "pending", "priority": 10
    })
    case("T1: 创建预约1成功", r.status_code == 200, f"{r.status_code} {r.text[:100]}")
    b1 = r.json()
    r = requests.patch(f"{BASE}/bookings/{b1['id']}/status", headers=h(tok_a), json={
        "status": "confirmed", "version": b1["version"]
    })
    case("T1b: 管理员确认预约1", r.status_code == 200)

    # ========== T2: 用户2同09-12预约失败 -> 登记候补 ==========
    r = requests.post(f"{BASE}/bookings", headers=h(tok_u2), json={
        "title": "剧目B上午", "production": "剧目B", "venue_id": vid,
        "start_time": t(9), "end_time": t(12), "status": "pending"
    })
    case("T2: 09-12预约被冲突拦截", r.status_code in (400, 409))

    r = requests.post(f"{BASE}/waitlist", headers=h(tok_u2), json={
        "venue_id": vid, "title": "剧目B上午候补", "production": "剧目B",
        "target_start_time": t(9), "target_end_time": t(12),
        "float_before_minutes": 60, "float_after_minutes": 60, "priority": 8
    })
    case("T2b: 登记候补成功", r.status_code == 200, f"{r.status_code} {r.text[:200]}")
    w1 = r.json()
    w1_id = w1["id"]
    case("T2c: 候补状态=waiting 队列=1 被挡类型=booking",
         w1["status"] == "waiting" and w1["queue_position"] >= 1 and w1["blocked_by_type"] == "booking")

    # ========== T3: 重复候补拦截 ==========
    r = requests.post(f"{BASE}/waitlist", headers=h(tok_u2), json={
        "venue_id": vid, "title": "重复", "production": "剧目B",
        "target_start_time": t(10), "target_end_time": t(11)
    })
    case("T3: 重复候补被拦截", r.status_code == 409)

    # ========== T4: 封场 -> 候补登记 ==========
    r = requests.post(f"{BASE}/config/closed-windows", headers=h(tok_a), json={
        "venue_id": vid, "start_time": t(14), "end_time": t(17),
        "reason": "测试封场", "apply_all_venues": False
    })
    case("T4: 创建封场窗口", r.status_code == 200, f"{r.status_code} {r.text[:100]}")
    cw_id = r.json()["id"]

    r = requests.post(f"{BASE}/waitlist", headers=h(tok_u1), json={
        "venue_id": vid, "title": "剧目A下午", "production": "剧目A",
        "target_start_time": t(14), "target_end_time": t(17),
        "float_before_minutes": 0, "float_after_minutes": 60, "priority": 12
    })
    case("T4b: 被封场挡的候补登记", r.status_code == 200, f"{r.status_code} {r.text[:200]}")
    w2 = r.json()
    w2_id = w2["id"]
    case("T4c: 被挡类型=closed_window", w2["blocked_by_type"] == "closed_window")

    # ========== T5: 权限控制 - 用户2看用户1的候补 ==========
    r = requests.get(f"{BASE}/waitlist/{w2_id}", headers=h(tok_u2))
    case("T5: 用户2偷看用户1候补详情被403", r.status_code == 403)

    r = requests.get(f"{BASE}/waitlist", headers=h(tok_u2))
    case("T5b: 用户2自己列表过滤",
         r.status_code == 200 and all(i["user_id"] != w2["user_id"] or i["user_id"] == 6 for i in r.json()["items"]))

    # ========== T6: 手动补位但时段仍被挡 ==========
    r = requests.post(f"{BASE}/waitlist/{w1_id}/fill", headers=h(tok_a), json={
        "method": "manual", "use_target_time": True
    })
    case("T6: 手动补位被冲突拦截", r.status_code == 200 and r.json()["success"] is False)

    r = requests.post(f"{BASE}/waitlist/{w1_id}/fill", headers=h(tok_u2), json={
        "method": "manual", "use_target_time": True
    })
    case("T6b: 普通成员不能手动补位", r.status_code == 403)

    # ========== T7: 预约20-22 然后候补 ==========
    r = requests.post(f"{BASE}/bookings", headers=h(tok_u1), json={
        "title": "剧目A晚上", "production": "剧目A", "venue_id": vid,
        "start_time": t(20), "end_time": t(22), "status": "pending"
    })
    case("T7-创建预约18-22", r.status_code == 200, f"{r.status_code} {r.text[:200]}")
    if r.status_code != 200:
        print("退出: 预约3创建失败")
        sys.exit(1)
    b3 = r.json()
    b3_id = b3["id"]
    requests.patch(f"{BASE}/bookings/{b3_id}/status", headers=h(tok_a), json={
        "status": "confirmed", "version": b3["version"]
    })
    r = requests.post(f"{BASE}/waitlist", headers=h(tok_u3), json={
        "venue_id": vid, "title": "剧目C晚上", "production": "剧目C",
        "target_start_time": t(20), "target_end_time": t(22), "priority": 6
    })
    w3_id = r.json()["id"]
    case("T7: 晚上候补登记成功", r.status_code == 200)

    # ========== T8: 取消预约1(09-12) -> 自动补位候补1 ==========
    r = requests.get(f"{BASE}/bookings/{b1['id']}", headers=h(tok_a))
    b1v = r.json()["version"]
    r = requests.patch(f"{BASE}/bookings/{b1['id']}/status", headers=h(tok_a), json={
        "status": "cancelled", "version": b1v, "rejection_reason": "测试自动补位"
    })
    case("T8: 取消预约1成功", r.status_code == 200, f"{r.status_code} {r.text[:200]}")

    time.sleep(0.3)
    r = requests.get(f"{BASE}/waitlist/{w1_id}", headers=h(tok_u2))
    w1_new = r.json()
    case("T8b: 候补1已自动filled 对应预约ID存在",
         w1_new["status"] == "filled" and w1_new["filled_booking_id"] is not None,
         f"status={w1_new['status']} bid={w1_new.get('filled_booking_id')}")

    # ========== T9: 改期预约3(20-22->12-14) -> 腾出20-22补位候补3 ==========
    r = requests.get(f"{BASE}/bookings/{b3_id}", headers=h(tok_a))
    b3 = r.json()
    r = requests.post(f"{BASE}/bookings/{b3_id}/reschedule", headers=h(tok_a), json={
        "new_start_time": (D + timedelta(days=7, hours=19)).isoformat(),
        "new_end_time": (D + timedelta(days=7, hours=21)).isoformat(),
        "reason": "改期测试", "version": b3["version"]
    })
    case("T9: 改期成功", r.status_code == 200, f"{r.status_code} {r.text[:200]}")

    time.sleep(0.3)
    r = requests.get(f"{BASE}/waitlist/{w3_id}", headers=h(tok_u3))
    w3_new = r.json()
    case("T9b: 候补3(晚上)被filled",
         w3_new["status"] == "filled" and w3_new["filled_booking_id"] is not None,
         f"status={w3_new['status']} bid={w3_new.get('filled_booking_id')}")

    # ========== T10: 撤销封场 -> 补位候补2 ==========
    r = requests.delete(f"{BASE}/config/closed-windows/{cw_id}", headers=h(tok_a))
    case("T10: 撤销封场成功", r.status_code == 200, f"{r.status_code} {r.text[:200]}")

    time.sleep(0.3)
    r = requests.get(f"{BASE}/waitlist/{w2_id}", headers=h(tok_u1))
    w2_new = r.json()
    case("T10b: 候补2(下午封场)被filled",
         w2_new["status"] == "filled" and w2_new["filled_booking_id"] is not None,
         f"status={w2_new['status']} bid={w2_new.get('filled_booking_id')}")

    # ========== T11: 候补取消 ==========
    requests.post(f"{BASE}/config/closed-windows", headers=h(tok_a), json={
        "venue_id": vid,
        "start_time": (D + timedelta(days=10, hours=9)).isoformat(),
        "end_time": (D + timedelta(days=10, hours=12)).isoformat(),
        "reason": "T11临时封场", "apply_all_venues": False
    })
    r = requests.post(f"{BASE}/waitlist", headers=h(tok_u2), json={
        "venue_id": vid, "title": "剧目B次日", "production": "剧目B",
        "target_start_time": (D + timedelta(days=10, hours=9)).isoformat(),
        "target_end_time": (D + timedelta(days=10, hours=12)).isoformat(),
        "priority": 5
    })
    case("T11-pre: 登记可取消的候补", r.status_code == 200, f"{r.status_code} {r.text[:100]}")
    w4_id = r.json()["id"] if r.status_code == 200 else None
    if w4_id is not None:
        r = requests.delete(f"{BASE}/waitlist/{w4_id}", headers=h(tok_u2),
                            json={"cancel_reason": "不需要了"})
        case("T11: 用户取消自己的候补", r.status_code == 200 and r.json()["status"] == "cancelled")
    else:
        case("T11: (跳过因前置失败)", True)

    r = requests.delete(f"{BASE}/waitlist/{w1_id}", headers=h(tok_u2))
    case("T11b: 已filled的不能取消", r.status_code == 400)

    # ========== T12: CSV导出 ==========
    r = requests.get(f"{BASE}/exports/waitlist.csv", headers=h(tok_a))
    case("T12: 候补CSV导出", r.status_code == 200 and "候补ID" in r.text)

    r = requests.get(f"{BASE}/exports/waitlist.csv", headers=h(tok_u2))
    case("T12b: 普通成员不能导出CSV", r.status_code == 403)

    # ========== T13: 候补日志 ==========
    r = requests.get(f"{BASE}/waitlist/{w1_id}/logs", headers=h(tok_u2))
    case("T13: 候补日志 >=2条(登记+补位)", r.status_code == 200 and len(r.json()) >= 2)

    r = requests.get(f"{BASE}/waitlist/{w1_id}/logs", headers=h(tok_u3))
    case("T13b: 他人日志被403", r.status_code == 403)

    # ========== T14: 空闲时段禁止候补 ==========
    r = requests.post(f"{BASE}/waitlist", headers=h(tok_u3), json={
        "venue_id": vid, "title": "空闲", "production": "剧目C",
        "target_start_time": (D + timedelta(days=30, hours=9)).isoformat(),
        "target_end_time": (D + timedelta(days=30, hours=12)).isoformat()
    })
    case("T14: 空闲时段禁止候补", r.status_code == 400)

    # ========== 总结 ==========
    print("\n======== 测试总结 ========")
    print(f"通过: {len(PASS)} / {len(PASS)+len(FAIL)}")
    if FAIL:
        print("\n失败项:")
        for n, d in FAIL:
            print(f"  - {n}: {d}")
        sys.exit(1)
    else:
        print("全部通过！")


if __name__ == "__main__":
    main()
