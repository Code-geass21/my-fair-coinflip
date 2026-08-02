let ws;
let playerId;
const coin = document.getElementById('coin');
const status = document.getElementById('status');

// Web Socket setup (connects to the same host that serves the page)
const ws_protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
const ws_url = `${ws_protocol}//${window.location.host}/ws`;

function connectWS() {
    ws = new WebSocket(ws_url);

    ws.onopen = () => {
        status.textContent = 'Connected. Waiting to join...';
    };

    ws.onmessage = (event) => {
        const message = JSON.parse(event.data);
        if (message.type === 'state') {
            document.getElementById('score-playerA').textContent = `Player A: ${message.scores.playerA}`;
            document.getElementById('score-playerB').textContent = `Player B: ${message.scores.playerB}`;
            document.getElementById('current-toss').textContent = `Toss: ${message.current_toss}/10`;
            if (message.last_result) {
                status.textContent = `Last flip was ${message.last_result.toUpperCase()}.`;
            }
        } else if (message.type === 'flip_result') {
            const degrees = message.result === 'heads' ? 3600 : 3780; // Large rotation + result
            coin.style.transform = `rotateX(${degrees}deg)`;
            status.textContent = `${message.player} flipped! Result is: ${message.result.toUpperCase()}`;
        } else if (message.type === 'error') {
            alert(message.message);
        }
    };

    ws.onerror = (e) => console.error('WebSocket Error:', e);
    ws.onclose = () => status.textContent = 'Connection closed. Refresh to retry.';
}

// UI Controls
document.getElementById('join-btn').onclick = () => {
    playerId = document.getElementById('player-id').value;
    if (!playerId) return alert('Enter your ID.');
    
    document.getElementById('game-setup').classList.add('hidden');
    document.getElementById('game-room').classList.remove('hidden');
    connectWS();
    
    // Once connected, wait a sec and join
    setTimeout(() => {
        ws.send(JSON.stringify({ type: 'join', player_id: playerId }));
    }, 500);
};

document.getElementById('flip-btn').onclick = () => {
    const seed = document.getElementById('client-seed').value || 'my_seed';
    ws.send(JSON.stringify({ type: 'flip', client_seed: seed }));
    coin.style.transform = `rotateX(0deg)`; // Reset rotation
    status.textContent = 'Flipping...';
};
