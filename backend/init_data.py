from sqlalchemy.orm import Session
from datetime import time, date

from database import SessionLocal, engine, Base
from database import User, Venue, OpenSlot, ClosedDate, PriorityRule, Booking
from auth import get_password_hash


def init_data():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    try:
        if db.query(User).count() == 0:
            print("创建初始用户...")
            admin = User(
                username="admin",
                password_hash=get_password_hash("admin123"),
                full_name="系统管理员",
                role="admin"
            )
            member1 = User(
                username="lisi",
                password_hash=get_password_hash("123456"),
                full_name="李四",
                role="member"
            )
            member2 = User(
                username="wangwu",
                password_hash=get_password_hash("123456"),
                full_name="王五",
                role="member"
            )
            member3 = User(
                username="zhaoliu",
                password_hash=get_password_hash("123456"),
                full_name="赵六",
                role="member"
            )
            db.add_all([admin, member1, member2, member3])
            db.commit()
            print("用户创建完成: admin/admin123, lisi/123456, wangwu/123456, zhaoliu/123456")

        if db.query(Venue).count() == 0:
            print("创建初始场地...")
            venue1 = Venue(
                name="一号排练厅",
                description="主排练厅，配备专业灯光音响",
                capacity=50,
                is_active=True
            )
            venue2 = Venue(
                name="二号排练厅",
                description="小型排练厅，适合小组排练",
                capacity=20,
                is_active=True
            )
            venue3 = Venue(
                name="三号剧场",
                description="正式演出剧场，带舞台和观众席",
                capacity=300,
                is_active=True
            )
            db.add_all([venue1, venue2, venue3])
            db.commit()
            print("场地创建完成")

        if db.query(OpenSlot).count() == 0:
            print("创建开放时段...")
            venues = db.query(Venue).all()
            for venue in venues:
                for day in range(5):
                    slot1 = OpenSlot(
                        venue_id=venue.id,
                        day_of_week=day,
                        start_time=time(9, 0),
                        end_time=time(12, 0)
                    )
                    slot2 = OpenSlot(
                        venue_id=venue.id,
                        day_of_week=day,
                        start_time=time(14, 0),
                        end_time=time(18, 0)
                    )
                    slot3 = OpenSlot(
                        venue_id=venue.id,
                        day_of_week=day,
                        start_time=time(19, 0),
                        end_time=time(22, 0)
                    )
                    db.add_all([slot1, slot2, slot3])
            db.commit()
            print("开放时段创建完成（周一至周五 9-12, 14-18, 19-22）")

        if db.query(PriorityRule).count() == 0:
            print("创建优先级规则...")
            rules = [
                PriorityRule(
                    name="年度大戏",
                    priority_level=100,
                    description="年度重点剧目享有最高优先级",
                    applies_to="production",
                    target_value="年度大戏"
                ),
                PriorityRule(
                    name="新剧首演",
                    priority_level=80,
                    description="新剧目首演前排练优先级较高",
                    applies_to="production",
                    target_value="新剧"
                ),
                PriorityRule(
                    name="日常排练",
                    priority_level=50,
                    description="日常排练",
                    applies_to="production",
                    target_value="日常"
                ),
                PriorityRule(
                    name="小型活动",
                    priority_level=30,
                    description="小型活动或彩排",
                    applies_to="production",
                    target_value="活动"
                )
            ]
            db.add_all(rules)
            db.commit()
            print("优先级规则创建完成")

        if db.query(ClosedDate).count() == 0:
            print("创建封场日期示例...")
            from datetime import timedelta
            today = date.today()
            next_week = today + timedelta(days=7)
            closed = ClosedDate(
                venue_id=None,
                date=next_week,
                reason="设备维护日"
            )
            db.add(closed)
            db.commit()
            print(f"封场日期创建完成: {next_week} （全场设备维护）")

        if db.query(Booking).count() == 0:
            print("创建示例预约...")
            from datetime import datetime, timedelta

            member1 = db.query(User).filter(User.username == "lisi").first()
            venue1 = db.query(Venue).filter(Venue.name == "一号排练厅").first()
            venue2 = db.query(Venue).filter(Venue.name == "二号排练厅").first()

            today = date.today()
            tomorrow = today + timedelta(days=1)
            day_after = today + timedelta(days=2)

            booking1 = Booking(
                version=1,
                title="《雷雨》第一幕排练",
                production="雷雨",
                venue_id=venue1.id,
                user_id=member1.id,
                status="confirmed",
                start_time=datetime.combine(tomorrow, time(14, 0)),
                end_time=datetime.combine(tomorrow, time(17, 0)),
                priority=80,
                notes="导演组全员参加",
                approver_id=1,
                approved_at=datetime.utcnow()
            )
            booking2 = Booking(
                version=1,
                title="《茶馆》彩排",
                production="茶馆",
                venue_id=venue2.id,
                user_id=member1.id,
                status="pending",
                start_time=datetime.combine(day_after, time(9, 0)),
                end_time=datetime.combine(day_after, time(12, 0)),
                priority=60,
                notes="带妆彩排"
            )
            db.add_all([booking1, booking2])
            db.commit()
            print("示例预约创建完成")

        print("\n初始化完成！")
        print("管理员账号: admin / admin123")
        print("成员账号: lisi / 123456")

    finally:
        db.close()


if __name__ == "__main__":
    init_data()
