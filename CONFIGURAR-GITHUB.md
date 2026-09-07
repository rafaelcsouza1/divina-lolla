# Publicação do site

O site público mora na pasta `docs/` e é servido pelo **GitHub Pages**.
O painel admin roda **localmente no seu Mac** e envia as atualizações
para o site online pelo botão **Publicar**.

    docs/          -> vira o site online (GitHub Pages)
    admin/         -> painel local, não faz parte do site público

> A pasta se chama `docs` porque o GitHub Pages, ao publicar a partir de uma
> branch, só aceita servir a raiz do repositório ou a pasta `/docs`.

> Manual de uso para quem cadastra as peças: abra o MANUAL.html.

## Uso no dia a dia

1. Dê dois cliques em `iniciar.command` (ou rode `./iniciar.command`).
   O painel abre em http://localhost:5000
2. Cadastre, edite ou remova produtos. As alterações já valem
   imediatamente no site local.
3. Clique em **Publicar no site** para enviar ao site online.
   O GitHub Pages atualiza em cerca de 1 a 2 minutos.

## O que já está configurado

- Repositório Git local, com `venv/`, `admin/config.json` e `chave/` fora do
  controle de versão.
- Repositório remoto no GitHub, via SSH.
- GitHub Pages publicando `main` + `/docs`.

## Entregar o painel para outra pessoa

O painel vai empacotado num `.zip` com a credencial de publicação dentro,
em `chave/publicar`. Quem recebe descompacta e dá dois cliques em
`iniciar.command` — não precisa configurar nada.

Essa credencial é uma *deploy key* com escrita **apenas neste
repositório**: não alcança a conta nem outros repos. Mas é compartilhada,
então trate o `.zip` como uma senha. Para revogar:

    gh repo deploy-key list --repo rafaelcsouza1/divina-lolla
    gh repo deploy-key delete <id> --repo rafaelcsouza1/divina-lolla

Para gerar um pacote novo (por exemplo, depois de revogar e criar outra
credencial), rode `./empacotar.command`.

## Painel hospedado, com senha

Além do pacote de desktop, o painel pode rodar num servidor — assim dá para
cadastrar peças pelo celular, de qualquer lugar, sem depender do Mac ligado.

    Dockerfile          imagem: só o código, nada de segredo
    entrypoint.sh       no boot: grava a credencial, clona o repo, sobe o gunicorn
    render.yaml         blueprint do Render
    requirements-server.txt

### Subir no Render

1. Render → **New** → **Blueprint** e aponte para este repositório.
2. Defina as duas variáveis que o blueprint pede:

   - `ADMIN_PASSWORD` — a senha de quem entra no painel.
   - `PUBLISH_KEY_B64` — a credencial de publicação em base64:

         base64 -i chave/publicar | tr -d '\n'

   O `SECRET_KEY` o Render gera sozinho. Ele mantém a sessão viva entre
   reinícios; sem ele, cada restart desloga quem estava dentro.

3. O painel sobe em `https://<nome>.onrender.com` e pede a senha.

### O que muda no painel hospedado

- **Login obrigatório.** Sem `ADMIN_PASSWORD` o serviço se recusa a subir, em
  dois pontos independentes: no `entrypoint.sh` e no próprio `app.py`. Um
  painel aberto na internet seria um formulário público de edição do site.
- **Salvar já publica.** O disco desses serviços é efêmero: o que ficasse
  esperando o botão Publicar sumiria no próximo reinício, sem aviso. Para
  desligar esse comportamento, defina `AUTO_PUBLISH=0` — mas então avise quem
  usa que precisa clicar em Publicar antes de fechar.
- **Um worker só.** O controle de tentativas de senha vive na memória do
  processo, e dois workers no mesmo clone git disputariam o índice.
- **No plano gratuito o serviço hiberna.** O primeiro acesso depois de um tempo
  parado leva de trinta a sessenta segundos para responder.

### Recomendação sobre a credencial

Gere uma deploy key **separada** para o servidor, em vez de reaproveitar a que
vai no pacote de desktop. Assim, revogar o acesso de um não derruba o outro:

    ssh-keygen -t ed25519 -N "" -C "painel-servidor" -f chave/servidor
    gh repo deploy-key add chave/servidor.pub \
      --repo rafaelcsouza1/divina-lolla \
      --allow-write --title "Painel hospedado"

Use `chave/servidor` para gerar o `PUBLISH_KEY_B64`.

## Domínio próprio (opcional)

Por padrão o site fica em `https://rafaelcsouza1.github.io/divina-lolla/`.

Para usar um domínio seu:

1. Crie o arquivo `docs/CNAME` com o domínio dentro, numa única linha:

       www.seudominio.com.br

2. No painel do seu provedor de domínio, adicione um registro CNAME:

       Nome:  www
       Valor: rafaelcsouza1.github.io

3. Para o domínio raiz (sem `www`), adicione registros A apontando para:

       185.199.108.153
       185.199.109.153
       185.199.110.153
       185.199.111.153

4. Clique em **Publicar no site** no painel. O GitHub detecta o `CNAME`
   e passa a servir o site nesse domínio (o certificado HTTPS sai em
   alguns minutos).

## Se algo der errado

- **"Git não encontrado"** — instale as ferramentas de linha de comando:
  `xcode-select --install`
- **Publicar falha com erro de permissão** — teste o acesso ao GitHub:
  `ssh -T git@github.com`
- **Site online não atualizou** — confira o progresso na aba
  **Actions** do repositório no GitHub; cada publicação dispara um deploy.
