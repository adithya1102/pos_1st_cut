import asyncio
import uuid
import os
from app.core.database import engine
from sqlalchemy import text

OUTLET_ID = '0b8a8349-6144-41a8-b028-b9089bd8eaea'
IP_ADDRESS = '192.168.1.7'

async def generate():
    async with engine.begin() as conn:
        # 1. Get current config counts
        res = await conn.execute(text("SELECT config_key, config_value FROM outlet_config WHERE outlet_id = :oid"), {'oid': OUTLET_ID})
        configs = {row[0]: int(row[1]) for row in res.fetchall()}
        n_count = configs.get('normal_table_count', 10)
        a_count = configs.get('ac_table_count', 10)

        # 2. Delete old hardcoded tables
        await conn.execute(text("DELETE FROM tables WHERE outlet_id = :oid"), {'oid': OUTLET_ID})

        # 2b. Alter table_number to varchar if it's still integer
        await conn.execute(text("ALTER TABLE tables ALTER COLUMN table_number TYPE varchar USING table_number::varchar"))

        html = f"""<html><head><style>
        body {{ font-family: sans-serif; background: #f8f9fa; text-align: center; }}
        .grid {{ display: flex; flex-wrap: wrap; justify-content: center; gap: 20px; padding: 20px; }}
        .card {{ background: white; padding: 20px; border-radius: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); width: 200px; }}
        h2 {{ color: #1b4332; margin-top: 40px; }}
        </style></head><body><h1>Gusto POS — WiFi QR Testing</h1>
        <p>Ensure your phone is connected to the same WiFi network ({IP_ADDRESS})</p>"""

        async def make_tables(prefix, count, title):
            nonlocal html
            html += f"<h2>{title}</h2><div class='grid'>"
            for i in range(1, count + 1):
                t_num = f"{prefix}-{i}"
                token = uuid.uuid4().hex[:8].upper()
                
                # Insert dynamic table
                zone = "normal" if prefix == "N" else "ac"
                await conn.execute(text(
                    "INSERT INTO tables (id, outlet_id, table_number, qr_token, status, zone) "
                    "VALUES (gen_random_uuid(), :oid, :t_num, :tok, 'AVAILABLE', :zone)"
                ), {'oid': OUTLET_ID, 't_num': t_num, 'tok': token, 'zone': zone})

                # Generate QR link
                url = f"http://{IP_ADDRESS}:3000/menu?t={token}"
                qr = f"https://api.qrserver.com/v1/create-qr-code/?size=200x200&data={url}"
                html += f"<div class='card'><h2 style='margin-top:0;'>{t_num}</h2><img src='{qr}' width='150'/><br><br><a href='{url}' target='_blank'>Open on PC</a></div>"
            html += "</div>"

        await make_tables("N", n_count, "NORMAL DINING")
        await make_tables("A", a_count, "AC FINE-DINE ❄️")
        html += "</body></html>"

        # 3. Save the HTML file
        os.makedirs("qr_codes", exist_ok=True)
        with open("qr_codes/index.html", "w", encoding="utf-8") as f:
            f.write(html)

        print(f"[OK] Generated {n_count} Normal and {a_count} AC tables in the database!")
        print(f"[OK] QR code page updated at backend/qr_codes/index.html")

if __name__ == "__main__":
    asyncio.run(generate())
