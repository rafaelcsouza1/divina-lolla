# Painel Divina Lolla — imagem para hospedar o admin com senha.
#
# A imagem carrega só o código. O catálogo vem de um clone do repositório feito
# no boot, e a credencial de publicação chega por variável de ambiente: nada
# secreto fica gravado aqui dentro.

FROM python:3.12-slim

# git publica no GitHub Pages; openssh-client usa a credencial de deploy.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git openssh-client ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements-server.txt ./
RUN pip install --no-cache-dir -r requirements-server.txt

COPY admin/ ./admin/
COPY entrypoint.sh ./
RUN chmod +x entrypoint.sh

ENV REPO_DIR=/data/repo \
    PUBLISH_KEY_PATH=/data/publicar \
    PYTHONUNBUFFERED=1 \
    FORCE_HTTPS=1

EXPOSE 8080

CMD ["./entrypoint.sh"]
