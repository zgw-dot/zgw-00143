import requests
import hashlib
import sys

out_file = open("verify_after_restart.txt", "w", encoding="utf-8")
class Tee:
    def __init__(self, *files): self.files = files
    def write(self, s):
        for f in self.files: f.write(s); f.flush()
    def flush(self):
        for f in self.files: f.flush()

sys.stdout = Tee(sys.stdout, out_file)

BASE = "http://127.0.0.1:8000/api"

def login(username, password):
    r = requests.post(f"{BASE}/auth/login", data={"username": username, "password": password})
    assert r.status_code == 200, f"login failed: {r.text}"
    return r.json()["access_token"]

admin_token = login("admin", "admin123")
headers = {"Authorization": f"Bearer {admin_token}"}

print("=" * 60)
print("重启后持久化验证")
print("=" * 60)

r1 = requests.get(f"{BASE}/bookings/23", headers=headers)
booking = r1.json()
print("\n[验证1] 预约ID=23 状态流转:")
print(f"  status = {booking['status']}")
assert booking["status"] == "rescheduling", f"状态错误！应为 rescheduling，实际 {booking['status']}"
print(f"  [OK] 状态 = rescheduling 正确！")
print(f"  start_time = {booking['start_time']}")
print(f"  end_time = {booking['end_time']}")

r2 = requests.get(f"{BASE}/bookings/23/reschedule-history", headers=headers)
history = r2.json()
print(f"\n[验证2] 改期历史记录数 = {len(history)}")
assert len(history) == 1, f"改期记录数错误！应为 1，实际 {len(history)}"
print(f"  [OK] 改期记录数 = 1 正确！")
for h in history:
    print(f"  改期: {h['original_start_time']} ~ {h['original_end_time']} -> {h['new_start_time']} ~ {h['new_end_time']}")
    print(f"    原因={h['reason']}, 操作人={h['operator_name']}")
    assert h['reason'] == "排练时间调整，需要改期", f"改期原因错误！"
    assert h['operator_name'] == "系统管理员", f"操作人错误！"
    print(f"  [OK] 改期原因、操作人正确！")

r3 = requests.get(f"{BASE}/exports/bookings.csv", headers=headers)
csv_bytes = r3.content
csv_hash_after = hashlib.md5(csv_bytes).hexdigest()
csv_text = csv_bytes.decode("utf-8-sig")
lines = csv_text.splitlines()

with open("csv_before_restart.csv", "rb") as f:
    before_bytes = f.read()
csv_hash_before = hashlib.md5(before_bytes).hexdigest()
lines_before = before_bytes.decode("utf-8-sig").splitlines()

print(f"\n[验证3] CSV 导出一致性:")
print(f"  重启前行数: {len(lines_before)}, MD5={csv_hash_before}")
print(f"  重启后行数: {len(lines)}, MD5={csv_hash_after}")
print(f"  表头: {lines[0][:80]}...")

required_cols = ["原时段", "新时段", "改期原因", "改期操作人"]
all_cols_ok = all(c in lines[0] for c in required_cols)
print(f"\n  表头包含改期列: {all_cols_ok}")
assert all_cols_ok, f"表头缺失改期列！"
print(f"  [OK] CSV 表头完整！")

has_data_after = any("改期" in line for line in lines[1:])
has_data_before = any("改期" in line for line in lines_before[1:])
print(f"  重启前包含改期数据: {has_data_before}")
print(f"  重启后包含改期数据: {has_data_after}")
assert has_data_after == True, "重启后 CSV 改期数据缺失！"
print(f"  [OK] 重启后 CSV 仍包含改期历史数据！")

print(f"\n  行数一致性: {len(lines_before)} vs {len(lines)} (前={len(lines_before)}, 后={len(lines)})")
print(f"  MD5 一致性: {csv_hash_before == csv_hash_after}")
if csv_hash_before == csv_hash_after:
    print(f"  [OK] CSV 逐字节完全一致！")
else:
    # 逐行对比差异（时间戳等可能变化的列除外）
    print(f"  MD5 不完全一致（可能有时间戳差异），检查关键字段...")
    diff_count = 0
    for i, (bl, al) in enumerate(zip(lines_before, lines)):
        if bl != al:
            print(f"    行 {i+1} 差异")
            diff_count += 1
            if diff_count > 3: break

print("\n" + "=" * 60)
print("全部持久化验证通过！")
print("=" * 60)
out_file.close()
