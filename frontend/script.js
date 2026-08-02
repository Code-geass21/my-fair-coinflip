let ws;
let playerId;
const coin = document.getElementById('coin');
const status = document.getElementById('status');
let flipCount = 0; // Tracks cumulative spins

const ws_protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
const ws_url = `${ws_protocol}//${window.location.host}/ws`;

function connectWS() {
    ws = new WebSocket(ws_url);

    ws.onopen = () => {
        status.textContent = 'Connected. Joining room...';
        setTimeout(() => {
            ws.send(JSON.stringify({ type: 'join', player_id: playerId }));
        }, 500);
    };

    ws.onmessage = (event) => {
        const message = JSON.parse(event.data);
        
        if (message.type === 'state') {
            const players = Object.keys(message.scores);
            if (players.length > 0) {
                document.getElementById('score-playerA').textContent = `${players[0]}: ${message.scores[players[0]]}`;
            }
            if (players.length > 1) {
                document.getElementById('score-playerB').textContent = `${players[1]}: ${message.scores[players[1]]}`;
            }
            document.getElementById('current-toss').textContent = `Toss: ${message.current_toss}/10`;
            
        } else if (message.type === 'flip_result') {
            // Force the coin to keep spinning forward by adding rotations cumulatively
            flipCount++;
            const baseSpins = flipCount * 3600; // 10 spins forward per flip
            const degrees = message.result === 'heads' ? baseSpins : baseSpins + 180; 
            
            coin.style.transform = `rotateX(${degrees}deg)`;
            status.textContent = `${message.player} flipped! Result: ${message.result.toUpperCase()}`;
            
        } else if (message.type === 'status') {
            status.textContent = message.message;
        } else if (message.type === 'error') {
            alert(message.message);
        }
    };

    ws.onerror = (e) => console.error('WebSocket Error:', e);
    ws.onclose = () => status.textContent = 'Connection closed. Refresh page to retry.';
}

document.getElementById('join-btn').onclick = () => {
    playerId = document.getElementById('player-id').value;
    if (!playerId) return alert('Enter your name.');
    
    document.getElementById('game-setup').classList.add('hidden');
    document.getElementById('game-room').classList.remove('hidden');
    connectWS();
};

document.getElementById('flip-btn').onclick = () => {
    const seed = document.getElementById('client-seed').value || 'my_seed';
    ws.send(JSON.stringify({ type: 'flip', client_seed: seed }));
    status.textContent = 'Flipping...';
};
