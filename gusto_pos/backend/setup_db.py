import sys
try:
    import psycopg2
    from psycopg2 import sql
    
    # Try various connection options
    conn_params = [
        {'host': 'localhost', 'user': 'postgres'},  # Unix socket with peer auth
        {'host': '127.0.0.1', 'user': 'postgres', 'password': ''},  # No password
        {'host': '127.0.0.1', 'user': 'postgres', 'password': 'postgres'},
    ]
    
    conn = None
    for params in conn_params:
        try:
            print(f"Trying connection with params: {params}")
            conn = psycopg2.connect(**params)
            print('Connected to PostgreSQL')
            break
        except psycopg2.OperationalError as e:
            print(f"Failed: {e}")
            continue
    
    if not conn:
        raise Exception("Could not connect to PostgreSQL with any method")
    
    conn.autocommit = True
    cursor = conn.cursor()
    print('Successfully connected to PostgreSQL')
    
    # Create user
    try:
        cursor.execute("CREATE USER gusto_admin WITH PASSWORD 'gusto_password'")
        print('User gusto_admin created')
    except psycopg2.errors.DuplicateObject:
        print('User gusto_admin already exists')
    
    # Create database
    try:
        cursor.execute("CREATE DATABASE gusto_pos_v2 OWNER gusto_admin")
        print('Database gusto_pos_v2 created')
    except psycopg2.errors.DuplicateDatabase:
        print('Database gusto_pos_v2 already exists')
    
    cursor.close()
    conn.close()
    print('Setup completed successfully')
except Exception as e:
    print(f'Error: {e}')
    sys.exit(1)
