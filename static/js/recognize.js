/**
 * recognize.js
 * Handles the webcam feed, frame capture, and communication with the backend
 * for face recognition and attendance marking.
 */

const videoElement = document.getElementById("videoElement");
const overlayCanvas = document.getElementById("overlayCanvas");
const captureCanvas = document.getElementById("captureCanvas");
const overlayContext = overlayCanvas.getContext("2d");
const captureContext = captureCanvas.getContext("2d");

const statusLabel = document.getElementById("systemStatus");
const successModal = document.getElementById("successModal");
const modalPanel = document.getElementById("modalPanel");
const modalIcon = document.getElementById("modalIcon");
const modalTitle = document.getElementById("modalTitle");
const modalMessage = document.getElementById("modalMessage");
const modalButton = document.getElementById("modalButton");
const videoContainer = document.querySelector(".fullscreen-video-container");

// Configuration
const CONFIG = {
    REFRESH_INTERVAL_MS: 500,
    IMAGE_QUALITY: 0.7,
    SEND_WIDTH: 640
};

// Application State
let isProcessingFrame = false;
let isSuccessModalOpen = false;
let currentModalUser = null;
let framesWithoutUser = 0;
const MAX_MISSING_FRAMES = 4; // Approx 2 seconds grace period
let acknowledgedUsers = new Map(); // Name -> framesMissingCount

// --- Initialization ---

// Mobile responsive adjustment
if (window.innerWidth <= 768) {
    document.body.classList.add("fullscreen-mode");
    const desktopHeader = document.querySelector(".desktop-header");
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
        statusLabel.innerText = "● System Active";
        startRecognitionLoop();
    } catch (err) {
        console.error("Camera Error:", err);
        statusLabel.innerText = "● Camera Error";
        statusLabel.style.color = "var(--danger)";
    }
}

startCamera();

// --- UI Helpers ---

function openModal(title, message, colorVar, relatedUser = null) {
    // If modal is already open for THIS user, just return (avoid flicker)
    if (isSuccessModalOpen && currentModalUser === relatedUser && relatedUser !== null) {
        return;
    }

    // If user has acknowledged this recently, do not show
    if (relatedUser && acknowledgedUsers.has(relatedUser)) {
        return;
    }

    isSuccessModalOpen = true;
    currentModalUser = relatedUser;
    framesWithoutUser = 0;

    // Update Content
    modalTitle.innerText = title;
    modalMessage.innerText = message;

    // Update Colors
    // colorVar should be like "var(--success)" or "var(--warning)" or hex
    modalPanel.style.borderColor = colorVar;
    modalPanel.style.boxShadow = `0 0 50px ${colorVar === 'var(--success)' ? 'rgba(0, 255, 127, 0.2)' : 'rgba(255, 165, 0, 0.2)'}`; // Approximate
    modalIcon.style.backgroundColor = colorVar;
    modalTitle.style.color = colorVar;
    modalButton.style.backgroundColor = colorVar;

    successModal.style.display = "flex";
}

function closeSuccessModal(isManual = false) {
    if (isManual && currentModalUser) {
        acknowledgedUsers.set(currentModalUser, 0); // Start tracking absence for this user
    }
    successModal.style.display = "none";
    isSuccessModalOpen = false;
    currentModalUser = null;
    framesWithoutUser = 0;
}

// Make globally valid for the onclick in HTML
window.closeModal = closeSuccessModal;

/**
 * Draws bounding boxes and labels on the overlay canvas.
 * Handles responsive scaling to ensure boxes align with the video feed.
 * @param {Array} matches - Array of recognition matches.
 */
function drawRecognitionBoxes(matches) {
    overlayContext.clearRect(0, 0, overlayCanvas.width, overlayCanvas.height);

    // Responsive Fit Logic: Calculate how the video is displayed
    const isMobile = window.innerWidth <= 768;
    const fitMode = isMobile ? "cover" : "contain";

    const videoRatio = videoElement.videoWidth / videoElement.videoHeight;
    const containerRatio = overlayCanvas.width / overlayCanvas.height;

    let drawWidth, drawHeight, startX, startY;

    if (fitMode === "cover") {
        if (containerRatio > videoRatio) {
            // Container is wider than video -> Crop height
            drawWidth = overlayCanvas.width;
            drawHeight = drawWidth / videoRatio;
            startX = 0;
            startY = (overlayCanvas.height - drawHeight) / 2;
        } else {
            // Container is taller than video -> Crop width
            drawHeight = overlayCanvas.height;
            drawWidth = drawHeight * videoRatio;
            startX = (overlayCanvas.width - drawWidth) / 2;
            startY = 0;
        }
    } else {
        // Contain Mode
        if (containerRatio > videoRatio) {
            // Container is wider -> Pillarbox
            drawHeight = overlayCanvas.height;
            drawWidth = drawHeight * videoRatio;
            startX = (overlayCanvas.width - drawWidth) / 2;
            startY = 0;
        } else {
            // Container is taller -> Letterbox
            drawWidth = overlayCanvas.width;
            drawHeight = drawWidth / videoRatio;
            startX = 0;
            startY = (overlayCanvas.height - drawHeight) / 2;
        }
    }

    const displayScale = drawWidth / videoElement.videoWidth;

    matches.forEach((match) => {
        const [x1, y1, x2, y2] = match.box;
        const name = match.name;
        // const similarity = match.similarity; // Unused for display but available

        // NOTE: Client should not be the source of truth for whether a user was
        // "marked" — the server returns `newly_marked` in the `matches` payload
        // and we open the modal centrally from the recognition loop to ensure
        // consistent messaging. We no longer open the modal from here.

        // Transform coordinates to display space
        const dx = startX + x1 * displayScale;
        const dy = startY + y1 * displayScale;
        const dw = (x2 - x1) * displayScale;
        const dh = (y2 - y1) * displayScale;

        // Styling
        let color = "var(--danger)"; // Default Unknown Red
        if (name !== "Unknown" && !name.startsWith("Unknown")) {
            color = "var(--success)"; // Known Green
        }
        // Force hex for canvas if needed, or get computed style. 
        // For simplicity using hardcoded hex fallback if var fails parsing by canvas (canvas needs standard colors)
        const uiColor = name !== "Unknown" && !name.startsWith("Unknown") ? "#00FF7F" : "#FF4D4D";

        overlayContext.strokeStyle = uiColor;
        overlayContext.lineWidth = 4;
        overlayContext.lineJoin = "round";
        overlayContext.strokeRect(dx, dy, dw, dh);

        overlayContext.fillStyle = uiColor;
        overlayContext.font = "bold 18px Inter, sans-serif";
        overlayContext.shadowColor = "black";
        overlayContext.shadowBlur = 4;

        // Label positioning
        const textY = dy > 60 ? dy - 10 : dy + dh + 20; // Move up if enough space, else below

        let labelY = textY;
        overlayContext.fillText(name, dx, labelY);

        // Show Extra Info
        if (match.class_name || match.father_name) {
            overlayContext.font = "bold 14px Inter, sans-serif";
            if (match.class_name) {
                labelY += 20;
                overlayContext.fillText(`Class: ${match.class_name}`, dx, labelY);
            }
            if (match.father_name) {
                labelY += 20;
                overlayContext.fillText(`Father: ${match.father_name}`, dx, labelY);
            }
        }
    });
}

// --- Main Loop ---

function startRecognitionLoop() {
    setInterval(async () => {
        // Skip if busy
        if (isProcessingFrame) return;
        isProcessingFrame = true;

        try {
            // 1. Sync Overlay Canvas Size with Container
            const rect = videoContainer.getBoundingClientRect();
            if (overlayCanvas.width !== rect.width || overlayCanvas.height !== rect.height) {
                overlayCanvas.width = rect.width;
                overlayCanvas.height = rect.height;
            }

            // 2. Capture Frame (Downscaled for performance)
            const scale = CONFIG.SEND_WIDTH / videoElement.videoWidth;
            const sendHeight = videoElement.videoHeight * scale;

            captureCanvas.width = CONFIG.SEND_WIDTH;
            captureCanvas.height = sendHeight;

            if (videoElement.readyState === videoElement.HAVE_ENOUGH_DATA) {
                captureContext.drawImage(videoElement, 0, 0, captureCanvas.width, captureCanvas.height);
            } else {
                return; // Video not ready
            }

            const imageData = captureCanvas.toDataURL("image/jpeg", CONFIG.IMAGE_QUALITY);

            // 3. Send to API
            const response = await fetch("/api/recognize", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ image: imageData }),
            });

            const data = await response.json();

            console.log(data)

            // 4. Update UI based on response
            if (data.attendance_error) {
                statusLabel.innerText = `● ${data.attendance_error}`;
                statusLabel.style.color = "var(--primary)"; // Info style

                // Check for specific "Already marked" error to show modal
                if (data.attendance_error.includes("already marked")) {
                    // Try to identify the user who is already marked to track them
                    // We assume the first detected known user is the one triggered this
                    let likelyUser = null;
                    if (data.matches && data.matches.length > 0) {
                        const known = data.matches.find(m => m.name !== "Unknown" && !m.name.startsWith("Unknown"));
                        if (known) likelyUser = known.name;
                    }

                    openModal("Notice", "Already marked present today.", "#FFD700", likelyUser); // Gold/Yellow
                    // Or use a hex that matches a warning style. 
                } else if (data.attendance_error.includes("Success")) {
                    let likelyUser = null;
                    if (data.matches && data.matches.length > 0) {
                        const known = data.matches.find(m => m.name !== "Unknown" && !m.name.startsWith("Unknown"));
                        if (known) likelyUser = known.name;
                    }
                    if (likelyUser) {
                        openModal("Marked!", "You are marked present today.", "var(--success)", likelyUser);
                    }
                }
            } else {
                // Show a "Marked" modal only if the server explicitly flagged
                // the match as newly marked (m.newly_marked === true).
                // let newlyMarked = null;
                // if (data.matches && data.matches.length > 0) {
                //     newlyMarked = data.matches.find(m => m.newly_marked === true);
                //     console.log(newlyMarked)
                // }
                // if (newlyMarked) {
                //     // Use a consistent user-facing message and include the name
                //     // for clarity in multi-face scenarios.
                //     console.log("Marked!", `${newlyMarked.name} is marked present today.`, "var(--success)", newlyMarked.name)
                //     openModal("Marked!", `${newlyMarked.name} is marked present today.`, "var(--success)", newlyMarked.name);
                // }
                let likelyUser = null;
                if (data.matches && data.matches.length > 0) {
                    const known = data.matches.find(m => m.name !== "Unknown" && !m.name.startsWith("Unknown"));
                    if (known) likelyUser = known.name;
                }
                if (likelyUser) {
                    openModal("Marked!", "You are marked present today.", "var(--success)", likelyUser);
                }
                statusLabel.innerText = "● System Active";
                statusLabel.style.color = "var(--success)";
            }

            if (data.success && data.matches) {
                // Upscale boxes back to video resolution for drawing logic
                const matches = data.matches.map((m) => {
                    return {
                        ...m,
                        box: m.box.map((coord) => coord / scale),
                    };
                });
                drawRecognitionBoxes(matches);

                // --- Auto Disappear Logic ---
                if (isSuccessModalOpen && currentModalUser) {
                    // Check if currentModalUser is still in frame (matches)
                    const isUserPresent = matches.some(m => m.name === currentModalUser);

                    if (isUserPresent) {
                        framesWithoutUser = 0; // Reset counter if seen
                    } else {
                        framesWithoutUser++;
                        // If user is missing for too many consecutive frames, close modal
                        if (framesWithoutUser > MAX_MISSING_FRAMES) {
                            closeSuccessModal(false); // Auto-close is NOT manual
                        }
                    }
                }

                // --- Acknowledged User Cleanup Logic ---
                // For anyone in the acknowledged Set, if they are NOT in matches, increment their missing count.
                // If missing count > MAX, remove them (so they can be warned again if they return).
                acknowledgedUsers.forEach((missingCount, user) => {
                    const isUserPresent = matches.some(m => m.name === user);
                    if (isUserPresent) {
                        acknowledgedUsers.set(user, 0); // Reset if seen
                    } else {
                        const newCount = missingCount + 1;
                        if (newCount > MAX_MISSING_FRAMES) {
                            acknowledgedUsers.delete(user);
                        } else {
                            acknowledgedUsers.set(user, newCount);
                        }
                    }
                });

            } else if (isSuccessModalOpen && currentModalUser) {
                // No matches found at all (or success=false), but modal is open with a user
                framesWithoutUser++;
                if (framesWithoutUser > MAX_MISSING_FRAMES) {
                    closeSuccessModal(false);
                }

                // Also increment for all acknowledged users since no one is matched
                acknowledgedUsers.forEach((missingCount, user) => {
                    const newCount = missingCount + 1;
                    if (newCount > MAX_MISSING_FRAMES) {
                        acknowledgedUsers.delete(user);
                    } else {
                        acknowledgedUsers.set(user, newCount);
                    }
                });
            }

        } catch (err) {
            console.error("Recognition Loop Error:", err);
            statusLabel.innerText = "● Recognition Error";
            statusLabel.style.color = "var(--danger)";
        } finally {
            isProcessingFrame = false;
        }
    }, CONFIG.REFRESH_INTERVAL_MS);
}

// --- Event Listeners ---

window.addEventListener("resize", () => {
    if (window.innerWidth <= 768) {
        document.body.classList.add("fullscreen-mode");
    } else {
        document.body.classList.remove("fullscreen-mode");
    }
});