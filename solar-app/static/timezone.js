function updateTimezone() {
    const lat = document.getElementById('latitude').value;
    const lon = document.getElementById('longitude').value;
    if (lat && lon) {
        fetch(`/get_timezone?lat=${lat}&lon=${lon}`)
            .then(response => response.json())
            .then(data => {
                document.getElementById('timezone').innerText = data.timezone || '';
            });
    }
}
