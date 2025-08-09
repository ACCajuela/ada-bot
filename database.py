import aiosqlite

async def connect_db():
    """
    Função assíncrona para conectar ao banco de dados.
    """
    return await aiosqlite.connect('ada.db')

async def init_db():
    """
    Função assíncrona para inicializar o banco de dados, criar as tabelas
    e garantir que a estrutura esteja atualizada.
    """
    async with aiosqlite.connect('ada.db') as conn:
        cursor = await conn.cursor()
        
        # Criação da tabela tasks (garantindo que a coluna 'status' existe)
        await cursor.execute('''
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                assigned_to TEXT,
                reminder_interval TEXT,
                start_date TEXT,
                due_date TEXT,
                status TEXT
            )
        ''')
        
        # Adiciona a coluna 'status' se ela não existir.
        try:
            await cursor.execute("ALTER TABLE tasks ADD COLUMN status TEXT")
        except aiosqlite.OperationalError as e:
            # A coluna já existe, então não faz nada.
            if "duplicate column name" not in str(e):
                raise
        
        # Criação da tabela clockpoint
        await cursor.execute('''
            CREATE TABLE IF NOT EXISTS clockpoint (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                check_in TEXT,
                check_out TEXT
            )
        ''')
        
        await conn.commit()

async def add_task(title, assigned_to, reminder_interval, start_date, due_date, status="A Fazer"):
    """
    Adiciona uma nova tarefa ao banco de dados.
    """
    async with aiosqlite.connect('ada.db') as conn:
        await conn.execute(
            '''
            INSERT INTO tasks(
                title, assigned_to, reminder_interval,
                start_date, due_date, status
            ) VALUES (?, ?, ?, ?, ?, ?)
            ''',
            (title, assigned_to, reminder_interval, start_date, due_date, status)
        )
        await conn.commit()

async def get_tasks():
    """
    Busca todas as tarefas do banco de dados, incluindo o status.
    """
    async with aiosqlite.connect('ada.db') as conn:
        cursor = await conn.cursor()
        await cursor.execute("SELECT id, title, assigned_to, reminder_interval, start_date, due_date, status FROM tasks")
        return await cursor.fetchall()

async def update_task_start_date(task_id, new_start_date):
    """
    Atualiza a data de início de uma tarefa específica.
    """
    async with aiosqlite.connect('ada.db') as conn:
        await conn.execute(
            "UPDATE tasks SET start_date = ? WHERE id = ?",
            (new_start_date, task_id)
        )
        await conn.commit()

async def update_task_status(task_id, new_status):
    """
    Atualiza o status de uma tarefa.
    """
    async with aiosqlite.connect('ada.db') as conn:
        await conn.execute(
            "UPDATE tasks SET status = ? WHERE id = ?",
            (new_status, task_id)
        )
        await conn.commit()

async def update_task_overdue(task_id, new_status, new_start_date):
    """
    Atualiza o status e a data de início de uma tarefa para gerenciar lembretes de atraso.
    """
    async with aiosqlite.connect('ada.db') as conn:
        await conn.execute(
            "UPDATE tasks SET status = ?, start_date = ? WHERE id = ?",
            (new_status, new_start_date, task_id)
        )
        await conn.commit()
