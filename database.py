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
        
        try:
            await cursor.execute("ALTER TABLE tasks ADD COLUMN status TEXT")
        except aiosqlite.OperationalError as e:
            if "duplicate column name" not in str(e):
                raise
        
        await cursor.execute('''
            CREATE TABLE IF NOT EXISTS clockpoint (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                check_in TEXT,
                check_out TEXT
            )
        ''')
        
        await conn.commit()

#Functions for tasks
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

async def get_tasks_filtered(assigned_to):
    """
    Busca tarefas filtrando pelo usuário ou cargo.
    """
    async with aiosqlite.connect('ada.db') as conn:
        cursor = await conn.execute("SELECT id, title, assigned_to, reminder_interval, start_date, due_date, status FROM tasks WHERE assigned_to = ?", (assigned_to,))
        tasks = await cursor.fetchall()
        return tasks

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
    Atualiza a data de início de uma tarefa.
    """
    async with aiosqlite.connect('ada.db') as conn:
        await conn.execute("UPDATE tasks SET start_date = ? WHERE id = ?", (new_start_date, task_id))
        await conn.commit()

async def update_task_status(task_id, assigned_to, new_status):
    """
    Atualiza o status de uma tarefa com base no ID e no responsável.
    Retorna True se a atualização foi bem-sucedida, False caso contrário.
    """
    async with aiosqlite.connect('ada.db') as conn:
        cursor = await conn.execute("UPDATE tasks SET status = ? WHERE id = ? AND assigned_to = ?", (new_status, task_id, assigned_to))
        await conn.commit()
        return cursor.rowcount > 0

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

async def delete_task(task_id):
    """
    Exclui uma tarefa do banco de dados pelo ID.
    Retorna True se a exclusão foi bem-sucedida, False caso contrário.
    """
    async with aiosqlite.connect('ada.db') as conn:
        cursor = await conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        await conn.commit()
        return cursor.rowcount > 0
    
#Functions for the clockpoint
async def is_user_checked_in(user_id):
    """
    Verifica se o usuário tem um check-in ativo (sem check-out).
    """
    async with aiosqlite.connect('ada.db') as conn:
        cursor = await conn.execute("SELECT 1 FROM clockpoint WHERE user_id = ? AND check_out IS NULL", (user_id,))
        return await cursor.fetchone() is not None

async def add_check_in(user_id, check_in_time):
    """
    Adiciona um novo registro de check-in.
    """
    async with aiosqlite.connect('ada.db') as conn:
        await conn.execute("INSERT INTO clockpoint (user_id, check_in) VALUES (?, ?)", (user_id, check_in_time))
        await conn.commit()

async def add_check_out(user_id, check_out_time):
    """
    Atualiza o último registro de check-in do usuário com o horário de check-out.
    """
    async with aiosqlite.connect('ada.db') as conn:
        await conn.execute("UPDATE clockpoint SET check_out = ? WHERE user_id = ? AND check_out IS NULL", (check_out_time, user_id))
        await conn.commit()

async def get_clockpoint_entries():
    """
    Retorna todos os registros de ponto do banco de dados.
    """
    async with aiosqlite.connect('ada.db') as conn:
        cursor = await conn.execute("SELECT id, user_id, check_in, check_out FROM clockpoint")
        entries = await cursor.fetchall()
        return entries

async def get_clockpoint_entries_by_user(user_id):
    """
    Retorna os registros de ponto de um usuário específico.
    """
    async with aiosqlite.connect('ada.db') as conn:
        cursor = await conn.execute("SELECT id, user_id, check_in, check_out FROM clockpoint WHERE user_id = ?", (user_id,))
        entries = await cursor.fetchall()
        return entries
    
async def get_clockpoint_entry_by_id(entry_id):
    """
    Retorna um registro de ponto específico pelo seu ID.
    """
    async with aiosqlite.connect('ada.db') as conn:
        cursor = await conn.execute("SELECT id, user_id, check_in, check_out FROM clockpoint WHERE id = ?", (entry_id,))
        entry = await cursor.fetchone()
        return entry

    
async def update_check_in_time(entry_id, new_check_in_time):
    """
    Atualiza o horário de check-in de um registro de ponto.
    """
    async with aiosqlite.connect('ada.db') as conn:
        await conn.execute("UPDATE clockpoint SET check_in = ? WHERE id = ?", (new_check_in_time, entry_id))
        await conn.commit()
        
async def update_check_out_time(entry_id, new_check_out_time):
    """
    Atualiza o horário de check-out de um registro de ponto.
    """
    async with aiosqlite.connect('ada.db') as conn:
        await conn.execute("UPDATE clockpoint SET check_out = ? WHERE id = ?", (new_check_out_time, entry_id))
        await conn.commit()
