(() => {
  "use strict";

  const elements = {
    tree: document.querySelector("#file-tree"),
    count: document.querySelector("#file-count"),
    search: document.querySelector("#search-input"),
    status: document.querySelector("#upload-status"),
    fileInput: document.querySelector("#file-input"),
    folderInput: document.querySelector("#folder-input"),
    uploadFiles: document.querySelector("#upload-files-button"),
    uploadFolder: document.querySelector("#upload-folder-button"),
    deleteButton: document.querySelector("#delete-button"),
    zoomIn: document.querySelector("#zoom-in"),
    zoomOut: document.querySelector("#zoom-out"),
    zoomReset: document.querySelector("#zoom-reset"),
    viewport: document.querySelector("#viewport"),
    stage: document.querySelector("#diagram-stage"),
    message: document.querySelector("#preview-message"),
    currentFile: document.querySelector("#current-file"),
    sidebar: document.querySelector("#sidebar"),
    sidebarToggle: document.querySelector("#sidebar-toggle"),
  };

  let files = [];
  let selectedPath = null;
  let scale = 1;
  let translateX = 0;
  let translateY = 0;
  let diagramWidth = 0;
  let diagramHeight = 0;
  let pointer = null;
  let renderSequence = 0;

  mermaid.initialize({
    startOnLoad: false,
    securityLevel: "strict",
    theme: "default",
    suppressErrorRendering: true,
  });

  async function api(url, options = {}) {
    const response = await fetch(url, options);
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.error || formatRejected(body.rejected) || "Não foi possível concluir a operação.");
    return body;
  }

  async function refreshFiles(preferredPath = selectedPath) {
    try {
      const data = await api("/api/files");
      files = data.files;
      elements.count.textContent = `${data.count} ${data.count === 1 ? "arquivo" : "arquivos"}`;
      if (preferredPath && files.includes(preferredPath)) selectedPath = preferredPath;
      else if (selectedPath && !files.includes(selectedPath)) selectedPath = null;
      renderTree();
    } catch (error) {
      setStatus(error.message, true);
    }
  }

  function makeTree(paths) {
    const root = { directories: new Map(), files: [] };
    paths.forEach((path) => {
      const parts = path.split("/");
      const filename = parts.pop();
      let node = root;
      parts.forEach((part) => {
        if (!node.directories.has(part)) node.directories.set(part, { directories: new Map(), files: [] });
        node = node.directories.get(part);
      });
      node.files.push({ name: filename, path });
    });
    return root;
  }

  function renderTree() {
    const query = elements.search.value.trim().toLocaleLowerCase("pt-BR");
    const visible = query ? files.filter((path) => path.toLocaleLowerCase("pt-BR").includes(query)) : files;
    elements.tree.replaceChildren();
    if (!visible.length) {
      const empty = document.createElement("div");
      empty.className = "tree-empty";
      empty.textContent = files.length ? "Nenhum arquivo corresponde à busca." : "Nenhum diagrama enviado ainda.";
      elements.tree.append(empty);
      return;
    }
    elements.tree.append(renderNode(makeTree(visible), true));
  }

  function renderNode(node, openFolders = false) {
    const fragment = document.createDocumentFragment();
    [...node.directories.entries()].sort(([a], [b]) => a.localeCompare(b, "pt-BR")).forEach(([name, child]) => {
      const details = document.createElement("details");
      details.className = "tree-folder";
      details.open = openFolders || Boolean(elements.search.value);
      const summary = document.createElement("summary");
      summary.textContent = `📁 ${name}`;
      const children = document.createElement("div");
      children.className = "tree-children";
      children.append(renderNode(child, openFolders));
      details.append(summary, children);
      fragment.append(details);
    });
    node.files.sort((a, b) => a.name.localeCompare(b.name, "pt-BR")).forEach((file) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `file-item${file.path === selectedPath ? " selected" : ""}`;
      button.title = file.path;
      button.dataset.path = file.path;
      const label = document.createElement("span");
      label.className = "file-name";
      label.textContent = file.name;
      button.append(label);
      button.addEventListener("click", () => selectFile(file.path));
      fragment.append(button);
    });
    return fragment;
  }

  async function selectFile(path) {
    selectedPath = path;
    renderTree();
    showMessage("Carregando diagrama…", "");
    elements.currentFile.textContent = path;
    elements.currentFile.hidden = false;
    elements.deleteButton.disabled = false;
    const sequence = ++renderSequence;
    try {
      const data = await api(`/api/file?path=${encodeURIComponent(path)}`);
      const result = await mermaid.render(`diagram-${sequence}`, data.content);
      if (sequence !== renderSequence) return;
      elements.stage.innerHTML = result.svg;
      const svg = elements.stage.querySelector("svg");
      const viewBox = svg && svg.viewBox && svg.viewBox.baseVal;
      diagramWidth = viewBox && viewBox.width ? viewBox.width : svg.getBoundingClientRect().width;
      diagramHeight = viewBox && viewBox.height ? viewBox.height : svg.getBoundingClientRect().height;
      svg.setAttribute("width", diagramWidth);
      svg.setAttribute("height", diagramHeight);
      elements.message.hidden = true;
      elements.viewport.hidden = false;
      setControls(true);
      requestAnimationFrame(fitDiagram);
      if (window.innerWidth <= 720) setSidebarCollapsed(true);
    } catch (error) {
      if (sequence !== renderSequence) return;
      elements.stage.replaceChildren();
      setControls(false);
      showMessage("Não foi possível renderizar o diagrama.", "Verifique a sintaxe do arquivo Mermaid.", true);
    }
  }

  function showMessage(title, detail, isError = false) {
    elements.viewport.hidden = true;
    elements.message.hidden = false;
    elements.message.classList.toggle("error", isError);
    elements.message.replaceChildren();
    const icon = document.createElement("div");
    icon.className = "empty-icon";
    icon.textContent = isError ? "!" : "◇";
    const strong = document.createElement("strong");
    strong.textContent = title;
    elements.message.append(icon, strong);
    if (detail) {
      const span = document.createElement("span");
      span.textContent = detail;
      elements.message.append(span);
    }
  }

  function setControls(enabled) {
    elements.zoomIn.disabled = !enabled;
    elements.zoomOut.disabled = !enabled;
    elements.zoomReset.disabled = !enabled;
  }

  function applyTransform() {
    elements.stage.style.transform = `translate(${translateX}px, ${translateY}px) scale(${scale})`;
    elements.zoomReset.textContent = `${Math.round(scale * 100)}%`;
  }

  function fitDiagram() {
    if (!diagramWidth || elements.viewport.hidden) return;
    const padding = 80;
    scale = Math.min((elements.viewport.clientWidth - padding) / diagramWidth, (elements.viewport.clientHeight - padding) / diagramHeight, 1);
    scale = Math.max(0.2, scale);
    translateX = (elements.viewport.clientWidth - diagramWidth * scale) / 2;
    translateY = (elements.viewport.clientHeight - diagramHeight * scale) / 2;
    applyTransform();
  }

  function zoomTo(nextScale, originX = elements.viewport.clientWidth / 2, originY = elements.viewport.clientHeight / 2) {
    nextScale = Math.max(0.2, Math.min(5, nextScale));
    const diagramX = (originX - translateX) / scale;
    const diagramY = (originY - translateY) / scale;
    translateX = originX - diagramX * nextScale;
    translateY = originY - diagramY * nextScale;
    scale = nextScale;
    applyTransform();
  }

  async function upload(fileList, folderMode) {
    if (!fileList.length) return;
    const form = new FormData();
    [...fileList].forEach((file) => {
      const path = folderMode && file.webkitRelativePath ? file.webkitRelativePath : file.name;
      form.append("paths", path);
      form.append("files", file, file.name);
    });
    setStatus(`Enviando ${fileList.length} ${fileList.length === 1 ? "arquivo" : "arquivos"}…`);
    try {
      const result = await api("/api/files", { method: "POST", body: form });
      const changed = [...result.accepted, ...result.replaced];
      const parts = [];
      if (result.accepted.length) parts.push(`${result.accepted.length} adicionado(s)`);
      if (result.replaced.length) parts.push(`${result.replaced.length} substituído(s)`);
      if (result.rejected.length) parts.push(`${result.rejected.length} rejeitado(s): ${formatRejected(result.rejected)}`);
      setStatus(parts.join(" · "), Boolean(result.rejected.length));
      await refreshFiles(selectedPath);
      if (selectedPath && result.replaced.includes(selectedPath)) await selectFile(selectedPath);
      else if (!selectedPath && changed.length) await selectFile(changed[0]);
    } catch (error) {
      setStatus(error.message, true);
      await refreshFiles();
    } finally {
      elements.fileInput.value = "";
      elements.folderInput.value = "";
    }
  }

  function formatRejected(rejected = []) {
    return rejected.map((item) => `${item.path}: ${item.reason}`).join("; ");
  }

  function setStatus(message, isError = false) {
    elements.status.textContent = message;
    elements.status.classList.toggle("error", isError);
  }

  async function deleteSelected() {
    if (!selectedPath || !window.confirm(`Excluir “${selectedPath}”?`)) return;
    const deleted = selectedPath;
    try {
      await api(`/api/file?path=${encodeURIComponent(deleted)}`, { method: "DELETE" });
      const previousIndex = files.indexOf(deleted);
      selectedPath = null;
      elements.currentFile.hidden = true;
      elements.deleteButton.disabled = true;
      elements.stage.replaceChildren();
      setControls(false);
      await refreshFiles();
      setStatus("Arquivo excluído.");
      const next = files[Math.min(previousIndex, files.length - 1)];
      if (next) await selectFile(next);
      else showMessage("Nenhum diagrama disponível", "Envie um arquivo .mmd para começar.");
    } catch (error) {
      setStatus(error.message, true);
      await refreshFiles();
    }
  }

  function setSidebarCollapsed(collapsed) {
    elements.sidebar.classList.toggle("collapsed", collapsed);
    elements.sidebarToggle.setAttribute("aria-expanded", String(!collapsed));
    elements.sidebarToggle.setAttribute("aria-label", collapsed ? "Abrir menu" : "Recolher menu");
  }

  elements.uploadFiles.addEventListener("click", () => elements.fileInput.click());
  elements.uploadFolder.addEventListener("click", () => elements.folderInput.click());
  elements.fileInput.addEventListener("change", () => upload(elements.fileInput.files, false));
  elements.folderInput.addEventListener("change", () => upload(elements.folderInput.files, true));
  elements.search.addEventListener("input", renderTree);
  elements.deleteButton.addEventListener("click", deleteSelected);
  elements.zoomIn.addEventListener("click", () => zoomTo(scale * 1.2));
  elements.zoomOut.addEventListener("click", () => zoomTo(scale / 1.2));
  elements.zoomReset.addEventListener("click", fitDiagram);
  elements.sidebarToggle.addEventListener("click", () => setSidebarCollapsed(!elements.sidebar.classList.contains("collapsed")));

  elements.viewport.addEventListener("wheel", (event) => {
    event.preventDefault();
    const rect = elements.viewport.getBoundingClientRect();
    zoomTo(scale * (event.deltaY < 0 ? 1.12 : 1 / 1.12), event.clientX - rect.left, event.clientY - rect.top);
  }, { passive: false });

  elements.viewport.addEventListener("pointerdown", (event) => {
    pointer = { id: event.pointerId, x: event.clientX, y: event.clientY, tx: translateX, ty: translateY };
    elements.viewport.setPointerCapture(event.pointerId);
    elements.viewport.classList.add("dragging");
  });
  elements.viewport.addEventListener("pointermove", (event) => {
    if (!pointer || pointer.id !== event.pointerId) return;
    translateX = pointer.tx + event.clientX - pointer.x;
    translateY = pointer.ty + event.clientY - pointer.y;
    applyTransform();
  });
  const endPointer = (event) => {
    if (pointer && pointer.id === event.pointerId) pointer = null;
    elements.viewport.classList.remove("dragging");
  };
  elements.viewport.addEventListener("pointerup", endPointer);
  elements.viewport.addEventListener("pointercancel", endPointer);

  let resizeTimer;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(fitDiagram, 120);
    if (window.innerWidth > 720) setSidebarCollapsed(false);
  });

  refreshFiles();
})();
