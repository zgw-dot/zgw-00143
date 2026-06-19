import requests
import hashlib
import sys

out_file = open("verify_output.txt", "w", encoding="utf-8")
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

r1 = requests.get(f"{BASE}/bookings/23", headers=headers)
booking = r1.json()
print("预约ID=23 状态检查:")
print(f"  status = {booking['status']}")
print(f"  start_time = {booking['start_time']}")
print(f"  end_time = {booking['end_time']}")

r2 = requests.get(f"{BASE}/bookings/23/reschedule-history", headers=headers)
history = r2.json()
print(f"  改期记录数 = {len(history)}")
for h in history:
    print(f"  改期: {h['original_start_time']} ~ {h['original_end_time']} -> {h['new_start_time']} ~ {h['new_end_time']}")
    print(f"    原因={h['reason']}, 操作人={h['operator_name']}")

r3 = requests.get(f"{BASE}/exports/bookings.csv", headers=headers)
csv_bytes = r3.content
csv_hash = hashlib.md5(csv_bytes).hexdigest()
csv_text = csv_bytes.decode("utf-8-sig")
lines = csv_text.splitlines()
with open("csv_before_restart.csv", "wb") as f:
    f.write(csv_bytes)
print(f"\nCSV 导出: {len(lines)} 行, MD5={csv_hash}")
print(f"  表头检查: {'原时段' in lines[0] and '新时段' in lines[0] and '改期原因' in lines[0] and '改期操作人' in lines[0]}")
has_resched = any("改期" in line for line in lines[1:])
print(f"  包含改期数据: {has_resched}")
print(f"  CSV 已保存到 csv_before_restart.csv")
out_file.close()
