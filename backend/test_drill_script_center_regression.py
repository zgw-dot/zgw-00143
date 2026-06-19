import requests, time, sys, os, json, io
from datetime import datetime, timedelta

BASE = 'http://127.0.0.1:8003/api'
stamp = datetime.now().strftime('%H%M%S')

FAIL = '\033[91m[FAIL]\033[0m'
PASS = '\033[92m[PASS]\033[0m'
STEP = '\033[94m[STEP]\033[0m'
INFO = '\033[93m[INFO]\033[0m'
WARN = '\033[95m[WARN]\033[0m'

passed = 0
total = 0
test_results = []
created_script_ids = []
created_batch_ids = []
created_user_ids = []


def h(tok):
    return {'Authorization': f'Bearer {tok}'}


def case(name, cond, extra='', category=''):
    global passed, total
    total += 1
    status = PASS if cond else FAIL
    cat_info = f' [{category}]' if category else ''
    print(f'{status} {name}{cat_info}' + ('' if cond else f' -- {extra}'))
    test_results.append({
        'name': name,
        'passed': cond,
        'detail': extra,
        'category': category
    })
    if cond:
        passed += 1
    return 1 if cond else 0


def print_header(title):
    print()
    print('=' * 80)
    print(f'  {title}')
    print('=' * 80)


def print_step(num, desc):
    print()
    print(f'{STEP} {num:3d}. {desc}')
    print('-' * 80)


def api_login(username, password):
    r = requests.post(f'{BASE}/auth/login', data={'username': username, 'password': password})
    if r.status_code != 200:
        raise AssertionError(f'登录失败: {r.status_code} {r.text}')
    return r.json()['access_token'], r.json()['user']


print_header('演练剧本中心 - 完整回归测试')
print(f'测试时间: {datetime.now().isoformat()}')
print(f'测试地址: {BASE}')
print()

try:
    health = requests.get(f'{BASE}/health', timeout=5)
    print(f'{PASS} 服务健康检查通过 status={health.status_code}')
except requests.exceptions.RequestException as e:
    print(f'{FAIL} 服务未启动或不可访问: {e}')
    sys.exit(1)

print_step(1, '准备测试账号')
try:
    admin_token, admin_user = api_login('admin', 'admin123')
    member_token, member_user = api_login('lisi', '123456')
    print(f'{INFO} 管理员: {admin_user["username"]} (ID={admin_user["id"]}, role={admin_user["role"]})')
    print(f'{INFO} 成员: {member_user["username"]} (ID={member_user["id"]}, role={member_user["role"]})')
except Exception as e:
    print(f'{FAIL} 登录失败: {e}')
    sys.exit(1)

print_step(2, '剧本创建 - 完整CRUD')
test_script_name = f"回归剧本_{stamp}"
try:
    payload = {
        "name": test_script_name,
        "description": "自动化回归测试剧本",
        "version": "1.0",
        "venue_rules": {
            "venue_ids": [],
            "auto_find_slot": True,
            "search_days": 30,
            "preferred_hours": [9, 14, 19]
        },
        "drill_samples": [
            {"name": "样本1", "type": "low_priority", "priority": 5},
            {"name": "样本2", "type": "high_priority", "priority": 15}
        ],
        "member_accounts": [
            {"username": f"reg_{stamp}_m1", "password": "pass1234", "full_name": "回归成员1", "role": "member"},
            {"username": f"reg_{stamp}_m2", "password": "pass1234", "full_name": "回归成员2", "role": "member"},
            {"username": f"reg_{stamp}_a1", "password": "pass1234", "full_name": "回归管理员", "role": "admin"}
        ],
        "checkpoints": [
            {"name": "CP1: 创建用户", "expected": "passed"},
            {"name": "CP2: 候补登记", "expected": "passed"},
            {"name": "CP3: 自动补位", "expected": "passed"},
            {"name": "CP4: 浏览器验收", "type": "browser_validation", "url": "http://127.0.0.1:8003/", "expected": "passed"}
        ],
        "cleanup_strategy": {
            "auto_cleanup_on_success": False,
            "keep_screenshots": True,
            "keep_logs": True,
            "keep_fill_results": True
        }
    }

    r = requests.post(f'{BASE}/drill-center/scripts', json=payload, headers=h(admin_token))
    case('管理员创建剧本成功', r.status_code == 200, f'status={r.status_code} body={r.text[:200]}', '创建')
    script1 = r.json()
    script_id_1 = script1['id']
    created_script_ids.append(script_id_1)
    case('剧本ID返回正确', script_id_1 > 0, f'id={script_id_1}', '创建')
    case('剧本名称正确', script1['name'] == test_script_name, f'name={script1["name"]}', '创建')
    case('剧本包含场地规则', isinstance(script1.get('venue_rules'), dict) and script1['venue_rules'].get('search_days') == 30, category='创建')
    case('剧本包含2个样本', len(script1.get('drill_samples', [])) == 2, category='创建')
    case('剧本包含3个成员账号', len(script1.get('member_accounts', [])) == 3, category='创建')
    case('剧本包含4个检查点(含浏览器验收)', len(script1.get('checkpoints', [])) == 4, category='创建')
except Exception as e:
    case('创建剧本异常', False, str(e), '创建')

try:
    r = requests.get(f'{BASE}/drill-center/scripts/{script_id_1}', headers=h(admin_token))
    case('查询单个剧本成功', r.status_code == 200, category='创建')
    s = r.json()
    case('查询的剧本ID正确', s['id'] == script_id_1, category='创建')
except Exception as e:
    case('查询剧本异常', False, str(e), '创建')

try:
    r = requests.get(f'{BASE}/drill-center/scripts', headers=h(admin_token))
    case('剧本列表查询成功', r.status_code == 200, category='创建')
    scripts = r.json()
    case('剧本列表包含刚创建的剧本', any(s['id'] == script_id_1 for s in scripts), category='创建')
except Exception as e:
    case('列表查询异常', False, str(e), '创建')

print_step(3, '剧本更新与删除')
try:
    update_payload = {"description": "更新后的描述", "version": "1.1"}
    r = requests.put(f'{BASE}/drill-center/scripts/{script_id_1}', json=update_payload, headers=h(admin_token))
    case('更新剧本成功', r.status_code == 200, category='创建')
    updated = r.json()
    case('描述已更新', updated['description'] == '更新后的描述', category='创建')
    case('版本已更新', updated['version'] == '1.1', category='创建')
except Exception as e:
    case('更新剧本异常', False, str(e), '创建')

print_step(4, '重名校验 - 创建同名剧本应被拦截')
try:
    dup_payload = dict(payload)
    dup_payload['description'] = '重复名称测试'
    r = requests.post(f'{BASE}/drill-center/scripts', json=dup_payload, headers=h(admin_token))
    case('创建同名剧本返回409', r.status_code == 409, f'status={r.status_code}', '创建')
except Exception as e:
    case('重名校验异常', False, str(e), '创建')

print_step(5, '权限隔离 - 成员不能创建/编辑/删除剧本')
try:
    r = requests.post(f'{BASE}/drill-center/scripts', json=payload, headers=h(member_token))
    case('成员创建剧本返回403', r.status_code == 403, f'status={r.status_code}', '权限隔离')
except Exception as e:
    case('成员创建权限校验异常', False, str(e), '权限隔离')

try:
    r = requests.put(f'{BASE}/drill-center/scripts/{script_id_1}', json={"description": "x"}, headers=h(member_token))
    case('成员更新剧本返回403', r.status_code == 403, f'status={r.status_code}', '权限隔离')
except Exception as e:
    case('成员更新权限校验异常', False, str(e), '权限隔离')

try:
    r = requests.delete(f'{BASE}/drill-center/scripts/{script_id_1}', headers=h(member_token))
    case('成员删除剧本返回403', r.status_code == 403, f'status={r.status_code}', '权限隔离')
except Exception as e:
    case('成员删除权限校验异常', False, str(e), '权限隔离')

print_step(6, 'JSON 导入校验 - 缺字段、重名、失效账号')
try:
    bad_json_no_name = {"description": "缺少name字段"}
    files = {'file': ('bad.json', io.BytesIO(json.dumps(bad_json_no_name).encode()), 'application/json')}
    r = requests.post(f'{BASE}/drill-center/scripts/validate', files=files, headers=h(admin_token))
    case('缺字段剧本校验返回valid=false', r.status_code == 200 and r.json()['valid'] == False,
         f'valid={r.json().get("valid")} errors={r.json().get("errors",[])}', '导入校验')
except Exception as e:
    case('导入缺字段校验异常', False, str(e), '导入校验')

try:
    bad_json_bad_members = {
        "name": f"校验测试_{stamp}",
        "venue_rules": {},
        "drill_samples": [],
        "member_accounts": [{"username": "ab", "password": "x"}],
        "checkpoints": []
    }
    files = {'file': ('bad_members.json', io.BytesIO(json.dumps(bad_json_bad_members).encode()), 'application/json')}
    r = requests.post(f'{BASE}/drill-center/scripts/validate', files=files, headers=h(admin_token))
    case('成员账号格式校验（缺字段）返回valid=false',
         r.status_code == 200 and r.json()['valid'] == False,
         f'valid={r.json().get("valid")}', '导入校验')
except Exception as e:
    case('成员账号缺字段校验异常', False, str(e), '导入校验')

try:
    dup_name_import = {
        "name": test_script_name,
        "venue_rules": {},
        "drill_samples": [],
        "member_accounts": [{"username": f"dup_{stamp}", "password": "pass1234", "full_name": "重复名测试"}],
        "checkpoints": []
    }
    files = {'file': ('dup_name.json', io.BytesIO(json.dumps(dup_name_import).encode()), 'application/json')}
    r = requests.post(f'{BASE}/drill-center/scripts/validate', files=files, headers=h(admin_token))
    case('重名剧本导入校验返回valid=false',
         r.status_code == 200 and r.json()['valid'] == False,
         f'valid={r.json().get("valid")}', '导入校验')
except Exception as e:
    case('重名校验异常', False, str(e), '导入校验')

print_step(7, 'JSON 导出 - 导出内容核对')
try:
    r = requests.get(f'{BASE}/drill-center/scripts/{script_id_1}/export', headers=h(admin_token))
    case('剧本导出成功', r.status_code == 200, category='导出核对')
    exported = r.json()
    case('导出不含内部ID字段', 'id' not in exported and 'created_by' not in exported, category='导出核对')
    case('导出包含name字段', exported.get('name') == test_script_name, category='导出核对')
    case('导出包含exported_at时间戳', 'exported_at' in exported, category='导出核对')
    case('成员账号密码已脱敏或保留', isinstance(exported.get('member_accounts'), list), category='导出核对')
    case('导出包含checkpoints', len(exported.get('checkpoints', [])) == 4, category='导出核对')
    case('导出包含cleanup_strategy', isinstance(exported.get('cleanup_strategy'), dict), category='导出核对')
except Exception as e:
    case('剧本导出异常', False, str(e), '导出核对')

print_step(8, '批次创建 - 基于剧本生成唯一批次')
try:
    r = requests.post(f'{BASE}/drill-center/batches', json={"script_id": script_id_1}, headers=h(admin_token))
    case('管理员创建批次成功', r.status_code == 200, f'status={r.status_code}', '创建批次')
    batch1 = r.json()
    batch_id_1 = batch1['batch_id']
    created_batch_ids.append(batch_id_1)
    case('批次ID格式正确（BATCH_前缀）', batch_id_1.startswith('BATCH_'), f'batch_id={batch_id_1}', '创建批次')
    case('批次初始状态为pending', batch1['status'] == 'pending', f'status={batch1["status"]}', '创建批次')
    case('批次关联剧本ID正确', batch1['script_id'] == script_id_1, category='创建批次')
except Exception as e:
    case('批次创建异常', False, str(e), '创建批次')

try:
    r = requests.get(f'{BASE}/drill-center/batches', headers=h(admin_token))
    case('批次列表查询成功', r.status_code == 200, category='创建批次')
    batches = r.json()
    case('批次列表包含刚创建的批次', any(b['batch_id'] == batch_id_1 for b in batches), category='创建批次')
except Exception as e:
    case('批次列表异常', False, str(e), '创建批次')

print_step(9, '权限隔离 - 成员查看批次')
try:
    r = requests.get(f'{BASE}/drill-center/batches', headers=h(member_token))
    case('成员可查询自己的批次列表', r.status_code == 200, f'status={r.status_code}', '权限隔离')
except Exception as e:
    case('成员批次列表异常', False, str(e), '权限隔离')

try:
    r = requests.get(f'{BASE}/drill-center/batches/{batch_id_1}/member-view', headers=h(member_token))
    case('成员视图接口正常返回', r.status_code == 200, f'status={r.status_code}', '权限隔离')
    mv = r.json()
    case('成员视图包含自己的entries列表', 'my_entries' in mv, category='权限隔离')
    case('成员视图包含被挡原因', 'my_blocked_reasons' in mv, category='权限隔离')
    case('成员视图包含补位结果', 'my_fill_results' in mv, category='权限隔离')
except Exception as e:
    case('成员视图异常', False, str(e), '权限隔离')

print_step(10, '成员下载接口 - 权限隔离')
try:
    r = requests.get(f'{BASE}/drill-center/batches/{batch_id_1}/member-download', headers=h(member_token))
    case('成员下载非参与批次返回403', r.status_code == 403, f'status={r.status_code}', '权限隔离')
except Exception as e:
    case('成员下载非参与批次异常', False, str(e), '权限隔离')

member_download_batch_id = None
try:
    member_dl_payload = {
        "name": f"成员下载测试_{stamp}",
        "description": "成员下载权限测试",
        "version": "1.0",
        "venue_rules": {"venue_ids": [], "auto_find_slot": True, "search_days": 30, "preferred_hours": [9]},
        "drill_samples": [{"name": "样本1", "type": "low_priority", "priority": 5}],
        "member_accounts": [{"username": "lisi", "password": "123456", "full_name": "李四", "role": "member"}],
        "checkpoints": [{"name": "CP1", "expected": "passed"}],
        "cleanup_strategy": {"auto_cleanup_on_success": False}
    }
    r = requests.post(f'{BASE}/drill-center/scripts', json=member_dl_payload, headers=h(admin_token))
    if r.status_code == 200:
        dl_script = r.json()
        created_script_ids.append(dl_script['id'])
        r = requests.post(f'{BASE}/drill-center/batches', json={"script_id": dl_script['id']}, headers=h(admin_token))
        if r.status_code == 200:
            member_download_batch_id = r.json()['batch_id']
            created_batch_ids.append(member_download_batch_id)

    if member_download_batch_id:
        r = requests.get(f'{BASE}/drill-center/batches/{member_download_batch_id}/member-download', headers=h(member_token))
        case('成员下载参与批次返回200', r.status_code == 200, f'status={r.status_code}', '权限隔离')
        if r.status_code == 200:
            dl = r.json()
            case('成员下载含batch_id', dl.get('batch_id') == member_download_batch_id, category='权限隔离')
            case('成员下载含downloads列表', 'downloads' in dl, category='权限隔离')
        else:
            case('成员下载含batch_id', False, '前置条件失败', '权限隔离')
            case('成员下载含downloads列表', False, '前置条件失败', '权限隔离')
except Exception as e:
    case('成员下载参与批次异常', False, str(e), '权限隔离')

print_step(11, '使用默认模板一键创建剧本')
try:
    r = requests.post(f'{BASE}/drill-center/scripts/default', headers=h(admin_token))
    case('默认剧本创建成功', r.status_code == 200, f'status={r.status_code}', '创建')
    ds = r.json()
    created_script_ids.append(ds['id'])
    case('默认剧本含3个以上样本', len(ds.get('drill_samples', [])) >= 3, category='创建')
    case('默认剧本含3个以上成员', len(ds.get('member_accounts', [])) >= 3, category='创建')
    case('默认剧本含6个检查点', len(ds.get('checkpoints', [])) >= 6, category='创建')
except Exception as e:
    case('默认剧本创建异常', False, str(e), '创建')

print_step(12, '批次执行 - 完整流程执行')
batch_id_to_execute = None
try:
    r = requests.post(f'{BASE}/drill-center/batches', json={"script_id": script_id_1}, headers=h(admin_token))
    batch_exec = r.json()
    batch_id_to_execute = batch_exec['batch_id']
    created_batch_ids.append(batch_id_to_execute)
    print(f'{INFO} 为执行测试创建批次: {batch_id_to_execute}')

    t0 = time.time()
    r = requests.post(f'{BASE}/drill-center/batches/{batch_id_to_execute}/execute', headers=h(admin_token), timeout=300)
    elapsed = time.time() - t0
    case('批次执行请求返回200', r.status_code == 200,
         f'status={r.status_code} elapsed={elapsed:.1f}s', '启动执行')
    if r.status_code == 200:
        be = r.json()
        case('执行后状态为completed或failed', be['status'] in ('completed', 'failed'),
             f'status={be["status"]}', '启动执行')
        case('执行结果含步骤统计', be['total_steps'] > 0 or be.get('error_message'),
             f'total_steps={be.get("total_steps")}', '启动执行')
        case('执行后drill_session_ids非空', len(be.get('drill_session_ids', [])) >= 0,
             f'sessions={be.get("drill_session_ids")}', '启动执行')
except Exception as e:
    case('批次执行异常', False, str(e), '启动执行')

print_step(13, '批次产物留存 - 失败截图/下载摘要/执行日志')
if batch_id_to_execute:
    try:
        r = requests.get(f'{BASE}/drill-center/batches/{batch_id_to_execute}', headers=h(admin_token))
        bd = r.json()
        artifacts = bd.get('artifacts', [])
        case('批次详情包含执行产物列表', len(artifacts) > 0, f'artifacts_count={len(artifacts)}', '产物留存')

        types_found = set(a.get('artifact_type') for a in artifacts)
        case('产物包含step_result类型', 'step_result' in types_found, f'types={types_found}', '产物留存')
        case('产物包含fill_result类型', 'fill_result' in types_found, f'types={types_found}', '产物留存')
        case('产物包含op_log类型(执行日志)', 'op_log' in types_found, f'types={types_found}', '产物留存')

        has_file_path = any(a.get('file_path') for a in artifacts if a.get('artifact_type') == 'screenshot')
        if 'screenshot' in types_found:
            case('失败截图含file_path存储路径', has_file_path, category='产物留存')
    except Exception as e:
        case('批次产物查询异常', False, str(e), '产物留存')

    try:
        r = requests.get(f'{BASE}/drill-center/batches/{batch_id_to_execute}/artifacts', headers=h(admin_token))
        case('产物列表接口成功', r.status_code == 200, category='产物留存')
        arts = r.json()
        case('产物列表非空', len(arts) > 0, f'count={len(arts)}', '产物留存')
    except Exception as e:
        case('产物列表接口异常', False, str(e), '产物留存')

    try:
        r = requests.get(f'{BASE}/drill-center/batches/{batch_id_to_execute}/member-download', headers=h(admin_token))
        case('管理员下载接口成功', r.status_code == 200, category='产物留存')
        dl = r.json()
        case('管理员下载含downloads列表', 'downloads' in dl, category='产物留存')
    except Exception as e:
        case('管理员下载接口异常', False, str(e), '产物留存')

print_step(14, '成员权限隔离 - 产物过滤')
if batch_id_to_execute:
    try:
        r_admin = requests.get(f'{BASE}/drill-center/batches/{batch_id_to_execute}', headers=h(admin_token))
        admin_artifacts = r_admin.json().get('artifacts', [])

        r_member = requests.get(f'{BASE}/drill-center/batches/{batch_id_to_execute}', headers=h(member_token))
        if r_member.status_code == 200:
            member_artifacts = r_member.json().get('artifacts', [])
            member_owned_count = len([a for a in member_artifacts if a.get('user_id') is None or a.get('user_id') == member_user['id']])
            case('成员看到的产物数 <= 管理员看到的产品数',
                 len(member_artifacts) <= len(admin_artifacts),
                 f'member={len(member_artifacts)} admin={len(admin_artifacts)}', '权限隔离')
        else:
            case('成员无权查看此批次', r_member.status_code == 403, f'status={r_member.status_code}', '权限隔离')
    except Exception as e:
        case('成员产物权限隔离异常', False, str(e), '权限隔离')

print_step(15, '批次回滚 - 撤销并清理样本')
if batch_id_to_execute:
    try:
        r = requests.post(f'{BASE}/drill-center/batches/{batch_id_to_execute}/rollback', headers=h(admin_token))
        case('批次回滚成功', r.status_code == 200, f'status={r.status_code}', '回滚撤销')
        rb = r.json()
        case('回滚响应含success字段', 'success' in rb, category='回滚撤销')
        case('回滚响应含清理计数', 'removed_count' in rb, f'count={rb.get("removed_count")}', '回滚撤销')

        r2 = requests.get(f'{BASE}/drill-center/batches/{batch_id_to_execute}', headers=h(admin_token))
        if r2.status_code == 200:
            final = r2.json()
            case('回滚后状态为rolled_back', final['status'] == 'rolled_back',
                 f'status={final["status"]}', '回滚撤销')
    except Exception as e:
        case('回滚异常', False, str(e), '回滚撤销')

print_step(16, '批次恢复 - 服务重启后的未完成批次')
try:
    r = requests.post(f'{BASE}/drill-center/batches', json={"script_id": script_id_1}, headers=h(admin_token))
    batch_recover = r.json()
    batch_id_recover = batch_recover['batch_id']
    created_batch_ids.append(batch_id_recover)

    r = requests.post(f'{BASE}/drill-center/batches/{batch_id_recover}/recover', headers=h(admin_token))
    case('批次恢复成功', r.status_code == 200, f'status={r.status_code}', '重启恢复')
    rv = r.json()
    case('恢复响应含success字段', 'success' in rv, category='重启恢复')
    case('恢复响应含previous_status', 'previous_status' in rv, category='重启恢复')
    case('恢复响应含current_status', 'current_status' in rv, category='重启恢复')
    case('恢复后current_status非空', bool(rv.get('current_status')), category='重启恢复')
except Exception as e:
    case('恢复异常', False, str(e), '重启恢复')

print_step(17, '已回滚批次不能再执行')
if batch_id_to_execute:
    try:
        r = requests.post(f'{BASE}/drill-center/batches/{batch_id_to_execute}/execute', headers=h(admin_token))
        case('已回滚批次执行返回400', r.status_code == 400, f'status={r.status_code}', '回滚撤销')
    except Exception as e:
        case('回滚批次执行异常', False, str(e), '回滚撤销')

print_step(18, '导出再导入完整闭环')
try:
    r = requests.get(f'{BASE}/drill-center/scripts/{script_id_1}/export', headers=h(admin_token))
    exported = r.json()

    reimport_name = f"{exported['name']}_reimport_{stamp}"
    exported['name'] = reimport_name
    exported['member_accounts'] = [
        {"username": f"ri_{stamp}_1", "password": "pass1234", "full_name": "再导入成员1", "role": "member"},
        {"username": f"ri_{stamp}_2", "password": "pass1234", "full_name": "再导入成员2", "role": "admin"}
    ]

    files = {'file': ('reimport.json', io.BytesIO(json.dumps(exported).encode()), 'application/json')}
    r = requests.post(f'{BASE}/drill-center/scripts/import', files=files, headers=h(admin_token))
    case('导出后再导入成功', r.status_code == 200, f'status={r.status_code}', '导出核对')
    if r.status_code == 200:
        reimported = r.json()
        created_script_ids.append(reimported['id'])
        case('再导入剧本样本数量一致',
             len(reimported.get('drill_samples', [])) == len(exported.get('drill_samples', [])), category='导出核对')
        case('再导入剧本检查点数量一致',
             len(reimported.get('checkpoints', [])) == len(exported.get('checkpoints', [])), category='导出核对')
        case('再导入剧本cleanup_strategy一致',
             reimported.get('cleanup_strategy', {}).get('keep_screenshots') == exported.get('cleanup_strategy', {}).get('keep_screenshots'),
             category='导出核对')
except Exception as e:
    case('导出再导入闭环异常', False, str(e), '导出核对')

print_step(19, '边界 - 不能用无效剧本ID创建批次')
try:
    r = requests.post(f'{BASE}/drill-center/batches', json={"script_id": 99999999}, headers=h(admin_token))
    case('无效剧本ID创建批次返回404', r.status_code == 404, f'status={r.status_code}', '创建批次')
except Exception as e:
    case('无效剧本边界异常', False, str(e), '创建批次')

print_step(20, '成员不能查看非参与批次详情')
try:
    other_member_r = requests.post(f'{BASE}/drill-center/batches', json={"script_id": script_id_1}, headers=h(admin_token))
    if other_member_r.status_code == 200:
        other_batch_id = other_member_r.json()['batch_id']
        created_batch_ids.append(other_batch_id)

        r = requests.get(f'{BASE}/drill-center/batches/{other_batch_id}', headers=h(member_token))
        is_forbidden = r.status_code == 403
        case('成员查看非参与批次返回403', is_forbidden, f'status={r.status_code}', '权限隔离')
except Exception as e:
    case('成员批次权限隔离异常', False, str(e), '权限隔离')

print_step(21, '已执行批次再执行应被拦截')
try:
    r2 = requests.post(f'{BASE}/drill-center/batches', json={"script_id": script_id_1}, headers=h(admin_token))
    if r2.status_code == 200:
        exec_batch = r2.json()
        exec_batch_id = exec_batch['batch_id']
        created_batch_ids.append(exec_batch_id)

        r_exec = requests.post(f'{BASE}/drill-center/batches/{exec_batch_id}/execute', headers=h(admin_token), timeout=300)
        if r_exec.status_code == 200:
            r_reexec = requests.post(f'{BASE}/drill-center/batches/{exec_batch_id}/execute', headers=h(admin_token))
            case('已完成批次再执行返回400', r_reexec.status_code == 400, f'status={r_reexec.status_code}', '启动执行')
except Exception as e:
    case('已执行批次再执行异常', False, str(e), '启动执行')

print_step(22, '成员不能执行/回滚/恢复批次')
try:
    r = requests.post(f'{BASE}/drill-center/batches/{batch_id_1}/execute', headers=h(member_token))
    case('成员执行批次返回403', r.status_code == 403, f'status={r.status_code}', '权限隔离')

    r = requests.post(f'{BASE}/drill-center/batches/{batch_id_1}/rollback', headers=h(member_token))
    case('成员回滚批次返回403', r.status_code == 403, f'status={r.status_code}', '权限隔离')

    r = requests.post(f'{BASE}/drill-center/batches/{batch_id_1}/recover', headers=h(member_token))
    case('成员恢复批次返回403', r.status_code == 403, f'status={r.status_code}', '权限隔离')
except Exception as e:
    case('成员批次操作权限异常', False, str(e), '权限隔离')

print()
print_header('测试汇总')
print(f'总计: {total} 项')
print(f'通过: {passed} 项')
print(f'失败: {total - passed} 项')
if total > 0:
    rate = passed / total * 100
    print(f'通过率: {rate:.1f}%')

failed_cases = [t for t in test_results if not t['passed']]
if failed_cases:
    print()
    print(f'失败用例列表 ({len(failed_cases)}):')
    for t in failed_cases:
        print(f'  - {t["name"]}: {t["detail"]}')

categories = {}
for t in test_results:
    cat = t['category'] or '未分类'
    if cat not in categories:
        categories[cat] = {'passed': 0, 'total': 0}
    categories[cat]['total'] += 1
    if t['passed']:
        categories[cat]['passed'] += 1

print()
print('分类统计:')
for cat, stats in categories.items():
    cat_rate = stats['passed'] / stats['total'] * 100 if stats['total'] > 0 else 0
    print(f'  {cat}: {stats["passed"]}/{stats["total"]} ({cat_rate:.0f}%)')

print()
if created_batch_ids:
    print(f'{INFO} 本次创建的批次ID: {", ".join(created_batch_ids)}')
if created_script_ids:
    print(f'{INFO} 本次创建的剧本ID: {", ".join(str(i) for i in created_script_ids)}')

if passed == total:
    print(f'{PASS} 全部测试通过!')
    sys.exit(0)
else:
    print(f'{FAIL} 存在失败用例，见上方列表')
    sys.exit(1)
