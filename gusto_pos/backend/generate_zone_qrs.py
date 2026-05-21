import asyncio
import os
from app.core.database import engine
from sqlalchemy import text

IP_ADDRESS = '192.168.1.7'
NORMAL_COUNT = 12
AC_COUNT = 4


async def generate():
    async with engine.begin() as conn:
        # Fetch the first seeded outlet
        res = await conn.execute(text("SELECT id FROM outlets ORDER BY created_at LIMIT 1"))
        row = res.fetchone()
        if not row:
            print("[ERROR] No outlets found. Run reset_db.py first to seed the database.")
            return
        outlet_id = str(row[0])
        print(f"[INFO] Using outlet_id: {outlet_id}")

        # Delete existing tables for this outlet and re-seed
        await conn.execute(text("DELETE FROM tables WHERE outlet_id = :oid"), {'oid': outlet_id})

        html = f"""<html><head><style>
        body {{ font-family: sans-serif; background: #f8f9fa; text-align: center; }}
        .grid {{ display: flex; flex-wrap: wrap; justify-content: center; gap: 20px; padding: 20px; }}
        .card {{ background: white; padding: 20px; border-radius: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); width: 200px; }}
        .zone-label {{ font-size: 12px; color: #888; margin-top: 8px; }}
        h2 {{ color: #1b4332; margin-top: 40px; }}
        .note {{ background: #fff3cd; border: 1px solid #ffc107; border-radius: 8px; padding: 12px; margin: 20px auto; max-width: 600px; font-size: 14px; color: #856404; }}
        </style></head><body>
        <h1>Gusto POS — Table Reference</h1>
        <p>Backend: <code>{IP_ADDRESS}:8000</code> &nbsp;|&nbsp; Frontend: <code>{IP_ADDRESS}:3000</code></p>
        <div class="note">
            QR codes are now <strong>session-based</strong>. Staff must open a table from the POS terminal
            (or call <code>POST /api/v1/tables/open</code>) to generate a live session token.
            The QR sticker printed from the POS encodes that token.
        </div>"""

        async def make_tables(prefix, count, title, zone):
            nonlocal html
            html += f"<h2>{title}</h2><div class='grid'>"
            for i in range(1, count + 1):
                t_num = f"{prefix}-{i}"
                await conn.execute(text(
                    "INSERT INTO tables (id, outlet_id, table_number, status, created_at) "
                    "VALUES (gen_random_uuid(), :oid, :t_num, 0, NOW())"
                ), {'oid': outlet_id, 't_num': t_num})

                open_url = f"http://{IP_ADDRESS}:8000/api/v1/tables/open"
                html += (
                    f"<div class='card'>"
                    f"<h2 style='margin-top:0;'>{t_num}</h2>"
                    f"<div class='zone-label'>Zone: {zone}</div>"
                    f"<br><a href='{open_url}' target='_blank' style='font-size:12px;'>Open via API</a>"
                    f"</div>"
                )
            html += "</div>"

        await make_tables("N", NORMAL_COUNT, "NORMAL DINING", "normal")
        await make_tables("A", AC_COUNT, "AC FINE-DINE", "ac")
        html += "</body></html>"

        os.makedirs("qr_codes", exist_ok=True)
        with open("qr_codes/index.html", "w", encoding="utf-8") as f:
            f.write(html)

        print(f"[OK] Seeded {NORMAL_COUNT} Normal (N-1..N-{NORMAL_COUNT}) and {AC_COUNT} AC (A-1..A-{AC_COUNT}) tables.")
        print(f"[OK] Reference page saved to backend/qr_codes/index.html")


if __name__ == "__main__":
    asyncio.run(generate())
