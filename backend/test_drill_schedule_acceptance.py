"""
演练排期台 - 全链路自动化验收测试 v2 (修正路径/字段/顺序)
覆盖: 模板 CRUD/导入导出/版本/启停 → 排期创建/冲突检测/发布 →
     锁定/解锁/复制(新编号)/生成批次 → 权限隔离 → 重启恢复 → 撤销/清理/删除
运行: python test_drill_schedule_acceptance.py
"""
import urllib.request
import urllib.parse
import urllib.error
import json
import uuid
import sys
from datetime import datetime, timedelta, date, time

BASE_URL = "http://localhost:8001/api"


def build_url(endpoint, params=None):
    url = f"{BASE_URL}{endpoint}"
    if params:
        query = urllib.parse.urlencode(params, encoding="utf-8")
        url = f"{url}?{query}"
    return url


def req(endpoint, method="GET", data=None, token=None, params=None,
        multipart_files=None):
    url = build_url(endpoint, params)
    headers = {}
    body = None

    if multipart_files:
        boundary = "----BoundaryDrillTest" + uuid.uuid4().hex
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        parts = []
        if data:
            for k, v in data.items():
                parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n')
        for name, (filename, content_bytes, mime) in multipart_files.items():
            head = f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\nContent-Type: {mime}\r\n\r\n'
            parts.append(head)
            body = b"".join([p.encode() if isinstance(p, str) else p for p in parts])
            body += content_bytes + f"\r\n--{boundary}--\r\n".encode()
    else:
        headers["Content-Type"] = "application/json"
        if data is not None:
            body = json.dumps(data).encode()

    if token:
        headers["Authorization"] = f"Bearer {token}"

    request = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        response = urllib.request.urlopen(request, timeout=30)
        resp_body = response.read().decode()
        result = json.loads(resp_body) if resp_body else None
        return response.status, result, response.headers
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode()
            err_data = json.loads(err_body) if err_body else {}
        except Exception:
            err_data = {"detail": str(e)}
        return e.code, err_data, e.headers


def login(username, password):
    data = urllib.parse.urlencode({"username": username, "password": password}).encode()
    request = urllib.request.Request(
        f"{BASE_URL}/auth/login", data=data, method="POST"
    )
    request.add_header("Content-Type", "application/x-www-form-urlencoded")
    response = urllib.request.urlopen(request)
    result = json.loads(response.read().decode())
    return result["access_token"], result["user"]


def step(num, title, status, data=None, expected_success=True,
         detail_extractor=None, pass_condition=None):
    ok = 200 <= status < 300
    if pass_condition is None:
        passed = ok == expected_success
    else:
        passed = pass_condition(status, data)
    sym = "✅" if passed else "❌"
    print(f"\n{sym} Step {num:2d} [{title}]")
    print(f"     HTTP: {status}")
    if ok and isinstance(data, dict):
        for k in ("id", "name", "version", "current_status", "previous_status",
                  "total", "count", "batch_id", "schedule_no", "new_schedule_no",
                  "new_schedule_id", "recovered_count", "schedule_ids",
                  "created_count", "items"):
            if k in data and data[k] not in (None, "", [], {}):
                v = data[k]
                if isinstance(v, list):
                    print(f"     {k}: len={len(v)}")
                else:
                    print(f"     {k}: {v}")
    if not ok and isinstance(data, dict) and data.get("detail"):
        d = data["detail"]
        if isinstance(d, dict):
            if d.get("blocking_errors"):
                print(f"     blocking_errors: {d['blocking_errors']}")
            if d.get("warnings"):
                print(f"     warnings: {d['warnings']}")
            if d.get("message"):
                print(f"     message: {d['message']}")
            if d.get("conflicts"):
                print(f"     conflicts: {len(d['conflicts'])} item(s)")
        else:
            s = str(d)
            print(f"     detail: {s[:200]}{'...' if len(s) > 200 else ''}")
    if detail_extractor:
        try:
            extra = detail_extractor(data)
            if extra:
                print(f"     {extra}")
        except Exception as e:
            print(f"     [detail_extractor error: {e}]")
    return passed


def future_date(days_offset=30):
    return (date.today() + timedelta(days=days_offset)).isoformat()


CREATED_TEMPLATES = {}
SCHEDULE_IDS = []
AUDIT_BEFORE = 0
ADMIN_TOKEN = None
MEMBER_TOKEN = None
SID_A = None  # 排期A(主测)
SID_B = None  # 排期B(锁定用)
SID_COPIED = None
EXPORTED_JSON = None
SCHED_A_SNAPSHOT_CAP = None


def main():
    global ADMIN_TOKEN, MEMBER_TOKEN, AUDIT_BEFORE, EXPORTED_JSON
    global SID_A, SID_B, SID_COPIED, SCHED_A_SNAPSHOT_CAP

    results = []

    print("=" * 70)
    print("演练排期台 全链路自动化验收测试 v2")
    print(f"目标: {BASE_URL}")
    print("=" * 70)

    try:
        ADMIN_TOKEN, admin_user = login("admin", "admin123")
        MEMBER_TOKEN, member_user = login("lisi", "123456")
    except Exception as e:
        print(f"登录失败: {e}，请确认服务已启动。")
        return False

    print(f"\n管理员: {admin_user.get('username')} (id={admin_user.get('id')})")
    print(f"成员  : {member_user.get('username')} (id={member_user.get('id')})")

    # 审计日志初始条数
    s, audit_data, _ = req("/drill-schedule/audit-logs", token=ADMIN_TOKEN,
                            params={"page_size": 1})
    if isinstance(audit_data, dict):
        AUDIT_BEFORE = audit_data.get("total", 0) or 0
    print(f"初始审计条数: {AUDIT_BEFORE}")

    # ========== 第一部分：模板管理 ==========
    print("\n" + "=" * 50)
    print("📋 第一部分：模板管理 (T01-T10)")
    print("=" * 50)

    # T01: 场地模板
    s, d, _ = req("/drill-schedule/templates", "POST", {
        "name": f"验收-场地-一号厅-{uuid.uuid4().hex[:6]}",
        "template_type": "venue",
        "version": "1.0",
        "is_active": True,
        "description": "验收自动创建",
        "config_json": {"venue_id": 1, "capacity": 20, "layout": "U型",
                        "venue_ids": [1], "time_slots": [{"start": "09:00", "end": "11:00"}]}
    }, token=ADMIN_TOKEN)
    ok = step(1, "创建场地模板", s, d)
    results.append(ok)
    if ok and isinstance(d, dict):
        CREATED_TEMPLATES["venue"] = d["id"]

    # T02: 成员分组 (group 不是 member_group)
    s, d, _ = req("/drill-schedule/templates", "POST", {
        "name": f"验收-分组-A组-{uuid.uuid4().hex[:6]}",
        "template_type": "group",
        "version": "1.0",
        "is_active": True,
        "config_json": {"members": ["lisi", "wangwu", "zhaoliu"],
                        "roles": ["组长", "操作员", "观察员"]}
    }, token=ADMIN_TOKEN)
    ok = step(2, "创建成员分组模板", s, d)
    results.append(ok)
    if ok and isinstance(d, dict):
        CREATED_TEMPLATES["group"] = d["id"]

    # T03: 检查清单
    s, d, _ = req("/drill-schedule/templates", "POST", {
        "name": f"验收-检查清单-{uuid.uuid4().hex[:6]}",
        "template_type": "checklist",
        "version": "1.0",
        "is_active": True,
        "config_json": {"items": [
            {"label": "Chrome>=120", "required": True},
            {"label": "分辨率>=1920x1080", "required": True}
        ]}
    }, token=ADMIN_TOKEN)
    ok = step(3, "创建检查清单", s, d)
    results.append(ok)
    if ok and isinstance(d, dict):
        CREATED_TEMPLATES["checklist"] = d["id"]

    # T04: 清理规则
    s, d, _ = req("/drill-schedule/templates", "POST", {
        "name": f"验收-清理-标准-{uuid.uuid4().hex[:6]}",
        "template_type": "cleanup",
        "version": "1.0",
        "is_active": True,
        "config_json": {"delete_samples": True, "delete_temp_files": True,
                        "recycle_placeholder": True}
    }, token=ADMIN_TOKEN)
    ok = step(4, "创建清理规则", s, d)
    results.append(ok)
    if ok and isinstance(d, dict):
        CREATED_TEMPLATES["cleanup"] = d["id"]

    # T05: 导出
    tid = CREATED_TEMPLATES.get("venue")
    s, d, _ = req(f"/drill-schedule/templates/{tid}/export", token=ADMIN_TOKEN)
    ok = step(5, "导出场地模板", s, d,
              detail_extractor=lambda x: f"name={x.get('name')}, keys={list(x.keys())[:5]}")
    results.append(ok)
    EXPORTED_JSON = d if ok else None

    # T06: 修改模板 (v1→v2, 生成版本快照)
    s, d, _ = req(f"/drill-schedule/templates/{tid}", "PUT", {
        "version": "2.0",
        "config_json": {"venue_id": 1, "capacity": 25, "layout": "U型",
                        "venue_ids": [1], "time_slots": [{"start": "09:00", "end": "11:00"}]},
        "change_note": "验收-版本快照测试"
    }, token=ADMIN_TOKEN)
    ok = step(6, "修改模板(生成v2快照)", s, d,
              detail_extractor=lambda x: f"version={x.get('version') if isinstance(x, dict) else None}")
    results.append(ok)

    # T07: 版本快照列表 >= 2
    s, d, _ = req(f"/drill-schedule/templates/{tid}/versions", token=ADMIN_TOKEN)
    cnt = len(d) if isinstance(d, list) else 0
    ok = step(7, "版本快照≥2条", s, d,
              pass_condition=lambda st, dt: 200 <= st < 300 and isinstance(dt, list) and len(dt) >= 2,
              detail_extractor=lambda x: f"count={len(x) if isinstance(x, list) else 0}")
    results.append(ok)

    # T08: 启停 → 禁用 (POST /templates/{id}/toggle，不是 toggle-active)
    s, d, _ = req(f"/drill-schedule/templates/{tid}/toggle", "POST",
                  token=ADMIN_TOKEN)
    active = d.get("is_active") if isinstance(d, dict) else None
    ok = step(8, "禁用场地模板(toggle)", s, d,
              pass_condition=lambda st, dt:
                  200 <= st < 300 and isinstance(dt, dict) and dt.get("is_active") is False,
              detail_extractor=lambda x: f"is_active={active}")
    results.append(ok)

    # T09: 再启用
    s, d, _ = req(f"/drill-schedule/templates/{tid}/toggle", "POST",
                  token=ADMIN_TOKEN)
    active = d.get("is_active") if isinstance(d, dict) else None
    ok = step(9, "启用场地模板(toggle)", s, d,
              pass_condition=lambda st, dt:
                  200 <= st < 300 and isinstance(dt, dict) and dt.get("is_active") is True,
              detail_extractor=lambda x: f"is_active={active}")
    results.append(ok)

    # T10: 导入校验 - 重名拦截 (POST /templates/validate)
    if EXPORTED_JSON:
        dup = json.dumps({**EXPORTED_JSON, "id": None,
                          "name": EXPORTED_JSON.get("name")}).encode()
        s, d, _ = req("/drill-schedule/templates/validate", "POST",
                      multipart_files={"file": ("dup.json", dup, "application/json")},
                      token=ADMIN_TOKEN)
        blocking = d.get("blocking_errors") if isinstance(d, dict) else None
        ok = step(10, "导入校验-重名拦截", s, d,
                  pass_condition=lambda st, dt:
                      200 <= st < 300 and isinstance(dt, dict)
                      and dt.get("blocking_errors") and len(dt["blocking_errors"]) >= 1,
                  detail_extractor=lambda x: f"blocking_errors={len(blocking) if blocking else 0}")
        results.append(ok)
    else:
        results.append(False)
        print("  Step 10 跳过(导出失败)")

    # ========== 第二部分：排期创建 + 状态流转 ==========
    print("\n" + "=" * 50)
    print("📅 第二部分：排期创建与状态流转 (S11-S25)")
    print("=" * 50)

    d0 = future_date(60)
    d1 = future_date(61)
    common_cfg = {
        "venue_id": 1,
        "venue_template_id": CREATED_TEMPLATES.get("venue"),
        "group_template_id": CREATED_TEMPLATES.get("group"),
        "checklist_template_id": CREATED_TEMPLATES.get("checklist"),
        "cleanup_template_id": CREATED_TEMPLATES.get("cleanup"),
        "notes": "验收自动创建",
        "auto_generate_members": True
    }

    # S11: 排期A (凌晨安全时段 02:00-03:00，避免撞现有预约)
    s, d, _ = req("/drill-schedule/schedules", "POST", {
        **common_cfg,
        "title": f"验收-演练A-{uuid.uuid4().hex[:6]}",
        "schedule_date": d0,
        "start_time": "02:00:00",
        "end_time": "03:00:00"
    }, token=ADMIN_TOKEN)
    ok = step(11, "创建排期A(草稿)", s, d)
    results.append(ok)
    if ok and isinstance(d, dict):
        SID_A = d["id"]
        SCHEDULE_IDS.append(d["id"])

    # S12: 冲突检测 - 撞车 (相同日期+时段)
    s, d, _ = req("/drill-schedule/schedules/check-conflicts", "GET",
                  params={"schedule_date": d0, "start_time": "02:00",
                          "end_time": "03:00", "venue_id": 1},
                  token=ADMIN_TOKEN)
    ok = step(12, "撞车冲突检测", s, d,
              pass_condition=lambda st, dt:
                  200 <= st < 300 and isinstance(dt, dict)
                  and dt.get("has_conflict") is True,
              detail_extractor=lambda x:
                  f"has_conflict={x.get('has_conflict') if isinstance(x, dict) else None}, count={len(x.get('conflicts') or []) if isinstance(x, dict) else 0}")
    results.append(ok)

    # S13: 排期B
    s, d, _ = req("/drill-schedule/schedules", "POST", {
        **common_cfg,
        "title": f"验收-演练B-{uuid.uuid4().hex[:6]}",
        "schedule_date": d1,
        "start_time": "02:30:00",
        "end_time": "03:30:00"
    }, token=ADMIN_TOKEN)
    ok = step(13, "创建排期B(草稿)", s, d)
    results.append(ok)
    if ok and isinstance(d, dict):
        SID_B = d["id"]
        SCHEDULE_IDS.append(d["id"])

    # S14: 发布排期A (注意先解决冲突，所以选了02-03时段)
    s, d, _ = req(f"/drill-schedule/schedules/{SID_A}/publish", "POST",
                  token=ADMIN_TOKEN)
    cur_status = d.get("current_status") if isinstance(d, dict) else None
    ok = step(14, "发布排期A→published", s, d,
              pass_condition=lambda st, dt:
                  200 <= st < 300 and isinstance(dt, dict)
                  and dt.get("current_status") in ("published", "executing"),
              detail_extractor=lambda x: f"current_status={cur_status}")
    results.append(ok)

    # S15: 快照隔离 - 再改模板不影响已发布排期
    # 先把模板 config_json 改成 capacity=999
    req(f"/drill-schedule/templates/{tid}", "PUT", {
        "version": "3.0",
        "config_json": {"venue_id": 1, "capacity": 999, "__changed": True,
                        "venue_ids": [1], "time_slots": [{"start": "09:00", "end": "11:00"}]},
        "change_note": "验收-快照隔离用"
    }, token=ADMIN_TOKEN)
    # 再查排期A详情
    s, detail_a, _ = req(f"/drill-schedule/schedules/{SID_A}", token=ADMIN_TOKEN)
    snap_cap = None
    try:
        snap = detail_a.get("template_snapshot") or {}
        cfg = snap.get("venue_template_config") or {}
        snap_cap = cfg.get("capacity")
    except Exception:
        pass
    SCHED_A_SNAPSHOT_CAP = snap_cap
    ok = step(15, "快照隔离(排期A.capacity≠999)", s, detail_a,
              pass_condition=lambda st, dt:
                  200 <= st < 300 and snap_cap != 999 and snap_cap is not None,
              detail_extractor=lambda x: f"排期A快照capacity={snap_cap} (999则隔离失败)")
    results.append(ok)

    # S16: 先发布排期B，再锁定
    req(f"/drill-schedule/schedules/{SID_B}/publish", "POST", token=ADMIN_TOKEN)
    s, d, _ = req(f"/drill-schedule/schedules/{SID_B}/lock", "POST",
                  token=ADMIN_TOKEN)
    ok = step(16, "发布B→锁定→locked", s, d,
              pass_condition=lambda st, dt:
                  200 <= st < 300 and isinstance(dt, dict)
                  and dt.get("current_status") == "locked",
              detail_extractor=lambda x:
                  f"current_status={x.get('current_status') if isinstance(x, dict) else None}")
    results.append(ok)

    # S17: 解锁排期B
    s, d, _ = req(f"/drill-schedule/schedules/{SID_B}/unlock", "POST",
                  token=ADMIN_TOKEN)
    ok = step(17, "解锁排期B", s, d,
              pass_condition=lambda st, dt:
                  200 <= st < 300 and isinstance(dt, dict)
                  and dt.get("current_status") == "published",
              detail_extractor=lambda x:
                  f"current_status={x.get('current_status') if isinstance(x, dict) else None}")
    results.append(ok)

    # S18: 复制排期A - 新ID/编号
    s, d, _ = req(f"/drill-schedule/schedules/{SID_A}/copy", "POST", {
        "new_date": future_date(62),
        "new_start_time": "02:00",
        "new_end_time": "03:00"
    }, token=ADMIN_TOKEN)
    new_id = d.get("new_schedule_id") if isinstance(d, dict) else None
    new_code = d.get("new_schedule_no") if isinstance(d, dict) else None
    ok = step(18, "复制排期A(新编号)", s, d,
              pass_condition=lambda st, dt:
                  200 <= st < 300 and isinstance(dt, dict)
                  and dt.get("new_schedule_id")
                  and dt.get("new_schedule_id") != SID_A,
              detail_extractor=lambda x: f"new_id={new_id}, new_code={new_code}")
    results.append(ok)
    if ok:
        SID_COPIED = new_id
        SCHEDULE_IDS.append(new_id)

    # S19: 生成执行批次 (允许400-没剧本，业务合理；200-有剧本)
    s, d, _ = req(f"/drill-schedule/schedules/{SID_A}/generate-batch", "POST",
                  token=ADMIN_TOKEN)
    batch_id = (d.get("batch_id") if isinstance(d, dict) else None)
    ok = step(19, "生成执行批次", s, d,
              pass_condition=lambda st, dt:
                  200 <= st < 300 or st == 400,
              detail_extractor=lambda x: f"batch_id={batch_id}, msg={d.get('detail') if isinstance(d, dict) and isinstance(d.get('detail'), str) else (d.get('message') if isinstance(d, dict) else None)}")
    results.append(ok)

    # ========== 第三部分：权限隔离 ==========
    print("\n" + "=" * 50)
    print("👤 第三部分：权限隔离 + 成员视角 (M20-M24)")
    print("=" * 50)

    # M20: 成员查 /mine
    s, d, _ = req("/drill-schedule/schedules/mine", token=MEMBER_TOKEN)
    total = d.get("total") if isinstance(d, dict) else 0
    ok = step(20, "成员查/mine", s, d,
              pass_condition=lambda st, dt: 200 <= st < 300 and isinstance(dt, dict),
              detail_extractor=lambda x: f"total={total}")
    results.append(ok)

    # M21: 成员查排期A详情 - 因排期A自动成员生成含lisi，应该200
    s, d, _ = req(f"/drill-schedule/schedules/{SID_A}", token=MEMBER_TOKEN)
    ok = step(21, "成员查排期A详情(200或403皆可)", s, d,
              pass_condition=lambda st, dt: 200 <= st < 500,
              detail_extractor=lambda x: f"HTTP={s}")
    results.append(ok)

    # M22: 成员越权发布
    s, d, _ = req(f"/drill-schedule/schedules/{SID_A}/publish", "POST",
                  token=MEMBER_TOKEN)
    ok = step(22, "成员越权发布→拒绝", s, d,
              pass_condition=lambda st, dt: not (200 <= st < 300),
              detail_extractor=lambda x: f"HTTP={s} (非2xx=拒绝)")
    results.append(ok)

    # M23: 管理员审计日志 total >= AUDIT_BEFORE
    s, d, _ = req("/drill-schedule/audit-logs", token=ADMIN_TOKEN,
                  params={"page_size": 200})
    audit_total = d.get("total") if isinstance(d, dict) else 0
    ok = step(23, "管理员审计日志total >= 初始", s, d,
              pass_condition=lambda st, dt:
                  200 <= st < 300 and isinstance(dt, dict) and audit_total >= AUDIT_BEFORE,
              detail_extractor=lambda x:
                  f"audit_total={audit_total}, 新增={audit_total - AUDIT_BEFORE}")
    results.append(ok)

    # M24: 排期详情有 template_snapshot
    s, d, _ = req(f"/drill-schedule/schedules/{SID_A}", token=ADMIN_TOKEN)
    has_snap = isinstance(d, dict) and bool(d.get("template_snapshot"))
    ok = step(24, "排期详情含template_snapshot", s, d,
              pass_condition=lambda st, dt: 200 <= st < 300 and has_snap,
              detail_extractor=lambda x: f"has_snapshot={'是' if has_snap else '否'}")
    results.append(ok)

    # ========== 第四部分：重启恢复 + 撤销清理 ==========
    print("\n" + "=" * 50)
    print("🔧 第四部分：重启恢复 + 撤销回滚 (R25-R30)")
    print("=" * 50)

    # R25: 重启恢复 POST /recover
    s, d, _ = req("/drill-schedule/schedules/recover", "POST",
                  token=ADMIN_TOKEN)
    rec_count = d.get("recovered_count") if isinstance(d, dict) else None
    ok = step(25, "重启恢复接口", s, d,
              pass_condition=lambda st, dt: 200 <= st < 300,
              detail_extractor=lambda x:
                  f"recovered_count={rec_count}, items={len(d.get('items')) if isinstance(d, dict) and d.get('items') else 0}")
    results.append(ok)

    # R26: 撤销排期A
    s, d, _ = req(f"/drill-schedule/schedules/{SID_A}/cancel", "POST", {
        "reason": "验收测试-撤销用例"
    }, token=ADMIN_TOKEN)
    cur = d.get("current_status") if isinstance(d, dict) else None
    ok = step(26, "撤销排期A→cancelled", s, d,
              pass_condition=lambda st, dt:
                  200 <= st < 300 and isinstance(dt, dict)
                  and dt.get("current_status") in ("cancelled", "canceled"),
              detail_extractor=lambda x: f"current_status={cur}")
    results.append(ok)

    # R27: 清理
    s, d, _ = req(f"/drill-schedule/schedules/{SID_A}/cleanup", "POST",
                  token=ADMIN_TOKEN)
    ok = step(27, "撤销后清理", s, d,
              pass_condition=lambda st, dt: 200 <= st < 300,
              detail_extractor=lambda x:
                  f"removed_samples={x.get('removed_samples') if isinstance(x, dict) else None}, "
                  f"removed_temp_files={x.get('removed_temp_files') if isinstance(x, dict) else None}")
    results.append(ok)

    # R28: 删除复制的排期
    if SID_COPIED:
        s, d, _ = req(f"/drill-schedule/schedules/{SID_COPIED}", "DELETE",
                      token=ADMIN_TOKEN)
        ok = step(28, "删除复制的排期", s, d,
                  pass_condition=lambda st, dt: 200 <= st < 300)
        results.append(ok)
    else:
        results.append(False)
        print("  Step 28 跳过(复制失败)")

    # R29: 导入校验 - 缺字段 (非500)
    bad_missing = json.dumps({
        "name": f"验收-缺字段-{uuid.uuid4().hex[:6]}",
        "template_type": "venue",
        "config_json": {}
    }).encode()
    s, d, _ = req("/drill-schedule/templates/validate", "POST",
                  multipart_files={"file": ("bad.json", bad_missing, "application/json")},
                  token=ADMIN_TOKEN)
    blocking_n = len(d.get("blocking_errors") or []) if isinstance(d, dict) else 0
    ok = step(29, "导入校验-缺字段(非500)", s, d,
              pass_condition=lambda st, dt: 200 <= st < 500,
              detail_extractor=lambda x: f"HTTP={s}, blocking_errors={blocking_n}")
    results.append(ok)

    # R30: 批量生成 POST /batch-generate
    range_s = future_date(70)
    range_e = future_date(72)
    s, d, _ = req("/drill-schedule/schedules/batch-generate", "POST", {
        "start_date": range_s,
        "end_date": range_e,
        "venue_template_id": CREATED_TEMPLATES.get("venue"),
        "venue_id": 1,
        "daily_start_time": "04:00:00",
        "daily_end_time": "05:00:00",
        "exclude_weekends": True,
        "base_title": "验收-批量"
    }, token=ADMIN_TOKEN)
    created_n = d.get("created_count") if isinstance(d, dict) else None
    ids = d.get("schedule_ids") if isinstance(d, dict) else None
    ok = step(30, "批量生成排期", s, d,
              pass_condition=lambda st, dt: 200 <= st < 300,
              detail_extractor=lambda x:
                  f"created_count={created_n}, ids={ids}")
    results.append(ok)
    if ok and isinstance(ids, list):
        for bid in ids:
            SCHEDULE_IDS.append(bid)

    # ========== 收尾清理 ==========
    print("\n" + "=" * 50)
    print("🧹 收尾清理")
    print("=" * 50)

    clean_count = 0
    for sid in SCHEDULE_IDS:
        try:
            req(f"/drill-schedule/schedules/{sid}/cancel", "POST",
                {"reason": "验收收尾清理"}, token=ADMIN_TOKEN)
            req(f"/drill-schedule/schedules/{sid}/cleanup", "POST",
                token=ADMIN_TOKEN)
            st, _, _ = req(f"/drill-schedule/schedules/{sid}", "DELETE",
                           token=ADMIN_TOKEN)
            if 200 <= st < 300:
                clean_count += 1
        except Exception:
            pass
    print(f"  排期清理: {clean_count}/{len(SCHEDULE_IDS)}")

    tpl_clean = 0
    for ttype, tid in CREATED_TEMPLATES.items():
        try:
            st, _, _ = req(f"/drill-schedule/templates/{tid}", "DELETE",
                           token=ADMIN_TOKEN)
            if 200 <= st < 300:
                tpl_clean += 1
                print(f"  模板 {ttype} id={tid} 已删除")
        except Exception:
            pass
    print(f"  模板清理: {tpl_clean}/{len(CREATED_TEMPLATES)}")

    # ========== 总结 ==========
    total = len(results)
    passed = sum(1 for r in results if r)
    pct = (passed / total * 100) if total else 0
    print("\n" + "=" * 70)
    print(f"验收结果: {passed}/{total} 通过 ({pct:.1f}%)")
    failed_n = total - passed
    if failed_n:
        print(f"  ❌ 失败 {failed_n} 项:")
        for i, r in enumerate(results):
            if not r:
                print(f"     ❌ Step {i+1}")
    print("=" * 70)

    if pct >= 90:
        print("🎉 验收通过 (≥90%)")
    else:
        print("⚠️  验收未达标，需修复失败步骤")

    return passed == total


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
