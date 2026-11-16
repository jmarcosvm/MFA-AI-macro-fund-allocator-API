# Imagem do MFA (R8.1). Um único processo uvicorn: cache e single-flight são por processo.
# Nenhum segredo aqui: chaves entram só por variável de ambiente em tempo de execução.
FROM python:3.15.1-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Usuário sem privilégio (uid/gid 10001), sem home e sem shell de login.
RUN groupadd --system --gid 10001 mfa \
    && useradd --system --uid 10001 --gid mfa --no-create-home --shell /usr/sbin/nologin mfa

WORKDIR /app

# Dependências primeiro (camada em cache enquanto o requirements.txt não mudar).
COPY requirements.txt .
RUN pip install -r requirements.txt

# Só o código do app (nunca COPY . .). Pertence ao root, somente leitura para o usuário mfa.
COPY app/ ./app/

USER mfa

# Documentação apenas; o Render usa a variável PORT (padrão 10000).
EXPOSE 10000

# Forma exec do sh + exec: o uvicorn vira PID 1 e recebe o SIGTERM do docker stop.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000}"]
