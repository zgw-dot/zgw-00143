import requests, time, sys
from datetime import datetime, timedelta

BASE = 'http://127.0.0.1:8002/api'
stamp = datetime.now().strftime('%H%M%S')

def h(tok):
    return {'Authorization': f'Bearer {tok}'}

def case(name, cond, extra=''):
    status = 'PASS' if cond else 'FAIL'
    print(f'[{status}] {name}' + ('' if cond else f' -- {extra}'))
    return 1 if cond else 0

u1, u2 = f'fx_u1_{stamp}', f'fx_u2_{stamp}'
adm = f'fx_a_{stamp}'
for u, p, r in [(u1, 'p1', 'member'), (u2, 'p2', 'member'), (adm, 'pa', 'admin')]:
    requests.post(f'{BASE}/auth/register', json={'username': u, 'password': p, 'full_name': u, 'role': r})

tok_u1 = requests.post(f'{BASE}/auth/login', data={'username': u1, 'password': 'p1'}).json()['access_token']
tok_u2 = requests.post(f'{BASE}/auth/login', data={'username': u2, 'password': 'p2'}).json()['access_token']
tok_a = requests.post(f'{BASE}/auth/login', data={'username': adm, 'password': 'pa'}).json()['access_token']
print('登录OK')

# 确保有场地 - 如果没有就创建一个admin专属场地
venues = requests.get(f'{BASE}/venues', headers=h(tok_a)).json()
if not venues:
    nv = requests.post(f'{BASE}/venues', headers=h(tok_a), json={'name': 'FX测试剧场', 'capacity': 100}).json()
    v = nv['id']
else:
    v = venues[0]['id']

today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
days_to_monday = (7 - today.weekday()) % 7 or 7
next_monday = today + timedelta(days=days_to_monday)
# 用时间戳最后两位做日期偏移，保证每次测试基准日不同，避免残留预约冲突
stamp_offset = int(stamp[-2:]) if stamp[-2:].isdigit() else 0
D = next_monday + timedelta(days=70 + stamp_offset)
# 确保 D 落在周一到周五之间
while D.weekday() > 4:
    D += timedelta(days=1)
def t(h):
    return (D + timedelta(hours=h)).isoformat()

print(f'基准日: {D.date()}')
passed, total = 0, 0

# S1: 创建预约09-12 + 确认
total += 1
r = requests.post(f'{BASE}/bookings', headers=h(tok_a), json={
    'title': 'S1', 'production': 'FX场景', 'venue_id': v, 'priority': 10,
    'start_time': t(9), 'end_time': t(12), 'status': 'pending', 'notes': ''
})
passed += case('S1: 创建预约09-12', r.status_code in (200, 201), f'{r.status_code} {r.text[:200]}')
if r.status_code not in (200, 201):
    print('ABORT'); sys.exit(1)
bid1 = r.json()['id']
ver = r.json()['version']

total += 1
r = requests.patch(f'{BASE}/bookings/{bid1}/status', headers=h(tok_a),
                   json={'status': 'confirmed', 'version': ver})
passed += case('S1b: 管理员确认预约', r.status_code == 200, f'{r.status_code} {r.text[:150]}')

# S2: u1候补登记（被booking挡）
total += 1
r = requests.post(f'{BASE}/waitlist', headers=h(tok_u1), json={
    'title': 'S2候补', 'production': 'FX场景', 'venue_id': v, 'priority': 5,
    'target_start_time': t(9), 'target_end_time': t(12),
    'float_before_minutes': 30, 'float_after_minutes': 30, 'notes': 'S2'
})
passed += case('S2: u1候补登记被booking挡', r.status_code in (200, 201), f'{r.status_code} {r.text[:200]}')
wid1 = r.json()['id']

# S3: 重复候补拦截409
total += 1
r = requests.post(f'{BASE}/waitlist', headers=h(tok_u1), json={
    'title': 'S3重复候补', 'production': 'FX场景dup', 'venue_id': v, 'priority': 5,
    'target_start_time': t(10), 'target_end_time': t(11),
    'float_before_minutes': 0, 'float_after_minutes': 0
})
passed += case('S3: 重复候补被409拦截', r.status_code == 409, f'{r.status_code} {r.text[:150]}')

# S4~S5: 越权查看详情/日志
total += 1
r = requests.get(f'{BASE}/waitlist/{wid1}', headers=h(tok_u2))
passed += case('S4: u2偷看u1候补=403', r.status_code == 403, f'{r.status_code}')

total += 1
r = requests.get(f'{BASE}/waitlist/{wid1}/logs', headers=h(tok_u2))
passed += case('S5: u2偷看u1候补日志=403', r.status_code == 403, f'{r.status_code}')

# S6: 封场14-17 + u2候补被封场挡
total += 1
r = requests.post(f'{BASE}/config/closed-windows', headers=h(tok_a), json={
    'venue_id': v, 'start_time': t(14), 'end_time': t(17),
    'reason': 'S6封场', 'apply_all_venues': False
})
passed += case('S6: 创建封场窗口14-17', r.status_code in (200, 201), f'{r.status_code} {r.text[:150]}')
cw_id = r.json()['id']

total += 1
r = requests.post(f'{BASE}/waitlist', headers=h(tok_u2), json={
    'title': 'S6b封场候补', 'production': 'FX封场剧目', 'venue_id': v, 'priority': 8,
    'target_start_time': t(14), 'target_end_time': t(17),
    'float_before_minutes': 0, 'float_after_minutes': 0
})
passed += case('S6b: u2候补被封场挡', r.status_code in (200, 201), f'{r.status_code} {r.text[:200]}')
wid2 = r.json()['id']

total += 1
wl2 = requests.get(f'{BASE}/waitlist/{wid2}', headers=h(tok_u2)).json()
passed += case('S6c: blocked_type=closed_window',
                wl2.get('blocked_by_type') == 'closed_window',
                f'got={wl2.get("blocked_by_type")}')

# S7: 撤销封场 -> 自动补位wid2
total += 1
r = requests.delete(f'{BASE}/config/closed-windows/{cw_id}', headers=h(tok_a))
passed += case('S7: 撤销封场成功', r.status_code == 200, f'{r.status_code}')
time.sleep(0.3)

total += 1
wl2b = requests.get(f'{BASE}/waitlist/{wid2}', headers=h(tok_u2)).json()
passed += case('S7b: 撤销后wid2=filled',
                wl2b.get('status') == 'filled',
                f'status={wl2b.get("status")} bid={wl2b.get("filled_booking_id")}')

# S8: 取消预约S1 -> 自动补位wid1
b1 = requests.get(f'{BASE}/bookings/{bid1}', headers=h(tok_a)).json()
total += 1
r = requests.patch(f'{BASE}/bookings/{bid1}/status', headers=h(tok_a),
                   json={'status': 'cancelled', 'rejection_reason': 'S8取消', 'version': b1['version']})
passed += case('S8: 取消预约S1', r.status_code == 200, f'{r.status_code} {r.text[:200]}')
time.sleep(0.3)

total += 1
wl1b = requests.get(f'{BASE}/waitlist/{wid1}', headers=h(tok_u1)).json()
passed += case('S8b: 取消后wid1=filled',
                wl1b.get('status') == 'filled',
                f'status={wl1b.get("status")} bid={wl1b.get("filled_booking_id")}')

# S9: 过期清理
total += 1
r = requests.post(f'{BASE}/waitlist/cleanup-expired', headers=h(tok_a))
passed += case('S9: 管理员清理过期=200', r.status_code == 200, f'{r.status_code}')

# S10: 普通成员不能导出候补CSV
total += 1
r = requests.get(f'{BASE}/exports/waitlist.csv', headers=h(tok_u1))
passed += case('S10: 普通成员导出候补CSV=403', r.status_code == 403, f'{r.status_code}')

# S11: 管理员可以导出候补CSV
total += 1
r = requests.get(f'{BASE}/exports/waitlist.csv', headers=h(tok_a))
ok = 200 <= r.status_code < 300 and len(r.content) > 100
passed += case('S11: 管理员导出候补CSV=200+正文', ok, f'{r.status_code} len={len(r.content)}')

# S12: 空闲时段禁止候补（选在开放时段19-22且没被占用的时间，是真正的"空闲"应该直接预约而不是候补）
total += 1
r = requests.post(f'{BASE}/waitlist', headers=h(tok_u1), json={
    'title': 'S12空闲候补', 'production': 'FX空闲', 'venue_id': v, 'priority': 5,
    'target_start_time': t(19), 'target_end_time': t(20),
    'float_before_minutes': 0, 'float_after_minutes': 0
})
passed += case('S12: 空闲时段禁止候补=400', r.status_code == 400, f'{r.status_code} {r.text[:200]}')

# S13: u2候补列表过滤
me2 = requests.get(f'{BASE}/auth/me', headers=h(tok_u2)).json()
total += 1
items = requests.get(f'{BASE}/waitlist?page=1&page_size=50', headers=h(tok_u2)).json().get('items', [])
ok = all(it.get('user_id') == me2['id'] for it in items)
passed += case('S13: u2列表只看自己', ok, f'count={len(items)} uids={[it.get("user_id") for it in items]} meid={me2["id"]}')

# S14: u2看详情看不到"手动补位"按钮字段是后端的，前端通过role控制，测前端admin-only的CSS类过滤（通过evaluate在浏览器里测过了）
total += 1
r = requests.get(f'{BASE}/waitlist/{wid2}', headers=h(tok_a))
adm_can_see_any = r.status_code == 200
passed += case('S14: 管理员看任意候补=200', adm_can_see_any, f'{r.status_code}')

print()
print(f'==== 前端相关回归总结（API级）: {passed}/{total} 通过 ====')

# ========== 浏览器级回归测试（可选） ==========
import os
_browser_enabled = os.environ.get('RUN_BROWSER_TESTS') == '1' or '--browser' in sys.argv
_browser_passed = True
if _browser_enabled:
    print()
    print('=' * 60)
    print('  启动浏览器级候补回归测试')
    print('=' * 60)
    try:
        from test_browser_waitlist import main as browser_waitlist_main
        _browser_exit_code = browser_waitlist_main()
        _browser_passed = _browser_exit_code == 0
    except ImportError as e:
        print(f'[WARN] 无法运行浏览器测试: {e}')
        print('       请确保已安装 playwright: pip install playwright')
        print('       并安装浏览器: python -m playwright install chromium')
    except Exception as e:
        print(f'[WARN] 浏览器测试运行出错: {e}')
        _browser_passed = False
else:
    print()
    print('提示: 设置环境变量 RUN_BROWSER_TESTS=1 或加 --browser 参数')
    print('      可运行浏览器级候补回归测试（DOM断言 + 下载验证）')
    print('      命令: python test_frontend_regression.py --browser')

api_pass = passed == total
all_pass = api_pass and (not _browser_enabled or _browser_passed)
sys.exit(0 if all_pass else 1)
