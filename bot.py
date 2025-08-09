import os
import re
from dotenv import load_dotenv
import discord
from discord.ext import commands, tasks
from discord.ext.commands import MemberConverter, RoleConverter
import aiosqlite
import datetime
import pytz
from database import init_db, connect_db, add_task, get_tasks, update_task_start_date, update_task_status, update_task_overdue

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


intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix=">", intents=intents)

@bot.event
async def on_ready():
    print(f"Connected sucessfully as {bot.user}")
    await init_db()
    check_reminders.start()

@bot.command()
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
        print(f"❌ Erro na tarefa de lembretes: {e}")

bot.run(TOKEN)    
