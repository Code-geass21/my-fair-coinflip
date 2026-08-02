let ws;
let playerId;
let myRole = null;   // "guesser" | "flipper" | null
let flipCount = 0;

const coin = document.getElementById('coin');
const status = document.getElementById('status');
const roleBanner = document.getElementById('role-banner');
const guessControls = document.getElementById('guess-controls');
const flipControls = document.getElementById('flip-controls');
const flipBtn = document.getElementById('flip-btn');
const gameOverPanel = document.getElementById('game-over-panel');
const gameOverTitle = document.getElementById('game-over-title');

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

        switch (message.type) {
            case 'roles': {
                myRole = message.roles[playerId] || null;
                gameOverPanel.classList.add('hidden');
                flipCount = 0;
                coin.style.transform = 'rotateX(0deg)';
                if (myRole === 'guesser') {
                    roleBanner.textContent = "You're the GUESSER — call it before each flip.";
                } else if (myRole === 'flipper') {
                    roleBanner.textContent = "You're the FLIPPER — flip once your opponent locks in a guess.";
                }
                break;
            }

            case 'state': {
                const players = Object.keys(message.scores);
                if (players.length > 0) {
                    document.getElementById('score-playerA').textContent = `${players[0]}: ${message.scores[players[0]]}`;
                }
                if (players.length > 1) {
                    document.getElementById('score-playerB').textContent = `${players[1]}: ${message.scores[players[1]]}`;
                }
                document.getElementById('current-toss').textContent = `Toss: ${message.current_toss}/${message.max_tosses}`;

                if (!message.game_started) {
                    status.textContent = 'Waiting for other player to join...';
                    guessControls.classList.add('hidden');
                    flipControls.classList.add('hidden');
                    break;
                }

                if (message.game_over) {
                    guessControls.classList.add('hidden');
                    flipControls.classList.add('hidden');
                    break;
                }

                if (message.awaiting_guess) {
                    if (myRole === 'guesser') {
                        guessControls.classList.remove('hidden');
                        flipControls.classList.add('hidden');
                        status.textContent = 'Make your call!';
                    } else {
                        guessControls.classList.add('hidden');
                        flipControls.classList.add('hidden');
                        status.textContent = 'Waiting for the guesser to call it...';
                    }
                } else {
                    guessControls.classList.add('hidden');
                    if (myRole === 'flipper') {
                        flipControls.classList.remove('hidden');
                        flipBtn.disabled = false;
                        status.textContent = 'Guess is locked in — go ahead and flip!';
                    } else {
                        flipControls.classList.add('hidden');
                        status.textContent = 'Guess locked in. Waiting for the flip...';
                    }
                }
                break;
            }

            case 'guess_locked': {
                if (myRole === 'guesser') {
                    status.textContent = 'Guess locked in. Waiting for the flip...';
                }
                guessControls.classList.add('hidden');
                break;
            }

            case 'flip_result': {
                flipCount++;
                const baseSpins = flipCount * 3600;
                const degrees = message.result === 'heads' ? baseSpins : baseSpins + 180;
                coin.style.transform = `rotateX(${degrees}deg)`;

                const verdict = message.correct ? 'correct! 🎉' : 'wrong.';
                status.textContent =
                    `Result: ${message.result.toUpperCase()} — ${message.guesser} guessed ${message.guess.toUpperCase()} — ${verdict}`;

                flipBtn.disabled = true;
                flipControls.classList.add('hidden');
                break;
            }

            case 'game_over': {
                let winnerText = message.winner === 'tie'
                    ? "It's a tie!"
                    : `${message.winner} wins! 🏆`;
                if (message.early_finish) {
                    winnerText += ' (clinched early — opponent could no longer catch up)';
                }
                gameOverTitle.textContent = winnerText;
                gameOverPanel.classList.remove('hidden');
                guessControls.classList.add('hidden');
                flipControls.classList.add('hidden');
                status.textContent = 'Game over.';
                break;
            }

            case 'status': {
                status.textContent = message.message;
                break;
            }

            case 'error': {
                alert(message.message);
                break;
            }
        }
    };

    ws.onerror = (e) => console.error('WebSocket Error:', e);
    ws.onclose = () => status.textContent = 'Connection closed. Refresh page to retry.';
}

document.getElementById('join-btn').onclick = () => {
    playerId = document.getElementById('player-id').value.trim();
    if (!playerId) return alert('Enter your name.');

    document.getElementById('game-setup').classList.add('hidden');
    document.getElementById('game-room').classList.remove('hidden');
    connectWS();
};

document.querySelectorAll('.guess-btn').forEach(btn => {
    btn.onclick = () => {
        const choice = btn.getAttribute('data-choice');
        ws.send(JSON.stringify({ type: 'guess', choice }));
        guessControls.classList.add('hidden');
    };
});

flipBtn.onclick = () => {
    ws.send(JSON.stringify({ type: 'flip' }));
    flipBtn.disabled = true;
    status.textContent = 'Flipping...';
};

document.getElementById('play-again-btn').onclick = () => {
    ws.send(JSON.stringify({ type: 'play_again' }));
    gameOverPanel.classList.add('hidden');
};
