/**
 * Laika 1:1 Square Image Cropper (local, zero dependencies).
 * Automatically attaches to any <input type="file" data-crop-square="true">
 * including inputs dynamically injected via HTMX modals.
 */
(function () {
    const VIEWPORT_SIZE = 320;
    let activeState = null;

    function createModal() {
        let overlay = document.getElementById("laika-cropper-overlay");
        if (overlay) return overlay;

        overlay = document.createElement("div");
        overlay.id = "laika-cropper-overlay";
        overlay.className =
            "fixed inset-0 z-[70] bg-black/80 backdrop-blur-sm hidden items-center justify-center p-4";
        overlay.innerHTML = `
            <div class="bg-surface border border-subtle rounded-2xl w-full max-w-md overflow-hidden shadow-2xl">
                <div class="px-5 py-4 border-b border-subtle flex items-center justify-between gap-3">
                    <div>
                        <h3 id="laika-crop-title" class="text-sm font-bold text-ink-primary">Recortar foto (1:1)</h3>
                        <p class="text-[11px] text-ink-secondary mt-0.5">Arraste para enquadrar e ajuste o zoom</p>
                    </div>
                    <button type="button" id="laika-crop-close" aria-label="Cancelar" class="p-1.5 rounded-lg text-ink-secondary hover:text-ink-primary hover:bg-elevated">
                        <i class="mdi mdi-close text-lg"></i>
                    </button>
                </div>

                <div class="p-5 space-y-4">
                    <div class="flex justify-center">
                        <div
                            id="laika-crop-stage"
                            style="width:${VIEWPORT_SIZE}px;height:${VIEWPORT_SIZE}px;touch-action:none;"
                            class="relative overflow-hidden rounded-xl border-2 border-patas-green bg-black select-none cursor-grab active:cursor-grabbing">
                            <canvas id="laika-crop-canvas" width="${VIEWPORT_SIZE}" height="${VIEWPORT_SIZE}" class="w-full h-full block"></canvas>
                            <div class="pointer-events-none absolute inset-0 grid grid-cols-3 grid-rows-3">
                                <div class="border-r border-b border-white/20"></div>
                                <div class="border-r border-b border-white/20"></div>
                                <div class="border-b border-white/20"></div>
                                <div class="border-r border-b border-white/20"></div>
                                <div class="border-r border-b border-white/20"></div>
                                <div class="border-b border-white/20"></div>
                                <div class="border-r border-white/20"></div>
                                <div class="border-r border-white/20"></div>
                                <div></div>
                            </div>
                        </div>
                    </div>

                    <div class="flex items-center gap-3 text-xs">
                        <i class="mdi mdi-magnify-minus-outline text-base text-ink-secondary"></i>
                        <input
                            id="laika-crop-zoom"
                            type="range"
                            min="1"
                            max="3"
                            step="0.02"
                            value="1"
                            class="flex-1 accent-[#05AC78]">
                        <i class="mdi mdi-magnify-plus-outline text-base text-ink-secondary"></i>
                        <button
                            type="button"
                            id="laika-crop-reset"
                            class="px-2.5 py-1 rounded-lg bg-elevated hover:bg-subtle border border-subtle text-[11px] font-medium text-ink-secondary hover:text-ink-primary">
                            Centralizar
                        </button>
                    </div>
                </div>

                <div class="px-5 py-3.5 border-t border-subtle bg-elevated/30 flex items-center justify-between gap-2 text-xs">
                    <button type="button" id="laika-crop-cancel" class="px-3.5 py-2 rounded-xl bg-elevated hover:bg-subtle border border-subtle font-medium text-ink-primary">
                        Cancelar
                    </button>
                    <button type="button" id="laika-crop-confirm" class="px-4 py-2 rounded-xl bg-patas-green hover:bg-patas-green-hover text-[#061c14] font-semibold inline-flex items-center gap-1.5">
                        <i class="mdi mdi-crop text-base"></i>
                        <span id="laika-crop-confirm-label">Confirmar recorte</span>
                    </button>
                </div>
            </div>
        `;
        document.body.appendChild(overlay);
        bindModalEvents(overlay);
        return overlay;
    }

    function clampOffsets() {
        if (!activeState || !activeState.img) return;
        const s = activeState;
        const drawW = s.img.naturalWidth * s.baseScale * s.zoom;
        const drawH = s.img.naturalHeight * s.baseScale * s.zoom;
        const maxX = Math.max(0, (drawW - VIEWPORT_SIZE) / 2);
        const maxY = Math.max(0, (drawH - VIEWPORT_SIZE) / 2);
        s.offsetX = Math.max(-maxX, Math.min(maxX, s.offsetX));
        s.offsetY = Math.max(-maxY, Math.min(maxY, s.offsetY));
    }

    function renderCanvas() {
        if (!activeState || !activeState.img) return;
        const s = activeState;
        const canvas = document.getElementById("laika-crop-canvas");
        if (!canvas) return;
        const ctx = canvas.getContext("2d");
        ctx.clearRect(0, 0, VIEWPORT_SIZE, VIEWPORT_SIZE);
        ctx.fillStyle = "#111";
        ctx.fillRect(0, 0, VIEWPORT_SIZE, VIEWPORT_SIZE);

        const drawW = s.img.naturalWidth * s.baseScale * s.zoom;
        const drawH = s.img.naturalHeight * s.baseScale * s.zoom;
        const dx = (VIEWPORT_SIZE - drawW) / 2 + s.offsetX;
        const dy = (VIEWPORT_SIZE - drawH) / 2 + s.offsetY;
        ctx.imageSmoothingEnabled = true;
        ctx.imageSmoothingQuality = "high";
        ctx.drawImage(s.img, dx, dy, drawW, drawH);
    }

    function loadCurrentFile() {
        const s = activeState;
        if (!s) return;
        const file = s.files[s.index];
        const titleEl = document.getElementById("laika-crop-title");
        const confirmLabel = document.getElementById("laika-crop-confirm-label");
        if (s.files.length > 1) {
            titleEl.textContent = `Recortar foto ${s.index + 1} de ${s.files.length} (1:1)`;
            confirmLabel.textContent =
                s.index + 1 < s.files.length ? "Recortar e próxima" : "Finalizar recorte";
        } else {
            titleEl.textContent = "Recortar foto (1:1)";
            confirmLabel.textContent = "Confirmar recorte";
        }

        const reader = new FileReader();
        reader.onload = function (ev) {
            const img = new Image();
            img.onload = function () {
                s.img = img;
                s.baseScale = Math.max(
                    VIEWPORT_SIZE / img.naturalWidth,
                    VIEWPORT_SIZE / img.naturalHeight
                );
                s.zoom = 1;
                s.offsetX = 0;
                s.offsetY = 0;
                const zoomInput = document.getElementById("laika-crop-zoom");
                if (zoomInput) zoomInput.value = "1";
                clampOffsets();
                renderCanvas();
            };
            img.src = ev.target.result;
        };
        reader.readAsDataURL(file);
    }

    function exportCroppedBlob(callback) {
        const s = activeState;
        const outSize = s.outputSize;
        const outCanvas = document.createElement("canvas");
        outCanvas.width = outSize;
        outCanvas.height = outSize;
        const ctx = outCanvas.getContext("2d");

        const ratio = outSize / VIEWPORT_SIZE;
        const drawW = s.img.naturalWidth * s.baseScale * s.zoom * ratio;
        const drawH = s.img.naturalHeight * s.baseScale * s.zoom * ratio;
        const dx = (outSize - drawW) / 2 + s.offsetX * ratio;
        const dy = (outSize - drawH) / 2 + s.offsetY * ratio;

        ctx.fillStyle = "#111";
        ctx.fillRect(0, 0, outSize, outSize);
        ctx.imageSmoothingEnabled = true;
        ctx.imageSmoothingQuality = "high";
        ctx.drawImage(s.img, dx, dy, drawW, drawH);

        outCanvas.toBlob(
            function (blob) {
                if (blob) {
                    callback(blob, "image/webp", ".webp");
                } else {
                    outCanvas.toBlob(
                        function (jpgBlob) {
                            callback(jpgBlob, "image/jpeg", ".jpg");
                        },
                        "image/jpeg",
                        0.9
                    );
                }
            },
            "image/webp",
            0.86
        );
    }

    function closeCropper(clearInput) {
        const overlay = document.getElementById("laika-cropper-overlay");
        if (overlay) {
            overlay.classList.add("hidden");
            overlay.classList.remove("flex");
        }
        if (clearInput && activeState && activeState.input) {
            activeState.input.value = "";
        }
        activeState = null;
    }

    function finishCropping() {
        const s = activeState;
        if (!s) return;
        const dt = new DataTransfer();
        s.results.forEach((f) => dt.items.add(f));
        s.input.files = dt.files;

        if (s.input.dataset.cropPreview && s.results[0]) {
            const previewImg = document.getElementById(s.input.dataset.cropPreview);
            const initials = document.getElementById("iniciais-avatar");
            if (previewImg) {
                previewImg.src = URL.createObjectURL(s.results[0]);
                previewImg.classList.remove("hidden");
            }
            if (initials) initials.classList.add("hidden");
        }
        closeCropper(false);
    }

    function bindModalEvents(overlay) {
        const stage = document.getElementById("laika-crop-stage");
        const zoomInput = document.getElementById("laika-crop-zoom");
        const resetBtn = document.getElementById("laika-crop-reset");
        const cancelBtn = document.getElementById("laika-crop-cancel");
        const closeBtn = document.getElementById("laika-crop-close");
        const confirmBtn = document.getElementById("laika-crop-confirm");

        let dragging = false;
        let lastX = 0;
        let lastY = 0;

        stage.addEventListener("pointerdown", function (e) {
            if (!activeState) return;
            dragging = true;
            lastX = e.clientX;
            lastY = e.clientY;
            stage.setPointerCapture(e.pointerId);
        });

        stage.addEventListener("pointermove", function (e) {
            if (!dragging || !activeState) return;
            activeState.offsetX += e.clientX - lastX;
            activeState.offsetY += e.clientY - lastY;
            lastX = e.clientX;
            lastY = e.clientY;
            clampOffsets();
            renderCanvas();
        });

        function stopDrag(e) {
            if (!dragging) return;
            dragging = false;
            if (stage.hasPointerCapture(e.pointerId)) {
                stage.releasePointerCapture(e.pointerId);
            }
        }
        stage.addEventListener("pointerup", stopDrag);
        stage.addEventListener("pointercancel", stopDrag);

        stage.addEventListener(
            "wheel",
            function (e) {
                if (!activeState) return;
                e.preventDefault();
                const delta = e.deltaY < 0 ? 0.08 : -0.08;
                activeState.zoom = Math.max(1, Math.min(3, activeState.zoom + delta));
                zoomInput.value = String(activeState.zoom);
                clampOffsets();
                renderCanvas();
            },
            { passive: false }
        );

        zoomInput.addEventListener("input", function () {
            if (!activeState) return;
            activeState.zoom = parseFloat(this.value) || 1;
            clampOffsets();
            renderCanvas();
        });

        resetBtn.addEventListener("click", function () {
            if (!activeState) return;
            activeState.zoom = 1;
            activeState.offsetX = 0;
            activeState.offsetY = 0;
            zoomInput.value = "1";
            clampOffsets();
            renderCanvas();
        });

        cancelBtn.addEventListener("click", () => closeCropper(true));
        closeBtn.addEventListener("click", () => closeCropper(true));

        confirmBtn.addEventListener("click", function () {
            if (!activeState || !activeState.img) return;
            const current = activeState.files[activeState.index];
            const baseName = (current.name || "foto").replace(/\.[^.]+$/, "");
            exportCroppedBlob(function (blob, mime, ext) {
                if (blob) {
                    const croppedFile = new File([blob], baseName + ext, {
                        type: mime,
                        lastModified: Date.now(),
                    });
                    activeState.results.push(croppedFile);
                }
                activeState.index += 1;
                if (activeState.index < activeState.files.length) {
                    loadCurrentFile();
                } else {
                    finishCropping();
                }
            });
        });

        overlay.addEventListener("click", function (e) {
            if (e.target === overlay) closeCropper(true);
        });
    }

    document.addEventListener("change", function (event) {
        const input = event.target;
        if (!input || input.tagName !== "INPUT" || input.type !== "file") return;
        if (input.dataset.cropSquare !== "true") return;
        if (!input.files || input.files.length === 0) return;

        const imageFiles = Array.from(input.files).filter((f) =>
            f.type.startsWith("image/")
        );
        if (imageFiles.length === 0) return;

        const overlay = createModal();
        activeState = {
            input: input,
            files: imageFiles,
            index: 0,
            results: [],
            outputSize: parseInt(input.dataset.cropSize || "1080", 10) || 1080,
            img: null,
            baseScale: 1,
            zoom: 1,
            offsetX: 0,
            offsetY: 0,
        };
        overlay.classList.remove("hidden");
        overlay.classList.add("flex");
        loadCurrentFile();
    });
})();
