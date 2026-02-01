/**
 * register.js
 * Handles the registration of new faces.
 * Captures an image, sends it to the backend for encoding, and provides
 * real-time feedback using a simplified recognition loop.
 */

const videoElement = document.getElementById("videoElement");
const captureBtn = document.getElementById("captureBtn");
// --- Class Tags Logic ---
const classNameInput = document.getElementById("className"); // Hidden input
const tagsContainer = document.getElementById("classTagsContainer");
const newClassArea = document.getElementById("newClassInputArea");
const newClassInput = document.getElementById("newClassInput");
const confirmClassBtn = document.getElementById("confirmClassBtn");

async function loadClasses() {
    try {
        const res = await fetch("/api/classes");
        const classes = await res.json();
        renderTags(classes);
    } catch (e) {
        console.error("Failed to load classes", e);
        // Fallback or empty
        renderTags([]);
    }
}

function renderTags(classes) {
    tagsContainer.innerHTML = "";

    // Create tags for existing classes
    classes.forEach(cls => {
        const tag = document.createElement("div");
        tag.className = "tag";
        tag.textContent = cls;
        tag.onclick = () => selectClass(cls, tag);
        tagsContainer.appendChild(tag);
    });

    // Add "+ Custom" tag
    const addTag = document.createElement("div");
    addTag.className = "tag tag-add-btn";
    addTag.textContent = "+ Valid/Custom";
    addTag.onclick = () => showCustomInput();
    tagsContainer.appendChild(addTag);
}

function selectClass(value, tagElement) {
    // Update Hidden Input
    classNameInput.value = value;

    // Visual Feedback
    const allTags = tagsContainer.querySelectorAll(".tag");
    allTags.forEach(t => t.classList.remove("selected"));

    // If it's a newly added custom tag, it might not be in the initial list, but passed element handles it
    if (tagElement) {
        tagElement.classList.add("selected");
    }

    // Hide custom input if open
    newClassArea.classList.remove("active");
}

function showCustomInput() {
    // Deselect others
    const allTags = tagsContainer.querySelectorAll(".tag");
    allTags.forEach(t => t.classList.remove("selected"));
    classNameInput.value = ""; // Clear current selection until formatted

    newClassArea.classList.add("active");
    newClassInput.focus();
}

confirmClassBtn.addEventListener("click", () => {
    const val = newClassInput.value.trim();
    if (val) {
        // Create a temporary visual tag and select it
        const tempTag = document.createElement("div");
        tempTag.className = "tag selected";
        tempTag.textContent = val;
        tempTag.onclick = () => selectClass(val, tempTag);

        // Insert before the "+ Add" button
        // The last child is the add button
        tagsContainer.insertBefore(tempTag, tagsContainer.lastChild);

        // Select it
        selectClass(val, tempTag);

        // Clear and hide input
        newClassInput.value = "";
        newClassArea.classList.remove("active");
    }
});


// Call on load
loadClasses();

const usernameInput = document.getElementById("username");
const fatherNameInput = document.getElementById("fatherName");
const statusArea = document.getElementById("statusArea");

const captureCanvas = document.getElementById("captureCanvas");
const overlayCanvas = document.getElementById("overlayCanvas");
const captureContext = captureCanvas.getContext("2d");
const overlayContext = overlayCanvas.getContext("2d");

const videoContainer = document.querySelector(".fullscreen-video-container");

// Configuration
const CONFIG = {
    FEEDBACK_INTERVAL_MS: 300,
    CAPTURE_QUALITY: 0.9,
    FEEDBACK_QUALITY: 0.7,
    SEND_WIDTH: 640
};

let isProcessingFeedback = false;

// --- Initialization ---

// Mobile responsive adjustment
if (window.innerWidth <= 768) {
    document.body.classList.add("fullscreen-mode");
    const mobileOnly = document.querySelector(".mobile-only");
    const desktopHeader = document.querySelector(".desktop-header");
    if (mobileOnly) mobileOnly.style.display = "block";
    if (desktopHeader) desktopHeader.style.display = "none";
}

// Start Webcam
async function startCamera() {
    try {
        const stream = await navigator.mediaDevices.getUserMedia({
            video: {
                facingMode: "user",
                width: { ideal: 1280 },
                height: { ideal: 720 },
            },
        });
        videoElement.srcObject = stream;
        startFeedbackLoop();
    } catch (err) {
        console.error("Camera Error:", err);
        statusArea.innerHTML = `<span class="status-error">Camera Access Denied</span>`;
    }
}

startCamera();

// --- Feedback Loop ---

/**
 * Runs a background loop to detect faces and draw bounding boxes.
 * This helps the user position themselves correctly before capturing.
 */
function startFeedbackLoop() {
    setInterval(async () => {
        if (isProcessingFeedback) return;
        isProcessingFeedback = true;

        try {
            // 1. Sync Canvas to Container Size
            const rect = videoContainer.getBoundingClientRect();
            if (overlayCanvas.width !== rect.width || overlayCanvas.height !== rect.height) {
                overlayCanvas.width = rect.width;
                overlayCanvas.height = rect.height;
            }

            // 2. Capture Frame for Detection
            const scale = CONFIG.SEND_WIDTH / videoElement.videoWidth;
            const sendHeight = videoElement.videoHeight * scale;

            captureCanvas.width = CONFIG.SEND_WIDTH;
            captureCanvas.height = sendHeight;

            if (videoElement.readyState === videoElement.HAVE_ENOUGH_DATA) {
                captureContext.drawImage(videoElement, 0, 0, captureCanvas.width, captureCanvas.height);
            } else {
                return;
            }

            const imageData = captureCanvas.toDataURL("image/jpeg", CONFIG.FEEDBACK_QUALITY);

            const response = await fetch("/api/recognize", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ image: imageData }),
            });
            const data = await response.json();

            if (data.success) {
                const matches = data.matches.map((m) => {
                    return {
                        ...m,
                        box: m.box.map((coord) => coord / scale),
                    };
                });
                drawFeedbackBoxes(matches);
            }
        } catch (err) {
            // Silently fail for feedback loop to avoid spamming console
        } finally {
            isProcessingFeedback = false;
        }
    }, CONFIG.FEEDBACK_INTERVAL_MS);
}

function drawFeedbackBoxes(matches) {
    overlayContext.clearRect(0, 0, overlayCanvas.width, overlayCanvas.height);

    const isMobile = window.innerWidth <= 768;
    const fitMode = isMobile ? "cover" : "contain";

    const videoRatio = videoElement.videoWidth / videoElement.videoHeight;
    const containerRatio = overlayCanvas.width / overlayCanvas.height;

    let drawWidth, drawHeight, startX, startY;

    if (fitMode === "cover") {
        if (containerRatio > videoRatio) {
            drawWidth = overlayCanvas.width;
            drawHeight = drawWidth / videoRatio;
            startX = 0;
            startY = (overlayCanvas.height - drawHeight) / 2;
        } else {
            drawHeight = overlayCanvas.height;
            drawWidth = drawHeight * videoRatio;
            startX = (overlayCanvas.width - drawWidth) / 2;
            startY = 0;
        }
    } else {
        // Contain
        if (containerRatio > videoRatio) {
            drawHeight = overlayCanvas.height;
            drawWidth = drawHeight * videoRatio;
            startX = (overlayCanvas.width - drawWidth) / 2;
            startY = 0;
        } else {
            drawWidth = overlayCanvas.width;
            drawHeight = drawWidth / videoRatio;
            startX = 0;
            startY = (overlayCanvas.height - drawHeight) / 2;
        }
    }

    const displayScale = drawWidth / videoElement.videoWidth;

    matches.forEach((match) => {
        const [x1, y1, x2, y2] = match.box;

        const dx = startX + x1 * displayScale;
        const dy = startY + y1 * displayScale;
        const dw = (x2 - x1) * displayScale;
        const dh = (y2 - y1) * displayScale;

        overlayContext.strokeStyle = "var(--success)"; // Green for feedback
        overlayContext.lineWidth = 4;
        overlayContext.lineJoin = "round";
        overlayContext.strokeRect(dx, dy, dw, dh);
    });
}

// --- Capture Handler ---

captureBtn.addEventListener("click", async () => {
    const name = usernameInput.value.trim();
    const className = classNameInput.value.trim();
    const fatherName = fatherNameInput.value.trim();

    if (!name) {
        alert("Please enter a name first.");
        return;
    }

    captureBtn.disabled = true;
    captureBtn.innerText = "Processing...";

    // Capture full resolution for registration
    captureCanvas.width = videoElement.videoWidth;
    captureCanvas.height = videoElement.videoHeight;
    captureContext.drawImage(videoElement, 0, 0, captureCanvas.width, captureCanvas.height);

    const imageData = captureCanvas.toDataURL("image/jpeg", CONFIG.CAPTURE_QUALITY);

    try {
        const response = await fetch("/api/register_capture", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                name: name,
                class_name: className,
                father_name: fatherName,
                image: imageData
            }),
        });
        const data = await response.json();

        if (data.success) {
            statusArea.innerHTML = `<span class="status-success" style="display:block; text-align:center;">${data.message}</span>`;
            usernameInput.value = "";
        } else {
            statusArea.innerHTML = `<span class="status-error" style="display:block; text-align:center;">${data.message}</span>`;
        }
    } catch (e) {
        console.error(e);
        statusArea.innerHTML = `<span class="status-error">Network Error</span>`;
    } finally {
        captureBtn.disabled = false;
        captureBtn.innerText = "Capture & Register";
    }
});

// Handle Resize
window.addEventListener("resize", () => {
    if (window.innerWidth <= 768) {
        document.body.classList.add("fullscreen-mode");
    } else {
        document.body.classList.remove("fullscreen-mode");
    }
});