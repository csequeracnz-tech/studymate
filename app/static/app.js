const subjectSelect = document.getElementById("subjectSelect");
const subjectSelectorButton = document.getElementById("subjectSelectorButton");
const subjectSelectorLabel = document.getElementById("subjectSelectorLabel");
const subjectSelectorMenu = document.getElementById("subjectSelectorMenu");
const documentList = document.getElementById("documentList");
const materialCount = document.getElementById("materialCount");
const dropZone = document.getElementById("dropZone");
const fileInput = document.getElementById("fileInput");
const refreshButton = document.getElementById("refreshButton");
const conversation = document.getElementById("conversation");
const emptyState = document.getElementById("emptyState");
const chatForm = document.getElementById("chatForm");
const questionInput = document.getElementById("questionInput");
const sendButton = document.getElementById("sendButton");
const newSubjectButton = document.getElementById("newSubjectButton");
const deleteSubjectButton = document.getElementById("deleteSubjectButton");
const newFolderButton = document.getElementById("newFolderButton");

let currentSubjectId = null;
let currentStudyMode = "material";
let currentFolderId = null;
let currentFolderName = null;
let pollingTimer = null;

// El Amigo conversation state
let currentSessionId = null;
let sessionLoading = false;

async function api(url, options = {}) {
    const method = (options.method || "GET").toUpperCase();

    if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
        if (!window.studyMateCsrfToken) {
            const csrfResponse = await fetch("/csrf-token", {
                credentials: "same-origin",
            });

            if (!csrfResponse.ok) {
                throw new Error("Unable to obtain CSRF token");
            }

            const csrfData = await csrfResponse.json();
            window.studyMateCsrfToken = csrfData.csrf_token;
        }

        const headers = new Headers(options.headers || {});
        headers.set(
            "X-CSRF-Token",
            window.studyMateCsrfToken
        );

        options.headers = headers;
    }

    const response = await fetch(url, options);

    if (!response.ok) {
        throw new Error(`Request failed: ${response.status}`);
    }

    return response.json();
}

function renderSubjectSelector() {
    if (!subjectSelectorMenu) return;

    subjectSelectorMenu.innerHTML = "";

    const options = Array.from(subjectSelect.options);

    for (const option of options) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "sidebar-dropdown-option";
        button.dataset.subjectId = option.value;
        button.setAttribute("role", "option");

        const selected =
            String(option.value) === String(currentSubjectId);

        if (selected) {
            button.classList.add("active");
            button.setAttribute("aria-selected", "true");
        } else {
            button.setAttribute("aria-selected", "false");
        }

        button.innerHTML = `
            <span class="sidebar-dropdown-check">${selected ? "✓" : ""}</span>
            <span>${option.textContent}</span>
        `;

        button.addEventListener("click", async () => {
            currentSubjectId = Number(option.value);
            subjectSelect.value = option.value;

            currentFolderId = null;
            currentFolderName = null;
            currentSessionId = null;

            subjectSelectorLabel.textContent = option.textContent;
            subjectSelectorMenu.hidden = true;
            subjectSelectorButton.setAttribute("aria-expanded", "false");

            renderSubjectSelector();

            await loadDocuments();
            await loadCurrentSession();
        });

        subjectSelectorMenu.appendChild(button);
    }

    const selectedOption = options.find(
        option => String(option.value) === String(currentSubjectId)
    );

    subjectSelectorLabel.textContent =
        selectedOption?.textContent || "Select subject";
}


async function loadSubjects() {
    const projects = await api("/projects");
    const subjects = [];

    for (const project of projects) {
        const projectSubjects = await api(`/projects/${project.id}/subjects`);

        for (const subject of projectSubjects) {
            subjects.push({
                ...subject,
                projectName: project.name
            });
        }
    }

    subjectSelect.innerHTML = "";

    for (const subject of subjects) {
        const option = document.createElement("option");
        option.value = subject.id;
        option.textContent = `${subject.name} — ${subject.projectName}`;
        subjectSelect.appendChild(option);
    }

    if (subjects.length) {
        currentSubjectId = Number(subjects[0].id);
        subjectSelect.value = currentSubjectId;
        renderSubjectSelector();
        currentFolderId = null;
        currentFolderName = null;
        await loadDocuments();
    }
}

async function loadDocuments() {
    if (!currentSubjectId) return;

    const [documentData, folderData] = await Promise.all([
        api(`/subjects/${currentSubjectId}/documents`),
        api(`/subjects/${currentSubjectId}/folders`)
    ]);

    const documents = documentData.documents || [];
    const folders = folderData.folders || [];

    documentList.innerHTML = "";

    // Folder navigation.
    if (currentFolderId === null) {
        renderRoot(folders, documents);
    } else {
        renderFolder(
            folders.find(folder => Number(folder.id) === Number(currentFolderId)),
            documents
        );
    }

    const processing = documents.some(
        doc => !doc.ready && doc.status !== "failed"
    );

    if (processing) {
        startPolling();
    } else {
        stopPolling();
    }
}

function renderRoot(folders, documents) {
    materialCount.textContent =
        `${documents.length} ${documents.length === 1 ? "file" : "files"}`;

    const folderDocuments = new Map();

    for (const folder of folders) {
        folderDocuments.set(Number(folder.id), []);
    }

    const unfiled = [];

    for (const doc of documents) {
        if (doc.folder_id && folderDocuments.has(Number(doc.folder_id))) {
            folderDocuments.get(Number(doc.folder_id)).push(doc);
        } else {
            unfiled.push(doc);
        }
    }

    for (const folder of folders) {
        const docs = folderDocuments.get(Number(folder.id)) || [];
        renderFolderCard(folder, docs);
    }

    if (unfiled.length) {
        if (folders.length) {
            addSectionLabel("Unfiled");
        }

        for (const doc of unfiled) {
            renderDocumentCard(doc);
        }
    }

    if (!folders.length && !unfiled.length) {
        renderEmptyMaterials();
    }
}

function renderFolder(folder, documents) {
    if (!folder) {
        currentFolderId = null;
        currentFolderName = null;
        renderRoot([], documents);
        return;
    }

    const folderDocs = documents.filter(
        doc => Number(doc.folder_id) === Number(folder.id)
    );

    materialCount.textContent =
        `${folderDocs.length} ${folderDocs.length === 1 ? "file" : "files"}`;

    const back = document.createElement("button");
    back.className = "folder-back";
    back.type = "button";
    back.innerHTML = "← All materials";

    back.addEventListener("click", async () => {
        currentFolderId = null;
        currentFolderName = null;
        await loadDocuments();
    });

    documentList.appendChild(back);

    const heading = document.createElement("div");
    heading.className = "folder-view-heading";
    heading.innerHTML = `
        <div class="folder-large-icon">📁</div>
        <div>
            <strong>${escapeHtml(folder.name)}</strong>
            <span>${documents.filter(
                doc => Number(doc.folder_id) === Number(folder.id)
            ).length} ${
                documents.filter(
                    doc => Number(doc.folder_id) === Number(folder.id)
                ).length === 1 ? "file" : "files"
            }</span>
        </div>
    `;

    documentList.appendChild(heading);

    if (!folderDocs.length) {
        const empty = document.createElement("div");
        empty.className = "folder-empty";
        empty.textContent = "This folder is empty.";
        documentList.appendChild(empty);
        return;
    }

    for (const doc of folderDocs) {
        renderDocumentCard(doc);
    }
}

function renderFolderCard(folder, documents) {
    const card = document.createElement("div");
    card.className = "folder-card";

    card.innerHTML = `
        <button class="folder-open" type="button">
            <span class="folder-icon">📁</span>
            <span class="folder-info">
                <strong>${escapeHtml(folder.name)}</strong>
            </span>
            <span class="folder-arrow">›</span>
        </button>

        <button
            class="folder-menu-button"
            type="button"
            aria-label="Folder actions"
        >⋯</button>

        <div class="folder-menu" hidden>
            <button class="folder-menu-item rename-folder" type="button">
                ✏️ Rename folder
            </button>
            <button class="folder-menu-item delete-folder" type="button">
                🗑️ Delete folder
            </button>
        </div>
    `;

    const openButton = card.querySelector(".folder-open");
    const menuButton = card.querySelector(".folder-menu-button");
    const menu = card.querySelector(".folder-menu");

    openButton.addEventListener("click", async () => {
        currentFolderId = Number(folder.id);
        currentFolderName = folder.name;
        await loadDocuments();
    });

    menuButton.addEventListener("click", event => {
        event.stopPropagation();

        document.querySelectorAll(".folder-menu").forEach(other => {
            if (other !== menu) other.hidden = true;
        });

        menu.hidden = !menu.hidden;
    });

    menu.querySelector(".rename-folder").addEventListener(
        "click",
        async () => {
            menu.hidden = true;

            const name = window.prompt(
                "Rename folder",
                folder.name
            );

            if (!name || !name.trim() || name.trim() === folder.name) {
                return;
            }

            try {
                const result = await api(`/folders/${folder.id}`, {
                    method: "PATCH",
                    headers: {
                        "Content-Type": "application/json"
                    },
                    body: JSON.stringify({
                        name: name.trim()
                    })
                });

                if (!result.success) {
                    alert(
                        result.error ||
                        "El Amigo couldn't rename that folder."
                    );
                    return;
                }

                await loadDocuments();
            } catch (error) {
                console.error(error);
                alert("El Amigo couldn't rename that folder.");
            }
        }
    );

    menu.querySelector(".delete-folder").addEventListener(
        "click",
        async () => {
            menu.hidden = true;

            const confirmed = window.confirm(
                `Delete "${folder.name}"?\n\n` +
                "The folder will be removed, but its materials " +
                "will stay in your subject as Unfiled."
            );

            if (!confirmed) return;

            try {
                const result = await api(`/folders/${folder.id}`, {
                    method: "DELETE"
                });

                if (!result.success) {
                    alert(
                        result.error ||
                        "El Amigo couldn't delete that folder."
                    );
                    return;
                }

                if (
                    currentFolderId !== null &&
                    Number(currentFolderId) === Number(folder.id)
                ) {
                    currentFolderId = null;
                    currentFolderName = null;
                }

                await loadDocuments();
            } catch (error) {
                console.error(error);
                alert("El Amigo couldn't delete that folder.");
            }
        }
    );

    documentList.appendChild(card);
}

function renderDocumentCard(doc) {
    const card = document.createElement("div");
    card.className = "document-card";

    let statusClass = "";
    let statusLabel = doc.status;

    if (doc.ready) {
        statusClass = "ready";
        statusLabel = "Ready";
    } else if (doc.status === "failed") {
        statusClass = "failed";
        statusLabel = "Failed";
    } else {
        statusLabel = "Processing";
    }

    card.innerHTML = `
        <div class="document-icon">${fileIcon(doc.file_type)}</div>

        <div class="document-details">
            <div class="document-name" title="${escapeHtml(doc.name)}">
                ${escapeHtml(doc.name)}
            </div>

            <div class="document-meta">
                <span class="status-dot ${statusClass}"></span>
                <span>${statusLabel}</span>
            </div>
        </div>

        <button
            class="document-delete-quick"
            type="button"
            aria-label="Delete material"
            title="Delete material"
        >×</button>

        <button
            class="document-menu-button"
            type="button"
            aria-label="Document actions"
            title="More actions"
        >⋯</button>

        <div class="document-menu" hidden>
            <div class="document-menu-title">Material</div>

            <button
                class="document-menu-item move-document"
                type="button"
            >
                📁 Move to folder
            </button>

            <button
                class="document-menu-item rename-document"
                type="button"
            >
                ✏️ Rename
            </button>

            <button
                class="document-menu-item delete-document"
                type="button"
            >
                🗑️ Delete
            </button>
        </div>
    `;


    // Clicking the material opens its preview.
    // Menu controls remain independent.
    card.addEventListener("click", event => {
        if (
            event.target.closest(".document-menu") ||
            event.target.closest(".document-menu-button")
        ) {
            return;
        }

        openDocumentPreview(doc);
    });

    const menuButton = card.querySelector(".document-menu-button");
    const menu = card.querySelector(".document-menu");
    const quickDelete = card.querySelector(".document-delete-quick");

    quickDelete.addEventListener("click", async event => {
        event.preventDefault();
        event.stopPropagation();

        const confirmed = window.confirm(
            `Delete "${doc.name}"?\n\n` +
            "This permanently removes the material and its indexed study content."
        );

        if (!confirmed) return;

        try {
            quickDelete.disabled = true;

            const result = await api(`/documents/${doc.id}`, {
                method: "DELETE"
            });

            if (!result.success) {
                alert(
                    result.error ||
                    "El Amigo couldn't delete that material."
                );
                quickDelete.disabled = false;
                return;
            }

            await loadDocuments();

        } catch (error) {
            console.error("Unable to delete material:", error);
            quickDelete.disabled = false;

            alert(
                "El Amigo couldn't delete that material."
            );
        }
    });

    menuButton.addEventListener("click", async event => {
        event.stopPropagation();

        document.querySelectorAll(".document-menu").forEach(other => {
            if (other !== menu) other.hidden = true;
        });

        if (!menu.hidden) {
            menu.hidden = true;
            return;
        }

        await populateMoveMenu(menu, doc);
        menu.hidden = false;
    });

    menu.querySelector(".rename-document").addEventListener(
        "click",
        async () => {
            menu.hidden = true;

            const name = window.prompt(
                "Rename material",
                doc.name
            );

            if (!name || !name.trim() || name.trim() === doc.name) {
                return;
            }

            try {
                const result = await api(`/documents/${doc.id}`, {
                    method: "PATCH",
                    headers: {
                        "Content-Type": "application/json"
                    },
                    body: JSON.stringify({
                        name: name.trim()
                    })
                });

                if (!result.success) {
                    alert(
                        result.error ||
                        "El Amigo couldn't rename that material."
                    );
                    return;
                }

                await loadDocuments();
            } catch (error) {
                console.error(error);
                alert("El Amigo couldn't rename that material.");
            }
        }
    );

    menu.querySelector(".delete-document").addEventListener(
        "click",
        async () => {
            menu.hidden = true;

            const confirmed = window.confirm(
                `Delete "${doc.name}"?\n\n` +
                "This will remove the material and its indexed " +
                "study content."
            );

            if (!confirmed) return;

            try {
                const result = await api(`/documents/${doc.id}`, {
                    method: "DELETE"
                });

                if (!result.success) {
                    alert(
                        result.error ||
                        "El Amigo couldn't delete that material."
                    );
                    return;
                }

                await loadDocuments();
            } catch (error) {
                console.error(error);
                alert("El Amigo couldn't delete that material.");
            }
        }
    );

    documentList.appendChild(card);
}


function closeDocumentPreview() {
    const modal = document.getElementById(
        "documentPreviewModal"
    );

    if (modal) {
        modal.remove();
    }
}


function getDocumentExtension(doc) {
    const name = doc.name || "";
    const dot = name.lastIndexOf(".");

    if (dot === -1) {
        return "";
    }

    return name.slice(dot).toLowerCase();
}


function openDocumentPreview(doc, pageNumber = null) {
    closeDocumentPreview();

    const modal = document.createElement("div");

    modal.id = "documentPreviewModal";
    modal.className = "document-preview-modal";

    modal.innerHTML = `
        <div class="document-preview-dialog">
            <div class="document-preview-header">
                <div class="document-preview-title">
                    <span class="eyebrow">MATERIAL</span>
                    <h3>${escapeHtml(doc.name)}</h3>
                </div>

                <button
                    type="button"
                    class="document-preview-close"
                    aria-label="Close preview"
                >×</button>
            </div>

            <div
                id="documentPreviewBody"
                class="document-preview-body"
            >
                <div class="document-preview-loading">
                    Loading material…
                </div>
            </div>
        </div>
    `;

    document.body.appendChild(modal);

    const body = document.getElementById(
        "documentPreviewBody"
    );

    const closeButton = modal.querySelector(
        ".document-preview-close"
    );

    closeButton.addEventListener(
        "click",
        closeDocumentPreview
    );

    modal.addEventListener("click", event => {
        if (event.target === modal) {
            closeDocumentPreview();
        }
    });

    const extension = getDocumentExtension(doc);

    let previewUrl =
        `/documents/${doc.id}/preview`;

    if (
        extension === ".pdf" &&
        pageNumber &&
        Number(pageNumber) > 0
    ) {
        previewUrl += `#page=${Number(pageNumber)}`;
    }

    if (extension === ".pdf") {
        body.innerHTML = `
            <iframe
                class="document-preview-frame"
                src="${previewUrl}"
                title="${escapeHtml(doc.name)}"
            ></iframe>
        `;

        return;
    }

    if (
        [".png", ".jpg", ".jpeg", ".webp", ".gif"]
            .includes(extension)
    ) {
        body.innerHTML = `
            <div class="document-preview-image-wrap">
                <img
                    class="document-preview-image"
                    src="${previewUrl}"
                    alt="${escapeHtml(doc.name)}"
                >
            </div>
        `;

        return;
    }

    if (extension === ".txt" || extension === ".md") {
        fetch(previewUrl)
            .then(response => {
                if (!response.ok) {
                    throw new Error(
                        `Preview request failed: ${response.status}`
                    );
                }

                return response.text();
            })
            .then(text => {
                body.innerHTML = "";

                const pre =
                    document.createElement("pre");

                pre.className =
                    "document-preview-text";

                pre.textContent = text;

                body.appendChild(pre);
            })
            .catch(error => {
                console.error(error);

                body.innerHTML = `
                    <div class="document-preview-error">
                        Unable to preview this material.
                    </div>
                `;
            });

        return;
    }

    body.innerHTML = `
        <div class="document-preview-unsupported">
            <div class="document-preview-file-icon">
                📄
            </div>

            <h4>Preview isn't available for this file type</h4>

            <p>
                This material can still be used by El Amigo,
                but your browser cannot display it directly.
            </p>

            <a
                class="document-preview-download"
                href="${previewUrl}"
                target="_blank"
                rel="noopener"
            >
                Open material
            </a>
        </div>
    `;
}


async function populateMoveMenu(menu, doc) {
    const folderData = await api(
        `/subjects/${currentSubjectId}/folders`
    );

    const folders = folderData.folders || [];

    menu.innerHTML = `
        <div class="document-menu-title">Move to…</div>

        <button
            class="document-menu-item"
            type="button"
            data-folder-id=""
        >
            📄 Unfiled
        </button>

        ${folders.map(folder => `
            <button
                class="document-menu-item"
                type="button"
                data-folder-id="${folder.id}"
            >
                📁 ${escapeHtml(folder.name)}
            </button>
        `).join("")}
    `;

    menu.querySelectorAll(".document-menu-item").forEach(button => {
        button.addEventListener("click", async () => {
            const rawFolderId = button.dataset.folderId;
            const folderId = rawFolderId === ""
                ? null
                : Number(rawFolderId);

            if (
                folderId === null &&
                doc.folder_id === null
            ) {
                menu.hidden = true;
                return;
            }

            if (
                folderId !== null &&
                Number(doc.folder_id) === folderId
            ) {
                menu.hidden = true;
                return;
            }

            try {
                const result = await api(
                    `/documents/${doc.id}/folder`,
                    {
                        method: "PATCH",
                        headers: {
                            "Content-Type": "application/json"
                        },
                        body: JSON.stringify({
                            folder_id: folderId
                        })
                    }
                );

                if (!result.success) {
                    alert(
                        result.error ||
                        "El Amigo couldn't move that material."
                    );
                    return;
                }

                menu.hidden = true;
                await loadDocuments();
            } catch (error) {
                console.error(error);
                alert(
                    "El Amigo couldn't move that material."
                );
            }
        });
    });
}

document.addEventListener("click", () => {
    document.querySelectorAll(".document-menu").forEach(menu => {
        menu.hidden = true;
    });
});

function addSectionLabel(text) {
    const label = document.createElement("div");
    label.className = "materials-section-label";
    label.textContent = text;
    documentList.appendChild(label);
}

function renderEmptyMaterials() {
    const empty = document.createElement("div");
    empty.className = "materials-empty";
    empty.innerHTML = `
        <div>📚</div>
        <strong>No materials yet</strong>
        <span>Upload your study material to get started.</span>
    `;
    documentList.appendChild(empty);
}

function fileIcon(type) {
    const icons = {
        ".pdf": "📕",
        ".doc": "📘",
        ".docx": "📘",
        ".ppt": "📙",
        ".pptx": "📙",
        ".xls": "📗",
        ".xlsx": "📗",
        ".csv": "📗",
        ".jpg": "🖼️",
        ".jpeg": "🖼️",
        ".png": "🖼️",
        ".webp": "🖼️",
        ".tiff": "🖼️",
        ".txt": "📝",
        ".md": "📝"
    };

    return icons[(type || "").toLowerCase()] || "📄";
}

async function startPollingIfNeeded() {
    await loadDocuments();
}

function startPolling() {
    if (pollingTimer) return;

    pollingTimer = setInterval(() => {
        loadDocuments().catch(console.error);
    }, 1500);
}

function stopPolling() {
    if (!pollingTimer) return;

    clearInterval(pollingTimer);
    pollingTimer = null;
}

async function uploadFiles(files) {
    if (!currentSubjectId || !files.length) return;

    for (const file of files) {
        const formData = new FormData();
        formData.append("file", file);

        if (currentFolderId !== null) {
            formData.append("folder_id", String(currentFolderId));
        }

        await api(`/subjects/${currentSubjectId}/documents`, {
            method: "POST",
            body: formData
        });
    }

    await loadDocuments();
    startPolling();
}

function addUserMessage(text) {
    removeEmptyState();

    const message = document.createElement("div");
    message.className = "message user";
    message.innerHTML = `
        <div class="bubble">${escapeHtml(text)}</div>
    `;

    conversation.appendChild(message);
    scrollConversation();
}

function addThinkingMessage() {
    removeEmptyState();

    const message = document.createElement("div");
    message.className = "message assistant";
    message.id = "thinkingMessage";
    message.innerHTML = `
        <div class="assistant-label">El Amigo</div>
        <div class="bubble thinking">Thinking with your material…</div>
    `;

    conversation.appendChild(message);
    scrollConversation();
}

function addAssistantMessage(
    answer,
    sources = [],
    researchSources = []
) {
    const thinking = document.getElementById("thinkingMessage");
    if (thinking) thinking.remove();

    const message = document.createElement("div");
    message.className = "message assistant";

    const materialHtml = sources.length
        ? `
            <div class="sources">
                <div class="sources-title">Your material</div>
                ${sources.map((source, index) => {
                    const location = sourceLocation(source);
                    const ref = `M${index + 1}`;

                    return `
                        <span class="source-card material-source-card">
                            <strong>${ref}</strong>
                            · ${escapeHtml(source.document_name)}
                            ${location ? ` · ${escapeHtml(location)}` : ""}
                        </span>
                    `;
                }).join("")}
            </div>
        `
        : "";

    const researchHtml = researchSources.length
        ? `
            <div class="sources research-sources">
                <div class="sources-title">External research · APA 7</div>

                ${researchSources.map(source => `
                    <div
                        class="research-source-card"
                        id="research-source-${escapeHtml(source.ref)}"
                    >
                        <div class="research-source-top">
                            <span class="research-ref">
                                ${escapeHtml(source.ref)}
                            </span>

                            <span class="research-host">
                                ${escapeHtml(source.hostname || "")}
                            </span>
                        </div>

                        <div class="research-source-title">
                            ${escapeHtml(source.title || source.label || "")}
                        </div>

                        ${
                            source.in_text_citation
                                ? `
                                    <div class="research-source-citation">
                                        ${escapeHtml(source.in_text_citation)}
                                    </div>
                                `
                                : ""
                        }

                        <div class="research-source-actions">
                            <a
                                href="${escapeHtml(source.url)}"
                                target="_blank"
                                rel="noopener noreferrer"
                            >Open source ↗</a>

                            <button
                                type="button"
                                class="copy-apa-button"
                                data-apa="${escapeHtml(source.apa_reference || "")}"
                            >Copy APA</button>
                        </div>
                    </div>
                `).join("")}
            </div>
        `
        : "";

    message.innerHTML = `
        <div class="assistant-label">El Amigo</div>
        <div class="bubble">${escapeHtml(answer)}</div>
        ${materialHtml}
        ${researchHtml}
    `;

    message.querySelectorAll(".copy-apa-button").forEach(button => {
        button.addEventListener("click", async () => {
            const citation = button.dataset.apa || "";

            if (!citation) return;

            try {
                await navigator.clipboard.writeText(citation);

                const oldText = button.textContent;
                button.textContent = "Copied ✓";

                setTimeout(() => {
                    button.textContent = oldText;
                }, 1400);
            } catch (error) {
                console.error("Could not copy APA citation", error);
            }
        });
    });

    conversation.appendChild(message);
    scrollConversation();
}

function sourceLocation(source) {
    if (source.page_number) return `page ${source.page_number}`;
    if (source.slide_number) return `slide ${source.slide_number}`;
    if (source.sheet_name) return `sheet ${source.sheet_name}`;
    if (source.section) return source.section;
    return "";
}

function removeEmptyState() {
    const state = document.getElementById("emptyState");
    if (state) state.remove();
}

function scrollConversation() {
    conversation.scrollTop = conversation.scrollHeight;
}

function escapeHtml(value) {
    const div = document.createElement("div");
    div.textContent = value ?? "";
    return div.innerHTML;
}

newSubjectButton.addEventListener("click", async () => {
    const name = window.prompt("What would you like to call this subject?");

    if (!name || !name.trim()) return;

    try {
        const projects = await api("/projects");

        if (!projects.length) {
            alert("No StudyMate project exists yet.");
            return;
        }

        const projectId = projects[0].id;

        const result = await api(`/projects/${projectId}/subjects`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                name: name.trim(),
                description: ""
            })
        });

        await loadSubjects();

        if (result.id) {
            currentSubjectId = Number(result.id);
            subjectSelect.value = String(result.id);
            renderSubjectSelector();
            currentFolderId = null;
            currentFolderName = null;
            await loadDocuments();
        }
    } catch (error) {
        console.error(error);
        alert("El Amigo couldn't create that subject.");
    }
});

deleteSubjectButton.addEventListener("click", async event => {
    event.preventDefault();
    event.stopPropagation();

    if (!currentSubjectId) return;

    const selectedOption = Array.from(subjectSelect.options).find(
        option => Number(option.value) === Number(currentSubjectId)
    );

    const subjectName =
        selectedOption?.textContent?.split(" — ")[0] ||
        "this subject";

    const confirmed = window.confirm(
        `Delete "${subjectName}"?\n\n` +
        "This permanently deletes all materials, folders and conversations " +
        "inside this subject.\n\n" +
        "This cannot be undone."
    );

    if (!confirmed) return;

    try {
        deleteSubjectButton.disabled = true;

        const deletedSubjectId = currentSubjectId;

        const result = await api(
            `/subjects/${deletedSubjectId}`,
            { method: "DELETE" }
        );

        if (!result.success) {
            alert(
                result.error ||
                "El Amigo couldn't delete that subject."
            );
            return;
        }

        localStorage.removeItem(
            `studymate_session_${deletedSubjectId}`
        );

        currentSubjectId = null;
        currentSessionId = null;
        currentFolderId = null;
        currentFolderName = null;

        clearConversation();

        await loadSubjects();

        if (!currentSubjectId) {
            subjectSelectorLabel.textContent = "No subjects";
            subjectSelectorMenu.innerHTML = "";
            documentList.innerHTML = "";
            materialCount.textContent = "0 files";
        }

    } catch (error) {
        console.error("Unable to delete subject:", error);
        alert("El Amigo couldn't delete that subject.");

    } finally {
        deleteSubjectButton.disabled = false;
    }
});


newFolderButton.addEventListener("click", async () => {
    if (!currentSubjectId) return;

    const name = window.prompt("What would you like to call this folder?");

    if (!name || !name.trim()) return;

    try {
        const result = await api(
            `/subjects/${currentSubjectId}/folders`,
            {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({
                    name: name.trim(),
                    description: ""
                })
            }
        );

        if (!result.success) {
            alert(result.error || "El Amigo couldn't create that folder.");
            return;
        }

        await loadDocuments();
    } catch (error) {
        console.error(error);
        alert("El Amigo couldn't create that folder.");
    }
});

subjectSelectorButton.addEventListener("click", event => {
    event.stopPropagation();

    const opening = subjectSelectorMenu.hidden;

    subjectSelectorMenu.hidden = !opening;
    subjectSelectorButton.setAttribute(
        "aria-expanded",
        opening ? "true" : "false"
    );

    if (opening) {
        renderSubjectSelector();
    }
});

document.addEventListener("click", event => {
    if (
        !subjectSelectorMenu.hidden &&
        !subjectSelectorMenu.contains(event.target) &&
        !subjectSelectorButton.contains(event.target)
    ) {
        subjectSelectorMenu.hidden = true;
        subjectSelectorButton.setAttribute("aria-expanded", "false");
    }
});

refreshButton.addEventListener("click", () => {
    loadDocuments().catch(console.error);
});

dropZone.addEventListener("click", () => fileInput.click());

fileInput.addEventListener("change", async () => {
    await uploadFiles([...fileInput.files]);
    fileInput.value = "";
});

["dragenter", "dragover"].forEach(eventName => {
    dropZone.addEventListener(eventName, event => {
        event.preventDefault();
        dropZone.classList.add("dragging");
    });
});

["dragleave", "drop"].forEach(eventName => {
    dropZone.addEventListener(eventName, event => {
        event.preventDefault();
        dropZone.classList.remove("dragging");
    });
});

dropZone.addEventListener("drop", async event => {
    await uploadFiles([...event.dataTransfer.files]);
});


// ------------------------------------------------------------------
// El Amigo conversations
// ------------------------------------------------------------------


// ------------------------------------------------------------------
// Conversation history
// ------------------------------------------------------------------

function ensureConversationHistoryUI() {
    if (document.getElementById("conversationHistory")) {
        return;
    }

    const sidebar = document.querySelector(".sidebar");
    const materialsHeader =
        document.querySelector(".materials-header");

    if (!sidebar || !materialsHeader) {
        return;
    }

    const panel = document.createElement("div");

    panel.id = "conversationHistory";
    panel.className = "conversation-history";

    panel.innerHTML = `
        <div class="conversation-history-header">
            <h2>Conversations</h2>

            <button
                id="newConversationButton"
                class="new-conversation-button"
                type="button"
                aria-label="New conversation"
                title="New conversation"
            >+</button>
        </div>

        <div
            id="conversationHistoryList"
            class="conversation-history-list"
        ></div>
    `;

    sidebar.insertBefore(panel, materialsHeader);

    const button =
        document.getElementById("newConversationButton");

    button.addEventListener("click", async () => {
        if (!currentSubjectId) return;

        await createNewSession();
    });
}


function ensureMaterialSearchUI() {
    if (document.getElementById("materialSearchPanel")) {
        return;
    }

    const sidebar = document.querySelector(".sidebar");
    const materialsHeader =
        document.querySelector(".materials-header");

    if (!sidebar || !materialsHeader) {
        return;
    }

    const panel = document.createElement("div");

    panel.id = "materialSearchPanel";
    panel.className = "material-search-panel";

    panel.innerHTML = `
        <div class="material-search-heading">
            <span>Search materials</span>
        </div>

        <div class="material-search-box">
            <span class="material-search-icon">⌕</span>
            <input
                id="materialSearchInput"
                type="search"
                autocomplete="off"
                placeholder="Search notes, PDFs, slides..."
                aria-label="Search study materials"
            >
        </div>

        <div
            id="materialSearchResults"
            class="material-search-results"
            hidden
        ></div>
    `;

    sidebar.insertBefore(panel, materialsHeader);

    const input =
        document.getElementById("materialSearchInput");

    const results =
        document.getElementById("materialSearchResults");

    let timer = null;
    let requestNumber = 0;

    input.addEventListener("input", () => {
        clearTimeout(timer);

        const query = input.value.trim();

        if (query.length < 2) {
            requestNumber += 1;
            results.innerHTML = "";
            results.hidden = true;
            return;
        }

        timer = setTimeout(async () => {
            if (!currentSubjectId) return;

            const thisRequest = ++requestNumber;

            results.hidden = false;
            results.innerHTML = `
                <div class="material-search-status">
                    Searching…
                </div>
            `;

            try {
                const result = await api(
                    `/search?q=${encodeURIComponent(query)}` +
                    `&subject_id=${currentSubjectId}&limit=8`
                );

                if (thisRequest !== requestNumber) {
                    return;
                }

                renderMaterialSearchResults(
                    result.results || [],
                    results
                );
            } catch (error) {
                console.error(error);

                if (thisRequest !== requestNumber) {
                    return;
                }

                results.innerHTML = `
                    <div class="material-search-status">
                        Search unavailable.
                    </div>
                `;
            }
        }, 280);
    });

    document.addEventListener("click", event => {
        if (
            !panel.contains(event.target) &&
            input.value.trim() === ""
        ) {
            results.hidden = true;
        }
    });
}


function materialSearchLocation(item) {
    if (item.page_number) {
        return `Page ${item.page_number}`;
    }

    if (item.slide_number) {
        return `Slide ${item.slide_number}`;
    }

    if (item.sheet_name) {
        return `Sheet: ${item.sheet_name}`;
    }

    if (item.section) {
        return item.section;
    }

    return "";
}


function renderMaterialSearchResults(items, container) {
    container.innerHTML = "";

    if (!items.length) {
        container.innerHTML = `
            <div class="material-search-status">
                No matching material found.
            </div>
        `;
        return;
    }

    for (const item of items) {
        const button = document.createElement("button");

        button.type = "button";
        button.className = "material-search-result";

        const location =
            materialSearchLocation(item);

        const content =
            String(item.content || "")
                .replace(/\s+/g, " ")
                .trim();

        const snippet =
            content.length > 180
                ? content.slice(0, 180) + "…"
                : content;

        button.innerHTML = `
            <div class="material-search-result-top">
                <strong>
                    ${escapeHtml(item.document_name || "Material")}
                </strong>
                ${
                    location
                        ? `<span>${escapeHtml(location)}</span>`
                        : ""
                }
            </div>

            <div class="material-search-snippet">
                ${escapeHtml(snippet)}
            </div>
        `;

        button.addEventListener("click", () => {
            openDocumentPreview(
                {
                    id: item.document_id,
                    name: item.document_name
                },
                item.page_number || null
            );
        });

        container.appendChild(button);
    }
}


function formatConversationDate(value) {
    const date = new Date(value);

    if (Number.isNaN(date.getTime())) {
        return "";
    }

    const now = new Date();

    const sameDay =
        date.getFullYear() === now.getFullYear() &&
        date.getMonth() === now.getMonth() &&
        date.getDate() === now.getDate();

    if (sameDay) {
        return "Today";
    }

    const yesterday = new Date(now);
    yesterday.setDate(now.getDate() - 1);

    const isYesterday =
        date.getFullYear() === yesterday.getFullYear() &&
        date.getMonth() === yesterday.getMonth() &&
        date.getDate() === yesterday.getDate();

    if (isYesterday) {
        return "Yesterday";
    }

    return date.toLocaleDateString(
        undefined,
        {
            day: "numeric",
            month: "short"
        }
    );
}


function conversationTitle(item) {
    const title = (item.title || "").trim();

    if (
        title &&
        title.toLowerCase() !== "new study session"
    ) {
        return title;
    }

    return "New study session";
}


async function loadConversationHistory() {
    ensureConversationHistoryUI();

    const list = document.getElementById(
        "conversationHistoryList"
    );

    if (!list || !currentSubjectId) {
        return;
    }

    try {
        const result = await api(
            `/subjects/${currentSubjectId}/sessions`
        );

        if (!result.success) {
            list.innerHTML =
                '<div class="conversation-history-empty">' +
                "Unable to load conversations." +
                "</div>";
            return;
        }

        const sessions = result.sessions || [];

        list.innerHTML = "";

        if (!sessions.length) {
            list.innerHTML =
                '<div class="conversation-history-empty">' +
                "No conversations yet." +
                "</div>";
            return;
        }

        let lastDateLabel = null;

        for (const item of sessions) {
            const dateLabel =
                formatConversationDate(item.updated_at);

            if (dateLabel !== lastDateLabel) {
                const dateHeading =
                    document.createElement("div");

                dateHeading.className =
                    "conversation-date-heading";

                dateHeading.textContent = dateLabel;

                list.appendChild(dateHeading);

                lastDateLabel = dateLabel;
            }

            const button = document.createElement("button");

            button.type = "button";
            button.className = "conversation-history-item";

            if (
                currentSessionId !== null &&
                Number(item.id) === Number(currentSessionId)
            ) {
                button.classList.add("active");
            }

            button.dataset.sessionId = item.id;

            button.innerHTML = `
                <span class="conversation-history-icon">
                    💬
                </span>
                <span class="conversation-history-title">
                    ${escapeHtml(conversationTitle(item))}
                </span>
            `;

            button.addEventListener("click", async () => {
                const sessionId =
                    Number(button.dataset.sessionId);

                if (!sessionId) return;

                currentSessionId = sessionId;

                localStorage.setItem(
                    `studymate_session_${currentSubjectId}`,
                    String(sessionId)
                );

                await loadSession(sessionId);
                await loadConversationHistory();
            });

            const row = document.createElement("div");
            row.className = "conversation-history-row";

            const deleteButton = document.createElement("button");
            deleteButton.type = "button";
            deleteButton.className = "conversation-delete-button";
            deleteButton.innerHTML = "&times;";
            deleteButton.title = "Delete conversation";
            deleteButton.setAttribute(
                "aria-label",
                `Delete ${conversationTitle(item)}`
            );

            deleteButton.addEventListener("click", async event => {
                event.preventDefault();
                event.stopPropagation();

                const sessionId = Number(item.id);
                if (!sessionId) return;

                const confirmed = window.confirm(
                    `Delete "${conversationTitle(item)}"?\n\n` +
                    "This conversation and its messages will be permanently deleted."
                );

                if (!confirmed) return;

                try {
                    const result = await api(
                        `/sessions/${sessionId}`,
                        { method: "DELETE" }
                    );

                    if (!result.success) {
                        alert(
                            result.error ||
                            "El Amigo couldn't delete the conversation."
                        );
                        return;
                    }

                    const wasActive =
                        Number(currentSessionId) === sessionId;

                    if (wasActive) {
                        localStorage.removeItem(
                            `studymate_session_${currentSubjectId}`
                        );

                        currentSessionId = null;
                        clearConversation();

                        // Stay genuinely blank until the user sends
                        // her next message.
                    }

                    await loadConversationHistory();
                    questionInput.focus();

                } catch (error) {
                    console.error(
                        "Unable to delete conversation:",
                        error
                    );

                    alert(
                        "El Amigo couldn't delete the conversation."
                    );
                }
            });

            row.appendChild(button);
            row.appendChild(deleteButton);
            list.appendChild(row);
        }
    } catch (error) {
        console.error(
            "Unable to load conversation history:",
            error
        );

        list.innerHTML =
            '<div class="conversation-history-empty">' +
            "Unable to load conversations." +
            "</div>";
    }
}


// ------------------------------------------------------------------
// Portable study summaries
// ------------------------------------------------------------------

function ensureSummaryUI() {
    if (document.getElementById("summaryButton")) {
        return;
    }

    const header = document.querySelector(".chat-header");

    if (!header) return;

    const actions = document.createElement("div");
    actions.className = "chat-header-actions";

    const summaryButton = document.createElement("button");

    summaryButton.id = "summaryButton";
    summaryButton.type = "button";
    summaryButton.className = "summary-button";
    summaryButton.textContent = "Create summary";

    summaryButton.addEventListener(
        "click",
        generateSummary
    );

    actions.appendChild(summaryButton);
    header.appendChild(actions);
}


function closeSummaryModal() {
    const modal =
        document.getElementById("summaryModal");

    if (modal) {
        modal.remove();
    }
}


function showSummaryModal(
    summary,
    scope,
    sources
) {
    closeSummaryModal();

    const modal = document.createElement("div");

    modal.id = "summaryModal";
    modal.className = "summary-modal";

    const sourceText = sources
        .map(source => {
            const locations =
                source.locations &&
                source.locations.length
                    ? ` — ${source.locations.join(", ")}`
                    : "";

            return `- ${source.document_name}${locations}`;
        })
        .join("\n");

    const portableText =
        `${summary}\n\n` +
        `---\n` +
        `Source material:\n` +
        sourceText;

    modal.innerHTML = `
        <div class="summary-dialog">
            <div class="summary-dialog-header">
                <div>
                    <span class="eyebrow">
                        STUDY SUMMARY
                    </span>
                    <h3>${escapeHtml(scope)}</h3>
                </div>

                <button
                    id="closeSummaryButton"
                    class="summary-close"
                    type="button"
                    aria-label="Close"
                >×</button>
            </div>

            <div
                id="summaryContent"
                class="summary-content"
            ></div>

            <div class="summary-dialog-footer">
                <span id="summaryCopyStatus">
                    Ready to copy into another AI
                </span>

                <button
                    id="copySummaryButton"
                    class="summary-copy-button"
                    type="button"
                >
                    Copy for AI
                </button>
            </div>
        </div>
    `;

    document.body.appendChild(modal);

    document.getElementById(
        "summaryContent"
    ).textContent = portableText;

    document.getElementById(
        "closeSummaryButton"
    ).addEventListener(
        "click",
        closeSummaryModal
    );

    document.getElementById(
        "copySummaryButton"
    ).addEventListener(
        "click",
        async () => {
            try {
                await navigator.clipboard.writeText(
                    portableText
                );

                document.getElementById(
                    "summaryCopyStatus"
                ).textContent =
                    "Copied — ready to paste into another AI";

            } catch (error) {
                console.error(error);

                document.getElementById(
                    "summaryCopyStatus"
                ).textContent =
                    "Copy failed — select the text manually.";
            }
        }
    );

    modal.addEventListener(
        "click",
        event => {
            if (event.target === modal) {
                closeSummaryModal();
            }
        }
    );
}


async function generateSummary() {
    if (!currentSubjectId) {
        return;
    }

    const button =
        document.getElementById("summaryButton");

    if (button) {
        button.disabled = true;
        button.textContent = "Creating...";
    }

    try {
        const body = {};

        if (currentFolderId !== null) {
            body.folder_id = currentFolderId;
        }

        const result = await api(
            `/subjects/${currentSubjectId}/summary`,
            {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify(body)
            }
        );

        if (!result.success) {
            alert(
                result.error ||
                "El Amigo couldn't create the summary."
            );
            return;
        }

        showSummaryModal(
            result.summary,
            result.scope,
            result.sources || []
        );

    } catch (error) {
        console.error(error);

        alert(
            "El Amigo couldn't create the summary."
        );
    } finally {
        if (button) {
            button.disabled = false;
            button.textContent = "Create summary";
        }
    }
}

function clearConversation() {
    conversation.innerHTML = "";

    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.id = "emptyState";

    empty.innerHTML = `
        <div class="empty-mark">EA</div>
        <h3>What would you like to study?</h3>
        <p>
            Ask El Amigo questions about your study material
            and build your understanding step by step.
        </p>
        <div class="suggestions">
            <button class="suggestion" type="button">
                Summarise my study material
            </button>
            <button class="suggestion" type="button">
                Explain the key concepts
            </button>
            <button class="suggestion" type="button">
                Quiz me on this subject
            </button>
        </div>
    `;

    conversation.appendChild(empty);

    empty.querySelectorAll(".suggestion").forEach(button => {
        button.addEventListener("click", () => {
            questionInput.value = button.textContent;
            questionInput.focus();
        });
    });
}


async function createNewSession() {
    if (!currentSubjectId) return;

    try {
        const result = await api(
            `/subjects/${currentSubjectId}/sessions`,
            {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({
                    title: "New study session"
                })
            }
        );

        if (!result.success) {
            alert(
                result.error ||
                "El Amigo couldn't create a new conversation."
            );
            return;
        }

        currentSessionId = Number(result.session.id);

        localStorage.setItem(
            `studymate_session_${currentSubjectId}`,
            String(currentSessionId)
        );

        clearConversation();
        await loadConversationHistory();
    } catch (error) {
        console.error(error);
        alert(
            "El Amigo couldn't create a new conversation."
        );
    }
}


async function loadSession(sessionId) {
    if (!sessionId) {
        await createNewSession();
        return;
    }

    sessionLoading = true;

    try {
        const result = await api(
            `/sessions/${sessionId}`
        );

        if (
            !result.success ||
            !result.session ||
            Number(result.session.subject_id) !==
                Number(currentSubjectId)
        ) {
            await createNewSession();
            return;
        }

        currentSessionId = Number(result.session.id);

        clearConversation();

        const messages = result.session.messages || [];

        if (!messages.length) {
            return;
        }

        const empty = document.getElementById("emptyState");

        if (empty) {
            empty.remove();
        }

        for (const message of messages) {
            if (message.role === "user") {
                addUserMessage(message.content);
            } else if (message.role === "assistant") {
                addAssistantMessage(
                    message.content,
                    []
                );
            }
        }

        await loadConversationHistory();
    } catch (error) {
        console.error("Unable to load study session:", error);

        // Don't lose the user to a broken session.
        await createNewSession();
    } finally {
        sessionLoading = false;
    }
}


async function loadCurrentSession() {
    if (!currentSubjectId) return;

    const key =
        `studymate_session_${currentSubjectId}`;

    const storedSessionId =
        localStorage.getItem(key);

    if (storedSessionId) {
        await loadSession(Number(storedSessionId));
    } else {
        currentSessionId = null;
        clearConversation();
    }
}

chatForm.addEventListener("submit", async event => {
    event.preventDefault();

    const question = questionInput.value.trim();

    if (
        !question ||
        !currentSubjectId ||
        sessionLoading
    ) {
        return;
    }

    // Create a session automatically if one doesn't exist.
    if (!currentSessionId) {
        await createNewSession();

        if (!currentSessionId) {
            return;
        }
    }

    addUserMessage(question);
    addThinkingMessage();

    questionInput.value = "";
    sendButton.disabled = true;

    try {
        const result = await api("/ask", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                question,
                subject_id: currentSubjectId,
                limit: 5,
                session_id: currentSessionId,
                mode: currentStudyMode
            })
        });

        if (result.success) {
            addAssistantMessage(
                result.answer,
                result.sources || [],
                result.research_sources || []
            );

            if (result.session_id) {
                currentSessionId =
                    Number(result.session_id);

                localStorage.setItem(
                    `studymate_session_${currentSubjectId}`,
                    String(currentSessionId)
                );

                await loadConversationHistory();
            }
        } else {
            addAssistantMessage(
                result.error ||
                "I couldn't answer that question."
            );
        }
    } catch (error) {
        addAssistantMessage(
            "I had trouble reaching the study service. Please try again."
        );

        console.error(error);
    } finally {
        sendButton.disabled = false;
        questionInput.focus();
    }
});


const sourceSelectorButton =
    document.getElementById("sourceSelectorButton");

const sourceSelectorMenu =
    document.getElementById("sourceSelectorMenu");

const sourceSelectorLabel =
    document.getElementById("sourceSelectorLabel");


function setStudyMode(mode) {
    currentStudyMode =
        mode === "research"
            ? "research"
            : "material";

    const research =
        currentStudyMode === "research";

    sourceSelectorLabel.textContent =
        research
            ? "Material + Research"
            : "My material only";

    document
        .querySelectorAll(".source-option")
        .forEach(option => {
            const selected =
                option.dataset.mode === currentStudyMode;

            option.classList.toggle(
                "active",
                selected
            );

            const check =
                option.querySelector(
                    ".source-option-check"
                );

            if (check) {
                check.textContent =
                    selected ? "✓" : "";
            }
        });

    questionInput.placeholder =
        research
            ? "Ask El Amigo to research a topic..."
            : "Ask El Amigo about your study material...";

    localStorage.setItem(
        "studymate_mode",
        currentStudyMode
    );
}


function closeSourceSelector() {
    sourceSelectorMenu.hidden = true;

    sourceSelectorButton.setAttribute(
        "aria-expanded",
        "false"
    );
}


sourceSelectorButton.addEventListener(
    "click",
    event => {
        event.stopPropagation();

        const opening =
            sourceSelectorMenu.hidden;

        sourceSelectorMenu.hidden =
            !opening;

        sourceSelectorButton.setAttribute(
            "aria-expanded",
            String(opening)
        );
    }
);


document
    .querySelectorAll(".source-option")
    .forEach(option => {
        option.addEventListener(
            "click",
            event => {
                event.stopPropagation();

                setStudyMode(
                    option.dataset.mode
                );

                closeSourceSelector();
                questionInput.focus();
            }
        );
    });


document.addEventListener(
    "click",
    event => {
        if (
            !event.target.closest(
                ".source-selector"
            )
        ) {
            closeSourceSelector();
        }
    }
);


setStudyMode(
    localStorage.getItem("studymate_mode") ||
    "material"
);


document.querySelectorAll(".suggestion").forEach(button => {
    button.addEventListener("click", () => {
        questionInput.value = button.textContent;
        questionInput.focus();
    });
});

questionInput.addEventListener("input", () => {
    questionInput.style.height = "auto";
    questionInput.style.height =
        Math.min(questionInput.scrollHeight, 160) + "px";
});

ensureConversationHistoryUI();
ensureMaterialSearchUI();
ensureSummaryUI();

loadSubjects().then(() => {
    return loadCurrentSession();
}).catch(error => {
    console.error(error);
    documentList.innerHTML =
        '<div class="document-card">Unable to load StudyMate.</div>';
});

/* ==========================================================
   Composer keyboard behaviour
   Enter       = send
   Shift+Enter = new line
   ========================================================== */

document.addEventListener("keydown", function (event) {
    const input = document.getElementById("questionInput");

    if (!input || event.target !== input) {
        return;
    }

    if (
        event.key === "Enter" &&
        !event.shiftKey &&
        !event.isComposing
    ) {
        event.preventDefault();

        if (
            chatForm &&
            !sendButton.disabled &&
            input.value.trim()
        ) {
            chatForm.requestSubmit();
        }
    }
});


// ------------------------------------------------------------------
// StudyMate multi-format output creation
// ------------------------------------------------------------------

const STUDYMATE_OUTPUT_FORMATS = {
    docx: {
        label: "Word document",
        shortLabel: "Word",
        description: "Assignments, reports and study guides",
        extension: "DOCX",
        example:
            "Create a detailed study guide from this conversation with clear headings and APA 7 references."
    },
    pdf: {
        label: "PDF",
        shortLabel: "PDF",
        description: "Polished study handouts and final copies",
        extension: "PDF",
        example:
            "Create a polished study handout covering the key concepts, comparisons and references."
    },
    pptx: {
        label: "PowerPoint",
        shortLabel: "PowerPoint",
        description: "Presentations and revision decks",
        extension: "PPTX",
        example:
            "Create a 10-slide presentation explaining the main ideas, with concise slides and APA 7 references."
    },
    xlsx: {
        label: "Excel workbook",
        shortLabel: "Excel",
        description: "Evidence tables and research matrices",
        extension: "XLSX",
        example:
            "Create an evidence table comparing the concepts, research findings and sources discussed."
    }
};


function ensureOutputUI() {
    if (document.getElementById("createOutputButton")) {
        return;
    }

    const header = document.querySelector(".chat-header");
    if (!header) return;

    let actions = header.querySelector(".chat-header-actions");

    if (!actions) {
        actions = document.createElement("div");
        actions.className = "chat-header-actions";
        header.appendChild(actions);
    }

    const wrapper = document.createElement("div");
    wrapper.className = "create-output-wrapper";

    wrapper.innerHTML = `
        <button
            id="createOutputButton"
            class="create-output-button"
            type="button"
            aria-haspopup="true"
            aria-expanded="false"
        >
            <span>＋ Create</span>
            <span class="create-output-chevron">⌄</span>
        </button>

        <div
            id="createOutputMenu"
            class="create-output-menu"
            hidden
        >
            <div class="create-output-menu-header">
                <strong>Create something</strong>
                <span>Turn this conversation into a study resource</span>
            </div>

            <div class="create-output-options">
                ${Object.entries(STUDYMATE_OUTPUT_FORMATS)
                    .map(([format, item]) => `
                        <button
                            class="create-output-option"
                            type="button"
                            data-output-format="${format}"
                        >
                            <span class="create-output-icon create-output-icon-${format}">
                                ${format === "docx" ? `
                                    <svg viewBox="0 0 24 24" aria-hidden="true">
                                        <path d="M6 2.75h8l4 4V21.25H6z"/>
                                        <path d="M14 2.75v4h4"/>
                                        <path d="M8.5 11h7M8.5 14h7M8.5 17h4.5"/>
                                    </svg>
                                ` : format === "pdf" ? `
                                    <svg viewBox="0 0 24 24" aria-hidden="true">
                                        <path d="M6 2.75h8l4 4V21.25H6z"/>
                                        <path d="M14 2.75v4h4"/>
                                        <path d="M8.5 12.5h7M8.5 15.5h5"/>
                                    </svg>
                                ` : format === "pptx" ? `
                                    <svg viewBox="0 0 24 24" aria-hidden="true">
                                        <rect x="3.5" y="4" width="17" height="12" rx="1.5"/>
                                        <path d="M12 16v4M8.5 20h7"/>
                                        <path d="M8 12V8h2.2a2 2 0 0 1 0 4H8z"/>
                                    </svg>
                                ` : `
                                    <svg viewBox="0 0 24 24" aria-hidden="true">
                                        <rect x="4" y="3.5" width="16" height="17" rx="1.5"/>
                                        <path d="M4 9h16M10 3.5v17M4 14.5h16"/>
                                    </svg>
                                `}
                            </span>

                            <span class="create-output-option-text">
                                <strong>${escapeHtml(item.label)}</strong>
                                <small>${escapeHtml(item.description)}</small>
                            </span>

                            <span class="create-output-arrow">›</span>
                        </button>
                    `)
                    .join("")}
            </div>
        </div>
    `;

    // Put Create before Create summary.
    actions.prepend(wrapper);

    const button =
        document.getElementById("createOutputButton");

    const menu =
        document.getElementById("createOutputMenu");

    button.addEventListener("click", event => {
        event.stopPropagation();

        const willOpen = menu.hidden;

        menu.hidden = !willOpen;
        button.setAttribute(
            "aria-expanded",
            String(willOpen)
        );
    });

    menu.querySelectorAll(
        "[data-output-format]"
    ).forEach(option => {
        option.addEventListener("click", () => {
            menu.hidden = true;

            button.setAttribute(
                "aria-expanded",
                "false"
            );

            showOutputModal(
                option.dataset.outputFormat
            );
        });
    });

    document.addEventListener("click", event => {
        if (!wrapper.contains(event.target)) {
            menu.hidden = true;

            button.setAttribute(
                "aria-expanded",
                "false"
            );
        }
    });
}


function closeOutputModal() {
    const modal =
        document.getElementById("outputModal");

    if (modal) {
        modal.remove();
    }
}


function showOutputModal(format) {
    const config =
        STUDYMATE_OUTPUT_FORMATS[format];

    if (!config) return;

    closeOutputModal();

    const modal = document.createElement("div");

    modal.id = "outputModal";
    modal.className = "output-modal";

    modal.innerHTML = `
        <div class="output-dialog">
            <div class="output-dialog-header">
                <div>
                    <span class="eyebrow">
                        CREATE ${escapeHtml(config.extension)}
                    </span>

                    <h3>
                        ${escapeHtml(config.label)}
                    </h3>

                    <p>
                        Tell El Amigo what you'd like to create
                        from this conversation.
                    </p>
                </div>

                <button
                    id="closeOutputButton"
                    class="output-close"
                    type="button"
                    aria-label="Close"
                >×</button>
            </div>

            <div class="output-dialog-body">
                <label
                    class="output-instructions-label"
                    for="outputInstructions"
                >
                    Instructions
                </label>

                <textarea
                    id="outputInstructions"
                    class="output-instructions"
                    rows="6"
                    placeholder="${escapeHtml(config.example)}"
                ></textarea>

                <div class="output-example">
                    <strong>Example</strong>
                    <span>${escapeHtml(config.example)}</span>
                </div>

                <div
                    id="outputStatus"
                    class="output-status"
                    aria-live="polite"
                ></div>
            </div>

            <div class="output-dialog-footer">
                <button
                    id="cancelOutputButton"
                    class="output-cancel-button"
                    type="button"
                >
                    Cancel
                </button>

                <button
                    id="generateOutputButton"
                    class="output-generate-button"
                    type="button"
                >
                    Generate ${escapeHtml(config.shortLabel)}
                </button>
            </div>
        </div>
    `;

    document.body.appendChild(modal);

    const instructions =
        document.getElementById("outputInstructions");

    instructions.focus();

    document.getElementById(
        "closeOutputButton"
    ).addEventListener(
        "click",
        closeOutputModal
    );

    document.getElementById(
        "cancelOutputButton"
    ).addEventListener(
        "click",
        closeOutputModal
    );

    document.getElementById(
        "generateOutputButton"
    ).addEventListener(
        "click",
        () => generateStudyOutput(format)
    );

    modal.addEventListener("click", event => {
        if (event.target === modal) {
            closeOutputModal();
        }
    });
}


async function generateStudyOutput(format) {
    const config =
        STUDYMATE_OUTPUT_FORMATS[format];

    const button =
        document.getElementById("generateOutputButton");

    const status =
        document.getElementById("outputStatus");

    const instructions =
        document.getElementById("outputInstructions");

    if (!currentSubjectId) {
        status.textContent =
            "Choose a subject first.";
        status.className =
            "output-status output-status-error";
        return;
    }

    if (!currentSessionId) {
        status.textContent =
            "Start a conversation with El Amigo first.";
        status.className =
            "output-status output-status-error";
        return;
    }

    const requestedInstructions =
        instructions.value.trim() ||
        config.example;

    button.disabled = true;
    instructions.disabled = true;

    button.textContent = "Creating…";

    status.textContent =
        `El Amigo is creating your ${config.label}. ` +
        "This may take a moment.";

    status.className =
        "output-status output-status-working";

    try {
        const result = await api(
            `/subjects/${currentSubjectId}/outputs`,
            {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({
                    session_id: currentSessionId,
                    format,
                    instructions: requestedInstructions
                })
            }
        );

        if (!result.success) {
            throw new Error(
                result.error ||
                "Unable to create output."
            );
        }

        showOutputSuccess(
            format,
            result
        );

    } catch (error) {
        console.error(error);

        status.textContent =
            error.message ||
            "Unable to create the file.";

        status.className =
            "output-status output-status-error";

        button.disabled = false;
        instructions.disabled = false;

        button.textContent =
            `Generate ${config.shortLabel}`;
    }
}


function showOutputSuccess(format, result) {
    const config =
        STUDYMATE_OUTPUT_FORMATS[format];

    const body =
        document.querySelector(
            "#outputModal .output-dialog-body"
        );

    const footer =
        document.querySelector(
            "#outputModal .output-dialog-footer"
        );

    if (!body || !footer) return;

    body.innerHTML = `
        <div class="output-success">
            <div class="output-success-mark">✓</div>

            <h4>Your ${escapeHtml(config.label)} is ready</h4>

            <p>
                ${escapeHtml(
                    result.title ||
                    "StudyMate output"
                )}
            </p>

            <span class="output-file-badge">
                ${escapeHtml(config.extension)}
            </span>
        </div>
    `;

    footer.innerHTML = `
        <button
            id="doneOutputButton"
            class="output-cancel-button"
            type="button"
        >
            Done
        </button>

        <a
            class="output-download-button"
            href="${escapeHtml(result.download_url)}"
        >
            Download ${escapeHtml(config.shortLabel)}
        </a>
    `;

    document.getElementById(
        "doneOutputButton"
    ).addEventListener(
        "click",
        closeOutputModal
    );
}


// Summary UI is created dynamically, so run output setup
// after the document has loaded and again shortly afterwards
// to ensure both actions share the same header container.
if (document.readyState === "loading") {
    document.addEventListener(
        "DOMContentLoaded",
        ensureOutputUI
    );
} else {
    ensureOutputUI();
}

setTimeout(ensureOutputUI, 250);
