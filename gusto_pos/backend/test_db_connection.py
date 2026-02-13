import sys
import psycopg2

try:
    conn = psycopg2.connect(
        host='127.0.0.1',
        user='gusto_admin',
        password='gusto_password',
        database='gusto_pos_v2'
    )
    cursor = conn.cursor()
    print('✓ Successfully connected to gusto_pos_v2 as gusto_admin')
    cursor.execute("SELECT version();")
    result = cursor.fetchone()
    print(f"✓ Database: {result[0]}")
    cursor.close()
    conn.close()
except Exception as e:
    print(f'✗ Error: {e}')
    sys.exit(1)
