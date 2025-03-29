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

    let currentVideoInfo = null; // Store fetched info

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
        loadingIndicator.style.display = 'flex'; // Use flex for loading display
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
            fetchButton.disabled = false;

            if (!response.ok) {
                let errorData;
                try {
                    errorData = await response.json();
                } catch (e) {
                    errorData = { error: `HTTP error! Status: ${response.status}` };
                }
                throw new Error(errorData.error || `HTTP error! Status: ${response.status}`);
            }

            const data = await response.json();
            currentVideoInfo = data; // Store fetched data
            displayResults(data);

        } catch (error) {
            console.error('Fetch error:', error);
            showError(error.message || "Failed to fetch video info. Check the URL or server logs.");
            loadingIndicator.style.display = 'none';
            fetchButton.disabled = false;
        }
    });

    // --- Event Listener for Download Button ---
    downloadButton.addEventListener('click', () => {
        if (!currentVideoInfo || !currentVideoInfo.webpage_url) {
            showError("No video information loaded to start download.");
            return;
        }

        const selectedQuality = qualitySelect.value;
        if (!selectedQuality) {
             showError("Please select a video quality.");
            return;
        }

        // Construct download URL
        const downloadUrl = `/download?url=${encodeURIComponent(currentVideoInfo.webpage_url)}&quality=${encodeURIComponent(selectedQuality)}&title=${encodeURIComponent(currentVideoInfo.title)}`;

        // Trigger download by navigating the browser
        showInfo("Preparing download... Your download will start shortly."); // Inform user
        downloadButton.disabled = true; // Prevent double clicks while preparing
        errorMessage.style.backgroundColor = 'rgba(92, 184, 92, 0.1)'; // Use info style temporarily
        errorMessage.style.borderColor = 'var(--success-color)';
        errorMessage.style.color = 'var(--success-color)';

        window.location.href = downloadUrl;

        // Re-enable button after a short delay (browser handles the download)
        setTimeout(() => {
             downloadButton.disabled = false;
             hideError(); // Hide the "Preparing" message
        }, 3000); // Adjust delay if needed
    });


    // --- Helper Functions ---
    function displayResults(data) {
        thumbnailImg.src = data.thumbnail_url || ''; // Handle missing thumbnail URL gracefully
        thumbnailImg.alt = data.title ? `${data.title} Thumbnail` : 'Video Thumbnail';
        videoTitle.textContent = data.title || 'Video Title Unavailable';

        // Populate quality dropdown
        qualitySelect.innerHTML = ''; // Clear previous options
        if (data.quality_options && Object.keys(data.quality_options).length > 0) {
            // Sort qualities numerically (descending) based on height
            const sortedQualities = Object.entries(data.quality_options) // [["1080p", 1080], ["720p", 720]]
                                       .sort(([, heightA], [, heightB]) => heightB - heightA) // Sort by height desc
                                       .map(([label]) => label); // Get back labels ["1080p", "720p"]

            sortedQualities.forEach(qualityLabel => {
                const option = document.createElement('option');
                option.value = qualityLabel; // e.g., "1080p"
                option.textContent = qualityLabel;
                qualitySelect.appendChild(option);
            });
            downloadButton.disabled = false;
        } else {
             const option = document.createElement('option');
             option.textContent = "No qualities found";
             option.disabled = true;
             qualitySelect.appendChild(option);
             downloadButton.disabled = true;
        }

        resultsArea.style.display = 'block';
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
        errorMessage.style.backgroundColor = 'rgba(92, 184, 92, 0.1)'; // Use a success/info style
        errorMessage.style.borderColor = 'var(--success-color)';
        errorMessage.style.color = 'var(--success-color)';
    }


    function hideError() {
        errorMessage.textContent = '';
        errorMessage.style.display = 'none';
    }

});