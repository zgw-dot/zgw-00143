import requests
import json
import time
from datetime import datetime, timedelta

BASE = "http://127.0.0.1:8001/api"


def p(title, data=None, ok=True):
    mark = "✅" if ok else "❌"
    print(f"\n{mark} === {title} ===")
    if data is not None:
        if isinstance(data, dict) and "access_token" in data:
            d = {k: v for k, v in data.items() if k != "access_token"}
            print(json.dumps(d, ensure_ascii=False, indent=2))
        else:
            try:
                print(json.dumps(data, ensure_ascii=False, indent=2))
            except Exception:
                print(str(data))


def login(username, password):
    role = "admin" if username == "admin" else "member"
    reg = requests.post(f"{BASE}/auth/register", json={
        "username": username, "password": password,
        "full_name": f"用户{username}",
        "role": role
    })
    r = requests.post(f"{BASE}/auth/login", data={"username": username, "password": password})
    if r.status_code != 200:
        print(f"登录失败 {r.status_code}: {r.text}")
        return None
    return r.json()


def headers(tok):
    return {"Authorization": f"Bearer {tok}"}


def ensure_data(tok_admin):
    r = requests.get(f"{BASE}/venues", headers=headers(tok_admin))
    venues = r.json()
    v1 = None
    for v in venues:
        if v["name"] == "一号排练厅":
            v1 = v
            break
    if not v1:
        r = requests.post(f"{BASE}/venues", headers=headers(tok_admin), json={
            "name": "一号排练厅", "description": "测试场地", "capacity": 50
        })
        v1 = r.json()
    vid = v1["id"]

    r = requests.get(f"{BASE}/config/open-slots", headers=headers(tok_admin))
    slots = [s for s in r.json() if s["venue_id"] == vid]
    if not slots:
        for day in range(7):
            requests.post(f"{BASE}/config/open-slots", headers=headers(tok_admin), json={
                "venue_id": vid, "day_of_week": day,
                "start_time": "09:00:00", "end_time": "22:00:00"
            })
    return vid


def main():
    print("========== 候补补位回归测试 ==========")
    admin_data = login("admin", "admin123")
    user1_data = login("user1", "user1123")
    user2_data = login("user2", "user2123")
    if not admin_data or not user1_data or not user2_data:
        print("登录失败")
        return
    tok_a = admin_data["access_token"]
    tok_u1 = user1_data["access_token"]
    tok_u2 = user2_data["access_token"]
    p("管理员登录", admin_data)
    p("用户1登录", user1_data)
    p("用户2登录", user2_data)

    vid = ensure_data(tok_a)
    p(f"测试场地ID: {vid}")

    t_base = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=10)
    t09 = (t_base + timedelta(hours=9)).isoformat()
    t12 = (t_base + timedelta(hours=12)).isoformat()
    t14 = (t_base + timedelta(hours=14)).isoformat()
    t17 = (t_base + timedelta(hours=17)).isoformat()
    t18 = (t_base + timedelta(hours=18)).isoformat()
    t21 = (t_base + timedelta(hours=21)).isoformat()

    # ======= 步骤1: 用户1创建预约 09-12 =======
    p("步骤1: 用户1创建预约 (09:00-12:00) 状态 pending")
    r = requests.post(f"{BASE}/bookings", headers=headers(tok_u1), json={
        "title": "剧目A上午排练", "production": "剧目A",
        "venue_id": vid, "start_time": t09, "end_time": t12,
        "status": "pending", "priority": 10
    })
    if r.status_code == 200:
        b1 = r.json()
        p("预约1创建成功", b1)
    else:
        p(f"预约1创建失败 {r.status_code}", r.json(), ok=False)
        return
    b1_id = b1["id"]

    # 管理员确认预约1
    r = requests.patch(f"{BASE}/bookings/{b1_id}/status", headers=headers(tok_a), json={
        "status": "confirmed", "version": b1["version"]
    })
    if r.status_code == 200:
        p("预约1已确认", r.json())
        b1 = r.json()
    else:
        p(f"确认失败 {r.status_code}", r.json(), ok=False)

    # ======= 步骤2: 用户2尝试同时段预约应该失败，然后登记候补 =======
    p("步骤2: 用户2尝试同09-12预约 (应冲突)")
    r = requests.post(f"{BASE}/bookings", headers=headers(tok_u2), json={
        "title": "剧目B上午排练", "production": "剧目B",
        "venue_id": vid, "start_time": t09, "end_time": t12,
        "status": "pending", "priority": 8
    })
    if r.status_code in (400, 409):
        p("预约2冲突被拦截 (正确)", r.json())
    else:
        p("预约2意外通过", r.json(), ok=False)

    p("步骤2b: 用户2登记候补 09-12 (前后浮动60分钟)")
    r = requests.post(f"{BASE}/waitlist", headers=headers(tok_u2), json={
        "venue_id": vid, "title": "剧目B上午候补", "production": "剧目B",
        "target_start_time": t09, "target_end_time": t12,
        "float_before_minutes": 60, "float_after_minutes": 60,
        "notes": "希望上午排练", "priority": 8
    })
    if r.status_code == 200:
        w1 = r.json()
        p("候补1登记成功", w1)
    else:
        p(f"候补1登记失败 {r.status_code}", r.json(), ok=False)
        return
    w1_id = w1["id"]

    # ======= 步骤3: 防重复登记测试 =======
    p("步骤3: 用户2重复登记同时段候补 (应失败)")
    r = requests.post(f"{BASE}/waitlist", headers=headers(tok_u2), json={
        "venue_id": vid, "title": "剧目B重复", "production": "剧目B",
        "target_start_time": t09, "target_end_time": t12,
        "float_before_minutes": 30, "float_after_minutes": 30,
        "priority": 8
    })
    if r.status_code == 409:
        p("重复候补被拦截 (正确)", r.json())
    else:
        p(f"重复候补未拦截 {r.status_code}", r.json(), ok=False)

    # ======= 步骤4: 用户1登记候补 14-17 (封场场景) =======
    p("步骤4: 创建封场窗口 14-17")
    r = requests.post(f"{BASE}/config/closed-windows", headers=headers(tok_a), json={
        "venue_id": vid, "start_time": t14, "end_time": t17,
        "reason": "设备维护", "apply_all_venues": False
    })
    if r.status_code == 200:
        cw1 = r.json()
        p("封场创建成功", cw1)
    else:
        p(f"封场失败 {r.status_code}", r.json(), ok=False)
        cw1 = {"id": None}

    p("步骤4b: 用户1尝试预约14-17 (被封场挡) 登记候补")
    r = requests.post(f"{BASE}/waitlist", headers=headers(tok_u1), json={
        "venue_id": vid, "title": "剧目A下午", "production": "剧目A",
        "target_start_time": t14, "target_end_time": t17,
        "float_before_minutes": 0, "float_after_minutes": 60,
        "notes": "封场撤销请补位", "priority": 12
    })
    if r.status_code == 200:
        w2 = r.json()
        p("候补2(封场)登记成功", w2)
    else:
        p(f"候补2失败 {r.status_code}", r.json(), ok=False)
        w2 = {"id": None}
    w2_id = w2.get("id")

    # ======= 步骤5: 权限 - 用户2看用户1的候补详情 =======
    p("步骤5: 用户2查看用户1的候补详情 (应403)")
    if w2_id:
        r = requests.get(f"{BASE}/waitlist/{w2_id}", headers=headers(tok_u2))
        if r.status_code == 403:
            p("权限拦截成功 (正确)", r.json())
        else:
            p(f"权限未拦截 {r.status_code}", r.json(), ok=False)

    p("步骤5b: 用户2查看自己的候补列表")
    r = requests.get(f"{BASE}/waitlist", headers=headers(tok_u2))
    if r.status_code == 200:
        data = r.json()
        p(f"用户2可见 {data['total']} 条", data)
    else:
        p(f"查询失败 {r.status_code}", r.json(), ok=False)

    p("步骤5c: 管理员查看所有候补")
    r = requests.get(f"{BASE}/waitlist", headers=headers(tok_a), params={"status": "waiting"})
    if r.status_code == 200:
        data = r.json()
        p(f"管理员可见排队中 {data['total']} 条", data)
    else:
        p(f"查询失败 {r.status_code}", r.json(), ok=False)

    # ======= 步骤6: 管理员手动补位 (候补1) - 先测试时段冲突 =======
    p("步骤6: 管理员手动补位候补1 (09-12仍被预约1占 → 应失败)")
    r = requests.post(f"{BASE}/waitlist/{w1_id}/fill", headers=headers(tok_a), json={
        "method": "manual", "notes": "测试冲突", "use_target_time": True
    })
    if r.status_code == 200:
        res = r.json()
        if not res["success"]:
            p("手动补位被冲突拦截 (正确)", res)
        else:
            p("意外补位成功", res, ok=False)
    else:
        p(f"错误 {r.status_code}", r.json(), ok=False)

    # ======= 步骤7: 用户3登记候补 18-21 =======
    user3_data = login("user3", "user3123")
    tok_u3 = user3_data["access_token"]
    p("用户3登录成功")

    p("步骤7: 用户1创建预约 18-21, 用户3登记候补")
    r = requests.post(f"{BASE}/bookings", headers=headers(tok_u1), json={
        "title": "剧目A晚上", "production": "剧目A",
        "venue_id": vid, "start_time": t18, "end_time": t21,
        "status": "pending", "priority": 10
    })
    if r.status_code != 200:
        p(f"预约3创建失败 {r.status_code}", r.json(), ok=False)
        return
    b3 = r.json()
    b3_id = b3["id"]
    r = requests.patch(f"{BASE}/bookings/{b3_id}/status", headers=headers(tok_a), json={
        "status": "confirmed", "version": b3["version"]
    })
    p("预约3(18-21)确认成功")

    r = requests.post(f"{BASE}/waitlist", headers=headers(tok_u3), json={
        "venue_id": vid, "title": "剧目C晚上", "production": "剧目C",
        "target_start_time": t18, "target_end_time": t21,
        "float_before_minutes": 0, "float_after_minutes": 0,
        "priority": 6
    })
    if r.status_code == 200:
        w3 = r.json()
        w3_id = w3["id"]
        p(f"候补3登记成功 ID={w3_id} 排队号={w3['queue_position']}")
    else:
        p(f"候补3失败 {r.status_code}", r.json(), ok=False)
        w3_id = None

    # ======= 步骤8: 取消预约1 → 触发自动补位 =======
    p("步骤8: 取消预约1(09-12) → 触发自动补位候补1")
    r = requests.patch(f"{BASE}/bookings/{b1_id}/status", headers=headers(tok_a), json={
        "status": "cancelled", "version": b1["version"],
        "rejection_reason": "测试自动补位"
    })
    if r.status_code == 200:
        res = r.json()
        p("预约1已取消", {"status": res.get("status"), "auto_fill_results": res.get("auto_fill_results")})
    else:
        p(f"取消失败 {r.status_code}", r.json(), ok=False)

    p("步骤8b: 查询候补1状态 → 应filled")
    r = requests.get(f"{BASE}/waitlist/{w1_id}", headers=headers(tok_u2))
    w1_new = r.json()
    ok = w1_new["status"] == "filled" and w1_new["filled_booking_id"] is not None
    p(f"候补1状态: {w1_new['status']}, 对应预约ID: {w1_new.get('filled_booking_id')}", w1_new, ok=ok)

    # ======= 步骤9: 改期预约3(18→21) 到 09-12 → 腾出晚上触发补位 =======
    p("步骤9: 改期预约3(18-21 → 09-12) → 腾出18-21 自动补位候补3")
    r = requests.get(f"{BASE}/bookings/{b3_id}", headers=headers(tok_a))
    b3 = r.json()
    r = requests.post(f"{BASE}/bookings/{b3_id}/reschedule", headers=headers(tok_a), json={
        "new_start_time": t09, "new_end_time": t12,
        "reason": "改期测试", "version": b3["version"]
    })
    if r.status_code == 200:
        res = r.json()
        p("改期完成", {"status": res.get("status"),
                        "new_start": res.get("start_time"),
                        "new_end": res.get("end_time"),
                        "auto_fill": res.get("auto_fill_results")})
    else:
        p(f"改期失败 {r.status_code}", r.json(), ok=False)

    if w3_id:
        r = requests.get(f"{BASE}/waitlist/{w3_id}", headers=headers(tok_u3))
        w3_new = r.json()
        ok = w3_new["status"] == "filled"
        p(f"候补3状态: {w3_new['status']}, 对应预约ID: {w3_new.get('filled_booking_id')}", w3_new, ok=ok)

    # ======= 步骤10: 撤销封场 → 触发补位候补2 =======
    p("步骤10: 撤销封场(14-17) → 自动补位候补2")
    if cw1.get("id"):
        r = requests.delete(f"{BASE}/config/closed-windows/{cw1['id']}", headers=headers(tok_a))
        if r.status_code == 200:
            res = r.json()
            p("封场已撤销", {"is_revoked": res.get("is_revoked"),
                              "auto_fill": res.get("auto_fill_results")})
        else:
            p(f"撤销失败 {r.status_code}", r.json(), ok=False)

    if w2_id:
        time.sleep(0.5)
        r = requests.get(f"{BASE}/waitlist/{w2_id}", headers=headers(tok_u1))
        w2_new = r.json()
        ok = w2_new["status"] == "filled"
        p(f"候补2状态: {w2_new['status']}, 对应预约ID: {w2_new.get('filled_booking_id')}", w2_new, ok=ok)

    # ======= 步骤11: 候补取消 =======
    p("步骤11: 用户2新建候补 → 然后取消")
    t22_00 = (t_base + timedelta(days=1, hours=9)).isoformat()
    t22_03 = (t_base + timedelta(days=1, hours=12)).isoformat()
    r = requests.post(f"{BASE}/waitlist", headers=headers(tok_u2), json={
        "venue_id": vid, "title": "剧目B次日", "production": "剧目B",
        "target_start_time": t22_00, "target_end_time": t22_03,
        "priority": 5
    })
    if r.status_code == 200:
        w4 = r.json()
        w4_id = w4["id"]
        r = requests.delete(f"{BASE}/waitlist/{w4_id}", headers=headers(tok_u2),
                            json={"cancel_reason": "不需要了"})
        if r.status_code == 200:
            w4c = r.json()
            ok = w4c["status"] == "cancelled"
            p(f"候补4已取消: {w4c['status']}", w4c, ok=ok)
        else:
            p(f"取消失败 {r.status_code}", r.json(), ok=False)
    else:
        p(f"候补4登记失败 {r.status_code}", r.json(), ok=False)

    # ======= 步骤12: CSV 导出 =======
    p("步骤12: 管理员导出候补CSV")
    r = requests.get(f"{BASE}/exports/waitlist.csv", headers=headers(tok_a))
    if r.status_code == 200 and "候补ID" in r.text:
        lines = r.text.strip().split("\n")
        p(f"CSV导出成功 ({len(lines)} 行, 含表头)")
    else:
        p(f"CSV导出失败 {r.status_code}", r.text[:200], ok=False)

    # ======= 步骤13: 候补日志 =======
    p("步骤13: 查询候补1的日志")
    r = requests.get(f"{BASE}/waitlist/{w1_id}/logs", headers=headers(tok_u2))
    if r.status_code == 200:
        logs = r.json()
        p(f"候补1日志 {len(logs)} 条", logs)
    else:
        p(f"日志查询失败 {r.status_code}", r.json(), ok=False)

    # ======= 步骤14: 普通成员尝试手动补位 (应403) =======
    p("步骤14: 普通成员尝试手动补位 (应403)")
    r = requests.post(f"{BASE}/waitlist/{w1_id}/fill", headers=headers(tok_u2), json={
        "method": "manual", "use_target_time": True
    })
    if r.status_code == 403:
        p("权限拦截成功 (正确)", r.json())
    else:
        p(f"权限未拦截 {r.status_code}", r.json(), ok=False)

    # ======= 步骤15: 时段不冲突时禁止候补 =======
    p("步骤15: 尝试登记空闲时段候补 (应失败)")
    free_s = (t_base + timedelta(days=2, hours=9)).isoformat()
    free_e = (t_base + timedelta(days=2, hours=12)).isoformat()
    r = requests.post(f"{BASE}/waitlist", headers=headers(tok_u2), json={
        "venue_id": vid, "title": "空闲时段", "production": "剧目B",
        "target_start_time": free_s, "target_end_time": free_e
    })
    if r.status_code == 400:
        p("空闲时段禁止候补 (正确)", r.json())
    else:
        p(f"未拦截 {r.status_code}", r.json(), ok=False)

    print("\n========== 测试总结 ==========")
    print("OK - 所有关键步骤执行完毕")


if __name__ == "__main__":
    main()
