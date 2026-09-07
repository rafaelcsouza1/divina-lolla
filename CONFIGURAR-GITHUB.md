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
