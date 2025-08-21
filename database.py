import aiosqlite
import datetime
import pytz

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
                guild_id TEXT NOT NULL,
                title TEXT,
                assigned_to TEXT,
                reminder_interval TEXT,
                start_date TEXT,
                due_date TEXT,
                status TEXT
            )
        ''')
        
        await cursor.execute('''
            CREATE TABLE IF NOT EXISTS clockpoint (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                user_id TEXT,
                check_in TEXT,
                check_out TEXT
            )
        ''')
        
        await cursor.execute('''
            CREATE TABLE IF NOT EXISTS meetings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                participants TEXT,
                topics TEXT,
                check_in_time TEXT,
                check_out_time TEXT
            )
        ''')
        
        await conn.commit()

async def add_task(guild_id, title, assigned_to, reminder_interval, start_date, due_date, status="A Fazer"):
    """
    Adiciona uma nova tarefa ao banco de dados.
    """
    async with aiosqlite.connect('ada.db') as conn:
        await conn.execute(
            '''
            INSERT INTO tasks(
                guild_id, title, assigned_to, reminder_interval,
                start_date, due_date, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ''',
            (guild_id, title, assigned_to, reminder_interval, start_date, due_date, status)
        )
        await conn.commit()

async def get_tasks_filtered(guild_id, assigned_to):
    """
    Busca tarefas filtrando pelo usuário ou cargo.
    """
    async with aiosqlite.connect('ada.db') as conn:
        cursor = await conn.execute(
            "SELECT id, guild_id, title, assigned_to, reminder_interval, start_date, due_date, status FROM tasks WHERE guild_id = ? AND assigned_to = ?",
            (guild_id, assigned_to)
        )
        tasks = await cursor.fetchall()
        return tasks

async def get_tasks(guild_id):
    """
    Busca todas as tarefas do servidor específico.
    """
    async with aiosqlite.connect('ada.db') as conn:
        cursor = await conn.cursor()
        await cursor.execute(
            "SELECT id, guild_id, title, assigned_to, reminder_interval, start_date, due_date, status FROM tasks WHERE guild_id = ?",
            (guild_id,)
        )
        return await cursor.fetchall()

async def update_task_start_date(guild_id, task_id, new_start_date):
    """
    Atualiza a data de início de uma tarefa.
    """
    async with aiosqlite.connect('ada.db') as conn:
        await conn.execute(
            "UPDATE tasks SET start_date = ? WHERE id = ? AND guild_id = ?", 
            (new_start_date, task_id, guild_id)
        )
        await conn.commit()

async def update_task_status(guild_id, task_id, assigned_to, new_status):
    """
    Atualiza o status de uma tarefa com base no ID e no responsável.
    Retorna True se a atualização foi bem-sucedida, False caso contrário.
    """
    async with aiosqlite.connect('ada.db') as conn:
        cursor = await conn.execute(
            "UPDATE tasks SET status = ? WHERE id = ? AND assigned_to = ? AND guild_id = ?", 
            (new_status, task_id, assigned_to, guild_id)
        )
        await conn.commit()
        return cursor.rowcount > 0

async def update_task_overdue(guild_id, task_id, new_status, new_start_date):
    """
    Atualiza o status e a data de início de uma tarefa para gerenciar lembretes de atraso.
    """
    async with aiosqlite.connect('ada.db') as conn:
        await conn.execute(
            "UPDATE tasks SET status = ?, start_date = ? WHERE id = ? AND guild_id = ?",
            (new_status, new_start_date, task_id, guild_id)
        )
        await conn.commit()

async def delete_task(guild_id, task_id):
    """
    Exclui uma tarefa do banco de dados pelo ID.
    Retorna True se a exclusão foi bem-sucedida, False caso contrário.
    """
    async with aiosqlite.connect('ada.db') as conn:
        cursor = await conn.execute(
            "DELETE FROM tasks WHERE id = ? AND guild_id = ?", 
            (task_id, guild_id)
        )
        await conn.commit()
        return cursor.rowcount > 0
    
async def is_user_checked_in(guild_id, user_id):
    """
    Verifica se o usuário tem um check-in ativo (sem check-out).
    """
    async with aiosqlite.connect('ada.db') as conn:
        cursor = await conn.execute(
            "SELECT 1 FROM clockpoint WHERE guild_id = ? AND user_id = ? AND check_out IS NULL", 
            (guild_id, user_id)
        )
        return await cursor.fetchone() is not None

async def add_check_in(guild_id, user_id, check_in_time):
    """
    Adiciona um novo registro de check-in.
    """
    async with aiosqlite.connect('ada.db') as conn:
        await conn.execute(
            "INSERT INTO clockpoint (guild_id, user_id, check_in) VALUES (?, ?, ?)", 
            (guild_id, user_id, check_in_time)
        )
        await conn.commit()

async def add_check_out(guild_id, user_id, check_out_time):
    """
    Atualiza o último registro de check-in do usuário com o horário de check-out.
    """
    async with aiosqlite.connect('ada.db') as conn:
        await conn.execute(
            "UPDATE clockpoint SET check_out = ? WHERE guild_id = ? AND user_id = ? AND check_out IS NULL", 
            (check_out_time, guild_id, user_id)
        )
        await conn.commit()

async def get_clockpoint_entries(guild_id):
    """
    Retorna todos os registros de ponto do servidor específico.
    """
    async with aiosqlite.connect('ada.db') as conn:
        cursor = await conn.cursor()
        await cursor.execute(
            "SELECT id, user_id, check_in, check_out FROM clockpoint WHERE guild_id = ?",
            (guild_id,)
        )
        entries = await cursor.fetchall()
        return entries

async def get_clockpoint_entries_by_user(guild_id, user_id):
    """
    Retorna os registros de ponto de um usuário específico no servidor.
    """
    async with aiosqlite.connect('ada.db') as conn:
        cursor = await conn.execute(
            "SELECT id, user_id, check_in, check_out FROM clockpoint WHERE guild_id = ? AND user_id = ?", 
            (guild_id, user_id)
        )
        entries = await cursor.fetchall()
        return entries
    
async def get_clockpoint_entry_by_id(guild_id, entry_id):
    """
    Retorna um registro de ponto específico pelo seu ID.
    """
    async with aiosqlite.connect('ada.db') as conn:
        cursor = await conn.execute(
            "SELECT id, user_id, check_in, check_out FROM clockpoint WHERE id = ? AND guild_id = ?", 
            (entry_id, guild_id)
        )
        entry = await cursor.fetchone()
        return entry

async def update_check_in_time(guild_id, entry_id, new_check_in_time):
    """
    Atualiza o horário de check-in de um registro de ponto.
    """
    async with aiosqlite.connect('ada.db') as conn:
        await conn.execute(
            "UPDATE clockpoint SET check_in = ? WHERE id = ? AND guild_id = ?", 
            (new_check_in_time, entry_id, guild_id)
        )
        await conn.commit()
        
async def update_check_out_time(guild_id, entry_id, new_check_out_time):
    """
    Atualiza o horário de check-out de um registro de ponto.
    """
    async with aiosqlite.connect('ada.db') as conn:
        await conn.execute(
            "UPDATE clockpoint SET check_out = ? WHERE id = ? AND guild_id = ?", 
            (new_check_out_time, entry_id, guild_id)
        )
        await conn.commit()

async def delete_clockpoint_by_id(guild_id, point_id):
    """
    Deleta um ponto de relógio pelo seu ID.
    """
    async with aiosqlite.connect('ada.db') as conn:
        cursor = await conn.cursor()
        await cursor.execute(
            "DELETE FROM clockpoint WHERE id = ? AND guild_id = ?", 
            (point_id, guild_id)
        )
        await conn.commit()
        return cursor.rowcount

async def add_meeting_check_in(guild_id, participants):
    """
    Registra o início de uma reunião para múltiplos participantes.
    """
    async with aiosqlite.connect('ada.db') as conn:
        check_in_time = datetime.datetime.now(pytz.timezone("America/Sao_Paulo")).isoformat()
        await conn.execute(
            "INSERT INTO meetings (guild_id, participants, topics, check_in_time) VALUES (?, ?, ?, ?)",
            (guild_id, participants, "", check_in_time)
        )
        await conn.commit()
        
async def add_meeting_topic(guild_id, meeting_id, new_topics):
    """
    Adiciona novos tópicos à reunião existente.
    """
    async with aiosqlite.connect('ada.db') as conn:
        cursor = await conn.execute(
            "SELECT topics FROM meetings WHERE id = ? AND guild_id = ?", 
            (meeting_id, guild_id)
        )
        existing_topics_tuple = await cursor.fetchone()
        existing_topics = existing_topics_tuple[0] if existing_topics_tuple else ""

        if existing_topics:
            updated_topics = f"{existing_topics}, {new_topics}"
        else:
            updated_topics = new_topics
        
        await conn.execute(
            "UPDATE meetings SET topics = ? WHERE id = ? AND guild_id = ?",
            (updated_topics, meeting_id, guild_id)
        )
        await conn.commit()

async def get_active_meeting_by_user(guild_id, user_id):
    """
    Busca a reunião ativa (sem check_out_time) em que um utilizador é participante.
    """
    async with aiosqlite.connect('ada.db') as conn:
        cursor = await conn.execute(
            "SELECT id, participants, topics, check_in_time FROM meetings WHERE guild_id = ? AND participants LIKE ? AND check_out_time IS NULL",
            (guild_id, f"%{user_id}%")
        )
        return await cursor.fetchone()

async def update_meeting_check_out(guild_id, meeting_id):
    """
    Registra o fim de uma reunião.
    """
    async with aiosqlite.connect('ada.db') as conn:
        check_out_time = datetime.datetime.now(pytz.timezone("America/Sao_Paulo")).isoformat()
        await conn.execute(
            "UPDATE meetings SET check_out_time = ? WHERE id = ? AND guild_id = ?",
            (check_out_time, meeting_id, guild_id)
        )
        await conn.commit()

async def get_all_meetings(guild_id):
    """
    Busca todas as reuniões do servidor específico.
    """
    async with aiosqlite.connect('ada.db') as conn:
        cursor = await conn.cursor()
        await cursor.execute(
            "SELECT id, participants, topics, check_in_time, check_out_time FROM meetings WHERE guild_id = ? ORDER BY check_in_time DESC",
            (guild_id,)
        )
        return await cursor.fetchall()

async def get_meetings_by_user(guild_id, user_id):
    """
    Busca todas as reuniões em que um utilizador específico participou no servidor.
    """
    async with aiosqlite.connect('ada.db') as conn:
        cursor = await conn.cursor()
        await cursor.execute(
            "SELECT id, participants, topics, check_in_time, check_out_time FROM meetings WHERE guild_id = ? AND participants LIKE ? ORDER BY check_in_time DESC",
            (guild_id, f"%{user_id}%")
        )
        return await cursor.fetchall()
    
async def delete_meeting_by_id(guild_id, meeting_id):
    """
    Deleta uma reunião pelo ID.
    """
    async with aiosqlite.connect('ada.db') as conn:
        cursor = await conn.cursor()
        await cursor.execute(
            "DELETE FROM meetings WHERE id = ? AND guild_id = ?", 
            (meeting_id, guild_id)
        )
        await conn.commit()
        return cursor.rowcount
    
