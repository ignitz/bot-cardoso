import os
import re
import logging
import time
import json
import requests
from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from flask import Flask, make_response
from jira import JIRA

# --- Configuração --- #
logging.basicConfig(level=logging.INFO)
load_dotenv()

COMMAND_TO_STATUS = {
    "start": "In Progress",
    "done": "Done",
    "cancel": "Canceled",
    "restart": "To Do",
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
OPENWEBUI_API_MODEL = os.environ.get("OPENWEBUI_API_MODEL", None)
OPENWEBUI_API_URL = os.environ.get("OPENWEBUI_API_URL", None)
OPENWEBUI_API_KEY = os.environ.get("OPENWEBUI_API_KEY", None)

# --- Fim da Configuração --- #

# Inicialização de Clientes
app = App(token=SLACK_BOT_TOKEN)
socket_mode_handler = SocketModeHandler(app, SLACK_APP_TOKEN)
flask_app = Flask(__name__)

jira_options = {"server": JIRA_SERVER}
jira = JIRA(
    options=jira_options,
    basic_auth=(
        JIRA_USERNAME,
        JIRA_API_TOKEN,
    ),
)


@flask_app.route("/health", methods=["GET"])
def slack_events():
    """Health check endpoint for use in Kubernetes as liveness probe."""
    if (
        socket_mode_handler.client is not None
        and socket_mode_handler.client.is_connected()
    ):
        return make_response("OK", 200)
    return make_response("The Socket Mode client is inactive", 503)


def summarize_chat_history(channel, thread_ts, logger):
    """Summarize the chat history using the OpenWebUI completions API."""
    result = app.client.conversations_replies(channel=channel, ts=thread_ts)
    messages = result.get("messages", [])
    while result.get("has_more", False):
        cursor = result.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break
        next_result = app.client.conversations_replies(
            channel=channel, ts=thread_ts, cursor=cursor
        )
        messages.extend(next_result.get("messages", []))
        result = next_result

    chat_history = "\n".join([message["text"] for message in messages])

    headers = {
        "Authorization": f"Bearer {OPENWEBUI_API_KEY}",
        "Content-Type": "application/json",
    }
    data = {
        "model": OPENWEBUI_API_MODEL,
        "messages": [
            {
                "role": "user",
                "content": (
                    "Summarize the following conversation, providing a solution if one was reached."
                    f"The summary should be in Portuguese and should be a maximum of 2 paragraphs.\n\n{chat_history}"
                )
            }
        ],
    }
    response = requests.post(
        f"{OPENWEBUI_API_URL}/api/chat/completions", headers=headers, json=data
    )
    response.raise_for_status()
    response_data = response.json()
    summary = response_data["choices"][0]["message"]["content"].strip()
    logger.info(f"Chat history summarized successfully for thread {thread_ts}")
    return summary

def find_jira_key_in_thread(channel, thread_ts, logger):
    """Busca o histórico de uma thread para encontrar a chave do card do Jira."""
    try:
        result = app.client.conversations_replies(channel=channel, ts=thread_ts)
        messages = result.get("messages", [])
        while result.get("has_more", False):
            cursor = result.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break
            next_result = app.client.conversations_replies(
                channel=channel, ts=thread_ts, cursor=cursor
            )
            messages.extend(next_result.get("messages", []))
            result = next_result
        for message in messages:
            # Procura pela mensagem específica postada pelo bot
            match = re.search(r"Card criado no Jira:.*?\|([A-Z]+-\d+)>", message.get("text", ""))
            if match:
                jira_key = match.group(1)
                logger.debug(f"Encontrado Jira key '{jira_key}' na thread {thread_ts}")
                return jira_key
    except Exception as e:
        logger.error(f"Erro ao buscar histórico da thread {thread_ts}: {e}")
    return None


def save_conversation_to_jira(channel, thread_ts, jira_key, logger):
    """Busca a conversa de uma thread, salva em JSON e anexa ao card do Jira."""
    try:
        result = app.client.conversations_replies(channel=channel, ts=thread_ts)
        messages = result.get("messages", [])
        while result.get("has_more", False):
            cursor = result.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break
            next_result = app.client.conversations_replies(
                channel=channel, ts=thread_ts, cursor=cursor
            )
            messages.extend(next_result.get("messages", []))
            result = next_result
        file_path = f"/tmp/slack-conversation-{thread_ts}.json"
        with open(file_path, "w") as f:
            json.dump(messages, f, indent=4)
        jira.add_attachment(issue=jira_key, attachment=file_path)
        logger.info(
            f"Conversa da thread {thread_ts} salva e anexada ao card {jira_key}"
        )
        os.remove(file_path)

    except Exception as e:
        logger.error(
            f"Erro ao salvar conversa da thread {thread_ts} no card {jira_key}: {e}"
        )


def create_jira_card(event, channel_name, logger):
    try:
        user_id = event.get("user")
        user_info = app.client.users_info(user=user_id).get("user", {})
        user_name = user_info.get("real_name", "N/A")
        user_email = user_info.get("profile", {}).get("email", "N/A")

        permalink = app.client.chat_getPermalink(
            channel=event["channel"], message_ts=event["ts"]
        )["permalink"]
        message_text = event.get("text", "")
        description = (
            f"Solicitação de: {user_name} ({user_email})\n"
            f"Thread no Slack: {permalink}\n\n"
            f"Mensagem: {message_text}"
        )

        # Remove special characters from the message text for the summary
        # Example: \n, \t, etc.
        clean_message_text = re.sub(r"[^a-zA-Z0-9 ]", "", message_text)
        issue_dict = {
            "project": {"key": JIRA_PROJECT_KEY},
            "summary": f"[{channel_name}] {clean_message_text[:50]}...",
            "description": description,
            "issuetype": {"name": "Task"},
        }
        if JIRA_PARENT_KEY is not None:
            issue_dict["parent"] = {"key": JIRA_PARENT_KEY}
        new_issue = jira.create_issue(fields=issue_dict)

        app.client.chat_postMessage(
            channel=event["channel"],
            thread_ts=event["ts"],
            text=(
                f"Card criado no Jira: <{new_issue.permalink()}|{new_issue.key}>"
                "\nPor favor, aguarde o antendimento do seu card."
            ),
        )

    except Exception as e:
        logger.error(f"Erro ao criar card: {e}")


@app.message(".*")
def handle_message_events(body, logger):
    event = body.get("event", {})
    if (
        event.get("user") is None
        or event.get("bot_id") is not None
        or event.get("thread_ts") is not None
    ):
        return

    try:
        channel_id = event.get("channel")
        channel_info = app.client.conversations_info(channel=channel_id).get(
            "channel", {}
        )
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
        say(
            text="Você não está autorizado a usar este comando.",
            thread_ts=event.get("thread_ts"),
        )
        return

    command = event.get("text", "").split(">", 1)[-1].strip().lower()

    if command == "restart":
        try:
            channel_id = event.get("channel")
            channel_info = app.client.conversations_info(channel=channel_id).get(
                "channel", {}
            )
            channel_name = channel_info.get("name", "N/A")
            create_jira_card(event, channel_name, logger)
        except Exception as e:
            logger.error(f"Erro ao processar comando: {e}")
            say(
                text="Ocorreu um erro ao processar comando restart.",
                thread_ts=event.get("thread_ts"),
            )
        return

    jira_key = find_jira_key_in_thread(event["channel"], thread_ts, logger)
    if not jira_key:
        say(
            text="Não encontrei um card do Jira associado a esta thread.",
            thread_ts=thread_ts,
        )
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
                    say(
                        f"Não foi possível encontrar um usuário único no Jira com o e-mail {user_email}.",
                        thread_ts=thread_ts,
                    )

        transitions = jira.transitions(jira_key)
        target_transition = next(
            (t for t in transitions if t["name"].lower() == target_status.lower()), None
        )

        if target_transition:
            jira.transition_issue(jira_key, target_transition["id"])
            say(
                f"Status do card <{jira.issue(jira_key).permalink()}|{jira_key}> alterado para '{target_status}'.",
                thread_ts=thread_ts,
            )
            if command == "done":
                try:
                    save_conversation_to_jira(
                        event["channel"], thread_ts, jira_key, logger
                    )
                    if (
                        OPENWEBUI_API_MODEL is not None
                        and
                        OPENWEBUI_API_URL is not None
                        and
                        OPENWEBUI_API_KEY is not None
                    ):
                        summary = summarize_chat_history(
                            event["channel"], thread_ts, logger
                        )
                        if summary:
                            jira.add_comment(jira_key, summary)
                            say(text=summary, thread_ts=thread_ts)
                    
                    reactions = app.client.reactions_get(
                        channel=event["channel"],
                        timestamp=thread_ts,
                    ).get("message", {}).get("reactions", [])
                    for reaction in reactions:
                        app.client.reactions_remove(
                            channel=event["channel"],
                            name=reaction["name"],
                            timestamp=thread_ts,
                        )
                    app.client.reactions_add(
                        channel=event["channel"],
                        name="white_check_mark",
                        timestamp=thread_ts,
                    )
                except Exception as e:
                    logger.error(f"Error adding reaction: {e}")
            elif command == "cancel":
                reactions = app.client.reactions_get(
                    channel=event["channel"],
                    timestamp=thread_ts,
                ).get("message", {}).get("reactions", [])
                for reaction in reactions:
                    app.client.reactions_remove(
                        channel=event["channel"],
                        name=reaction["name"],
                        timestamp=thread_ts,
                    )
                app.client.reactions_add(
                    channel=event["channel"],
                    name="x",
                    timestamp=thread_ts,
                )
            elif command == "restart" or command == "start":
                reactions = app.client.reactions_get(
                    channel=event["channel"],
                    timestamp=thread_ts,
                ).get("message", {}).get("reactions", [])
                for reaction in reactions:
                    app.client.reactions_remove(
                        channel=event["channel"],
                        name=reaction["name"],
                        timestamp=thread_ts,
                    )
                app.client.reactions_add(
                    channel=event["channel"],
                    name="eyes",
                    timestamp=thread_ts,
                )

        else:
            valid_statuses = [t["name"] for t in transitions]
            say(
                f"Não é possível mover para '{target_status}'. Status disponíveis: {", ".join(valid_statuses)}",
                thread_ts=thread_ts,
            )

    except Exception as e:
        logger.error(f"Erro ao processar comando para o card {jira_key}: {e}")
        say(
            f"Ocorreu um erro ao processar o comando para o card {jira_key}.",
            thread_ts=thread_ts,
        )


@app.event("message")
def handle_message_events(body, logger):
    logger.debug(body)


if __name__ == "__main__":

    class NoHealth(logging.Filter):
        def filter(self, record):
            return "GET /health" not in record.getMessage()

    if JIRA_PARENT_KEY is None:
        logging.warning(
            "JIRA_PARENT_KEY não definido, os cards serão criados diretamente no projeto."
        )
    socket_mode_handler.connect()
    # Remover log do healthcheck
    logging.getLogger("werkzeug").addFilter(NoHealth())
    flask_app.run(host="0.0.0.0", port=8080)
