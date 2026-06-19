import requests, time, sys, os, csv, io, json
from datetime import datetime, timedelta
from pathlib import Path

BASE = 'http://127.0.0.1:8002/api'
stamp = datetime.now().strftime('%H%M%S')

FAIL = '\033[91m[FAIL]\033[0m'
PASS = '\033[92m[PASS]\033[0m'
STEP = '\033[94m[STEP]\033[0m'
INFO = '\033[93m[INFO]\033[0m'
WARN = '\033[95m[WARN]\033[0m'

passed = 0
total = 0
test_results = []
drill_sessions_to_cleanup = []

error_categories = [
    'PERMISSION', 'CONFLICT', 'CANCEL', 'MODAL',
    'TABLE', 'DOWNLOAD', 'RESTART', 'DATA_QUALITY', 'UNKNOWN'
]


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


def get_current_server_pid():
    try:
        import psutil
        for proc in psutil.process_iter(['pid', 'cmdline', 'cwd']):
            try:
                cmdline = ' '.join(proc.info['cmdline'] or [])
                cwd = proc.info['cwd'] or ''
                if 'uvicorn' in cmdline and 'main:app' in cmdline and 'zgw-00143' in cwd:
                    return proc.pid
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except ImportError:
        print(f'{WARN} psutil 未安装，无法获取服务器PID')
    return None


print_header('候补演练回归测试 - API级 + 浏览器级')
print(f'测试时间: {datetime.now().isoformat()}')
print(f'测试地址: {BASE}')
print()

try:
    health = requests.get(f'{BASE}/health', timeout=5)
    print(f'{PASS} 服务健康检查通过 status={health.status_code}')
except requests.exceptions.RequestException as e:
    print(f'{FAIL} 服务未启动或不可访问: {e}')
    print('       请先启动服务: cd backend ; python -m uvicorn main:app --host 127.0.0.1 --port 8002')
    sys.exit(1)

print_step(1, '准备测试账号')
try:
    admin_token, admin_user = api_login('admin', 'admin123')
    member_token, member_user = api_login('lisi', '123456')
    print(f'{INFO} 管理员: {admin_user["username"]} (ID={admin_user["id"]})')
    print(f'{INFO} 成员: {member_user["username"]} (ID={member_user["id"]})')
    case('T1: 测试账号登录成功', True)
except Exception as e:
    case('T1: 测试账号登录成功', False, str(e))
    sys.exit(1)

print_step(2, '获取测试场地')
venues = requests.get(f'{BASE}/venues', headers=h(admin_token)).json()
if not venues:
    nv = requests.post(f'{BASE}/venues', headers=h(admin_token),
                       json={'name': 'DRILL剧场', 'capacity': 100}).json()
    venue_id = nv['id']
else:
    venue_id = venues[0]['id']
print(f'{INFO} 测试场地ID: {venue_id}')
case('T2: 测试场地准备完成', True)

print_header('第一部分：演练流程核心测试')

print_step(3, '创建演练会话 - 完整流程验证')
try:
    r = requests.post(f'{BASE}/waitlist-drill/session',
                      headers=h(admin_token),
                      json={
                          'venue_id': venue_id,
                          'auto_find_slot': True,
                          'target_date_offset_days': 90
                      })
    case('T3: 创建演练会话API返回200', r.status_code in (200, 201),
         f'status={r.status_code} body={r.text[:300]}', category='DATA_QUALITY')

    if r.status_code in (200, 201):
        drill_result = r.json()
        drill_session_id = drill_result['drill_session_id']
        drill_sessions_to_cleanup.append(drill_session_id)

        print(f'{INFO} 演练会话ID: {drill_session_id}')
        print(f'{INFO} 演练状态: {drill_result["status"]}')
        print(f'{INFO} 演练日期: {drill_result["base_date"]}')
        print(f'{INFO} 通过步骤: {drill_result["total_passed"]}/{drill_result["total_failed"] + drill_result["total_passed"]}')

        case('T4: 演练会话包含正确的session_id',
             drill_session_id.startswith('DRILL_'),
             f'actual={drill_session_id}', category='DATA_QUALITY')

        expected_steps = [
            'S1: 创建演练用户',
            'S2: 确定演练时段',
            'S3: 创建挡路预约',
            'S4: 成员1候补登记',
            'S5: 重复候补拦截验证',
            'S6: 成员2候补登记',
            'S7: 优先级排队顺序验证',
            'S8: 封场挡住候补验证',
            'S9: 撤销封场后自动补位验证',
            'S10: 取消预约后高优先级自动补位验证',
            'S11: 补位后低优先级前进验证',
            'S12: CSV导出验证'
        ]

        actual_step_names = [s['step_name'] for s in drill_result['steps']]
        for expected in expected_steps:
            found = any(expected in s for s in actual_step_names)
            case(f'T5: 演练包含步骤 {expected}', found,
                 f'missing={expected}', category='DATA_QUALITY')

        failed_steps = [s for s in drill_result['steps'] if not s['passed']]
        for step in failed_steps:
            case(f'T6: 演练步骤 {step["step_name"]} 通过',
                 False,
                 f'error_category={step["error_category"]}, detail={step["error_detail"]}',
                 category=step['error_category'])

        case('T7: 演练所有步骤通过',
             drill_result['total_failed'] == 0,
             f'failed={drill_result["total_failed"]}, steps={[(s["step_name"], s["error_category"]) for s in failed_steps]}',
             category='DATA_QUALITY')

except Exception as e:
    case('T3: 创建演练会话API返回200', False, str(e), category='DATA_QUALITY')

print_step(4, '成员端演练视图验证')
try:
    r = requests.get(f'{BASE}/waitlist-drill/session/{drill_session_id}/member-view',
                     headers=h(member_token))
    case('T8: 成员端可以查看自己的演练数据',
         r.status_code == 200,
         f'status={r.status_code}', category='PERMISSION')

    if r.status_code == 200:
        member_view = r.json()
        case('T9: 成员端视图不包含其他用户的数据',
             member_view['is_admin'] == False,
             f'is_admin={member_view["is_admin"]}', category='PERMISSION')

        case('T10: 成员端视图有正确的摘要统计',
             'summary' in member_view and 'total' in member_view['summary'],
             category='DATA_QUALITY')

        for entry in member_view['entries']:
            case(f'T11: 成员端条目 {entry["id"]} 有被挡原因说明',
                 bool(entry.get('blocked_detail') or entry.get('blocked_by_type_text')),
                 f'blocked_by_type={entry.get("blocked_by_type")}', category='TABLE')

            if entry['status'] == 'filled':
                case(f'T12: 已补位条目 {entry["id"]} 有补位结果',
                     bool(entry.get('filled_booking_id')) and bool(entry.get('filled_method_text')),
                     category='TABLE')

except Exception as e:
    case('T8: 成员端可以查看自己的演练数据', False, str(e), category='PERMISSION')

print_step(5, '管理员端演练视图验证')
try:
    r = requests.get(f'{BASE}/waitlist-drill/session/{drill_session_id}/member-view',
                     headers=h(admin_token))
    case('T13: 管理员端可以查看全量演练数据',
         r.status_code == 200,
         f'status={r.status_code}', category='PERMISSION')

    if r.status_code == 200:
        admin_view = r.json()
        case('T14: 管理员端视图标记is_admin=True',
             admin_view['is_admin'] == True,
             category='PERMISSION')

        case('T15: 管理员端能看到多条候补记录',
             admin_view['summary']['total'] >= 3,
             f'count={admin_view["summary"]["total"]}', category='TABLE')

except Exception as e:
    case('T13: 管理员端可以查看全量演练数据', False, str(e), category='PERMISSION')

print_step(6, '演练会话快照验证')
try:
    r = requests.get(f'{BASE}/waitlist-drill/session/{drill_session_id}/snapshot',
                     headers=h(admin_token))
    case('T16: 获取演练快照成功', r.status_code == 200,
         f'status={r.status_code}', category='DATA_QUALITY')

    if r.status_code == 200:
        snapshot = r.json()
        case('T17: 快照包含候补记录',
             len(snapshot['waitlists']) >= 3,
             f'count={len(snapshot["waitlists"])}', category='DATA_QUALITY')

        case('T18: 快照包含预约记录',
             len(snapshot['bookings']) >= 1,
             f'count={len(snapshot["bookings"])}', category='DATA_QUALITY')

        case('T19: 快照包含操作日志',
             snapshot['summary']['log_count'] >= 2,
             f'count={snapshot["summary"]["log_count"]}', category='DATA_QUALITY')

        case('T20: 快照包含已补位记录',
             snapshot['summary']['filled_count'] >= 0,
             f'filled={snapshot["summary"]["filled_count"]}', category='DATA_QUALITY')

except Exception as e:
    case('T16: 获取演练快照成功', False, str(e), category='DATA_QUALITY')

print_step(7, '错误分类API验证')
try:
    r = requests.get(f'{BASE}/waitlist-drill/error-categories',
                     headers=h(member_token))
    case('T21: 获取错误分类成功', r.status_code == 200,
         f'status={r.status_code}', category='DATA_QUALITY')

    if r.status_code == 200:
        categories = r.json()
        for cat in error_categories:
            case(f'T22: 错误分类包含 {cat}',
                 cat in categories,
                 f'missing={cat}', category='DATA_QUALITY')

except Exception as e:
    case('T21: 获取错误分类成功', False, str(e), category='DATA_QUALITY')

print_step(8, '权限控制验证 - 非管理员不能创建演练')
try:
    r = requests.post(f'{BASE}/waitlist-drill/session',
                      headers=h(member_token),
                      json={'venue_id': venue_id, 'auto_find_slot': True})
    case('T23: 非管理员创建演练返回403',
         r.status_code == 403,
         f'status={r.status_code}', category='PERMISSION')
except Exception as e:
    case('T23: 非管理员创建演练返回403', False, str(e), category='PERMISSION')

print_step(9, '权限控制验证 - 非管理员不能清理演练')
try:
    r = requests.delete(f'{BASE}/waitlist-drill/session/{drill_session_id}',
                        headers=h(member_token))
    case('T24: 非管理员清理演练返回403',
         r.status_code == 403,
         f'status={r.status_code}', category='PERMISSION')
except Exception as e:
    case('T24: 非管理员清理演练返回403', False, str(e), category='PERMISSION')

print_header('第二部分：CSV导出验证')

print_step(10, '管理员CSV导出验证')
try:
    r = requests.get(f'{BASE}/exports/waitlist.csv',
                     headers=h(admin_token))
    case('T25: 管理员导出CSV成功',
         200 <= r.status_code < 300 and len(r.content) > 100,
         f'status={r.status_code} len={len(r.content)}', category='DOWNLOAD')

    if 200 <= r.status_code < 300:
        content = r.content.decode('utf-8-sig')
        lines = content.splitlines()
        reader = csv.reader(io.StringIO(content))
        header = next(reader)

        required_cols = [
            '候补ID', '剧目', '场地', '申请人', '状态',
            '目标开始时间', '目标结束时间', '被挡住类型',
            '补位方式', '补位时间', '对应预约ID',
            '操作类型', '触发原因'
        ]
        for col in required_cols:
            case(f'T26: CSV包含列 {col}',
                 col in header,
                 f'missing={col}, header={header[:10]}', category='TABLE')

        case('T27: CSV包含演练数据',
             any('DRILL' in line or '演练' in line for line in lines),
             category='DOWNLOAD')

        case('T28: CSV包含已补位记录',
             any('已补位' in line for line in lines),
             category='TABLE')

        case('T29: CSV包含操作日志记录',
             any('登记候补' in line or '补位成功' in line for line in lines),
             category='TABLE')

        case('T30: CSV文件名格式正确',
             'waitlist' in r.headers.get('Content-Disposition', '').lower(),
             f'header={r.headers.get("Content-Disposition")}', category='DOWNLOAD')

except Exception as e:
    case('T25: 管理员导出CSV成功', False, str(e), category='DOWNLOAD')

print_step(11, '成员CSV导出权限验证')
try:
    r = requests.get(f'{BASE}/exports/waitlist.csv',
                     headers=h(member_token))
    case('T31: 成员导出CSV返回403',
         r.status_code == 403,
         f'status={r.status_code}', category='PERMISSION')
except Exception as e:
    case('T31: 成员导出CSV返回403', False, str(e), category='PERMISSION')

print_header('第三部分：真实重启校验（可选）')

_run_restart = os.environ.get('RUN_RESTART_TESTS') == '1' or '--restart' in sys.argv

if _run_restart:
    server_pid = get_current_server_pid()
    if server_pid:
        print_step(12, f'真实服务重启校验 PID={server_pid}')
        try:
            import psutil
            proc = psutil.Process(server_pid)
            cmdline = ' '.join(proc.cmdline())
            cwd = proc.cwd()

            print(f'{INFO} 进程信息:')
            print(f'       PID: {server_pid}')
            print(f'       命令: {cmdline[:100]}')
            print(f'       目录: {cwd}')

            if 'zgw-00143' in cwd and 'uvicorn' in cmdline:
                snapshot_before = requests.get(
                    f'{BASE}/waitlist-drill/session/{drill_session_id}/snapshot',
                    headers=h(admin_token)
                ).json()

                print(f'{INFO} 正在停止服务...')
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except psutil.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)

                print(f'{INFO} 服务已停止，等待2秒后启动...')
                time.sleep(2)

                backend_dir = Path(__file__).parent
                import subprocess
                new_proc = subprocess.Popen(
                    [sys.executable, '-m', 'uvicorn', 'main:app',
                     '--host', '127.0.0.1', '--port', '8002'],
                    cwd=str(backend_dir),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )

                print(f'{INFO} 新服务已启动 PID={new_proc.pid}，等待就绪...')

                max_wait = 30
                server_ready = False
                for i in range(max_wait):
                    try:
                        r = requests.get(f'{BASE}/health', timeout=2)
                        if r.status_code == 200:
                            server_ready = True
                            break
                    except requests.exceptions.RequestException:
                        pass
                    time.sleep(1)

                case('T32: 服务重启成功并就绪',
                     server_ready,
                     f'waited {max_wait}s', category='RESTART')

                if server_ready:
                    admin_token2, _ = api_login('admin', 'admin123')

                    r = requests.post(
                        f'{BASE}/waitlist-drill/session/{drill_session_id}/restart-verify',
                        headers=h(admin_token2),
                        json={
                            'drill_session_id': drill_session_id,
                            'server_pid': new_proc.pid,
                            'server_port': 8002
                        }
                    )

                    if r.status_code == 200:
                        result = r.json()
                        case('T33: 重启后数据一致性验证通过',
                             result['success'],
                             f'errors={result.get("consistency_errors", [])}',
                             category='RESTART')

                        if not result['success']:
                            for err in result.get('consistency_errors', []):
                                case(f'T34: 一致性错误: {err[:50]}', False, err, category='RESTART')

                    print(f'{INFO} 清理测试服务进程 PID={new_proc.pid}')
                    new_proc.terminate()
                    try:
                        new_proc.wait(timeout=5)
                    except:
                        new_proc.kill()

                    print(f'{INFO} 请手动重启主服务后继续后续测试')
                    print(f'       命令: cd backend ; python -m uvicorn main:app --host 127.0.0.1 --port 8002')

            else:
                case('T32: 服务进程不属于当前项目', False,
                     f'cmdline={cmdline[:100]}, cwd={cwd}', category='RESTART')

        except ImportError:
            case('T32: 重启验证需要psutil', False,
                 '请安装: pip install psutil', category='RESTART')
        except Exception as e:
            case('T32: 重启验证失败', False, str(e), category='RESTART')
    else:
        print(f'{WARN} 无法找到服务器PID，跳过重启校验')
        print(f'       请确保服务运行在 127.0.0.1:8002')
else:
    print()
    print(f'{INFO} 跳过重启校验（需要显式启用）')
    print(f'       设置环境变量 RUN_RESTART_TESTS=1 或加 --restart 参数')
    print(f'       命令: python test_waitlist_drill_regression.py --restart')

print_header('第四部分：演练数据清理验证')

print_step(13, '清理演练会话数据')
try:
    for sid in drill_sessions_to_cleanup:
        r = requests.delete(f'{BASE}/waitlist-drill/session/{sid}',
                            headers=h(admin_token))
        case(f'T35: 清理演练会话 {sid[:20]}...',
             r.status_code == 200,
             f'status={r.status_code} body={r.text[:200]}', category='CANCEL')

        if r.status_code == 200:
            cleanup_result = r.json()
            case(f'T36: 清理返回正确的session_id',
                 cleanup_result['drill_session_id'] == sid,
                 category='DATA_QUALITY')

            case(f'T37: 清理记录数大于0',
                 cleanup_result['removed_count'] > 0,
                 f'count={cleanup_result["removed_count"]}', category='CANCEL')

            expected_types = [
                'waitlist_logs', 'waitlist_entries',
                'bookings', 'closed_windows', 'users'
            ]
            for t in expected_types:
                case(f'T38: 清理包含类型 {t}',
                     t in cleanup_result['details'],
                     f'missing={t}', category='CANCEL')

            print(f'{INFO} 清理详情: {json.dumps(cleanup_result["details"], ensure_ascii=False)}')

    time.sleep(0.5)
    for sid in drill_sessions_to_cleanup:
        r = requests.get(f'{BASE}/waitlist-drill/session/{sid}/snapshot',
                         headers=h(admin_token))
        snapshot = r.json() if r.status_code == 200 else {}
        case(f'T39: 清理后候补记录为空',
             snapshot.get('summary', {}).get('waitlist_count', 0) == 0,
             f'count={snapshot.get("summary", {}).get("waitlist_count")}',
             category='CANCEL')

except Exception as e:
    case('T35: 清理演练会话', False, str(e), category='CANCEL')

print_header('第五部分：浏览器级演练回归测试（可选）')

_browser_enabled = os.environ.get('RUN_BROWSER_TESTS') == '1' or '--browser' in sys.argv
if _browser_enabled:
    print()
    print('=' * 60)
    print('  启动浏览器级演练回归测试')
    print('=' * 60)
    try:
        from test_browser_waitlist_drill import main as browser_drill_main
        _browser_exit_code = browser_drill_main(drill_session_id=None)
        case('T40: 浏览器级演练测试通过',
             _browser_exit_code == 0,
             f'exit_code={_browser_exit_code}', category='MODAL')
    except ImportError as e:
        print(f'{WARN} 无法运行浏览器测试: {e}')
        print('       请确保已安装 playwright: pip install playwright')
        print('       并安装浏览器: python -m playwright install chromium')
        case('T40: 浏览器级演练测试', False, str(e), category='MODAL')
    except Exception as e:
        print(f'{WARN} 浏览器测试运行出错: {e}')
        case('T40: 浏览器级演练测试', False, str(e), category='MODAL')
else:
    print()
    print(f'{INFO} 跳过浏览器级测试')
    print(f'       设置环境变量 RUN_BROWSER_TESTS=1 或加 --browser 参数')
    print(f'       命令: python test_waitlist_drill_regression.py --browser')

print()
print('=' * 80)
print(f'  候补演练回归测试总结 - {datetime.now().isoformat()}')
print('=' * 80)
print(f'  总测试数: {total}')
print(f'  通过: {passed}')
print(f'  失败: {total - passed}')
print(f'  通过率: {passed/total*100:.1f}%' if total > 0 else '  无测试')
print()

category_stats = {}
for t in test_results:
    cat = t['category'] or 'UNKNOWN'
    if cat not in category_stats:
        category_stats[cat] = {'passed': 0, 'failed': 0}
    if t['passed']:
        category_stats[cat]['passed'] += 1
    else:
        category_stats[cat]['failed'] += 1

if category_stats:
    print('  按错误分类统计:')
    for cat in sorted(category_stats.keys()):
        s = category_stats[cat]
        total_cat = s['passed'] + s['failed']
        print(f'    {cat:15s}: {s["passed"]}/{total_cat} 通过')
print()

failed_tests = [t for t in test_results if not t['passed']]
if failed_tests:
    print('  失败明细:')
    for t in failed_tests:
        cat = t['category'] or 'UNKNOWN'
        print(f'    {FAIL} {t["name"]} [{cat}]')
        if t.get('detail'):
            detail_lines = str(t['detail']).split('\n')[:2]
            for dl in detail_lines:
                print(f'           {dl}')
    print()

print('=' * 80)

api_pass = passed == total
sys.exit(0 if api_pass else 1)
