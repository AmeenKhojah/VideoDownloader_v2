document.addEventListener('DOMContentLoaded', () => {
    const urlInput = document.getElementById('url-input');
    const fetchButton = document.getElementById('fetch-button');
    const loadingIndicator = document.getElementById('loading-indicator');
    const errorMessage = document.getElementById('error-message');
    const resultsArea = document.getElementById('results-area');
    const thumbnailImg = document.getElementById('thumbnail-img');
    const videoTitle = document.getElementById('video-title');
    const qualitySelect = document.getElementById('quality-select');
    const downloadButton = document.getElementById('download-button');

    // --- Store fetched video info globally in this scope ---
    let currentVideoInfo = null;

    // --- Event Listener for Fetch Button ---
    fetchButton.addEventListener('click', async () => {
        const url = urlInput.value.trim();
        if (!url) {
            showError("Please paste a video URL.");
            return;
        }

        // Reset UI
        hideError();
        resultsArea.style.display = 'none';
        loadingIndicator.style.display = 'flex';
        fetchButton.disabled = true;
        downloadButton.disabled = true;
        currentVideoInfo = null; // Clear previous info

        try {
            const response = await fetch('/fetch_info', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ url: url }),
            });

            loadingIndicator.style.display = 'none';
            fetchButton.disabled = false; // Re-enable fetch button

            if (!response.ok) {
                let errorData;
                try { errorData = await response.json(); }
                catch (e) { errorData = { error: `HTTP error! Status: ${response.status}` }; }
                throw new Error(errorData.error || `HTTP error! Status: ${response.status}`);
            }

            const data = await response.json();
            currentVideoInfo = data; // Store fetched data (includes title, webpage_url, extractor etc.)
            displayResults(data);

        } catch (error) {
            console.error('Fetch error:', error);
            showError(error.message || "Failed to fetch video info. Check the URL or server logs.");
            loadingIndicator.style.display = 'none';
            fetchButton.disabled = false; // Re-enable fetch button on error too
        }
    });

    // --- Event Listener for Download Button ---
    downloadButton.addEventListener('click', () => {
        // Check if currentVideoInfo and necessary fields exist
        if (!currentVideoInfo || !currentVideoInfo.webpage_url || !currentVideoInfo.title) {
            showError("Video information not fully loaded. Please fetch info again.");
            return;
        }
        // Optional: Check extractor key existence (backend handles fallback if missing)
        if (!currentVideoInfo.extractor) {
             console.warn("Extractor key missing from fetched info. Backend will attempt to determine it.");
             // We can proceed, backend will try fetching extractor key again if needed
        }

        const selectedQuality = qualitySelect.value;
        if (!selectedQuality) {
             showError("Please select a video quality.");
            return;
        }

        // --- !!! CONSTRUCT DOWNLOAD URL WITH EXTRACTOR !!! ---
        // Include url, quality, title, and the extractor key
        const downloadUrlParams = new URLSearchParams({
            url: currentVideoInfo.webpage_url,
            quality: selectedQuality,
            title: currentVideoInfo.title,
            // Provide extractor key, fallback to 'Generic' if somehow undefined/null
            extractor: currentVideoInfo.extractor || 'Generic'
        });
        const downloadUrl = `/download?${downloadUrlParams.toString()}`;

        console.log("Requesting download URL:", downloadUrl); // Log the URL being requested

        // Inform user and disable button temporarily
        showInfo("Preparing download... Your download will start shortly.");
        downloadButton.disabled = true;
        errorMessage.style.backgroundColor = 'rgba(92, 184, 92, 0.1)';
        errorMessage.style.borderColor = 'var(--success-color)';
        errorMessage.style.color = 'var(--success-color)';

        // Trigger download by navigating the browser
        window.location.href = downloadUrl;

        // Re-enable button after a short delay (browser handles the download initiation)
        // Longer delay might be needed if server encoding takes time before download starts
        setTimeout(() => {
             downloadButton.disabled = false;
             hideError(); // Clear the "Preparing" message
        }, 5000); // Increased delay to 5 seconds

    });


    // --- Helper Functions ---
    function displayResults(data) {
        // Use the potentially proxied thumbnail URL
        if (data.thumbnail_url) {
            thumbnailImg.src = data.thumbnail_url;
            thumbnailImg.style.display = 'block'; // Ensure it's visible
        } else {
            thumbnailImg.src = '#'; // Clear src if no thumbnail
            thumbnailImg.style.display = 'none'; // Hide img element if no thumbnail
        }
        thumbnailImg.alt = data.title ? `${data.title} Thumbnail` : 'Video Thumbnail';
        videoTitle.textContent = data.title || 'Video Title Unavailable';

        // Populate quality dropdown
        qualitySelect.innerHTML = ''; // Clear previous options
        if (data.quality_options && Object.keys(data.quality_options).length > 0) {
            const sortedQualities = Object.entries(data.quality_options)
                                       .sort(([, heightA], [, heightB]) => heightB - heightA)
                                       .map(([label]) => label);

            sortedQualities.forEach(qualityLabel => {
                const option = document.createElement('option');
                option.value = qualityLabel;
                option.textContent = qualityLabel;
                qualitySelect.appendChild(option);
            });
            downloadButton.disabled = false; // Enable download button
        } else {
             const option = document.createElement('option');
             option.textContent = "No qualities found";
             option.disabled = true;
             qualitySelect.appendChild(option);
             downloadButton.disabled = true; // Keep download disabled
        }

        resultsArea.style.display = 'block'; // Show results area
    }

    function showError(message) {
        errorMessage.textContent = message;
        errorMessage.style.display = 'block';
        errorMessage.style.backgroundColor = 'rgba(217, 83, 79, 0.1)';
        errorMessage.style.borderColor = 'var(--error-color)';
        errorMessage.style.color = 'var(--error-color)';
    }
     function showInfo(message) { // Function to show non-error messages
        errorMessage.textContent = message;
        errorMessage.style.display = 'block';
        errorMessage.style.backgroundColor = 'rgba(92, 184, 92, 0.1)';
        errorMessage.style.borderColor = 'var(--success-color)';
        errorMessage.style.color = 'var(--success-color)';
    }

    function hideError() {
        errorMessage.textContent = '';
        errorMessage.style.display = 'none';
    }

}); // End DOMContentLoaded
