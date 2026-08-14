import os
import re
import shutil
import tempfile
from pathlib import Path, PurePosixPath

from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import RequestEntityTooLarge


CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")
TASK_MARKER = re.compile(r"^(?P<prefix>\s*[-+*]\s+\[)(?P<state>[ xX>!])(?P<suffix>\].*)$")
FENCE_MARKER = re.compile(r"^\s{0,3}(?P<marker>`{3,}|~{3,})")
TASK_STATES = {" ", ">", "x", "!"}


class InvalidPath(ValueError):
    pass


def file_kind(relative):
    path = PurePosixPath(relative)
    if path.suffix.lower() == ".mmd":
        return "mermaid"
    if path.suffix.lower() == ".md":
        return "markdown"
    return None


def markdown_task_matches(lines):
    matches = {}
    fence = None
    for index, line in enumerate(lines):
        body = line.rstrip("\r\n")
        fence_match = FENCE_MARKER.match(body)
        if fence_match:
            marker = fence_match.group("marker")
            if fence is None:
                fence = (marker[0], len(marker))
            elif marker[0] == fence[0] and len(marker) >= fence[1]:
                fence = None
            continue
        if fence is None:
            match = TASK_MARKER.match(body)
            if match:
                matches[index] = match
    return matches


def create_app(storage_dir=None):
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = int(os.getenv("MAX_UPLOAD_MB", "50")) * 1024 * 1024

    configured_storage = storage_dir or os.getenv("STORAGE_DIR", "/data")
    storage_root = Path(configured_storage).resolve()
    storage_root.mkdir(parents=True, exist_ok=True)
    app.config["STORAGE_ROOT"] = storage_root

    def safe_path(raw_path, require_supported=True):
        if not isinstance(raw_path, str):
            raise InvalidPath("Caminho ausente.")

        normalized = raw_path.replace("\\", "/").strip()
        if not normalized or normalized.startswith("/") or WINDOWS_DRIVE.match(normalized):
            raise InvalidPath("Caminho inválido.")
        if CONTROL_CHARS.search(normalized):
            raise InvalidPath("O caminho contém caracteres inválidos.")

        relative = PurePosixPath(normalized)
        if any(part in ("", ".", "..") for part in relative.parts):
            raise InvalidPath("O caminho não pode conter '.' ou '..'.")
        if require_supported and not file_kind(relative):
            raise InvalidPath("Somente arquivos .mmd e .md são permitidos.")

        target = storage_root.joinpath(*relative.parts)
        try:
            target.resolve(strict=False).relative_to(storage_root)
        except ValueError as exc:
            raise InvalidPath("O caminho está fora do diretório de dados.") from exc

        current = storage_root
        for part in relative.parts:
            current = current / part
            if current.exists() and current.is_symlink():
                raise InvalidPath("Links simbólicos não são permitidos.")

        return target, relative.as_posix()

    def safe_directory(raw_path):
        target, relative = safe_path(raw_path, require_supported=False)
        if target == storage_root:
            raise InvalidPath("O diretório raiz não pode ser renomeado.")
        return target, relative

    def list_files():
        files = []
        for candidate in storage_root.rglob("*"):
            if not candidate.is_file() or candidate.is_symlink():
                continue
            relative = candidate.relative_to(storage_root)
            if not file_kind(relative):
                continue
            if any(parent.is_symlink() for parent in candidate.parents if parent != storage_root):
                continue
            files.append(relative.as_posix())
        return sorted(files, key=str.casefold)

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/api/files")
    def files_index():
        files = list_files()
        return jsonify(files=files, count=len(files))

    @app.get("/api/file")
    def read_file():
        try:
            target, relative = safe_path(request.args.get("path"))
            if not target.is_file():
                return jsonify(error="Arquivo não encontrado."), 404
            content = target.read_text(encoding="utf-8")
            return jsonify(path=relative, content=content, type=file_kind(relative))
        except InvalidPath as exc:
            return jsonify(error=str(exc)), 400
        except UnicodeDecodeError:
            return jsonify(error="O arquivo não contém texto UTF-8 válido."), 422
        except OSError:
            app.logger.exception("Falha ao ler arquivo")
            return jsonify(error="Não foi possível ler o arquivo."), 500

    @app.patch("/api/markdown/task")
    def update_markdown_task():
        data = request.get_json(silent=True) or {}
        line_number = data.get("line")
        state = data.get("state")
        previous_state = data.get("previous_state")

        if not isinstance(line_number, int) or isinstance(line_number, bool) or line_number < 0:
            return jsonify(error="Linha de tarefa inválida."), 400
        if state not in TASK_STATES or previous_state not in TASK_STATES:
            return jsonify(error="Estado de tarefa inválido."), 400

        temp_name = None
        try:
            target, relative = safe_path(data.get("path"))
            if file_kind(relative) != "markdown":
                return jsonify(error="Somente tarefas em arquivos .md podem ser alteradas."), 400
            if not target.is_file():
                return jsonify(error="Arquivo não encontrado."), 404

            content = target.read_text(encoding="utf-8")
            lines = content.splitlines(keepends=True)
            if line_number >= len(lines):
                return jsonify(error="A tarefa foi alterada. Recarregue o arquivo."), 409

            task_matches = markdown_task_matches(lines)
            line = lines[line_number]
            ending = "\n" if line.endswith("\n") else ""
            body = line[:-1] if ending else line
            if body.endswith("\r"):
                body = body[:-1]
                ending = "\r" + ending
            match = task_matches.get(line_number)
            current_state = match.group("state").lower() if match else None
            if not match or current_state != previous_state:
                return jsonify(error="A tarefa foi alterada. Recarregue o arquivo."), 409

            if state == ">":
                for index, candidate_match in task_matches.items():
                    if index != line_number and candidate_match.group("state") == ">":
                        candidate = lines[index]
                        lines[index] = (
                            candidate_match.group("prefix") + " " + candidate_match.group("suffix")
                            + candidate[len(candidate.rstrip("\r\n")):]
                        )

            lines[line_number] = match.group("prefix") + state + match.group("suffix") + ending
            updated = "".join(lines)
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", newline="", dir=target.parent,
                prefix=".task-", suffix=".tmp", delete=False,
            ) as temporary:
                temp_name = temporary.name
                temporary.write(updated)
            os.replace(temp_name, target)
            temp_name = None
            return jsonify(path=relative, content=updated, line=line_number, state=state)
        except InvalidPath as exc:
            return jsonify(error=str(exc)), 400
        except UnicodeDecodeError:
            return jsonify(error="O arquivo não contém texto UTF-8 válido."), 422
        except OSError:
            app.logger.exception("Falha ao atualizar tarefa Markdown")
            return jsonify(error="Não foi possível atualizar a tarefa."), 500
        finally:
            if temp_name:
                try:
                    Path(temp_name).unlink(missing_ok=True)
                except OSError:
                    app.logger.warning("Falha ao remover arquivo temporário %s", temp_name)

    @app.post("/api/files")
    def upload_files():
        uploads = request.files.getlist("files")
        paths = request.form.getlist("paths")
        if not uploads:
            return jsonify(error="Nenhum arquivo foi enviado."), 400

        accepted = []
        replaced = []
        rejected = []

        for index, upload in enumerate(uploads):
            submitted_path = paths[index] if index < len(paths) else upload.filename
            display_path = submitted_path or upload.filename or "arquivo sem nome"
            temp_name = None
            try:
                target, relative = safe_path(submitted_path)
                data = upload.read()
                data.decode("utf-8")
                existed = target.is_file()
                target.parent.mkdir(parents=True, exist_ok=True)

                with tempfile.NamedTemporaryFile(
                    mode="wb", dir=target.parent, prefix=".upload-", suffix=".tmp", delete=False
                ) as temporary:
                    temp_name = temporary.name
                    temporary.write(data)
                os.replace(temp_name, target)
                temp_name = None
                (replaced if existed else accepted).append(relative)
            except (InvalidPath, UnicodeDecodeError) as exc:
                reason = str(exc) if isinstance(exc, InvalidPath) else "O arquivo não contém texto UTF-8 válido."
                rejected.append({"path": display_path, "reason": reason})
            except OSError:
                app.logger.exception("Falha ao gravar upload")
                rejected.append({"path": display_path, "reason": "Não foi possível gravar o arquivo."})
            finally:
                if temp_name:
                    try:
                        Path(temp_name).unlink(missing_ok=True)
                    except OSError:
                        app.logger.warning("Falha ao remover arquivo temporário %s", temp_name)

        payload = {"accepted": accepted, "replaced": replaced, "rejected": rejected}
        if not accepted and not replaced:
            return jsonify(payload), 400
        return jsonify(payload)

    @app.delete("/api/file")
    def delete_file():
        try:
            target, relative = safe_path(request.args.get("path"))
            if not target.is_file():
                return jsonify(error="Arquivo não encontrado."), 404
            target.unlink()

            parent = target.parent
            while parent != storage_root:
                try:
                    parent.rmdir()
                except OSError:
                    break
                parent = parent.parent
            return jsonify(deleted=relative)
        except InvalidPath as exc:
            return jsonify(error=str(exc)), 400
        except OSError:
            app.logger.exception("Falha ao excluir arquivo")
            return jsonify(error="Não foi possível excluir o arquivo."), 500

    @app.delete("/api/directory")
    def delete_directory():
        try:
            target, relative = safe_directory(request.args.get("path"))
            if not target.is_dir():
                return jsonify(error="Pasta não encontrada."), 404
            if any(item.is_symlink() for item in target.rglob("*")):
                return jsonify(error="A pasta contém links simbólicos e não pode ser excluída."), 400

            shutil.rmtree(target)
            return jsonify(deleted=relative)
        except InvalidPath as exc:
            return jsonify(error=str(exc)), 400
        except OSError:
            app.logger.exception("Falha ao excluir pasta")
            return jsonify(error="Não foi possível excluir a pasta."), 500

    @app.patch("/api/path")
    def rename_path():
        data = request.get_json(silent=True) or {}
        item_type = data.get("type")
        resolver = safe_path if item_type == "file" else safe_directory if item_type == "directory" else None
        if resolver is None:
            return jsonify(error="Tipo de item inválido."), 400

        try:
            source, old_relative = resolver(data.get("old_path"))
            destination, new_relative = resolver(data.get("new_path"))
            if source == destination:
                return jsonify(old_path=old_relative, new_path=new_relative, type=item_type)
            if not source.exists() or (item_type == "file" and not source.is_file()) or (item_type == "directory" and not source.is_dir()):
                return jsonify(error="Arquivo ou pasta não encontrado."), 404
            if destination.exists():
                return jsonify(error="Já existe um item com esse nome."), 409
            if item_type == "directory":
                if any(item.is_symlink() for item in source.rglob("*")):
                    return jsonify(error="A pasta contém links simbólicos e não pode ser movida."), 400
                try:
                    destination.relative_to(source)
                    return jsonify(error="Uma pasta não pode ser movida para dentro dela mesma."), 400
                except ValueError:
                    pass

            destination.parent.mkdir(parents=True, exist_ok=True)
            source.rename(destination)
            return jsonify(old_path=old_relative, new_path=new_relative, type=item_type)
        except InvalidPath as exc:
            return jsonify(error=str(exc)), 400
        except OSError:
            app.logger.exception("Falha ao renomear item")
            return jsonify(error="Não foi possível renomear o item."), 500

    @app.errorhandler(RequestEntityTooLarge)
    def request_too_large(_error):
        limit = int(app.config["MAX_CONTENT_LENGTH"] / 1024 / 1024)
        return jsonify(error=f"O upload excede o limite de {limit} MB."), 413

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
