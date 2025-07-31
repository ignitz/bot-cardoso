# Bot Cardoso

> ignitzhjfk@gmail.com

Este é um bot para Slack que cria e atualiza cards no Jira a partir de mensagens em canais específicos.
Serve mais para atendimento de suporte, onde cada mensagem em um canal monitorado gera um card no Jira.

## Funcionalidades

- Cria um card no Jira para cada nova mensagem em um canal monitorado (que não seja de um bot ou em uma thread).
- Responde na thread da mensagem original com o link para o card criado no Jira.
- Permite atualizar o status do card do Jira mencionando o bot na thread com comandos específicos.
- Atribui o card no Jira ao usuário que iniciou o trabalho (`@bot start`).
- Adiciona uma reação de :white_check_mark: na mensagem original quando o card é concluído.

## Como Rodar

1.  **Clone o repositório:**
    ```bash
    git clone https://github.com/seu-usuario/bot-cardoso.git
    cd bot-cardoso
    ```

2.  **Crie e ative um ambiente virtual:**
    ```bash
    python -m venv .venv
    source .venv/bin/activate
    ```

3.  **Instale as dependências:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Configure as variáveis de ambiente:**
    Crie um arquivo `.env` na raiz do projeto, utilizando o `.env_example` como base.

    ```
    SLACK_BOT_TOKEN="xoxb-..."
    SLACK_APP_TOKEN="xapp-..."
    JIRA_SERVER="https://seu-jira.atlassian.net"
    JIRA_USERNAME="seu-email@dominio.com"
    JIRA_API_TOKEN="seu-token-de-api"
    JIRA_PROJECT_KEY="PROJ"
    JIRA_PARENT_KEY="PROJ-123" # Opcional: Chave de uma tarefa pai para criar sub-tarefas
    INCLUDE_CHANNELS="canal-1,canal-2" # Nomes dos canais para monitorar, separados por vírgula
    ```

5.  **Execute o bot:**
    ```bash
    python main.py
    ```

## Configuração no Slack

Para que o bot funcione, você precisa criar um App no Slack e configurá-lo corretamente.

1.  **Crie um novo App no Slack:**
    - Acesse [https://api.slack.com/apps](https://api.slack.com/apps) e clique em "Create New App".
    - Escolha "From scratch", dê um nome ao seu app e selecione o Workspace onde ele será instalado.

2.  **Habilite o Socket Mode:**
    - No menu lateral, vá em **Settings > Socket Mode**.
    - Ative o "Socket Mode".
    - Gere um "App-Level Token" com o nome que preferir. Copie este token e cole no seu arquivo `.env` como `SLACK_APP_TOKEN`.

3.  **Configure as Permissões (Scopes):**
    - No menu lateral, vá em **Features > OAuth & Permissions**.
    - Na seção "Bot Token Scopes", adicione os seguintes scopes:
        - `app_mentions:read`
        - `channels:history`
        - `channels:read`
        - `chat:write`
        - `groups:history`
        - `im:history`
        - `mpim:history`
        - `reactions:write`
        - `users:read`
        - `users:read.email`

4.  **Assine os Eventos do Bot:**
    - No menu lateral, vá em **Features > Event Subscriptions**.
    - Ative os "Event Subscriptions".
    - Em "Subscribe to bot events", adicione os seguintes eventos:
        - `app_mention`
        - `message.channels`

5.  **Instale o App no Workspace:**
    - No menu lateral, vá em **Settings > Basic Information**.
    - Clique em "Install to Workspace" e siga as instruções.
    - Após a instalação, você receberá o "Bot User OAuth Token". Copie este token e cole no seu arquivo `.env` como `SLACK_BOT_TOKEN`.

6.  **Adicione o Bot aos Canais:**
    - Nos canais do Slack que você configurou em `INCLUDE_CHANNELS`, adicione o bot como um membro.

## Como Usar

- **Para criar um card no Jira:**
  - Envie uma mensagem em um dos canais monitorados. O bot irá criar o card e responder na thread com o link.

- **Para interagir com um card existente:**
  - Na thread da mensagem que originou o card, mencione o bot com um dos seguintes comandos:
    - `@seu-bot start`: Atribui o card a você no Jira e move o status para "In Progress".
    - `@seu-bot done`: Move o status do card para "Done".
    - `@seu-bot cancel`: Move o status do card para "Done".
