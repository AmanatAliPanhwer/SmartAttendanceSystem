/**
 * image_viewer.js
 * Handles the full-screen image viewing experience with zoom and pan.
 */

// Structure for the viewer
const viewerHTML = `
<div id="imageViewer" class="image-viewer" style="display: none;">
    <span class="close-viewer">&times;</span>
    <div class="viewer-content">
        <img id="viewerImage" src="" alt="Full Screen View" />
    </div>
    <div class="viewer-controls">
        <button id="zoomInBtn" class="btn btn-outline">+</button>
        <button id="zoomOutBtn" class="btn btn-outline">-</button>
        <button id="resetZoomBtn" class="btn btn-outline">Reset</button>
    </div>
</div>
`;

// Inject viewer into body
document.body.insertAdjacentHTML('beforeend', viewerHTML);

const viewer = document.getElementById('imageViewer');
const viewerImg = document.getElementById('viewerImage');
const closeBtn = document.querySelector('.close-viewer');
const zoomInBtn = document.getElementById('zoomInBtn');
const zoomOutBtn = document.getElementById('zoomOutBtn');
const resetBtn = document.getElementById('resetZoomBtn');

let scale = 1;
let translateX = 0;
let translateY = 0;
let isDragging = false;
let startX, startY;

function openViewer(src) {
    viewerImg.src = src;
    viewer.style.display = 'flex';
    resetZoom();
}

function closeViewer() {
    viewer.style.display = 'none';
}

function updateTransform() {
    viewerImg.style.transform = `translate(${translateX}px, ${translateY}px) scale(${scale})`;
}

function resetZoom() {
    scale = 1;
    translateX = 0;
    translateY = 0;
    updateTransform();
}

function zoom(delta) {
    scale += delta;
    if (scale < 0.1) scale = 0.1; // Min zoom
    if (scale > 5) scale = 5;     // Max zoom
    updateTransform();
}

// Event Listeners
closeBtn.onclick = closeViewer;
viewer.onclick = (e) => {
    if (e.target === viewer) closeViewer();
};

zoomInBtn.onclick = (e) => { e.stopPropagation(); zoom(0.1); };
zoomOutBtn.onclick = (e) => { e.stopPropagation(); zoom(-0.1); };
resetBtn.onclick = (e) => { e.stopPropagation(); resetZoom(); };

// Wheel Zoom
viewer.onwheel = (e) => {
    e.preventDefault();
    const delta = e.deltaY > 0 ? -0.1 : 0.1;
    zoom(delta);
};

// Panning
viewerImg.onmousedown = (e) => {
    e.preventDefault(); // Prevent default drag
    isDragging = true;
    startX = e.clientX - translateX;
    startY = e.clientY - translateY;
    viewerImg.style.cursor = 'grabbing';
};

window.onmouseup = () => {
    isDragging = false;
    viewerImg.style.cursor = 'grab';
};

window.onmousemove = (e) => {
    if (!isDragging) return;
    e.preventDefault();
    translateX = e.clientX - startX;
    translateY = e.clientY - startY;
    updateTransform();
};

// Make accessible to other scripts
window.openImageViewer = openViewer;
