"""
MySQL 建表 + 插入测试用户脚本

用法：
  cd AIconverstionSys
  python scripts/init_mysql.py
"""

import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / "backend" / ".env")

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

async def main():
    import bcrypt
    from app.models.database import init_db, get_async_session_factory
    from app.models.database import UserProfile
    from datetime import datetime

    def hash_password(pwd: str) -> str:
        return bcrypt.hashpw(pwd.encode(), bcrypt.gensalt()).decode()

    print("建表...")
    await init_db()
    print("  ✅ 表结构创建完成")

    # role: 'admin' 看全部数据；'user' 仅能看 accessible_enterprises 内绑定的化工企业
    test_users = [
        {
            "user_id": "user_admin_001",
            "username": "admin",
            "password_hash": hash_password("admin123"),
            "nickname": "系统管理员",
            "role": "admin",
            "accessible_enterprises": ["*"],  # admin 全权
            "registered_at": datetime(2024, 1, 1),
        },
        {
            "user_id": "user_test_001",
            "username": "chem_user_a",
            "password_hash": hash_password("chemA123"),
            "nickname": "化工企业A·碳合规",
            "role": "user",
            "accessible_enterprises": ["C001"],  # 1:1 绑定化工企业A
            "registered_at": datetime(2024, 1, 15),
        },
        {
            "user_id": "user_test_002",
            "username": "chem_user_d",
            "password_hash": hash_password("chemD123"),
            "nickname": "化工企业D·演示",
            "role": "user",
            "accessible_enterprises": ["C004"],  # 化工企业D
            "registered_at": datetime(2025, 3, 1),
        },
        # 跨行业账号（石化 / 光伏 / 煤炭）
        {
            "user_id": "user_petchem_001",
            "username": "petchem_user_a",
            "password_hash": hash_password("petA123"),
            "nickname": "石化企业A·碳合规",
            "role": "user",
            "accessible_enterprises": ["C021"],  # 石化企业A
            "registered_at": datetime(2024, 6, 1),
        },
        {
            "user_id": "user_solar_001",
            "username": "solar_user_a",
            "password_hash": hash_password("solarA123"),
            "nickname": "光伏企业A·绿电规划",
            "role": "user",
            "accessible_enterprises": ["C022"],  # 光伏企业A
            "registered_at": datetime(2024, 6, 15),
        },
        {
            "user_id": "user_coal_001",
            "username": "coal_user_a",
            "password_hash": hash_password("coalA123"),
            "nickname": "煤炭企业A·安环部",
            "role": "user",
            "accessible_enterprises": ["C023"],  # 煤炭企业A
            "registered_at": datetime(2024, 7, 1),
        },
    ]

    factory = get_async_session_factory()
    async with factory() as session:
        for u in test_users:
            existing = await session.get(UserProfile, u["user_id"])
            if existing:
                # 已存在则更新关键字段（幂等）
                existing.username = u["username"]
                existing.role = u["role"]
                existing.accessible_enterprises = u["accessible_enterprises"]
                existing.nickname = u["nickname"]
                existing.password_hash = u["password_hash"]
                print(f"  更新已存在用户: {u['username']}")
                continue
            session.add(UserProfile(**u))
        await session.commit()

    print("\n测试账号：")
    print("  admin         / admin123     (管理员，可看全部企业)")
    print("  chem_user_a     / chemA123     (绑定化工企业A C001 / 化工)")
    print("  chem_user_d     / chemD123     (绑定化工企业D C004 / 煤化工)")
    print("  petchem_user_a  / petA123      (绑定石化企业A C021 / 石油化工)")
    print("  solar_user_a    / solarA123    (绑定光伏企业A C022 / 光伏)")
    print("  coal_user_a     / coalA123     (绑定煤炭企业A C023 / 煤炭)")
    print("\n✅ MySQL 初始化完成！")

if __name__ == "__main__":
    asyncio.run(main())
