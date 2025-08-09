import os
import re
from dotenv import load_dotenv
import discord
from discord.ext import commands, tasks
from discord.ext.commands import MemberConverter, RoleConverter
import aiosqlite
import datetime
import pytz
from database import init_db, connect_db, add_task, get_tasks, get_tasks_filtered, update_task_start_date, update_task_status, update_task_overdue, delete_task, is_user_checked_in, add_check_in, add_check_out, get_clockpoint_entries, get_clockpoint_entries_by_user, update_check_in_time, update_check_out_time, get_clockpoint_entry_by_id

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
BR_TZ = pytz.timezone("America/Sao_Paulo")

OVERDUE_INTERVAL = 24 * 60 * 60

REMINDER_CHANNEL_ID = 1403827054251610272

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
    'editar_ponto'
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

#Tasks

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

@bot.command(help="Adiciona uma nova tarefa por cargo ou por usuário.") 
async def add_tarefa (ctx, *, args):
    try:

        things = [p.strip() for p in args.split("|")]

        if len(things) < 6:
            await ctx.send("⚠️ Formato inválido. Use:\n`>add_tarefa título | tipo | responsável | data início | data fim | intervalo do lembrete`")
            return

        title, tp, destiny, start_date, due_date, reminder_interval = things
    
        #Start and Due Date
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
        
        #Reminder Interval
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

        #Atribuittion
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

@bot.command(help="Listar todas as tarefas, ou por cargo, ou por usuário.")
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
            # Tenta resolver para um cargo
            try:
                role = await commands.RoleConverter().convert(ctx, args)
                filter_name = f"@{role.name}"
            except commands.RoleNotFound:
                # Tenta resolver para um membro
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

@bot.command(help="Atualiza o status da tarefa pelo id e pela atribuição.")
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

@bot.command(help="Deleta tarefa por id.")
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

#Clockpoint

@bot.command(help="Começa a contagem do relógio de ponto.")
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

@bot.command(help="Para a contagem do relógio de ponto.")
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

@bot.command(help="Lista todos os pontos ou por usuário.")
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

            # Parse dates and calculate duration
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

@bot.command(help="Edita o check in ou check out pelo id.")
async def editar_ponto(ctx, entry_id: int, tipo_registro: str, *, novo_horario: str):
    """
    Permite que o usuário edite o seu próprio registro de ponto.
    Exemplo de uso: >editar_ponto 1 check_in 20/09/2025 09:00
    """
    try:
        # Pega o registro do ponto pelo ID
        entry = await get_clockpoint_entry_by_id(entry_id)

        if not entry:
            await ctx.send(f"❌ Registro de ponto com ID **{entry_id}** não encontrado.")
            return

        # Verifica se o registro pertence ao usuário que executou o comando
        if str(entry[1]) != str(ctx.author.id):
            await ctx.send("❌ Você só pode editar os seus próprios registros de ponto.")
            return

        # Valida e converte o novo horário
        try:
            new_dt = BR_TZ.localize(datetime.datetime.strptime(novo_horario, "%d/%m/%Y %H:%M"))
            new_dt_iso = new_dt.isoformat()
        except ValueError:
            await ctx.send("❌ Formato de data e hora inválido. Use `DD/MM/AAAA HH:MM`.")
            return

        # Pega o horário atual do registro para validação
        old_check_in_dt = datetime.datetime.fromisoformat(entry[2]).astimezone(BR_TZ)
        old_check_out_str = entry[3]
        old_check_out_dt = datetime.datetime.fromisoformat(old_check_out_str).astimezone(BR_TZ) if old_check_out_str else None

        # Lógica para atualização
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

@tasks.loop(minutes=1)
async def check_reminders():
    """
    Função de loop que verifica e envia lembretes para tarefas.
    """
    print("Verificando lembretes...")
    now = datetime.datetime.now(BR_TZ)
    
    try:
        tasks_list = await get_tasks()
        
        # Encontra o canal de lembretes
        reminder_channel = bot.get_channel(REMINDER_CHANNEL_ID)
        
        if not reminder_channel:
            print(f"❌ Canal com ID {REMINDER_CHANNEL_ID} não encontrado.")
            return

        for task in tasks_list:
            task_id, title, assigned_to, interval_str, start_date_str, due_date_str, status = task
            
            # Se o status da tarefa for "Concluída", pule para a próxima tarefa
            if status == "Concluída":
                continue
            
            start_dt = datetime.datetime.fromisoformat(start_date_str).astimezone(BR_TZ)
            due_dt = datetime.datetime.fromisoformat(due_date_str).astimezone(BR_TZ)
            
            # Formata a menção ao usuário ou cargo para a mensagem
            mention = assigned_to
            if assigned_to.startswith('@'):
                mention = f"<@&{discord.utils.get(reminder_channel.guild.roles, name=assigned_to.lstrip('@')).id}>"
            else:
                mention = f"<@{discord.utils.get(reminder_channel.guild.members, display_name=assigned_to).id}>"


            # Lógica para tarefas atrasadas
            if now > due_dt:
                if status != "Atrasada":
                    # Primeiro lembrete de atraso
                    overdue_message = (
                        f"🚨 **TAREFA ATRASADA!** 🚨\n"
                        f"**{mention}**\n"
                        f"A tarefa **'{title}'** venceu em {due_dt.strftime('%d/%m/%Y %H:%M')}.\n"
                        f"**Responsável:** {assigned_to}"
                    )
                    await reminder_channel.send(overdue_message)
                    
                    # Atualiza o status e a data de início para começar os lembretes diários
                    await update_task_overdue(task_id, "Atrasada", now.isoformat())
                    continue
                
                else:
                    # Lembretes diários para tarefas já atrasadas
                    reminder_interval = OVERDUE_INTERVAL
                    time_passed = (now - start_dt).total_seconds()
                    num_intervals = int(time_passed // reminder_interval)
                    next_reminder_dt = start_dt + datetime.timedelta(seconds=(num_intervals + 1) * reminder_interval)

                    if now >= next_reminder_dt:
                        reminder_message = (
                            f"🔔 **Lembrete de Tarefa (Atrasada)** 🔔\n"
                            f"**{mention}**\n"
                            f"**Título:** {title}\n"
                            f"**Vencimento:** {due_dt.strftime('%d/%m/%Y %H:%M')}\n"
                            f"**Responsável:** {assigned_to}"
                        )
                        await reminder_channel.send(reminder_message)
                        
                        # Atualiza a data de início para o próximo lembrete diário
                        await update_task_start_date(task_id, next_reminder_dt.isoformat())

            # Lógica para tarefas não atrasadas (lembretes periódicos originais)
            else:
                reminder_interval = int(interval_str)
                time_passed = (now - start_dt).total_seconds()
                num_intervals = int(time_passed // reminder_interval)
                next_reminder_dt = start_dt + datetime.timedelta(seconds=num_intervals * reminder_interval)

                if now >= next_reminder_dt:
                    reminder_message = (
                        f"🔔 **Lembrete de Tarefa** 🔔\n"
                        f"**{mention}**\n"
                        f"**Título:** {title}\n"
                        f"**Vencimento:** {due_dt.strftime('%d/%m/%Y %H:%M')}\n"
                        f"**Responsável:** {assigned_to}"
                    )
                    await reminder_channel.send(reminder_message)
                    
                    # Atualiza a data de início para o próximo lembrete periódico
                    new_start_dt = start_dt + datetime.timedelta(seconds=(num_intervals + 1) * reminder_interval)
                    await update_task_start_date(task_id, new_start_dt.isoformat())
    
    except Exception as e:
        print(f"❌ Erro nos lembretes: {e}")

bot.run(TOKEN)    
