import os
import re
from dotenv import load_dotenv
import discord
from discord.ext import commands, tasks
from discord.ext.commands import MemberConverter, RoleConverter
import aiosqlite
import datetime
import pytz
from database import (
    init_db, connect_db, add_task, get_tasks, update_task_start_date,
    delete_clockpoint_by_id, update_task_status,
    add_meeting_check_in, get_active_meeting_by_user, update_meeting_check_out,
    add_meeting_topic, get_all_meetings, get_meetings_by_user, get_tasks_filtered,
    delete_task, is_user_checked_in, add_check_in, add_check_out, get_clockpoint_entries_by_user,
    get_clockpoint_entries, get_clockpoint_entry_by_id, update_check_in_time, update_task_overdue,
    update_check_out_time, delete_meeting_by_id
)

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
BR_TZ = pytz.timezone("America/Sao_Paulo")

OVERDUE_INTERVAL = 24 * 60 * 60

TIME_UNITS = {
    'semana': 7 * 24 * 60 * 60,
    'semanas': 7 * 24 * 60 * 60,
    'mes': 30 * 24 * 60 * 60,
    'meses': 30 * 24 * 60 * 60,
    'dia': 24 * 60 * 60,
    'dias': 24 * 60 * 60,
    'hora': 60 * 60,
    'horas': 60 * 60,
    'minuto': 60,
    'minutos': 60,
}

COMMAND_ORDER = [
    'ajuda',
    'add_tarefa',
    'list_tarefas',
    'update_status',
    'delete_tarefa',
    'check_in',
    'check_out',
    'list_ponto',
    'editar_ponto',

]

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix=">", intents=intents)

bot.remove_command('help')

@bot.event
async def on_ready():
    print(f"Connected sucessfully as {bot.user}")
    await init_db()
    check_reminders.start()


@bot.command(help="Mostra esta mensagem de ajuda com todos os comandos disponíveis.")
async def ajuda(ctx):
    """
    Mostra esta mensagem de ajuda com todos os comandos disponíveis.
    A ordem de exibição é definida na lista COMMAND_ORDER.
    """
    embed = discord.Embed(
        title="🤖 Comandos do Bot de Gerenciamento",
        description="Aqui estão todos os comandos que você pode usar:",
        color=discord.Color.green()
    )

    for command_name in COMMAND_ORDER:
        command = bot.get_command(command_name)
        if command and not command.hidden:
            embed.add_field(
                name=f"`>{command.name}`",
                value=f"{command.help}",
                inline=False
            )
    
    await ctx.send(embed=embed)

@bot.command(help="Adiciona uma nova tarefa por cargo ou por usuário, define a data de inicio e término e o tempo de intervalo entre lembretes. Ex: >add_tarefa 'Exemplo' | usuario | @usuario  |  18/09/2025 08:30 | 15/10/2025 23:59 | 1 dia ou >add_tarefa 'Exemplo' | cargo | @cargo  |  18/09/2025 08:30 | 15/10/2025 23:59 | 1 dia") 
async def add_tarefa (ctx, *, args):
    """
    Adiciona uma nova tarefA.
    TÍTULO | TIPO | CARGO | @ | DATA DE INÍCIO | DATA DE TÉRMINO | INTERVALO DE LEMBRETES
    """
    try:

        things = [p.strip() for p in args.split("|")]

        if len(things) < 6:
            await ctx.send("⚠️ Formato inválido. Use:\n`>add_tarefa título | tipo | responsável | data início | data fim | intervalo do lembrete`")
            return

        title, tp, destiny, start_date, due_date, reminder_interval = things
        try:
            start_dt = BR_TZ.localize(datetime.datetime.strptime(start_date, "%d/%m/%Y %H:%M"))
            if start_dt < datetime.datetime.now(BR_TZ):
                await ctx.send("❌ Data de início não pode ser retroativa!")
                return
        except ValueError:
            await ctx.send("❌ Data de início inválida. Use DD/MM/AAAA HH:MM.")
            return
        
        try:
            due_dt = BR_TZ.localize(datetime.datetime.strptime(due_date, "%d/%m/%Y %H:%M"))
            if due_dt <= start_dt:
                await ctx.send("❌ Data de término deve ser depois da data de início.")
                return
        except ValueError:
            await ctx.send("❌ Data de término inválida. Use DD/MM/AAAA HH:MM.")
            return
        
        frequency_in_seconds = None
        
        match = re.search(r'(\d+)\s*(semanas?|meses?|dias?|horas?|minutos?)', reminder_interval, re.IGNORECASE)

        if match:
            number = int(match.group(1))
            text_unit = match.group(2).lower()
            
            if text_unit in TIME_UNITS:
                frequency_in_seconds = number * TIME_UNITS[text_unit]
            else:
                await ctx.send("❌ Unidade de tempo inválida. Use 'semana(s)', 'mes(es)', 'dia(s)', 'hora(s) ou minuto(s)'.")
                return
        else:
            await ctx.send("❌ Formato de intervalo inválido. Use, por exemplo: `2 semanas`, `3 dias`, `1 mes`, `12 horas` ou `3 minutos`.")
            return

        name_destiny = None
        if tp.lower() == "usuario":
            try:
                destiny_member = await commands.MemberConverter().convert(ctx, destiny)
                name_destiny = destiny_member.display_name
            except commands.MemberNotFound:
                await ctx.send(f"❌ Usuário '{destiny}' não encontrado no servidor.")
                return
        elif tp.lower() == "cargo":
            try:
                destiny_role = await commands.RoleConverter().convert(ctx, destiny)
                name_destiny = f"@{destiny_role.name}"
            except commands.RoleNotFound:
                await ctx.send(f"❌ Cargo '{destiny}' não encontrado no servidor.")
                return
        else:
            await ctx.send("❌ Você precisa colocar o tipo da atribuição. Use 'usuario' ou 'cargo'.")
            return
        
        
        conn = await connect_db()
        cursor = await conn.cursor()
        
        start_dt_str = start_dt.isoformat()
        due_dt_str = due_dt.isoformat()
        
        await cursor.execute(
            '''
            INSERT INTO tasks(
                title, assigned_to, reminder_interval,
                start_date, due_date, status
            ) VALUES (?, ?, ?, ?, ?, ?)
            ''',
            (
                title,
                name_destiny,
                str(frequency_in_seconds),
                start_dt_str,
                due_dt_str,
                "A Fazer",
            )
        )
        await conn.commit()
        await conn.close()
        
        await ctx.send(f"✅ Tarefa **'{title}'** criada com sucesso e atribuída a {name_destiny}.")
        
    except Exception as e:
        await ctx.send(f"❌ Erro ao criar a tarefa: {e}")

@bot.command(help="Listar todas as tarefas, ou por cargo, ou por usuário. Ex: >list_tarefas ou >list_tarefas @usuario ou >list_tarefas @cargo ")
async def list_tarefas(ctx, *, args=None):
    """
    Comando para listar todas as tarefas ou filtrar por usuário/cargo.
    Exemplo de uso:
    - >list_tarefas                 (Lista todas as tarefas)
    - >list_tarefas @nome_do_cargo (Lista tarefas de um cargo)
    - >list_tarefas nome_do_usuario (Lista tarefas de um usuário)
    """
    try:
        tasks_list = []
        filter_name = None

        if args:
            try:
                role = await commands.RoleConverter().convert(ctx, args)
                filter_name = f"@{role.name}"
            except commands.RoleNotFound:
                try:
                    member = await commands.MemberConverter().convert(ctx, args)
                    filter_name = member.display_name
                except commands.MemberNotFound:
                    await ctx.send(f"❌ Não foi possível encontrar um usuário ou cargo com o nome '{args}'.")
                    return
        
        if filter_name:
            tasks_list = await get_tasks_filtered(filter_name)
            title = f"Tarefas para {filter_name}"
        else:
            tasks_list = await get_tasks()
            title = "Todas as Tarefas"
        
        if not tasks_list:
            await ctx.send(f"Não há tarefas para exibir.")
            return

        embed = discord.Embed(
            title=title,
            color=discord.Color.blue()
        )
        
        for task in tasks_list:
            task_id, task_title, assigned_to, _, _, due_date_str, status = task
            due_dt = datetime.datetime.fromisoformat(due_date_str).astimezone(BR_TZ)
            due_date_formatted = due_dt.strftime('%d/%m/%Y %H:%M')
            
            embed.add_field(
                name=f"📝 {task_title} (ID: {task_id})",
                value=f"**Responsável:** {assigned_to}\n**Vencimento:** {due_date_formatted}\n**Status:** {status}",
                inline=False
            )
            
        await ctx.send(embed=embed)

    except Exception as e:
        await ctx.send(f"❌ Ocorreu um erro ao listar as tarefas: {e}")

@bot.command(help="Atualiza o status da tarefa pelo id e pela atribuição. Ex: >update_status id @ A Fazer ou >update_status id @ Em Andamento ou >update_status id @ Conluída")
async def update_status(ctx, task_id: int, destiny: str, *, status: str):
    """
    Comando para atualizar o status de uma tarefa com base no ID e no responsável.
    Status válidos: "A Fazer", "Em Andamento", "Concluída".
    Exemplo de uso: >update_status 1 @Cargo Concluída
    """
    valid_statuses = ["A Fazer", "Em Andamento", "Concluída"]
    
    if status not in valid_statuses:
        await ctx.send(f"❌ Status inválido. Use um dos seguintes: {', '.join(valid_statuses)}")
        return

    name_destiny = None
    try:
        role = await commands.RoleConverter().convert(ctx, destiny)
        name_destiny = f"@{role.name}"
    except commands.RoleNotFound:
        try:
            member = await commands.MemberConverter().convert(ctx, destiny)
            name_destiny = member.display_name
        except commands.MemberNotFound:
            await ctx.send(f"❌ Não foi possível encontrar um usuário ou cargo com o nome '{destiny}'.")
            return
            
    if name_destiny:
        try:
            success = await update_task_status(task_id, name_destiny, status)
            if success:
                await ctx.send(f"✅ O status da tarefa com ID **{task_id}** (atribuída a {name_destiny}) foi atualizado para **{status}**.")
            else:
                await ctx.send(f"❌ Não foi possível encontrar a tarefa com ID **{task_id}** atribuída a {name_destiny}.")
        except Exception as e:
            await ctx.send(f"❌ Ocorreu um erro ao atualizar o status da tarefa: {e}")

@bot.command(help="Administrador do servidor deleta tarefa por id. Ex: >deleta_tarefa id")
@commands.has_permissions(administrator=True)
async def delete_tarefa(ctx, task_id: int):
    """
    Comando para excluir uma tarefa pelo ID. Apenas para administradores.
    Exemplo de uso: >delete_tarefa 1
    """
    try:
        success = await delete_task(task_id)
        if success:
            await ctx.send(f"✅ Tarefa com ID **{task_id}** excluída com sucesso.")
        else:
            await ctx.send(f"❌ Não foi possível encontrar a tarefa com ID **{task_id}**.")
    except Exception as e:
        await ctx.send(f"❌ Ocorreu um erro ao excluir a tarefa: {e}")

@bot.command(help="Começa a contagem do relógio de ponto. Ex: >check_in")
async def check_in(ctx):
    """
    Comando para registrar o início do expediente.
    Exemplo de uso: >check_in
    """
    user_id = str(ctx.author.id)
    now = datetime.datetime.now(BR_TZ)
    
    if await is_user_checked_in(user_id):
        await ctx.send("⏰ Você já está com um check-in ativo.")
        return

    try:
        await add_check_in(user_id, now.isoformat())
        await ctx.send(f"✅ **Check-in** registrado com sucesso em: **{now.strftime('%H:%M:%S')}**.")
    except Exception as e:
        await ctx.send(f"❌ Ocorreu um erro ao registrar o check-in: {e}")

@bot.command(help="Para a contagem do relógio de ponto. Ex: >check_out")
async def check_out(ctx):
    """
    Comando para registrar o fim do expediente.
    Exemplo de uso: >check_out
    """
    user_id = str(ctx.author.id)
    now = datetime.datetime.now(BR_TZ)
    
    if not await is_user_checked_in(user_id):
        await ctx.send("❌ Você não tem um check-in ativo para registrar o check-out.")
        return
        
    try:
        await add_check_out(user_id, now.isoformat())
        await ctx.send(f"✅ **Check-out** registrado com sucesso em: **{now.strftime('%H:%M:%S')}**.")
    except Exception as e:
        await ctx.send(f"❌ Ocorreu um erro ao registrar o check-out: {e}")

@bot.command(help="Lista todos os pontos ou por usuário. Ex: >list_ponto ou >list_ponto @usuario")
async def list_ponto(ctx, member: discord.Member = None):
    """
    Comando para listar os registros de ponto.
    Exemplo de uso:
    - >list_ponto
    - >list_ponto @usuario
    """
    try:
        entries = []
        if member:
            entries = await get_clockpoint_entries_by_user(str(member.id))
            title = f"Registros de Ponto para {member.display_name}"
        else:
            entries = await get_clockpoint_entries()
            title = "Todos os Registros de Ponto"

        if not entries:
            await ctx.send(f"Não há registros de ponto para exibir.")
            return

        embed = discord.Embed(
            title=title,
            color=discord.Color.gold()
        )

        for entry_id, user_id, check_in_str, check_out_str in entries:
            user = await bot.fetch_user(int(user_id))
            user_name = user.display_name if user else "Usuário Desconhecido"

            check_in_dt = datetime.datetime.fromisoformat(check_in_str).astimezone(BR_TZ)
            check_out_dt = None
            duration_str = "Em andamento"

            if check_out_str:
                check_out_dt = datetime.datetime.fromisoformat(check_out_str).astimezone(BR_TZ)
                duration = check_out_dt - check_in_dt
                hours, remainder = divmod(duration.total_seconds(), 3600)
                minutes, _ = divmod(remainder, 60)
                duration_str = f"{int(hours)}h {int(minutes)}m"

            embed.add_field(
                name=f"👤 {user_name} (ID do Ponto: {entry_id})",
                value=f"**Entrada:** {check_in_dt.strftime('%d/%m/%Y %H:%M')}\n**Saída:** {check_out_dt.strftime('%d/%m/%Y %H:%M') if check_out_dt else 'N/A'}\n**Duração:** {duration_str}",
                inline=False
            )

        await ctx.send(embed=embed)
    except Exception as e:
        await ctx.send(f"❌ Ocorreu um erro ao listar os registros: {e}")

@bot.command(help="Edita o check in ou check out pelo id. Ex: >editar_ponto check_in id data e horario ou >editar_ponto checkout id data e horario")
async def editar_ponto(ctx, entry_id: int, tipo_registro: str, *, novo_horario: str):
    """
    Permite que o usuário edite o seu próprio registro de ponto.
    Exemplo de uso: >editar_ponto 1 check_in 20/09/2025 09:00
    """
    try:
        entry = await get_clockpoint_entry_by_id(entry_id)

        if not entry:
            await ctx.send(f"❌ Registro de ponto com ID **{entry_id}** não encontrado.")
            return

        if str(entry[1]) != str(ctx.author.id):
            await ctx.send("❌ Você só pode editar os seus próprios registros de ponto.")
            return

        try:
            new_dt = BR_TZ.localize(datetime.datetime.strptime(novo_horario, "%d/%m/%Y %H:%M"))
            new_dt_iso = new_dt.isoformat()
        except ValueError:
            await ctx.send("❌ Formato de data e hora inválido. Use `DD/MM/AAAA HH:MM`.")
            return

        old_check_in_dt = datetime.datetime.fromisoformat(entry[2]).astimezone(BR_TZ)
        old_check_out_str = entry[3]
        old_check_out_dt = datetime.datetime.fromisoformat(old_check_out_str).astimezone(BR_TZ) if old_check_out_str else None

        tipo_registro = tipo_registro.lower()
        if tipo_registro == "check_in":
            if old_check_out_dt and new_dt > old_check_out_dt:
                await ctx.send("❌ O novo horário de check-in não pode ser depois do check-out existente.")
                return
            await update_check_in_time(entry_id, new_dt_iso)
            await ctx.send(f"✅ O check-in do registro **{entry_id}** foi atualizado para **{new_dt.strftime('%d/%m/%Y %H:%M')}**.")
        elif tipo_registro == "check_out":
            if new_dt < old_check_in_dt:
                await ctx.send("❌ O novo horário de check-out não pode ser antes do check-in existente.")
                return
            await update_check_out_time(entry_id, new_dt_iso)
            await ctx.send(f"✅ O check-out do registro **{entry_id}** foi atualizado para **{new_dt.strftime('%d/%m/%Y %H:%M')}**.")
        else:
            await ctx.send("❌ Tipo de registro inválido. Use 'check_in' ou 'check_out'.")
    except Exception as e:
        await ctx.send(f"❌ Ocorreu um erro ao editar o registro de ponto: {e}")

@commands.has_permissions(administrator=True)
@bot.command()(help="Administrador do servidor deleta o ponto por id. Ex: >delete_ponto 15")
async def delete_ponto(ctx, point_id: int):
    """
    Deleta um registro de ponto pelo seu ID. Apenas administradores podem usar.
    Exemplo de uso: >delete_ponto 15
    """
    try:
        rows_deleted = await delete_clockpoint_by_id(point_id)
        if rows_deleted > 0:
            await ctx.send(f"✅ Registro de ponto com ID **{point_id}** deletado com sucesso.")
        else:
            await ctx.send(f"⚠️ Nenhum registro de ponto encontrado com o ID **{point_id}**.")
    except Exception as e:
        await ctx.send(f"❌ Ocorreu um erro ao deletar o registro: {e}")

@bot.command()(help="Começa a contagem do tempo de reunião. Ex: >check_in_reuniao @Fulano @Ciclano @Beltrano")
async def check_in_reuniao(ctx, *members: discord.Member):
    """
    Comando para iniciar uma reunião com outros membros.
    Exemplo de uso: >check_in_reuniao @utilizador1 @utilizador2
    """
    participants_list = list(members) + [ctx.author]
    participants_list = list(set(participants_list))
    
    participants_ids = ",".join([str(m.id) for m in participants_list])
    
    active_meeting = await get_active_meeting_by_user(str(ctx.author.id))
    
    if active_meeting:
        await ctx.send("❌ Você já está em uma reunião. Use `>check_out` para finalizar.")
        return
        
    try:
        await add_meeting_check_in(participants_ids)
        participants_names = [m.display_name for m in participants_list]
        await ctx.send(f"✅ Reunião iniciada com os participantes: **{', '.join(participants_names)}**. Use `>add_topico` para adicionar tópicos.")
    except Exception as e:
        await ctx.send(f"❌ Ocorreu um erro ao iniciar a reunião: {e}")

@bot.command()(help="Quem está na reunião pode adicionar tópicos que foram mencionados. Ex: >add_topico Planejamento")
async def add_topico(ctx, *, topics: str):
    """
    Adiciona tópicos à sua reunião ativa. Qualquer participante pode usar.
    Exemplo de uso: >add_topico tópico 1, tópico 2, tópico 3
    """
    user_id = str(ctx.author.id)
    active_meeting = await get_active_meeting_by_user(user_id)

    if not active_meeting:
        await ctx.send("❌ Você não está em uma reunião ativa. Use `>check_in_meet` para iniciar uma.")
        return
    
    meeting_id = active_meeting[0]
    
    try:
        await add_meeting_topic(meeting_id, topics)
        await ctx.send(f"✅ Tópicos **`{topics}`** adicionados à reunião.")
    except Exception as e:
        await ctx.send(f"❌ Ocorreu um erro ao adicionar os tópicos: {e}")

@bot.command()(help="Comando para finalizar a reunião. Qualquer participante pode usar. Ex: >check_out_reuniao")
async def check_out_reuniao(ctx):
    """
    Comando para finalizar a reunião atual. Qualquer participante pode usar.
    """
    user_id = str(ctx.author.id)
    active_meeting_data = await get_active_meeting_by_user(user_id)
    
    if not active_meeting_data:
        await ctx.send("❌ Você não está em uma reunião ativa. Use `>check_in` para iniciar uma.")
        return
        
    meeting_id, participants_str, topics, check_in_time_str = active_meeting_data
    
    check_in_time = datetime.datetime.fromisoformat(check_in_time_str).astimezone(BR_TZ)
    now = datetime.datetime.now(BR_TZ)
    duration = now - check_in_time
    hours, remainder = divmod(duration.total_seconds(), 3600)
    minutes, seconds = divmod(remainder, 60)
    duration_str = f"{int(hours)}h {int(minutes)}m {int(seconds)}s"

    participants_ids = participants_str.split(',')
    participants_mentions = [f"<@{uid}>" for uid in participants_ids]
    
    try:
        await update_meeting_check_out(meeting_id)
        
        await ctx.send(
            f"✅ **{ctx.author.display_name}** finalizou a reunião.\n"
            f"**Início:** {check_in_time.strftime('%H:%M:%S')}\n"
            f"**Duração:** {duration_str}\n"
            f"**Participantes:** {', '.join(participants_mentions)}\n"
            f"**Tópicos:** `{topics}`"
        )
    except Exception as e:
        await ctx.send(f"❌ Ocorreu um erro ao finalizar a reunião: {e}")

@bot.command()(help="Comando para listar todas as reuniões ou por usuário. Ex: >list_reuniao ou >list_reuniao @usuario")
async def list_reuniao(ctx, member: discord.Member = None):
    """
    Lista todas as reuniões ou as reuniões de um utilizador específico.
    Exemplos de uso:
    >list_reuniao        (lista todas as reuniões)
    >list_reuniao @usuario  (lista as reuniões de um utilizador específico)
    """
    try:
        if member:
            meetings = await get_meetings_by_user(str(member.id))
            if not meetings:
                await ctx.send(f"⚠️ Nenhuma reunião encontrada para o utilizador **{member.display_name}**.")
                return
            title_text = f"Histórico de Reuniões de {member.display_name}"
        else:
            meetings = await get_all_meetings()
            if not meetings:
                await ctx.send("⚠️ Nenhuma reunião encontrada no histórico.")
                return
            title_text = "Histórico de Reuniões"

        embed = discord.Embed(title=title_text, color=discord.Color.blue())
        for meeting in meetings:
            meeting_id, participants_str, topics, check_in_time_str, check_out_time_str = meeting
            
            participants_ids = participants_str.split(',')
            participants_names = []
            for uid in participants_ids:
                m = ctx.guild.get_member(int(uid))
                participants_names.append(m.display_name if m else f"ID: {uid}")
            
            check_in_time = datetime.datetime.fromisoformat(check_in_time_str).astimezone(BR_TZ)
            duration_str = "Em andamento"
            if check_out_time_str:
                check_out_time = datetime.datetime.fromisoformat(check_out_time_str).astimezone(BR_TZ)
                duration = check_out_time - check_in_time
                hours, remainder = divmod(duration.total_seconds(), 3600)
                minutes, seconds = divmod(remainder, 60)
                duration_str = f"{int(hours)}h {int(minutes)}m {int(seconds)}s"

            embed.add_field(
                name=f"Reunião #{meeting_id}",
                value=(
                    f"**Início:** {check_in_time.strftime('%d/%m/%Y %H:%M:%S')}\n"
                    f"**Duração:** {duration_str}\n"
                    f"**Participantes:** {', '.join(participants_names)}\n"
                    f"**Tópicos:** {topics or 'Nenhum'}"
                ),
                inline=False
            )
        await ctx.send(embed=embed)
    except Exception as e:
        await ctx.send(f"❌ Ocorreu um erro ao listar as reuniões: {e}")

@commands.has_permissions(administrator=True)
@bot.command()(help="Administradores do servidor podem deletar uma reunião por id. Ex: >delete_reunião 15")
async def delete_reuniao(ctx, meeting_id: int):
    """
    Deleta uma reunião pelo seu ID. Apenas administradores podem usar.
    Exemplo de uso: >delete_meeting 15
    """
    try:
        rows_deleted = await delete_meeting_by_id(meeting_id)
        if rows_deleted > 0:
            await ctx.send(f"✅ Reunião com ID **{meeting_id}** deletada com sucesso.")
        else:
            await ctx.send(f"⚠️ Nenhuma reunião encontrada com o ID **{meeting_id}**.")
    except Exception as e:
        await ctx.send(f"❌ Ocorreu um erro ao deletar a reunião: {e}")

@tasks.loop(minutes=1)
async def check_reminders():
    """
    Função de loop que verifica e envia lembretes para tarefas.
    - Se uma tarefa estiver "Em Andamento", envia lembretes periódicos.
    - Se a tarefa estiver atrasada, a mensagem de lembrete será alterada.
    """
    print("Verificando lembretes...")
    now = datetime.datetime.now(BR_TZ)
    
    try:
        tasks = await get_tasks()
        
        for task in tasks:
            task_id, title, assigned_to, interval_str, start_date_str, due_date_str, status = task
            
            start_dt = datetime.datetime.fromisoformat(start_date_str).astimezone(BR_TZ)
            due_dt = datetime.datetime.fromisoformat(due_date_str).astimezone(BR_TZ)
            
            if status == "Em Andamento":
                reminder_interval = int(interval_str)
                
                next_reminder_dt = start_dt
                while next_reminder_dt < now:
                    next_reminder_dt += datetime.timedelta(seconds=reminder_interval)
                
                if next_reminder_dt - datetime.timedelta(seconds=reminder_interval) <= now <= next_reminder_dt:
                    destiny = None
                    user_found = discord.utils.get(bot.get_all_members(), display_name=assigned_to)
                    if user_found:
                        destiny = user_found
                    else:
                        role_name = assigned_to.lstrip('@')
                        for guild in bot.guilds:
                            role_found = discord.utils.get(guild.roles, name=role_name)
                            if role_found:
                                destiny = role_found
                                break

                    if destiny:
                        is_overdue = now > due_dt
                        
                        if is_overdue:
                            reminder_message = (
                                f"🚨 **TAREFA ATRASADA!** 🚨\n"
                                f"A tarefa **'{title}'** venceu em {due_dt.strftime('%d/%m/%Y %H:%M')}.\n"
                                f"**Responsável:** {assigned_to}\n"
                                f"Este é um lembrete periódico de atraso."
                            )
                        else:
                            reminder_message = (
                                f"🔔 **Lembrete de Tarefa** 🔔\n"
                                f"**Título:** {title}\n"
                                f"**Vencimento:** {due_dt.strftime('%d/%m/%Y %H:%M')}\n"
                                f"**Responsável:** {assigned_to}"
                            )
                        
                        if isinstance(destiny, discord.Member):
                            target_channel = next((c for c in destiny.guild.text_channels if c.permissions_for(destiny.guild.me).send_messages), None)
                            if target_channel:
                                await target_channel.send(f"{destiny.mention}\n{reminder_message}")
                        elif isinstance(destiny, discord.Role):
                            target_channel = next((c for c in destiny.guild.text_channels if c.permissions_for(destiny.guild.me).send_messages), None)
                            if target_channel:
                                await target_channel.send(f"{destiny.mention}\n{reminder_message}")

                    await update_task_start_date(task_id, (next_reminder_dt + datetime.timedelta(seconds=reminder_interval)).isoformat())
            
    except Exception as e:
        print(f"❌ Erro na tarefa de lembretes: {e}")

bot.run(TOKEN)    
