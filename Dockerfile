FROM python:3.12-slim

WORKDIR /app

# Instala as dependências do sistema
COPY requirements.txt /app/requirements.txt
COPY main.py /app/main.py
RUN pip install -r /app/requirements.txt

ENTRYPOINT [ "python", "/app/main.py" ]
CMD []
