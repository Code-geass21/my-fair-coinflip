let ws;
let playerId = null;   // authenticated username
let myRole = null;
let flipCount = 0;

const coin = document.getElementById('coin');
const status = document.getElementById('status');
const roleBanner = document.getElementById('role-banner');
const lifetimeStatsEl = document.getElementById('lifetime-stats');
const guessControls = document.getElementById('guess-controls');
const flipControls = document.getElementById('flip-controls');
const flipBtn = document.getElementById('flip-btn');
const gameOverPanel = document.getElementById('game-over-panel');
const gameOverTitle = document.getElementById('game-over-title');

const authScreen = document.getElementById('auth-screen');
const authUsername = document.getElementById('auth-username');
const authPassword = document.getElementById('auth-password');
const authStatus = document.getElementById('auth-status');
const gameRoom = document.getElementById('game-room');

const ws_protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
const ws_url = `${ws_protocol}//${window.location.host}/ws`;

// ---------- Auth ----------

async function authRequest(endpoint) {
    const username = authUsername.value.trim();
    const password = authPassword.value;
    if (!username || !password) {
        authStatus.textContent = 'Enter a username and password.';
        return;
    }
    authStatus.textContent = 'Please wait...';
    try {
        const res = await fetch(`/api/${endpoint}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password })
        });
        const data = await res.json();
        if (!res.ok) {
            authStatus.textContent = data.detail || 'Something went wrong.';
            return;
        }
        playerId = data.username;
        authScreen.classList.add('hidden');
        gameRoom.classList.remove('hidden');
        connectWS();
    } catch (e) {
        authStatus.textContent = 'Could not reach the server.';
    }
}

document.getElementById('login-btn').onclick = () => authRequest('login');
document.getElementById('register-btn').onclick = () => authRequest('register');

// ---------- WebSocket / game ----------

function connectWS() {
    ws = new WebSocket(ws_url);

    ws.onopen = () => {
        status.textContent = 'Connected. Joining room...';
        setTimeout(() => {
            ws.send(JSON.stringify({ type: 'join', player_id: playerId }));
        }, 300);
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

            case 'lifetime_stats': {
                const parts = Object.entries(message.stats).map(
                    ([name, s]) => `${name}: ${s.wins}W-${s.losses}L${s.ties ? `-${s.ties}T` : ''}`
                );
                lifetimeStatsEl.textContent = parts.length ? `Lifetime: ${parts.join('  |  ')}` : '';
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
                    gameOverPanel.classList.add('hidden');
                    roleBanner.textContent = '';
                    myRole = null;
                    flipCount = 0;
                    coin.style.transform = 'rotateX(0deg)';
                    document.getElementById('score-playerA').textContent = 'Player A: 0';
                    document.getElementById('score-playerB').textContent = 'Player B: 0';
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

                // 1. Instantly show it's spinning
                status.textContent = 'Flipping... 🪙';

                // 2. Wait EXACTLY 3 seconds for the CSS animation to finish
                setTimeout(() => {
                    const verdict = message.correct ? 'correct! 🎉' : 'wrong.';
                    status.textContent =
                        `Result: ${message.result.toUpperCase()} — ${message.guesser} guessed ${message.guess.toUpperCase()} — ${verdict}`;
                }, 3000);

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

            case 'opponent_dropped': {
                // This triggers the browser popup!
                alert(message.message);
                status.textContent = 'Waiting for another player to join...';
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

document.getElementById('logout-btn').onclick = () => {
    if (ws) {
        ws.close();
    }
    playerId = null;
    myRole = null;
    flipCount = 0;
    coin.style.transform = 'rotateX(0deg)';
    authPassword.value = '';
    authStatus.textContent = '';
    gameOverPanel.classList.add('hidden');
    guessControls.classList.add('hidden');
    flipControls.classList.add('hidden');
    lifetimeStatsEl.textContent = '';
    roleBanner.textContent = '';
    gameRoom.classList.add('hidden');
    authScreen.classList.remove('hidden');
};
