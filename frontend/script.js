let ws;
let playerId = null;
let myRole = null;
let flipCount = 0;

// UI Elements
const coin = document.getElementById('coin');
const status = document.getElementById('status');
const roleBanner = document.getElementById('role-banner');
const guessControls = document.getElementById('guess-controls');
const flipControls = document.getElementById('flip-controls');
const flipBtn = document.getElementById('flip-btn');

const authScreen = document.getElementById('auth-screen');
const mainApp = document.getElementById('main-app');
const gameView = document.getElementById('game-view');
const dashboardView = document.getElementById('dashboard-view');

const resolutionPanel = document.getElementById('resolution-panel');
const resolutionTitle = document.getElementById('resolution-title');
const resolutionMsg = document.getElementById('resolution-msg');
const loserInputs = document.getElementById('loser-inputs');
const gameOverPanel = document.getElementById('game-over-panel');

const ws_protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
const ws_url = `${ws_protocol}//${window.location.host}/ws`;

// ---------- Tab Navigation ----------
document.getElementById('tab-game').onclick = () => switchTab('game');
document.getElementById('tab-dashboard').onclick = () => switchTab('dashboard');

function switchTab(tab) {
    document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
    document.getElementById(`tab-${tab}`).classList.add('active');

    if (tab === 'game') {
        gameView.classList.remove('hidden');
        dashboardView.classList.add('hidden');
    } else {
        gameView.classList.add('hidden');
        dashboardView.classList.remove('hidden');
    }
}

// ---------------Auth Request-------------------
async function authRequest(endpoint) {
    const username = document.getElementById('auth-username').value.trim();
    const password = document.getElementById('auth-password').value;
    const authStatus = document.getElementById('auth-status');

    if (!username || !password) return authStatus.textContent = 'Enter username & password.';
    authStatus.textContent = 'Please wait...';

    try {
        const res = await fetch(`/api/${endpoint}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password })
        });

        // Gracefully handle server crashes (500 errors) so JSON.parse doesn't break
        if (!res.ok) {
            try {
                const errorData = await res.json();
                authStatus.textContent = errorData.detail || 'Error.';
            } catch (err) {
                authStatus.textContent = `Server crashed (${res.status}). Check backend logs.`;
            }
            return;
        }

        const data = await res.json();

        playerId = data.username;
        authScreen.classList.add('hidden');
        mainApp.classList.remove('hidden');

        updateDashboard(data.stats || {});
        connectWS();

    } catch (e) {
        console.error("Network Error:", e);
        authStatus.textContent = 'Network error. Could not reach server.';
    }
}

document.getElementById('login-btn').onclick = () => authRequest('login');
document.getElementById('register-btn').onclick = () => authRequest('register');

function updateDashboard(stats) {
    // Safely default values to 0 if they don't exist yet
    const wins = stats.wins || 0;
    const losses = stats.losses || 0;
    const ties = stats.ties || 0;
    const playTime = stats.total_play_time_seconds || 0;

    const html = `
        <div><strong>Total Wins:</strong> ${wins}</div>
        <div><strong>Total Losses:</strong> ${losses}</div>
        <div><strong>Ties:</strong> ${ties}</div>
        <div><strong>Playtime:</strong> ${Math.floor(playTime / 60)} mins</div>
    `;
    document.getElementById('lifetime-stats').innerHTML = html;
}

// ---------- WebSocket Logic ----------
function connectWS() {
    ws = new WebSocket(ws_url);

    ws.onopen = () => {
        status.textContent = 'Connected. Joining room...';
        setTimeout(() => ws.send(JSON.stringify({ type: 'join', player_id: playerId })), 300);
    };

    ws.onmessage = (event) => {
        const message = JSON.parse(event.data);

        switch (message.type) {
            case 'roles': {
                myRole = message.roles[playerId] || null;
                resolutionPanel.classList.add('hidden');
                gameOverPanel.classList.add('hidden');
                flipCount = 0;
                coin.style.transform = 'rotateX(0deg)';
                roleBanner.textContent = myRole === 'guesser' ? "You are the GUESSER 🤔" : "You are the FLIPPER 🪙";
                break;
            }

            case 'lifetime_stats': {
                if (message.stats[playerId]) updateDashboard(message.stats[playerId]);
                break;
            }

            case 'state': {
                const players = Object.keys(message.scores);
                if (players.length > 0) document.getElementById('score-playerA').textContent = `${players[0]}: ${message.scores[players[0]]}`;
                if (players.length > 1) document.getElementById('score-playerB').textContent = `${players[1]}: ${message.scores[players[1]]}`;
                document.getElementById('current-toss').textContent = `Toss: ${message.current_toss}/${message.max_tosses}`;

                if (!message.game_started) {
                    status.textContent = 'Waiting for other player...';
                    guessControls.classList.add('hidden');
                    flipControls.classList.add('hidden');
                    break;
                }

                if (message.resolution_pending) {
                    // Game is frozen waiting for loser to pay up
                    guessControls.classList.add('hidden');
                    flipControls.classList.add('hidden');
                    break;
                }

                if (message.game_over) break;

                if (message.awaiting_guess) {
                    if (myRole === 'guesser') {
                        guessControls.classList.remove('hidden');
                        status.textContent = 'Make your call!';
                    } else {
                        status.textContent = 'Waiting for guesser...';
                    }
                } else {
                    guessControls.classList.add('hidden');
                    if (myRole === 'flipper') {
                        flipControls.classList.remove('hidden');
                        flipBtn.disabled = false;
                        status.textContent = 'Guess locked in. FLIP!';
                    } else {
                        status.textContent = 'Waiting for flip...';
                    }
                }
                break;
            }

            case 'guess_locked': {
                if (myRole === 'guesser') status.textContent = 'Guess locked. Waiting for flip...';
                guessControls.classList.add('hidden');
                break;
            }

            case 'flip_result': {
                flipCount++;
                const baseSpins = flipCount * 3600;
                const degrees = message.result === 'heads' ? baseSpins : baseSpins + 180;
                coin.style.transform = `rotateX(${degrees}deg)`;

                status.textContent = 'Flipping... 🪙';
                flipBtn.disabled = true;
                flipControls.classList.add('hidden');

                setTimeout(() => {
                    const verdict = message.correct ? 'correct! 🎉' : 'wrong.';
                    const visualResult = message.result === 'heads' ? 'Flower (❀)' : 'Person (👤)';
                    status.textContent = `Result: ${visualResult} — ${message.guesser} guessed ${message.guess} — ${verdict}`;
                }, 3000);
                break;
            }

            case 'game_over': {
                resolutionPanel.classList.remove('hidden');
                resolutionTitle.textContent = `${message.winner} wins! 🏆`;

                if (message.resolution_pending) {
                    if (playerId === message.loser) {
                        resolutionMsg.textContent = "You lost! Please submit your investment bet to finish the game.";
                        loserInputs.classList.remove('hidden');
                        gameOverPanel.classList.add('hidden');
                    } else {
                        resolutionMsg.textContent = `Waiting for ${message.loser} to submit their stock investment...`;
                        loserInputs.classList.add('hidden');
                        gameOverPanel.classList.add('hidden');
                    }
                } else {
                    // Tie game, no resolution needed
                    resolutionMsg.textContent = "It was a tie. No investments required.";
                    gameOverPanel.classList.remove('hidden');
                }
                break;
            }

            case 'resolution_complete': {
                resolutionMsg.textContent = message.message; // Shows "X invested in Y!"
                loserInputs.classList.add('hidden');
                gameOverPanel.classList.remove('hidden'); // Reveal Play Again button
                break;
            }

            case 'opponent_dropped':
                alert(message.message);
                status.textContent = 'Opponent left. Waiting...';
                break;

            case 'status':
                status.textContent = message.message;
                break;
            case 'error':
                alert(message.message);
                break;
        }
    };
}

// Game Actions
document.querySelectorAll('.guess-btn').forEach(btn => {
    btn.onclick = () => {
        ws.send(JSON.stringify({ type: 'guess', choice: btn.getAttribute('data-choice') }));
        guessControls.classList.add('hidden');
    };
});

flipBtn.onclick = () => {
    ws.send(JSON.stringify({ type: 'flip' }));
    flipBtn.disabled = true;
};

// --- NEW: Submit Investment ---
document.getElementById('submit-investment-btn').onclick = () => {
    const stock = document.getElementById('stock-ticker').value.trim();
    const amount = document.getElementById('stock-amount').value.trim();

    if (!stock || !amount) return alert("Please enter both a stock ticker and an amount.");

    ws.send(JSON.stringify({
        type: 'resolve_bet',
        stock_name: stock,
        amount: parseFloat(amount)
    }));

    document.getElementById('submit-investment-btn').disabled = true;
    document.getElementById('submit-investment-btn').textContent = "Submitting...";
};

document.getElementById('play-again-btn').onclick = () => {
    ws.send(JSON.stringify({ type: 'play_again' }));
    resolutionPanel.classList.add('hidden');
    gameOverPanel.classList.add('hidden');
    document.getElementById('submit-investment-btn').disabled = false;
    document.getElementById('submit-investment-btn').textContent = "Commit Investment";
};

document.getElementById('logout-btn').onclick = () => location.reload();
