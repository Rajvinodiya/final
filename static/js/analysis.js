document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('analysis-form');
    if (!form) return;

    // Character counter
    const textarea = document.getElementById('analysis-text');
    const charCount = document.getElementById('char-count');

    function updateCharCount() {
        charCount.textContent = `${textarea.value.length}/500`;
    }

    updateCharCount();
    textarea.addEventListener('input', updateCharCount);

    // Example buttons
    document.querySelectorAll('.example-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            textarea.value = e.target.dataset.text;
            updateCharCount();
        });
    });

    // Form submission handler
    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const button = form.querySelector('button[type="submit"]');
        button.disabled = true;
        button.innerHTML = `<i class="bi bi-gear me-2"></i>Processing...`;

        try {
            const response = await fetch('/analysis', {
                method: 'POST',
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                body: `text=${encodeURIComponent(textarea.value)}`
            });

            if (!response.ok) throw new Error('Analysis failed');
            const html = await response.text();
            document.getElementById('results-section').innerHTML =
                new DOMParser().parseFromString(html, 'text/html')
                .getElementById('results-section').innerHTML;

        } catch (error) {
            alert(`Error: ${error.message}`);
        } finally {
            button.disabled = false;
            button.innerHTML = `<i class="bi bi-magic me-2"></i>Analyze`;
        }
    });
});