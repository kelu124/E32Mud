def html(PORT):
  return """<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"UTF-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />
  <title>Local MUD Terminal</title>
  <style>
    body { background-color: #000; color: #0f0; font-family: monospace; margin: 0; display: flex; flex-direction: column; height: 100vh; }
    #output { flex: 1; overflow-y: auto; padding: 10px; white-space: pre-wrap; }
    #input { border: none; padding: 10px; font-size: 1em; background: #111; color: #0f0; width: 100%; box-sizing: border-box; }
  </style>
</head>
<body>
  <div id=\"output\"></div>
  <input id=\"input\" type=\"text\" placeholder=\"Type your command...\" autofocus />
  <script>
    const ws = new WebSocket('ws://' + location.hostname + ':"""+str(PORT)+"""/ws');
    const output = document.getElementById('output');
    const input = document.getElementById('input');
    let awaitingName = true; // first thing the user types goes to localStorage

    function print(message) {
      output.textContent += message + '\\n';
      output.scrollTop = output.scrollHeight;
    }

    ws.onopen = () => {
      console.log('[Connected to MUD]');
      const name = localStorage.getItem('player_name');
      if (name) {
        ws.send('__auth ' + name);
        awaitingName = false;
      }
    };

    ws.onmessage = (event) => {
      const data = event.data;
      print(data);
      // If the server asks for a name again (e.g. wrong password), reset.
      if (data.toLowerCase().includes('enter your name')) {
        localStorage.removeItem('player_name');
        awaitingName = true;
      }
    };

    ws.onclose = () => print('[Disconnected]');

    input.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') {
        const command = input.value;
        if (command.trim() === '') return;
        print('> ' + command);
        ws.send(command);
        if (awaitingName) {
          localStorage.setItem('player_name', command.trim());
          awaitingName = false;
        }
        input.value = '';
      }
    });
  </script>
</body>
</html>
"""
