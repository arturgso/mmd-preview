# Mermaid Viewer

Visualizador web pequeno e em tema escuro para arquivos Mermaid (`.mmd`). Permite enviar arquivos ou pastas, navegar pela estrutura preservada, renomear itens e visualizar os diagramas com zoom e pan. Não possui editor, banco de dados ou autenticação.

## Executar com Docker

```bash
docker compose up -d
```

Acesse <http://localhost:8000>. Para usar outra porta no host:

```bash
APP_PORT=8080 docker compose up -d
```

Para acompanhar os logs:

```bash
docker compose logs -f app
```

Para parar a aplicação sem remover os diagramas:

```bash
docker compose down
```

Não use `docker compose down -v` a menos que queira apagar também o volume persistente.

## Armazenamento e backup

Os arquivos são armazenados em `/data` dentro do container. O `compose.yaml` monta nesse caminho o volume nomeado `mermaid_data`, que continua existindo quando o container é parado ou recriado.

Com a aplicação em execução, copie todo o conteúdo para uma pasta local:

```bash
docker compose cp app:/data ./mermaid-backup
```

Para restaurar um backup:

```bash
docker compose cp ./mermaid-backup/. app:/data
```

Também é possível trocar o volume nomeado por um bind mount, como `./data:/data`. Nesse caso, garanta que o usuário `10001` do container possa gravar na pasta do host.

## Uso

- **Upload de arquivos:** escolha um ou vários `.mmd`; eles serão armazenados na raiz.
- **Selecionar pasta:** escolha uma pasta inteira; sua estrutura relativa será preservada. Arquivos que não terminem em `.mmd` serão informados como rejeitados.
- **Substituir:** envie novamente um arquivo com o mesmo caminho e nome.
- **Renomear:** use o ícone de lápis ao lado de um arquivo ou pasta. Nomes existentes não são sobrescritos.
- **Excluir:** use o ícone de exclusão na própria linha do arquivo.
- **Buscar:** filtre por qualquer trecho do nome ou do caminho.
- **Preview:** use os controles da sidebar, a roda do mouse e o arraste para zoom e pan.

O limite padrão por requisição é 50 MB. Ele pode ser alterado com `MAX_UPLOAD_MB`, por exemplo:

```bash
MAX_UPLOAD_MB=100 docker compose up -d
```

## Desenvolvimento local

Requer Python 3.12 ou mais recente.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
STORAGE_DIR=./data flask --app app run --port 8000 --debug
```

O bundle do Mermaid.js é servido localmente pela aplicação; não é necessário acesso à internet durante o uso.

## Testes

```bash
python -m unittest discover -s tests -v
```

## API

- `GET /api/files` — lista os caminhos disponíveis.
- `GET /api/file?path=...` — lê um arquivo.
- `POST /api/files` — recebe multipart com os campos repetidos `paths` e `files`.
- `DELETE /api/file?path=...` — exclui um arquivo.
- `PATCH /api/path` — renomeia um arquivo ou diretório sem sobrescrever itens existentes.

Somente caminhos relativos terminados em `.mmd` são aceitos. Caminhos absolutos, traversal, links simbólicos e conteúdo que não seja UTF-8 são rejeitados.
