import os
import re
import logging
import time
from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from jira import JIRA

# --- Configuração --- #
logging.basicConfig(level=logging.INFO)
load_dotenv()

COMMAND_TO_STATUS = {
    "start": "In Progress",
    "done": "Done",
    "cancel": "Cancel",
    "restart": "Restart",
}

REQUIRED_ENV_VARS = [
    "INCLUDE_CHANNELS",
    "INCLUDE_USERS",
    "SLACK_BOT_TOKEN",
    "SLACK_APP_TOKEN",
    "JIRA_SERVER",
    "JIRA_PROJECT_KEY",
    "JIRA_USERNAME",
    "JIRA_SERVER",
    "JIRA_API_TOKEN",
]
for var in REQUIRED_ENV_VARS:
    if var not in os.environ:
        raise EnvironmentError(f"Missing required environment variable: {var}")
INCLUDE_CHANNELS = os.environ["INCLUDE_CHANNELS"].split(",")
INCLUDE_USERS = os.environ["INCLUDE_USERS"].split(",")

SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
SLACK_APP_TOKEN = os.environ["SLACK_APP_TOKEN"]
JIRA_SERVER = os.environ["JIRA_SERVER"]
JIRA_USERNAME = os.environ["JIRA_USERNAME"]
JIRA_API_TOKEN = os.environ["JIRA_API_TOKEN"]
JIRA_PROJECT_KEY = os.environ["JIRA_PROJECT_KEY"]
JIRA_PARENT_KEY = os.environ.get("JIRA_PARENT_KEY", None)

# --- Fim da Configuração --- #

# Inicialização de Clientes
app = App(token=SLACK_BOT_TOKEN)
jira_options = {'server': JIRA_SERVER}
jira = JIRA(
    options=jira_options,
    basic_auth=(
        JIRA_USERNAME,
        JIRA_API_TOKEN,
    ),
)


def find_jira_key_in_thread(channel, thread_ts, logger):
    """Busca o histórico de uma thread para encontrar a chave do card do Jira."""
    try:
        result = app.client.conversations_replies(channel=channel, ts=thread_ts)
        messages = result.get("messages", [])
        while result.get("has_more", False):
            cursor = result.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break
            next_result = app.client.conversations_replies(channel=channel, ts=thread_ts, cursor=cursor)
            messages.extend(next_result.get("messages", []))
            result = next_result
        for message in result.get("messages", []):
            # Procura pela mensagem específica postada pelo bot
            match = re.search(r"Card criado no Jira:.*?\|([A-Z]+-\d+)>", message.get("text", ""))
            if match:
                jira_key = match.group(1)
                logger.debug(f"Encontrado Jira key '{jira_key}' na thread {thread_ts}")
                return jira_key
    except Exception as e:
        logger.error(f"Erro ao buscar histórico da thread {thread_ts}: {e}")
    return None

def create_jira_card(event, channel_name, logger):
    try:
        user_id = event.get("user")
        user_info = app.client.users_info(user=user_id).get("user", {})
        user_name = user_info.get("real_name", "N/A")
        user_email = user_info.get("profile", {}).get("email", "N/A")

        permalink = app.client.chat_getPermalink(channel=event["channel"], message_ts=event["ts"])["permalink"]
        message_text = event.get("text", "")
        description = (
            f"Solicitação de: {user_name} ({user_email})\n"
            f"Thread no Slack: {permalink}\n\n"
            f"Mensagem: {message_text}"
        )

        clean_message_text = re.sub(r'[^a-zA-Z0-9 ]', '', message_text)
        issue_dict = {
            'project': {'key': JIRA_PROJECT_KEY},
            'summary': f"[{channel_name}] {clean_message_text[:50]}...",
            'description': description,
            'issuetype': {'name': 'Task'},
        }
        if JIRA_PARENT_KEY is not None:
            issue_dict['parent'] = {'key': JIRA_PARENT_KEY}
        new_issue = jira.create_issue(fields=issue_dict)

        app.client.chat_postMessage(
            channel=event["channel"],
            thread_ts=event["ts"],
            text=(
                f"Card criado no Jira: <{new_issue.permalink()}|{new_issue.key}>"
                "\nPor favor, aguarde o antendimento do seu card."
            )
        )
    except Exception as e:
        logger.error(f"Erro ao criar card: {e}")


@app.message(".*")
def handle_message_events(body, logger):
    event = body.get("event", {})
    if event.get("user") is None or event.get("bot_id") is not None or event.get("thread_ts") is not None:
        return

    try:
        channel_id = event.get("channel")
        channel_info = app.client.conversations_info(channel=channel_id).get("channel", {})
        channel_name = channel_info.get("name", "N/A")

        if channel_name not in INCLUDE_CHANNELS:
            return

        create_jira_card(event, channel_name, logger)

    except Exception as e:
        logger.error(f"Erro ao processar mensagem: {e}")


@app.event("app_mention")
def handle_app_mention_events(body, say, logger):
    event = body.get("event", {})
    user_id = event.get("user")
    user_info = app.client.users_info(user=user_id).get("user", {})
    user_email = user_info.get("profile", {}).get("email")

    thread_ts = event.get("thread_ts")
    if not thread_ts:
        return
    
    if user_email not in INCLUDE_USERS:
        say(text="Você não está autorizado a usar este comando.", thread_ts=event.get("thread_ts"))
        return

    command = event.get("text", "").split('>', 1)[-1].strip().lower()

    if command == "restart":
        try:
            channel_id = event.get("channel")
            channel_info = app.client.conversations_info(channel=channel_id).get("channel", {})
            channel_name = channel_info.get("name", "N/A")
            create_jira_card(event, channel_name, logger)
        except Exception as e:
            logger.error(f"Erro ao processar comando: {e}")
            say(f"Ocorreu um erro ao processar o comando.", thread_ts=thread_ts)
        return

    jira_key = find_jira_key_in_thread(event["channel"], thread_ts, logger)
    if not jira_key:
        say(text="Não encontrei um card do Jira associado a esta thread.", thread_ts=thread_ts)
        return

    target_status = COMMAND_TO_STATUS.get(command)

    if not target_status:
        valid_commands = ", ".join(COMMAND_TO_STATUS.keys())
        say(f"Comando inválido. Use: {valid_commands}", thread_ts=thread_ts)
        return

    try:
        if command == "start":
            if user_email:
                jira_users = jira.search_users(query=user_email)
                if len(jira_users) == 1:
                    jira.assign_issue(jira_key, user_email)
                    say(f"Card atribuído a {user_email}.", thread_ts=thread_ts)
                else:
                    say(f"Não foi possível encontrar um usuário único no Jira com o e-mail {user_email}.", thread_ts=thread_ts)

        transitions = jira.transitions(jira_key)
        target_transition = next((t for t in transitions if t['name'].lower() == target_status.lower()), None)

        if target_transition:
            jira.transition_issue(jira_key, target_transition['id'])
            say(f"Status do card <{jira.issue(jira_key).permalink()}|{jira_key}> alterado para '{target_status}'.", thread_ts=thread_ts)
            if command == "done":
                try:
                    app.client.reactions_add(
                        channel=event["channel"],
                        name="white_check_mark",
                        timestamp=thread_ts,
                    )
                except Exception as e:
                    logger.error(f"Error adding reaction: {e}")
        else:
            valid_statuses = [t['name'] for t in transitions]
            say(f"Não é possível mover para '{target_status}'. Status disponíveis: {", ".join(valid_statuses)}", thread_ts=thread_ts)

    except Exception as e:
        logger.error(f"Erro ao processar comando para o card {jira_key}: {e}")
        say(f"Ocorreu um erro ao processar o comando para o card {jira_key}.", thread_ts=thread_ts)

if __name__ == "__main__":
    while True:
        try:
            handler = SocketModeHandler(app, SLACK_APP_TOKEN)
            if JIRA_PARENT_KEY is None:
                logging.warning("JIRA_PARENT_KEY não definido, os cards serão criados diretamente no projeto.")
            handler.start()
        except Exception as e:
            logging.error(f"Erro inesperado, reiniciando em 10 segundos: {e}")
            time.sleep(10)
