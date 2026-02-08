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

const videoContainer = document.querySelector(".video-container");

// Configuration
const CONFIG = {
    FEEDBACK_INTERVAL_MS: 300,
    CAPTURE_QUALITY: 0.9,
    FEEDBACK_QUALITY: 0.7,
    SEND_WIDTH: 640
};

let isProcessingFeedback = false;

// --- Initialization ---

// Mobile responsive adjustment removed

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

            const response = await fetch("/api/detect_faces", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ image: imageData }),
            });
            const data = await response.json();

            if (data.success && data.boxes) {
                // Upscale boxes
                const boxes = data.boxes.map((box) => {
                    return box.map((coord) => coord / scale);
                });
                drawFeedbackBoxes(boxes);
            }
        } catch (err) {
            // Silently fail for feedback loop to avoid spamming console
        } finally {
            isProcessingFeedback = false;
        }
    }, CONFIG.FEEDBACK_INTERVAL_MS);
}

function drawFeedbackBoxes(boxes) {
    overlayContext.clearRect(0, 0, overlayCanvas.width, overlayCanvas.height);

    const displayedWidth = videoElement.clientWidth;
    const displayedHeight = videoElement.clientHeight;

    if (overlayCanvas.width !== displayedWidth || overlayCanvas.height !== displayedHeight) {
        overlayCanvas.width = displayedWidth;
        overlayCanvas.height = displayedHeight;
    }

    const scaleX = displayedWidth / videoElement.videoWidth;
    const scaleY = displayedHeight / videoElement.videoHeight;

    boxes.forEach((box) => {
        const [x1, y1, x2, y2] = box;

        const dx = x1 * scaleX;
        const dy = y1 * scaleY;
        const dw = (x2 - x1) * scaleX;
        const dh = (y2 - y1) * scaleY;

        overlayContext.strokeStyle = "#00FF7F"; // Green
        overlayContext.lineWidth = 4;
        overlayContext.lineJoin = "round";
        overlayContext.strokeRect(dx, dy, dw, dh);
    });
}

// --- Capture Handler ---

const grNumberInput = document.getElementById("grNumber");
const sectionInput = document.getElementById("section");

captureBtn.addEventListener("click", async () => {
    const name = usernameInput.value.trim();
    const className = classNameInput.value.trim();
    const fatherName = fatherNameInput.value.trim();
    const grNumber = grNumberInput.value.trim();
    const section = sectionInput.value;

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
                gr_number: grNumber,
                section: section,
                image: imageData
            }),
        });
        const data = await response.json();

        if (data.success) {
            statusArea.innerHTML = `<span class="status-success" style="display:block; text-align:center;">${data.message}</span>`;
            // Redirect to reports page after a short delay
            setTimeout(() => {
                // Use encodeURIComponent to handle special characters if necessary, though message is usually simple
                window.location.href = "/reports?success=" + encodeURIComponent("Registration Successful!");
            }, 1000);
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

// Resize listener removed

// --- Recapture / Pre-fill Logic ---
function checkUrlParams() {
    const params = new URLSearchParams(window.location.search);
    const name = params.get("name");
    const className = params.get("class_name");
    const fatherName = params.get("father_name");
    const grNumber = params.get("gr_number");
    const section = params.get("section");

    if (name) usernameInput.value = name;
    if (fatherName) fatherNameInput.value = fatherName;
    if (grNumber) grNumberInput.value = grNumber;
    if (section) sectionInput.value = section;

    if (className) {
        // Set value immediately
        classNameInput.value = className;

        // Try to find and visually select the tag after a short delay (to ensure tags loaded)
        setTimeout(() => {
            const allTags = tagsContainer.querySelectorAll(".tag");
            let found = false;
            for (let tag of allTags) {
                if (tag.textContent === className) {
                    selectClass(className, tag);
                    found = true;
                    break;
                }
            }
            // If not found (custom class), we could create a visual tag, 
            // but for now relying on the hidden input is sufficient.
        }, 500);
    }
}

checkUrlParams();
